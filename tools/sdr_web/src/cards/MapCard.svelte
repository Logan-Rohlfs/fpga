<script lang="ts">
  // Map card (spec 13.6). Tiles come only from the server's local /tiles store; this card never reaches a remote tile server.
  import L from 'leaflet';
  import 'leaflet/dist/leaflet.css';
  import { onMount } from 'svelte';
  import { scheduler } from '../lib/frame';
  import {
    footerText, framingBounds, gpsStatus, graticule, lastFix, layerPlan, makeSeeder, nearestSite, needsRefit, resolveSite, validTrack, type Bounds, type GpsStatus,
    type LatLon, type SiteInfo,
  } from '../lib/geo';
  import { cardStatus } from '../lib/cards/status';
  import { staleAge } from '../lib/cards/value';
  import { dataVersion, flightSchema, flightStores, hello, segmentStart, serverNow } from '../lib/link';
  import { firstRowFrom, segmentFloor } from '../lib/cards/segment';

  let { id, config }: { id: string; config: Record<string, unknown> } = $props();

  const ATTRIBUTION = 'Basemap: USGS The National Map';
  const TILE_URL = '/tiles/{layer}/{z}/{x}/{y}';
  const MAX_TRACK_POINTS = 4000;
  const FRAME_MIN_KM = 0.8;       // the pad-only view (before and at launch); the frame widens as the path drifts
  const FRAME_PAD_PX = 28;
  const FRAME_MAX_ZOOM = 17;
  const ERROR_TILE = 'data:image/svg+xml,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#2a2a2e"/>'
    + '<text x="128" y="132" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#8a8a92">tile not downloaded</text></svg>');

  const layer = $derived(config.layer === 'topo' ? 'topo' : 'imagery');
  const sourceKey = $derived(config.source === 'A' || config.source === 'B' ? config.source : 'best');
  const sites = $derived(($hello?.sites ?? []) as SiteInfo[]);

  // The selector and follow toggle are per-viewer view state; the preset's config only seeds them.
  let siteId = $state<string | null>(null);
  let follow = $state(true);
  // Re-seed only when the config VALUE changes: CardGrid builds a new config object on every change.
  const seedSite = makeSeeder<string | null>();
  const seedFollow = makeSeeder<boolean>();
  $effect(() => { const v = (config.site as string | null) ?? null; if (seedSite(v)) siteId = v; });
  $effect(() => { const v = config.follow !== false; if (seedFollow(v)) follow = v; });

  // Auto (no site chosen): the registered site nearest the newest GPS fix, kept through dropouts.
  let autoId = $state<string | null>(null);
  const site = $derived(resolveSite(sites, siteId, null, autoId));
  const plan = $derived(site ? layerPlan(site, layer) : null);

  let el: HTMLDivElement;
  let map = $state.raw<L.Map | null>(null);
  let gps = $state<GpsStatus>({ valid: false, position: null, text: 'GPS: no data' });
  let footer = $state('');

  let tileGroup: L.LayerGroup | null = null;
  let gratGroup: L.LayerGroup | null = null;
  let pad: L.CircleMarker | null = null;
  let trackLine: L.Polyline | null = null;
  let here: L.CircleMarker | null = null;
  let trackKey = '';
  let path: LatLon[] = [];
  let moving = false;
  const report = cardStatus();
  let fittedSite = '';

  function storeNow() {
    return (sourceKey === 'A' ? flightStores.A : sourceKey === 'B' ? flightStores.B : undefined) ?? flightStores.best;
  }

  /** Leaflet throws on bounds queries until the map has a centre and zoom (applySite sets them). */
  const hasView = (m: L.Map | null): m is L.Map => !!m && !!(m as unknown as { _loaded?: boolean })._loaded;

  function drawGraticule() {
    if (!hasView(map) || !gratGroup) return;
    gratGroup.clearLayers();
    if (plan?.available) return;
    const b = map.getBounds();
    const g = graticule([[b.getSouth(), b.getWest()], [b.getNorth(), b.getEast()]]);
    const south = b.getSouth(), north = b.getNorth(), west = b.getWest(), east = b.getEast();
    for (const lat of g.lats) {
      L.polyline([[lat, west], [lat, east]], { className: 'map-grat', interactive: false, weight: 1 }).addTo(gratGroup);
      L.marker([lat, west], { interactive: false, icon: L.divIcon({ className: 'map-grat-label', html: lat.toFixed(3) + '°', iconSize: [60, 14], iconAnchor: [-2, 7] }) }).addTo(gratGroup);
    }
    for (const lon of g.lons) {
      L.polyline([[south, lon], [north, lon]], { className: 'map-grat', interactive: false, weight: 1 }).addTo(gratGroup);
      L.marker([south, lon], { interactive: false, icon: L.divIcon({ className: 'map-grat-label', html: lon.toFixed(3) + '°', iconSize: [60, 14], iconAnchor: [30, 16] }) }).addTo(gratGroup);
    }
  }

  function rebuildTiles() {
    if (!map || !tileGroup) return;
    tileGroup.clearLayers();
    if (site && plan?.available) {
      map.setMinZoom(plan.minZoom);
      if (plan.baseMaxNative !== null) {
        L.tileLayer(TILE_URL.replace('{layer}', layer), {
          maxNativeZoom: plan.baseMaxNative, maxZoom: 19, errorTileUrl: ERROR_TILE, attribution: ATTRIBUTION,
        }).addTo(tileGroup);
      }
      if (plan.detailMaxNative !== null) {
        L.tileLayer(TILE_URL.replace('{layer}', layer), {
          minZoom: 14, maxNativeZoom: plan.detailMaxNative, maxZoom: 19, bounds: plan.detailBounds,
          errorTileUrl: ERROR_TILE, attribution: ATTRIBUTION,
        }).addTo(tileGroup);
      }
    } else {
      map.setMinZoom(0);
    }
    drawGraticule();
  }

  function applySite() {
    if (!map) return;
    pad?.remove();
    pad = null;
    if (site) {
      pad = L.circleMarker(site.pad, { radius: 6, className: 'map-pad', interactive: false }).addTo(map);
      if (fittedSite !== site.id) {
        fittedSite = site.id;
        map.fitBounds(framingBounds([], site.pad, FRAME_MIN_KM), { padding: [FRAME_PAD_PX, FRAME_PAD_PX], animate: false });
      }
    } else if (fittedSite !== '-') {
      fittedSite = '-';
      map.setView([0, 0], 2);
    }
    trackKey = '';
  }

  function draw() {
    if (!hasView(map)) return;
    const store = storeNow();
    const latest = store.latest();
    const fix = lastFix(store, $flightSchema);
    const found = fix ? nearestSite(sites, fix) : null;
    if (found && found.id !== autoId) autoId = found.id;
    gps = gpsStatus(latest ? latest.values : null, $flightSchema);
    report(latest
      ? { synthetic: !!(latest.flags & 1), flight: true, age: staleAge(latest.t, serverNow(), 1), fields: ['lat_deg', 'lon_deg', 'gps_fix'] }
      : null);
    const from = firstRowFrom(store, segmentFloor(config.segment, $segmentStart));
    const key = `${sourceKey}:${store.version}:${store.length}:${$flightSchema ? 1 : 0}:${config.show_track !== false}:${from}`;
    if (key !== trackKey) {
      trackKey = key;
      path = validTrack(store, $flightSchema, MAX_TRACK_POINTS, from) as LatLon[];
      const pts = config.show_track === false ? [] : path;
      // Leaflet cannot clip an empty polyline, so the line exists only while it has points.
      if (!pts.length) { trackLine?.remove(); trackLine = null; }
      else if (!trackLine) trackLine = L.polyline(pts, { className: 'map-track', interactive: false, weight: 2 }).addTo(map);
      else trackLine.setLatLngs(pts);
    }
    if (gps.position) {
      if (!here) here = L.circleMarker(gps.position, { radius: 6, className: 'map-here', interactive: false }).addTo(map);
      else here.setLatLng(gps.position);
    } else if (here) {
      here.remove();
      here = null;
    }
    if (follow) frame();
    footer = footerText({ site, layerAvailable: !!plan?.available, position: gps.position });
  }

  /** Follow: keep the whole path (and the pad and vehicle) in view, centred, refitting only when it is needed. */
  function frame() {
    if (!hasView(map) || moving) return;
    const anchor: LatLon | null = site?.pad ?? gps.position;
    if (!anchor) return;
    const want = framingBounds(gps.position ? [...path, gps.position] : path, anchor, FRAME_MIN_KM);
    const b = map.getBounds();
    const view: Bounds = [[b.getSouth(), b.getWest()], [b.getNorth(), b.getEast()]];
    if (needsRefit(view, want)) map.fitBounds(want, { padding: [FRAME_PAD_PX, FRAME_PAD_PX], maxZoom: FRAME_MAX_ZOOM });
  }

  onMount(() => {
    // Fractional zoom lets Follow fit the path tightly instead of jumping a whole zoom level.
    map = L.map(el, { zoomControl: true, attributionControl: true, maxZoom: 19, zoomSnap: 0.25, zoomDelta: 0.5 });
    // Give the map a view at once: layers added to a map that is not loaded yet never get a working renderer.
    map.setView([0, 0], 2);
    fittedSite = '-';
    map.attributionControl.setPrefix(false);
    tileGroup = L.layerGroup().addTo(map);
    gratGroup = L.layerGroup().addTo(map);
    map.on('moveend', drawGraticule);
    map.on('movestart', () => { moving = true; });
    map.on('moveend', () => { moving = false; if (follow) scheduler.markDirty(id); });
    // Any pan or zoom by the user hands the view over to them until Follow is ticked again.
    const manual = () => { follow = false; };
    map.on('dragstart', manual);
    const box = map.getContainer();
    box.addEventListener('wheel', manual, { passive: true });
    box.addEventListener('dblclick', manual);
    box.addEventListener('touchstart', (e) => { if (e.touches.length > 1) manual(); }, { passive: true });
    box.querySelector('.leaflet-control-zoom')?.addEventListener('pointerdown', manual);
    const unregister = scheduler.register(id, draw);
    const unsub = dataVersion.subscribe(() => scheduler.markDirty(id));
    const ro = new ResizeObserver(() => { map?.invalidateSize(); drawGraticule(); });
    ro.observe(el);
    return () => {
      ro.disconnect();
      unsub();
      unregister();
      map?.remove();
      map = null;
    };
  });

  // Site, layer or coverage changed: rebuild the tile layers, the pad and the view.
  $effect(() => {
    if (!map) return;
    void [site, layer, plan];
    applySite();     // first: the view must exist before the graticule asks for bounds
    rebuildTiles();
    scheduler.markDirty(id);
  });
  // Settings that only change what draw() shows.
  $effect(() => {
    void [sourceKey, follow, config.show_track, config.segment, $segmentStart];
    trackKey = '';
    scheduler.markDirty(id);
  });
</script>

<div class="mapcard">
  <div class="bar">
    <select aria-label="Site" value={sites.some((s) => s.id === siteId) ? siteId : ''} disabled={!sites.length}
      title="Auto picks the registered site nearest the vehicle's GPS fix"
      onchange={(e) => (siteId = e.currentTarget.value || null)}>
      {#if !sites.length}<option value="">No sites</option>{:else}<option value="">Auto: {site?.name ?? '—'}</option>{/if}
      {#each sites as s (s.id)}<option value={s.id}>{s.name}</option>{/each}
    </select>
    <label class="follow" title="Keep the whole flight path in view, centred. Panning or zooming turns it off.">
      <input type="checkbox" bind:checked={follow} /> Follow</label>
    <span class="gps" class:bad={!gps.valid}>{gps.text}</span>
  </div>
  <div class="view">
    <div class="map" bind:this={el}></div>
    {#if !gps.valid}
      <div class="overlay" role="status">GPS position invalid: horizontal position unknown</div>
    {/if}
  </div>
  <div class="foot note">{footer}&nbsp;</div>
</div>

<style>
  .mapcard { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 6px 10px; font-size: 12px; }
  .bar select { max-width: 55%; min-width: 0; }
  .follow { display: inline-flex; gap: 4px; align-items: center; }
  .gps { margin-left: auto; font-family: var(--f-mono); color: var(--good); }
  .gps.bad { color: var(--warn); }
  .view { position: relative; flex: 1; min-height: 0; }
  .map { position: absolute; inset: 0; background: var(--wf-bg); }
  .overlay {
    position: absolute; left: 50%; top: 12px; transform: translateX(-50%); z-index: 500; pointer-events: none;
    background: color-mix(in srgb, var(--bg) 85%, transparent); color: var(--warn); border: 1px solid var(--line-2);
    padding: 4px 10px; border-radius: 4px; font-size: 12px; text-align: center; max-width: 90%;
  }
  .foot { padding: 4px 10px; margin: 0; font-size: 12px; min-height: 1.4em; }
  .map :global(.map-track) { stroke: var(--brand); fill: none; }
  .map :global(.map-pad) { stroke: var(--fg); fill: var(--if); fill-opacity: 0.9; }
  .map :global(.map-here) { stroke: var(--fg); fill: var(--brand); fill-opacity: 1; }
  .map :global(.map-grat) { stroke: var(--faint); opacity: 0.5; }
  .map :global(.map-grat-label) { color: var(--faint); font: 10px var(--f-mono); background: none; border: 0; white-space: nowrap; }
  .mapcard :global(.leaflet-container) { background: var(--wf-bg); font-family: var(--f-ui); }
</style>

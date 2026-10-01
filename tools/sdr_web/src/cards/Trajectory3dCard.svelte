<script lang="ts">
  // 3D trajectory: three.js is loaded with a dynamic import so it stays out of the entry chunk. Renders on demand only
  // (data version, controls change, resize, visibility), plus while the camera eases or orbits. Positions and camera
  // framing come from lib/cards/traj.ts; this file is glue.
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import type * as ThreeNS from 'three';
  import { lastFix, makeSeeder, nearestSite, resolveSite, type SiteInfo } from '../lib/geo';
  import {
    altitudeColor, cameraOffset, darken, edgeAverage, fitDistance, followAzimuth, groundProjection, groundTiles, trackPoints, trackSphere,
    type GroundSpan,
  } from '../lib/cards/traj';
  import { scheduler } from '../lib/frame';
  import { cardStatus } from '../lib/cards/status';
  import { staleAge } from '../lib/cards/value';
  import { dataVersion, flightSchema, flightStores, hello, segmentStart, serverNow } from '../lib/link';
  import { firstRowFrom, segmentFloor } from '../lib/cards/segment';

  let { id, config }: { id: string; config: Record<string, unknown> } = $props();

  type CamMode = 'follow' | 'orbit' | 'free';
  const CAM_MODES: { id: CamMode; text: string; title: string }[] = [
    { id: 'follow', text: 'Follow', title: 'Side-on view that keeps the whole flight in frame' },
    { id: 'orbit', text: 'Orbit', title: 'Circle the flight, keeping it all in frame' },
    { id: 'free', text: 'Free', title: 'Drag to rotate, scroll to zoom, right-drag to pan' },
  ];
  const FOV = 45;
  const MIN_RADIUS_M = 40;        // framing radius at liftoff, so the view starts close on the pad
  const FRAME_MARGIN = 1.25;
  const FOLLOW_EL = (15 * Math.PI) / 180;
  const ORBIT_EL = (22 * Math.PI) / 180;
  const MIN_DRIFT_M = 60;         // below this horizontal drift the follow azimuth holds
  const EASE_S = 0.5;             // camera easing time constant
  const GROW_S = 0.12;            // faster when the track outgrows the view (boost), so it never leaves the frame
  const GROUND_RGB: [number, number, number] = [107, 107, 107];   // until the edge colour of the loaded tiles is known
  const GROUND_FILL = `rgb(${GROUND_RGB.join(', ')})`;
  const FEATHER = 0.14;           // fraction of the tile canvas faded into the edge colour on each side
  const EDGE_DARKEN = 0.45;       // the ground beyond the tiles is a darker shade of their edge, so the track and trace stand out
  const TRACK_PX = 3;
  const HALO_PX = 7;              // a dark outline under the track keeps it readable on sand and on sky
  const TRACE_Y = 1.5;            // ground trace height (m): just above the tile plane
  const SHADOW = 0x101012;

  const sites = $derived(($hello?.sites ?? []) as SiteInfo[]);
  // Auto (site null): the registered site nearest the newest GPS fix, kept through dropouts.
  let autoId = $state<string | null>(null);
  const site = $derived(resolveSite(sites, config.site as string | null, null, autoId));
  // Keyed on id and pad values so a hello republish with the same site does not refetch tiles or rebuild the track.
  const siteKey = $derived(site ? `${site.id}|${site.pad[0]}|${site.pad[1]}` : '');
  const layer = $derived(String(config.layer ?? 'imagery'));
  const exaggeration = $derived(Number(config.exaggeration ?? 1));
  const source = $derived(String(config.source ?? 'best'));
  const segment = $derived(config.segment);
  const orbitDps = $derived(Number(config.orbit_dps ?? 6));

  // The camera mode is per-viewer view state; the preset's config only seeds it (as the map's Follow toggle).
  let camMode = $state<CamMode>('follow');
  const seedCam = makeSeeder<CamMode>();
  $effect(() => {
    const v = (['follow', 'orbit', 'free'].includes(config.camera as string) ? config.camera : 'follow') as CamMode;
    if (seedCam(v)) camMode = v;
  });

  let host: HTMLDivElement;
  let mode = $state<'track' | 'column' | null>(null);
  let loadError = $state('');
  let ready = $state(false);

  const report = cardStatus();
  let draw: () => void = () => {};
  let rebuildGround: () => void = () => {};
  let rebuildTrack: () => void = () => {};
  const dirty = () => scheduler.markDirty(id);

  // Redraw when the data, the config or the site changes (the draw function itself is installed after three loads).
  $effect(() => {
    void $dataVersion; void $segmentStart; void segment; void exaggeration; void source; void siteKey; void ready; void camMode;
    const store = flightStores[source as 'best' | 'A' | 'B'] ?? flightStores.best;
    const latest = store.latest();
    const fix = lastFix(store, $flightSchema);
    const found = fix ? nearestSite(sites, fix) : null;
    if (found && found.id !== autoId) autoId = found.id;
    report(latest
      ? { synthetic: !!(latest.flags & 1), flight: true, age: staleAge(latest.t, serverNow(), 1), fields: ['lat_deg', 'lon_deg', 'alt_agl_m'] }
      : null);
    dirty();
  });
  $effect(() => {
    void layer; void siteKey; void ready;
    rebuildGround();
  });

  onMount(() => {
    let disposed = false;
    let cleanup = () => {};

    (async () => {
      let THREE: typeof ThreeNS;
      let OrbitControls: typeof import('three/examples/jsm/controls/OrbitControls.js').OrbitControls;
      let Line2: typeof import('three/examples/jsm/lines/Line2.js').Line2;
      let LineGeometry: typeof import('three/examples/jsm/lines/LineGeometry.js').LineGeometry;
      let LineMaterial: typeof import('three/examples/jsm/lines/LineMaterial.js').LineMaterial;
      try {
        THREE = await import('three');
        ({ OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js'));
        ({ Line2 } = await import('three/examples/jsm/lines/Line2.js'));
        ({ LineGeometry } = await import('three/examples/jsm/lines/LineGeometry.js'));
        ({ LineMaterial } = await import('three/examples/jsm/lines/LineMaterial.js'));
      } catch (e) {
        loadError = `3D view unavailable: ${e instanceof Error ? e.message : String(e)}`;
        return;
      }
      if (disposed) return;

      let renderer: ThreeNS.WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      } catch {
        loadError = '3D view unavailable: WebGL could not start';
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      host.appendChild(renderer.domElement);
      renderer.domElement.style.display = 'block';

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(FOV, 1, 1, 600000);
      camera.position.set(-2500, 1800, 3500);
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.set(0, 400, 0);
      controls.maxPolarAngle = Math.PI / 2 - 0.02;   // stay above the ground
      controls.update();

      // A subtle reference grid over the tile area (it fades with the tiles at distance).
      const grid = new THREE.GridHelper(8000, 16, 0xffffff, 0xffffff);
      const gridMat = grid.material as ThreeNS.Material;
      gridMat.transparent = true;
      gridMat.opacity = 0.14;
      gridMat.depthWrite = false;
      scene.add(grid);
      const padMarker = new THREE.Mesh(new THREE.CylinderGeometry(25, 25, 4, 16), new THREE.MeshBasicMaterial({ color: 0xffffff }));
      scene.add(padMarker);

      // Beyond the tiles: an effectively infinite plane in the average colour of the tile edge, with fog in the same
      // colour, so the imagery fades into the horizon instead of ending at a hard square edge.
      const edgeColor = new THREE.Color(GROUND_FILL);
      const farMat = new THREE.MeshBasicMaterial({ color: edgeColor, polygonOffset: true, polygonOffsetFactor: 4, polygonOffsetUnits: 4 });
      const farGeom = new THREE.PlaneGeometry(1_000_000, 1_000_000);
      farGeom.rotateX(-Math.PI / 2);
      const farPlane = new THREE.Mesh(farGeom, farMat);
      farPlane.position.y = -2;
      scene.add(farPlane);
      scene.fog = new THREE.Fog(edgeColor, 20000, 120000);

      // Ground: the z15 tiles drawn onto `base` (transparent where a tile is missing), composed onto the texture over the
      // edge colour, with the outer band feathered into that colour.
      const TILE_PX = 256;
      let ground: ThreeNS.Mesh | null = null;
      let groundTex: ThreeNS.CanvasTexture | null = null;
      let groundGen = 0;
      let composeTimer: ReturnType<typeof setTimeout> | null = null;

      function disposeGround() {
        if (ground) {
          scene.remove(ground);
          ground.geometry.dispose();
          (ground.material as ThreeNS.Material).dispose();
          ground = null;
        }
        groundTex?.dispose();
        groundTex = null;
        if (composeTimer) clearTimeout(composeTimer);
        composeTimer = null;
      }

      function setEdgeColor(css: string) {
        edgeColor.set(css);
        farMat.color.copy(edgeColor);
        (scene.fog as ThreeNS.Fog).color.copy(edgeColor);
      }

      rebuildGround = () => {
        const gen = ++groundGen;
        disposeGround();
        setEdgeColor(`rgb(${darken(GROUND_RGB, EDGE_DARKEN).join(', ')})`);
        if (!site) { dirty(); return; }
        const span: GroundSpan = groundTiles(site.pad);
        const cols = span.x1 - span.x0 + 1;
        const rows = span.y1 - span.y0 + 1;
        const tileM = span.sizeM / cols;
        const base = document.createElement('canvas');
        base.width = cols * TILE_PX;
        base.height = rows * TILE_PX;
        const bctx = base.getContext('2d');
        const canvas = document.createElement('canvas');
        canvas.width = base.width;
        canvas.height = base.height;
        const ctx = canvas.getContext('2d');
        if (!ctx || !bctx) return;
        const probe = document.createElement('canvas');
        probe.width = probe.height = 64;
        const pctx = probe.getContext('2d', { willReadFrequently: true });
        const tex = new THREE.CanvasTexture(canvas);
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = 4;

        const compose = () => {
          composeTimer = null;
          if (gen !== groundGen) return;
          let rgb: [number, number, number] = GROUND_RGB;
          if (pctx) {
            pctx.clearRect(0, 0, 64, 64);
            pctx.drawImage(base, 0, 0, 64, 64);
            rgb = edgeAverage(pctx.getImageData(0, 0, 64, 64).data, 64, 64, 4) ?? GROUND_RGB;
          }
          rgb = darken(rgb, EDGE_DARKEN);
          const fill = `rgb(${rgb.join(', ')})`;
          setEdgeColor(fill);
          const w = canvas.width;
          const h = canvas.height;
          ctx.fillStyle = fill;
          ctx.fillRect(0, 0, w, h);
          ctx.drawImage(base, 0, 0);
          const fw = w * FEATHER;
          const fh = h * FEATHER;
          // Fade each side from the edge colour (opaque at the border) to the imagery.
          const edge = (x0: number, y0: number, x1: number, y1: number, rx: number, ry: number, rw: number, rh: number) => {
            const g = ctx.createLinearGradient(x0, y0, x1, y1);
            g.addColorStop(0, `rgba(${rgb.join(', ')}, 1)`);
            g.addColorStop(1, `rgba(${rgb.join(', ')}, 0)`);
            ctx.fillStyle = g;
            ctx.fillRect(rx, ry, rw, rh);
          };
          edge(0, 0, fw, 0, 0, 0, fw, h);
          edge(w, 0, w - fw, 0, w - fw, 0, fw, h);
          edge(0, 0, 0, fh, 0, 0, w, fh);
          edge(0, h, 0, h - fh, 0, h - fh, w, fh);
          tex.needsUpdate = true;
          dirty();
        };
        const schedule = () => { if (!composeTimer) composeTimer = setTimeout(compose, 120); };

        const geom = new THREE.PlaneGeometry(cols * tileM, rows * tileM);
        geom.rotateX(-Math.PI / 2);
        const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ map: tex }));
        mesh.position.set(span.originEast + (cols * tileM) / 2, -1, -(span.originNorth - (rows * tileM) / 2));
        scene.add(mesh);
        ground = mesh;
        groundTex = tex;
        compose();
        for (let ty = span.y0; ty <= span.y1; ty++) {
          for (let tx = span.x0; tx <= span.x1; tx++) {
            const img = new Image();
            img.onload = () => {
              if (gen !== groundGen) return;
              bctx.drawImage(img, (tx - span.x0) * TILE_PX, (ty - span.y0) * TILE_PX, TILE_PX, TILE_PX);
              schedule();
            };
            img.onerror = () => { /* a missing tile shows the edge colour */ };
            img.src = `/tiles/${layer}/${span.z}/${tx}/${ty}`;
          }
        }
      };

      // The track: a thick altitude-coloured line over a dark halo, and a dot at the newest point. Under it, the ground
      // trace (the track's 2D projection), a dot under the vehicle and a dashed drop line between the two dots.
      const trackObjs: ThreeNS.Object3D[] = [];
      const lineMats: InstanceType<typeof LineMaterial>[] = [];
      let trackPts: Float32Array = new Float32Array(0);
      function disposeTrack() {
        for (const o of trackObjs) {
          scene.remove(o);
          const m = o as ThreeNS.Mesh;
          m.geometry?.dispose();
          (m.material as ThreeNS.Material | undefined)?.dispose();
        }
        trackObjs.length = 0;
        lineMats.length = 0;
      }
      function addObj<T extends ThreeNS.Object3D>(o: T, order: number): T {
        o.renderOrder = order;
        scene.add(o);
        trackObjs.push(o);
        return o;
      }
      function fatLine(points: Float32Array, px: number, opts: { color?: number; colors?: Float32Array; opacity?: number; under?: boolean }) {
        const g = new LineGeometry();
        g.setPositions(points);
        if (opts.colors) g.setColors(opts.colors);
        const m = new LineMaterial({
          linewidth: px, color: opts.color ?? 0xffffff, vertexColors: !!opts.colors,
          transparent: true,   // all in the transparent pass, so renderOrder (trace, halo, line) decides what is on top
          opacity: opts.opacity ?? 1, fog: false,
          depthWrite: !opts.under,   // an outline or trace must not hide the line drawn over it
        });
        m.resolution.set(sizeW || 1, sizeH || 1);
        lineMats.push(m);
        return new Line2(g, m);
      }
      function dot(at: ArrayLike<number>, px: number, color: ThreeNS.ColorRepresentation) {
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([at[0], at[1], at[2]]), 3));
        return new THREE.Points(g, new THREE.PointsMaterial({ color, size: px, sizeAttenuation: false, fog: false, depthTest: false }));
      }

      // Runs from the scheduled draw only, and rebuilds the track objects just when the inputs changed, so
      // off-screen or frozen cards do no rescans or GPU buffer reallocation.
      let trackKey = '';
      rebuildTrack = () => {
        const schema = get(flightSchema);
        const store = flightStores[source as 'best' | 'A' | 'B'] ?? flightStores.best;
        const from = firstRowFrom(store, segmentFloor(segment, get(segmentStart)));
        const key = `${source}:${store.version}:${store.length}:${schema ? 1 : 0}:${from}:${exaggeration}:${siteKey}`;
        if (key === trackKey) return;
        trackKey = key;
        disposeTrack();
        trackPts = new Float32Array(0);
        if (!schema || !store.length) { mode = null; return; }
        const t = trackPoints(store, schema, site?.pad ?? [0, 0], exaggeration, from);
        mode = t.mode;
        trackPts = t.points;
        const n = t.points.length / 3;
        if (!n) return;
        const colors = new Float32Array(n * 3);
        const top = Math.max(t.maxAlt * exaggeration, 1);
        for (let i = 0; i < n; i++) colors.set(altitudeColor(t.points[i * 3 + 1] / top), i * 3);
        const head = t.points.subarray((n - 1) * 3, n * 3);
        const ground = groundProjection(t.points, TRACE_Y);
        if (n >= 2) {
          if (t.mode === 'track') addObj(fatLine(ground, 2.5, { color: SHADOW, opacity: 0.8, under: true }), 1);
          addObj(fatLine(t.points, HALO_PX, { color: SHADOW, opacity: 0.5, under: true }), 2);
          addObj(fatLine(t.points, TRACK_PX, { colors }), 3);
        }
        if (head[1] > TRACE_Y + 1) {
          const drop = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(head[0], head[1], head[2]), new THREE.Vector3(head[0], TRACE_Y, head[2])]);
          const dropLine = new THREE.Line(drop, new THREE.LineDashedMaterial({ color: SHADOW, dashSize: 6, gapSize: 5, transparent: true, opacity: 0.7, fog: false }));
          dropLine.computeLineDistances();
          (dropLine.material as ThreeNS.LineDashedMaterial).dashSize = Math.max(4, head[1] / 60);
          (dropLine.material as ThreeNS.LineDashedMaterial).gapSize = Math.max(3, head[1] / 90);
          addObj(dropLine, 1);
        }
        addObj(dot([head[0], TRACE_Y, head[2]], 7, SHADOW), 4);
        addObj(dot(head, 10, SHADOW), 5);
        addObj(dot(head, 6, new THREE.Color(...altitudeColor(head[1] / top))), 6);
      };

      // ---- camera: follow and orbit ease toward a pose that fits the whole track; any user input switches to free.
      let az = -0.7;
      let lastFrame = 0;
      const want = new THREE.Vector3();
      const wantTarget = new THREE.Vector3();
      let programmatic = false;
      const onStart = () => { if (!programmatic && camMode !== 'free') camMode = 'free'; };

      /** Move the camera one frame toward its framed pose. True while it still needs more frames. */
      function stepCamera(now: number): boolean {
        const dt = lastFrame ? Math.min(0.25, (now - lastFrame) / 1000) : 0;
        lastFrame = now;
        if (camMode === 'free') { lastFrame = 0; return false; }
        const sphere = trackSphere(trackPts, MIN_RADIUS_M);
        if (camMode === 'follow') az = followAzimuth(trackPts, az, MIN_DRIFT_M);
        else az += (orbitDps * Math.PI / 180) * dt;
        const dist = fitDistance(sphere.r, FOV, camera.aspect || 1, FRAME_MARGIN);
        const off = cameraOffset(az, camMode === 'orbit' ? ORBIT_EL : FOLLOW_EL, dist);
        wantTarget.set(...sphere.center);
        want.set(sphere.center[0] + off[0], Math.max(sphere.center[1] + off[1], 2), sphere.center[2] + off[2]);
        const growing = camera.position.distanceTo(controls.target) < dist * 0.97;
        const k = dt ? 1 - Math.exp(-dt / (growing ? GROW_S : EASE_S)) : 1;
        camera.position.lerp(want, k);
        controls.target.lerp(wantTarget, k);
        programmatic = true;
        controls.update();
        programmatic = false;
        const settled = camera.position.distanceTo(want) < dist * 0.002 && controls.target.distanceTo(wantTarget) < dist * 0.002;
        return camMode === 'orbit' || !settled;
      }

      let sizeW = 0;
      let sizeH = 0;
      draw = () => {
        rebuildTrack();
        const w = host.clientWidth;
        const h = host.clientHeight;
        if (w > 0 && h > 0 && (w !== sizeW || h !== sizeH)) {
          sizeW = w;
          sizeH = h;
          renderer.setSize(w, h, false);
          renderer.domElement.style.width = `${w}px`;
          renderer.domElement.style.height = `${h}px`;
          camera.aspect = w / h;
          for (const m of lineMats) m.resolution.set(w, h);
        }
        const moving = stepCamera(performance.now());
        // Depth precision follows the viewing distance (close on the pad, kilometres out at apogee).
        const d = camera.position.distanceTo(controls.target);
        camera.near = Math.min(500, Math.max(1, d * 0.01));
        const fog = scene.fog as ThreeNS.Fog;
        fog.near = Math.max(15000, d * 4);
        fog.far = fog.near * 6;
        camera.updateProjectionMatrix();
        renderer.render(scene, camera);
        if (moving) dirty();
      };

      const unregister = scheduler.register(id, () => draw());
      const onChange = () => dirty();
      controls.addEventListener('change', onChange);
      controls.addEventListener('start', onStart);
      const ro = new ResizeObserver(onChange);
      ro.observe(host);
      ready = true;
      dirty();

      cleanup = () => {
        unregister();
        controls.removeEventListener('change', onChange);
        controls.removeEventListener('start', onStart);
        controls.dispose();
        ro.disconnect();
        groundGen++;
        disposeGround();
        disposeTrack();
        grid.geometry.dispose();
        gridMat.dispose();
        padMarker.geometry.dispose();
        (padMarker.material as ThreeNS.Material).dispose();
        farGeom.dispose();
        farMat.dispose();
        renderer.dispose();
        renderer.domElement.remove();
        draw = () => {};
        rebuildGround = () => {};
        rebuildTrack = () => {};
      };
    })();

    return () => {
      disposed = true;
      cleanup();
    };
  });
</script>

<div class="traj">
  <div class="host" bind:this={host}></div>
  {#if loadError}
    <p class="note msg">{loadError}</p>
  {:else if !ready}
    <p class="note msg">Loading 3D view</p>
  {:else}
    <div class="seg cam" role="group" aria-label="Camera">
      {#each CAM_MODES as m (m.id)}
        <button aria-pressed={camMode === m.id} title={m.title} onclick={() => (camMode = m.id)}>{m.text}</button>
      {/each}
    </div>
    {#if mode === 'column'}
      <p class="note badge">Horizontal position unknown (GPS invalid)</p>
    {:else if mode === null}
      <p class="note badge">No flight data yet</p>
    {/if}
  {/if}
  {#if ready && !site}<p class="note badge low">No site registry entry: ground is not drawn</p>{/if}
</div>

<style>
  .traj { position: relative; height: 100%; min-height: 0; overflow: hidden; }
  .host { position: absolute; inset: 0; }
  .msg { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; padding: 12px; }
  .badge { position: absolute; top: 8px; left: 8px; padding: 2px 6px; border-radius: 4px; background: color-mix(in srgb, var(--bg, #000) 70%, transparent); pointer-events: none; }
  .badge.low { top: auto; bottom: 8px; }
  .cam { position: absolute; top: 8px; right: 8px; background: color-mix(in srgb, var(--bg) 70%, transparent); backdrop-filter: blur(4px); }
  .cam button { background: transparent; font-size: 12px; padding: 2px 9px; }
</style>

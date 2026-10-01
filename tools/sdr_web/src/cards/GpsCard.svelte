<script lang="ts">
  // GPS fix state, satellite count and position. The fix is always shown as text; colour only reinforces it.
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { scheduler } from '../lib/frame';
  import { flightSchema, flightStores, serverNow, stats } from '../lib/link';
  import { startLive } from '../lib/cards/live';
  import { cardStatus } from '../lib/cards/status';
  import {
    fieldIndex, flightKey, gpsFixLabel, gpsFixLevel, noFlightNotice, otherFramesPerS, sourceLabel, staleAge, type Level,
  } from '../lib/cards/value';

  let { id, config }: { id: string; config: Record<string, any> } = $props(); // eslint-disable-line @typescript-eslint/no-explicit-any

  let view = $state<{ fix: string; level: Level | null; sats: string; lat: string; lon: string } | null>(null);
  const report = cardStatus();
  const FIELDS = ['gps_fix', 'gps_sats', 'lat_deg', 'lon_deg', 'gps_alt_m'];
  let age = $state<number | null>(null);
  let notice = $state<string | null>(null);
  const born = Date.now() / 1000;

  const num = (v: number, d: number) => (Number.isFinite(v) ? v.toFixed(d) : '—');

  function draw() {
    const schema = get(flightSchema);
    const store = flightStores[flightKey(config.source)];
    const latest = store && schema ? store.latest() : null;
    const st = get(stats);
    notice = noFlightNotice({ flightRows: store?.length ?? 0, otherFramesPerS: otherFramesPerS(st?.rates), waitedS: Date.now() / 1000 - born });
    const fi = fieldIndex(schema, 'gps_fix');
    if (!latest || fi < 0) { view = null; age = null; report(null); return; }
    const fix = latest.values[fi];
    const at = (k: string) => latest.values[fieldIndex(schema, k)];
    view = {
      fix: gpsFixLabel(schema, fix), level: gpsFixLevel(schema, fix),
      sats: num(at('gps_sats'), 0), lat: num(at('lat_deg'), 6), lon: num(at('lon_deg'), 6),
    };
    age = staleAge(latest.t, serverNow(), 1);
    report({ synthetic: !!(latest.flags & 1), flight: true, age, fields: FIELDS });
  }

  onMount(() => startLive(id, draw));
  $effect(() => { void [config.source, $flightSchema]; scheduler.markDirty(id); });
</script>

<div class="gps">
  {#if !view}
    <p class="note">Waiting for FLIGHT frames ({sourceLabel(config.source)})</p>
    {#if notice}<p class="note">{notice}</p>{/if}
  {:else}
    <div class="chip {view.level ?? ''} fix" class:dim={age !== null}>Fix: {view.fix}</div>
    <dl class="derived">
      <dt>Satellites</dt><dd class="mono">{view.sats}</dd>
      <dt>Latitude</dt><dd class="mono">{view.lat}</dd>
      <dt>Longitude</dt><dd class="mono">{view.lon}</dd>
    </dl>
  {/if}
</div>

<style>
  .gps { padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
  .fix { align-self: flex-start; font-size: 14px; }
  .dim { opacity: 0.6; }
  dl { margin: 0; }
  dd { margin: 0; text-align: right; }
</style>

<script lang="ts">
  // One flight-field value, big, with optional threshold colouring (always also shown as text) and min/max.
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { scheduler } from '../lib/frame';
  import { dataVersion, flightSchema, flightStores, serverNow, stats } from '../lib/link';
  import { format, unitFor, unitLabel, unitPrefs } from '../lib/units';
  import { MinMax, badgeFor, fieldIndex, noFlightNotice, staleAge, thresholdLevel, type Level } from '../lib/cards/value';

  let { id, config }: { id: string; config: Record<string, any> } = $props(); // eslint-disable-line @typescript-eslint/no-explicit-any

  interface Col {
    name: string; text: string; unit: string; level: Level | null; min: string | null; max: string | null;
    flags: number | null; age: number | null; empty: boolean;
  }
  let cols = $state<Col[]>([]);
  let badge = $state<'REPLAY' | 'SIMULATED' | null>(null);
  let missing = $state(false);
  let notice = $state<string | null>(null);
  const mm = [new MinMax(), new MinMax()];
  const born = Date.now() / 1000;
  let lastKey = '';

  const sources = (): { name: string; key: 'best' | 'A' | 'B' }[] =>
    config.source === 'both' ? [{ name: 'A', key: 'A' }, { name: 'B', key: 'B' }]
      : [{ name: '', key: config.source === 'A' || config.source === 'B' ? config.source : 'best' }];

  function draw() {
    const schema = get(flightSchema);
    const idx = fieldIndex(schema, config.field);
    missing = !!schema && idx < 0;
    const key = `${config.field}|${config.source}`;
    if (key !== lastKey) { mm.forEach((m) => m.reset()); lastKey = key; }
    const field = idx >= 0 ? schema!.fields[idx] : null;
    const unit = field ? unitFor(field.quantity, config.units, get(unitPrefs)) : null;
    const digits = typeof config.digits === 'number' ? config.digits : (field?.digits ?? 1);
    const now = serverNow();
    const profile = get(stats)?.source.profile?.id ?? 'unknown';
    let anyRows = 0;
    badge = null;
    cols = sources().map((s, i) => {
      const store = flightStores[s.key];
      const latest = store && idx >= 0 ? store.latest() : null;
      anyRows += store?.length ?? 0;
      if (!latest || !field) {
        return { name: s.name, text: '—', unit: '', level: null, min: null, max: null, flags: null, age: null, empty: true };
      }
      const si = latest.values[idx];
      if (config.track_minmax) mm[i].push(si);
      const fmt = (v: number | null) => (v === null ? null : format(v, field.quantity, unit, digits));
      badge ??= badgeFor(latest.flags, profile);
      return {
        name: s.name, text: format(si, field.quantity, unit, digits), unit: unitLabel(field.quantity, unit),
        level: thresholdLevel(si, config.thresholds ?? []), min: fmt(mm[i].min), max: fmt(mm[i].max),
        flags: latest.flags, age: staleAge(latest.t, now, 1), empty: false,
      };
    });
    const rates = get(stats)?.rates ?? {};
    notice = noFlightNotice({
      flightRows: anyRows, otherFramesPerS: Object.values(rates).reduce((a, b) => a + (b > 0 ? b : 0), 0),
      waitedS: Date.now() / 1000 - born,
    });
  }

  onMount(() => {
    const off = scheduler.register(id, draw);
    const unsub = dataVersion.subscribe(() => scheduler.markDirty(id));
    const tick = setInterval(() => scheduler.markDirty(id), 500);
    return () => { off(); unsub(); clearInterval(tick); };
  });
  $effect(() => { void [config.field, config.source, config.digits, config.units, config.thresholds, config.track_minmax, $unitPrefs, $flightSchema]; scheduler.markDirty(id); });

  const srcLabel = $derived(config.source === 'both' ? 'A and B' : config.source === 'best' ? 'best' : `channel ${config.source}`);
  const anyStale = $derived(cols.some((c) => c.age !== null));
  const LEVEL_TEXT: Record<Level, string> = { good: 'OK', warn: 'WARN', bad: 'ALERT' };
</script>

<div class="num">
  {#if badge || anyStale}
    <div class="chips">
      {#if badge}<span class="tag">{badge}</span>{/if}
      {#if anyStale}<span class="chip warn" role="status">Stale {cols.find((c) => c.age !== null)?.age?.toFixed(0)} s</span>{/if}
    </div>
  {/if}
  {#if missing}
    <p class="note">This source has no field '{config.field}'.</p>
  {:else if cols.every((c) => c.empty)}
    <p class="note">Waiting for FLIGHT frames ({srcLabel})</p>
    {#if notice}<p class="note">{notice}</p>{/if}
  {:else}
    <div class="row">
      {#each cols as c}
        <div class="col {c.level ?? ''}" class:dim={c.age !== null}>
          {#if c.name}<span class="who">{c.name}</span>{/if}
          <span class="val mono">{c.text}</span><span class="u">{c.unit}</span>
          {#if c.level}<span class="chip {c.level}">{LEVEL_TEXT[c.level]}</span>{/if}
          {#if config.track_minmax && c.min !== null}<span class="mm mono">min {c.min} / max {c.max}</span>{/if}
        </div>
      {/each}
    </div>
    {#if config.track_minmax}<button class="btn" onclick={() => { mm.forEach((m) => m.reset()); scheduler.markDirty(id); }}>Reset min/max</button>{/if}
  {/if}
</div>

<style>
  .num { padding: 10px 12px; height: 100%; display: flex; flex-direction: column; gap: 6px; justify-content: center; container-type: size; }
  .chips { display: flex; gap: 6px; }
  .row { display: flex; gap: 18px; flex-wrap: wrap; align-items: flex-end; }
  .col { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 6px; }
  .val { font-size: clamp(24px, 22cqmin, 72px); font-weight: 500; line-height: 1; }
  .u { color: var(--muted); font-size: 14px; }
  .who { color: var(--muted); font: 600 12px var(--f-ui); }
  .mm { color: var(--muted); font-size: 12px; flex-basis: 100%; }
  .good .val { color: var(--good); }
  .warn .val { color: var(--warn); }
  .bad .val { color: var(--bad); }
  .dim { opacity: 0.6; }
  .btn { align-self: flex-start; padding: 2px 8px; font-size: 12px; }
</style>

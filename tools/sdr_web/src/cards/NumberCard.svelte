<script lang="ts">
  // One flight-field value, big, with optional threshold colouring (always also shown as text) and min/max.
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { scheduler } from '../lib/frame';
  import { flightSchema, flightStores, serverNow, stats } from '../lib/link';
  import { startLive } from '../lib/cards/live';
  import { format, unitFor, unitLabel, unitPrefs } from '../lib/units';
  import { cardStatus } from '../lib/cards/status';
  import {
    MinMax, fieldIndex, flightKey, newCursor, noFlightNotice, otherFramesPerS, pushNewRows, sourceLabel, staleAge,
    thresholdLevel, type Level,
  } from '../lib/cards/value';

  let { id, config }: { id: string; config: Record<string, any> } = $props(); // eslint-disable-line @typescript-eslint/no-explicit-any

  interface Col {
    name: string; label: string; text: string; unit: string; level: Level | null; min: string | null; max: string | null;
    age: number | null; empty: boolean;
  }
  let cols = $state<Col[]>([]);
  const report = cardStatus();
  let missing = $state(false);
  let notice = $state<string | null>(null);
  const mm = [new MinMax(), new MinMax()];
  const cursors = [newCursor(), newCursor()];
  const started = [false, false];
  const born = Date.now() / 1000;
  let lastKey = '';

  const resetMinMax = () => {
    mm.forEach((m) => m.reset());
    cursors.forEach((c, i) => { c.t = -Infinity; c.seq = -Infinity; started[i] = false; });
  };

  const sources = (): { name: string; key: 'best' | 'A' | 'B' }[] =>
    config.source === 'both' ? [{ name: 'A', key: 'A' }, { name: 'B', key: 'B' }] : [{ name: '', key: flightKey(config.source) }];

  function draw() {
    const schema = get(flightSchema);
    const idx = fieldIndex(schema, config.field);
    const seqIdx = fieldIndex(schema, 'seq');
    missing = !!schema && idx < 0;
    const key = `${config.field}|${config.source}`;
    if (key !== lastKey) { resetMinMax(); lastKey = key; }
    const field = idx >= 0 ? schema!.fields[idx] : null;
    const unit = field ? unitFor(field.quantity, config.units, get(unitPrefs)) : null;
    const digits = typeof config.digits === 'number' ? config.digits : (field?.digits ?? 1);
    const now = serverNow();
    const st = get(stats);
    let anyRows = 0;
    let synthetic = false;
    cols = sources().map((s, i) => {
      const store = flightStores[s.key];
      const latest = store && idx >= 0 ? store.latest() : null;
      anyRows += store?.length ?? 0;
      if (!store || !latest || !field) {
        return { name: s.name, label: '', text: '—', unit: '', level: null, min: null, max: null, age: null, empty: true };
      }
      const si = latest.values[idx];
      if (config.track_minmax) {
        if (!started[i]) {
          cursors[i].t = latest.t - 1e-9;   // since mount: history before the card existed does not count
          started[i] = true;
        }
        pushNewRows(store, idx, seqIdx, mm[i], cursors[i]);
      }
      const fmt = (v: number | null) => (v === null ? null : format(v, field.quantity, unit, digits));
      synthetic ||= !!(latest.flags & 1);
      return {
        name: s.name, label: field.label, text: format(si, field.quantity, unit, digits), unit: unitLabel(field.quantity, unit),
        level: thresholdLevel(si, config.thresholds ?? []), min: fmt(mm[i].min), max: fmt(mm[i].max),
        age: staleAge(latest.t, now, 1), empty: false,
      };
    });
    report({ synthetic, flight: true, age: cols.find((c) => c.age !== null)?.age ?? null, fields: [config.field] });
    notice = noFlightNotice({ flightRows: anyRows, otherFramesPerS: otherFramesPerS(st?.rates), waitedS: Date.now() / 1000 - born });
  }

  onMount(() => startLive(id, draw));
  $effect(() => { void [config.field, config.source, config.digits, config.units, config.thresholds, config.track_minmax, $unitPrefs, $flightSchema]; scheduler.markDirty(id); });

  const LEVEL_TEXT: Record<Level, string> = { good: 'GOOD', warn: 'WARN', bad: 'BAD' };
</script>

<div class="num">
  {#if missing}
    <p class="note">This source has no field '{config.field}'.</p>
  {:else if cols.every((c) => c.empty)}
    <p class="note">Waiting for FLIGHT frames ({sourceLabel(config.source)})</p>
    {#if notice}<p class="note">{notice}</p>{/if}
  {:else}
    <div class="row" class:mm-on={config.track_minmax} style:--n={cols.length}
      style:--chars={Math.max(5, ...cols.map((c) => c.text.length + (c.unit ? 1.2 : 0)))}>
      {#each cols as c}
        <div class="col {c.level ?? ''}" class:dim={c.age !== null}>
          {#if c.name}<span class="who">{c.name}</span>{/if}
          <span class="val mono">{c.text}</span><span class="u">{c.unit}</span>
          {#if c.level}<span class="chip {c.level}">{LEVEL_TEXT[c.level]}</span>{/if}
          {#if config.track_minmax && c.min !== null}<span class="mm mono">min {c.min} … max {c.max}{#if c === cols[cols.length - 1]}<button
            class="reset" title="Reset min and max" aria-label="Reset min and max"
            onclick={() => { resetMinMax(); scheduler.markDirty(id); }}>↺</button>{/if}</span>{/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .num { padding: 2px 12px 8px; height: 100%; display: flex; flex-direction: column; gap: 6px; justify-content: center; container-type: size; }
  .row { display: flex; gap: 18px; flex-wrap: wrap; align-items: flex-end; }
  .col { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 6px; }
  /* The card's label line is its header (compact frame), so the number gets the rest of the height. */
  /* Sized to fill the width for the text's length (at least 5 characters, so small values do not jump in size). */
  .val { --fit: calc((100cqw - 24px) / var(--n, 1) / (var(--chars, 6) * 0.64));
    font-size: clamp(18px, min(60cqh, var(--fit)), 132px); font-weight: 500; line-height: 1; }
  .mm-on .val { font-size: clamp(18px, min(44cqh, var(--fit)), 120px); }
  .u { color: var(--muted); font-size: 14px; }
  .who { color: var(--muted); font: 600 12px var(--f-ui); }
  .mm { color: var(--muted); font-size: 12px; flex-basis: 100%; }
  .good .val { color: var(--good); }
  .warn .val { color: var(--warn); }
  .bad .val { color: var(--bad); }
  .dim { opacity: 0.6; }
  .reset { margin-left: 6px; padding: 0 4px; border: 0; background: none; color: var(--muted); cursor: pointer; font-size: 13px; }
  .reset:hover { color: var(--fg); }
</style>

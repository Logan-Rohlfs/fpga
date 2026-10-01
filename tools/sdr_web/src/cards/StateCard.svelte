<script lang="ts">
  // Flight phase as a coloured badge (name always shown), the time in phase (mm:ss), seq and the interlock bits.
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { scheduler } from '../lib/frame';
  import { flightSchema, flightStores, serverNow, stats } from '../lib/link';
  import { startLive } from '../lib/cards/live';
  import { cardStatus } from '../lib/cards/status';
  import {
    decodeBits, fieldIndex, flagLabel, flightKey, formatMmSs, noFlightNotice, otherFramesPerS, sourceLabel, staleAge, timeInPhase,
  } from '../lib/cards/value';

  let { id, config }: { id: string; config: Record<string, any> } = $props(); // eslint-disable-line @typescript-eslint/no-explicit-any

  // Phase hues adapted to the theme tokens; unknown phases get no colour.
  const PHASE_CLASS: Record<string, string> = {
    IDLE: 'idle', ARMED: 'warn', BOOST: 'bad', COAST: 'accent', DESCENT: 'synth', LANDED: 'good',
  };

  let phase = $state<string | null>(null);
  let inPhase = $state<number | null>(null);
  let seq = $state<number | null>(null);
  let bits = $state<{ name: string; on: boolean }[]>([]);
  const report = cardStatus();
  let age = $state<number | null>(null);
  let notice = $state<string | null>(null);
  const born = Date.now() / 1000;

  function draw() {
    const schema = get(flightSchema);
    const store = flightStores[flightKey(config.source)];
    const pi = fieldIndex(schema, 'phase');
    const si = fieldIndex(schema, 'phase_status');
    const qi = fieldIndex(schema, 'seq');
    const latest = store && pi >= 0 ? store.latest() : null;
    const st = get(stats);
    notice = noFlightNotice({ flightRows: store?.length ?? 0, otherFramesPerS: otherFramesPerS(st?.rates), waitedS: Date.now() / 1000 - born });
    if (!latest || !schema) { phase = null; bits = []; age = null; inPhase = null; seq = null; report(null); return; }
    const v = latest.values[pi];
    phase = schema.fields[pi].enum?.[v] ?? `UNKNOWN (${Number.isFinite(v) ? v : '?'})`;
    seq = qi >= 0 && Number.isFinite(latest.values[qi]) ? latest.values[qi] : null;
    const sf = si >= 0 ? schema.fields[si] : null;
    bits = sf?.bits ? decodeBits(latest.values[si], sf.bits) : [];
    inPhase = config.show_time_in_phase ? timeInPhase(store!, pi) : null;
    age = staleAge(latest.t, serverNow(), 1);
    report({ synthetic: !!(latest.flags & 1), flight: true, age, fields: ['phase', 'seq', 'phase_status'] });
  }

  onMount(() => startLive(id, draw));
  $effect(() => { void [config.source, config.show_time_in_phase, $flightSchema]; scheduler.markDirty(id); });
</script>

<div class="state">
  {#if phase === null}
    <p class="note">Waiting for FLIGHT frames ({sourceLabel(config.source)})</p>
    {#if notice}<p class="note">{notice}</p>{/if}
  {:else}
    <div class="main">
      <div class="phase mono {PHASE_CLASS[phase] ?? ''}" class:dim={age !== null}>{phase}</div>
      <div class="note mono">
        {[inPhase !== null ? `${formatMmSs(inPhase)} in phase` : null, seq !== null ? `seq ${seq}` : null].filter(Boolean).join(' · ')}
      </div>
    </div>
    {#if bits.length}
      <!-- On/off is shown by a filled or hollow dot as well as colour; the full name and state are in the tooltip. -->
      <ul class="bits" aria-label="Interlocks">
        {#each bits as b}
          <li class="flag" class:on={b.on} title="{b.name.replace(/_/g, ' ')}: {b.on ? 'on' : 'off'}"
            aria-label="{b.name.replace(/_/g, ' ')}: {b.on ? 'on' : 'off'}">{flagLabel(b.name)}</li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<style>
  /* Phase and flags side by side when the card is wide enough, stacked when it is narrow. */
  .state { padding: 10px 12px; display: flex; flex-wrap: wrap; align-items: flex-start; gap: 8px 16px; container-type: inline-size; }
  .main { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .phase { align-self: flex-start; font-size: clamp(20px, 9cqw, 34px); font-weight: 600; letter-spacing: 0.04em; padding: 2px 12px; border-radius: 6px;
    color: var(--muted); background: color-mix(in srgb, var(--muted) 14%, transparent); }
  .phase.idle { color: var(--muted); }
  .phase.good { color: var(--good); background: color-mix(in srgb, var(--good) 16%, transparent); }
  .phase.warn { color: var(--warn); background: color-mix(in srgb, var(--warn) 16%, transparent); }
  .phase.bad { color: var(--bad); background: color-mix(in srgb, var(--bad) 16%, transparent); }
  .phase.accent { color: var(--accent); background: color-mix(in srgb, var(--accent) 16%, transparent); }
  .phase.synth { color: var(--synth); background: color-mix(in srgb, var(--synth) 16%, transparent); }
  .dim { opacity: 0.6; }
  .bits { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px; flex: 1 1 150px; align-content: flex-start; }
  .flag { display: inline-flex; align-items: center; gap: 5px; padding: 1px 7px 1px 6px; border-radius: 4px; font: 500 12px var(--f-ui);
    white-space: nowrap; color: var(--muted); background: color-mix(in srgb, var(--muted) 10%, transparent); }
  .flag::before { content: ''; width: 7px; height: 7px; border-radius: 50%; box-sizing: border-box; border: 1.5px solid currentColor; }
  .flag.on { color: var(--good); background: color-mix(in srgb, var(--good) 14%, transparent); }
  .flag.on::before { background: currentColor; }
</style>

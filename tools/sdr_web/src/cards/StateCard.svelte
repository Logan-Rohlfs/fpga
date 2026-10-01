<script lang="ts">
  // Flight phase as a large label with the interlock bits and, optionally, the time spent in the phase.
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { scheduler } from '../lib/frame';
  import { dataVersion, flightSchema, flightStores, serverNow, stats } from '../lib/link';
  import { badgeFor, decodeBits, fieldIndex, noFlightNotice, staleAge, timeInPhase } from '../lib/cards/value';

  let { id, config }: { id: string; config: Record<string, any> } = $props(); // eslint-disable-line @typescript-eslint/no-explicit-any

  let phase = $state<string | null>(null);
  let inPhase = $state<number | null>(null);
  let bits = $state<{ name: string; on: boolean }[]>([]);
  let badge = $state<'REPLAY' | 'SIMULATED' | null>(null);
  let age = $state<number | null>(null);
  let notice = $state<string | null>(null);
  const born = Date.now() / 1000;

  const key = () => (config.source === 'A' || config.source === 'B' ? config.source : 'best') as 'best' | 'A' | 'B';

  function draw() {
    const schema = get(flightSchema);
    const store = flightStores[key()];
    const pi = fieldIndex(schema, 'phase');
    const si = fieldIndex(schema, 'phase_status');
    const latest = store && pi >= 0 ? store.latest() : null;
    const rates = get(stats)?.rates ?? {};
    notice = noFlightNotice({
      flightRows: store?.length ?? 0, otherFramesPerS: Object.values(rates).reduce((a, b) => a + (b > 0 ? b : 0), 0),
      waitedS: Date.now() / 1000 - born,
    });
    if (!latest || !schema) { phase = null; bits = []; badge = null; age = null; inPhase = null; return; }
    const v = latest.values[pi];
    phase = schema.fields[pi].enum?.[v] ?? `UNKNOWN (${Number.isFinite(v) ? v : '?'})`;
    const sf = si >= 0 ? schema.fields[si] : null;
    bits = sf?.bits ? decodeBits(latest.values[si], sf.bits) : [];
    inPhase = config.show_time_in_phase ? timeInPhase(store!, pi) : null;
    badge = badgeFor(latest.flags, get(stats)?.source.profile?.id ?? 'unknown');
    age = staleAge(latest.t, serverNow(), 1);
  }

  onMount(() => {
    const off = scheduler.register(id, draw);
    const unsub = dataVersion.subscribe(() => scheduler.markDirty(id));
    const tick = setInterval(() => scheduler.markDirty(id), 500);
    return () => { off(); unsub(); clearInterval(tick); };
  });
  $effect(() => { void [config.source, config.show_time_in_phase, $flightSchema]; scheduler.markDirty(id); });

  const srcLabel = $derived(config.source === 'best' ? 'best' : `channel ${config.source}`);
</script>

<div class="state">
  {#if badge || age !== null}
    <div class="chips">
      {#if badge}<span class="tag">{badge}</span>{/if}
      {#if age !== null}<span class="chip warn" role="status">Stale {age.toFixed(0)} s</span>{/if}
    </div>
  {/if}
  {#if phase === null}
    <p class="note">Waiting for FLIGHT frames ({srcLabel})</p>
    {#if notice}<p class="note">{notice}</p>{/if}
  {:else}
    <div class="phase mono" class:dim={age !== null}>{phase}</div>
    {#if inPhase !== null}<div class="note mono">{inPhase.toFixed(1)} s in phase</div>{/if}
    <ul class="bits">
      {#each bits as b}
        <li class="chip" class:good={b.on} class:off={!b.on}>{b.name.replace(/_/g, ' ')}: {b.on ? 'on' : 'off'}</li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .state { padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
  .chips { display: flex; gap: 6px; }
  .phase { font-size: clamp(22px, 5vw, 40px); font-weight: 600; letter-spacing: 0.04em; }
  .dim { opacity: 0.6; }
  .bits { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
  .bits .chip { text-transform: none; letter-spacing: 0.02em; font-weight: 500; }
  .chip.off { color: var(--muted); background: color-mix(in srgb, var(--muted) 12%, transparent); }
</style>

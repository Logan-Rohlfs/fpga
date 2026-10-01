<script lang="ts">
  // Sensor health bits and interlocks as on/off chips. Every state is text; colour only reinforces it.
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { scheduler } from '../lib/frame';
  import { dataVersion, flightSchema, flightStores, serverNow, stats } from '../lib/link';
  import { badgeFor, decodeBits, fieldIndex, noFlightNotice, staleAge } from '../lib/cards/value';

  let { id, config }: { id: string; config: Record<string, any> } = $props(); // eslint-disable-line @typescript-eslint/no-explicit-any

  type Bit = { name: string; on: boolean };
  let groups = $state<{ title: string; bits: Bit[] }[] | null>(null);
  let badge = $state<'REPLAY' | 'SIMULATED' | null>(null);
  let age = $state<number | null>(null);
  let notice = $state<string | null>(null);
  let profile = $state('unknown');
  const born = Date.now() / 1000;

  const key = () => (config.source === 'A' || config.source === 'B' ? config.source : 'best') as 'best' | 'A' | 'B';

  function draw() {
    const schema = get(flightSchema);
    const store = flightStores[key()];
    const latest = store && schema ? store.latest() : null;
    profile = get(stats)?.source.profile?.id ?? 'unknown';
    const rates = get(stats)?.rates ?? {};
    notice = noFlightNotice({
      flightRows: store?.length ?? 0, otherFramesPerS: Object.values(rates).reduce((a, b) => a + (b > 0 ? b : 0), 0),
      waitedS: Date.now() / 1000 - born,
    });
    if (!latest || !schema) { groups = null; badge = null; age = null; return; }
    const out: { title: string; bits: Bit[] }[] = [];
    for (const k of ['health', 'phase_status']) {
      const i = fieldIndex(schema, k);
      const bits = i >= 0 ? schema.fields[i].bits : undefined;
      if (bits) out.push({ title: schema.fields[i].label, bits: decodeBits(latest.values[i], bits) });
    }
    groups = out;
    badge = badgeFor(latest.flags, profile);
    age = staleAge(latest.t, serverNow(), 1);
  }

  onMount(() => {
    const off = scheduler.register(id, draw);
    const unsub = dataVersion.subscribe(() => scheduler.markDirty(id));
    const tick = setInterval(() => scheduler.markDirty(id), 500);
    return () => { off(); unsub(); clearInterval(tick); };
  });
  $effect(() => { void [config.source, $flightSchema]; scheduler.markDirty(id); });

  const srcLabel = $derived(config.source === 'best' ? 'best' : `channel ${config.source}`);
</script>

<div class="health">
  {#if badge || age !== null}
    <div class="chips">
      {#if badge}<span class="tag">{badge}</span>{/if}
      {#if age !== null}<span class="chip warn" role="status">Stale {age.toFixed(0)} s</span>{/if}
    </div>
  {/if}
  {#if !groups}
    <p class="note">Waiting for FLIGHT frames ({srcLabel})</p>
    {#if notice}<p class="note">{notice}</p>{/if}
  {:else}
    {#each groups as g}
      <section>
        <h3>{g.title}</h3>
        <ul class="bits" class:dim={age !== null}>
          {#each g.bits as b}
            <li class="chip" class:good={b.on} class:off={!b.on}>{b.name.replace(/_/g, ' ')}: {b.on ? 'on' : 'off'}</li>
          {/each}
        </ul>
      </section>
    {/each}
    {#if profile === 'apex_demo'}
      <p class="note">Demo replay: unwired sensors and interlocks read off by design.</p>
    {/if}
  {/if}
</div>

<style>
  .health { padding: 10px 12px; display: flex; flex-direction: column; gap: 10px; }
  .chips { display: flex; gap: 6px; }
  h3 { margin: 0 0 4px; font: 600 11.5px var(--f-ui); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
  .bits { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
  .bits .chip { text-transform: none; letter-spacing: 0.02em; font-weight: 500; }
  .chip.off { color: var(--muted); background: color-mix(in srgb, var(--muted) 12%, transparent); }
  .dim { opacity: 0.6; }
</style>

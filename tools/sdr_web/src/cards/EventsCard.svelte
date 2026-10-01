<script lang="ts">
  // Virtualized event log: one category (flight or link), kind chips as a view filter, newest first by default.
  import VirtualList from '../components/VirtualList.svelte';
  import { FLIGHT_CATEGORY_KINDS, LINK_KINDS, filterEvents, formatEvent, lastLaunch } from '../lib/events';
  import { eventsStore } from '../lib/link';
  import { unitPrefs } from '../lib/units';

  let { config }: { id: string; config: Record<string, unknown> } = $props();

  const category = $derived(config.category === 'link' ? 'link' : 'flight');
  const allKinds = $derived<readonly string[]>(category === 'link' ? LINK_KINDS : FLIGHT_CATEGORY_KINDS);
  // Chip toggles are a local view filter; null means "follow the configured kinds".
  let local = $state<{ category: string; kinds: string[] } | null>(null);
  const kinds = $derived(
    local && local.category === category ? local.kinds : ((config.kinds as string[] | undefined) ?? [...allKinds]),
  );
  const selected = $derived(new Set(kinds));
  const rows = $derived(filterEvents($eventsStore, category, selected, config.newest_first !== false));
  const launchT = $derived(lastLaunch($eventsStore));

  function toggle(k: string) {
    const next = selected.has(k) ? kinds.filter((x) => x !== k) : allKinds.filter((x) => selected.has(x) || x === k);
    local = { category, kinds: next };
  }
  const label = (k: string) => k.replace(/_/g, ' ');
</script>

<div class="events">
  <div class="chips" role="group" aria-label="Event kinds">
    {#each allKinds as k (k)}
      <button class="chip" class:on={selected.has(k)} aria-pressed={selected.has(k)} onclick={() => toggle(k)}>{label(k)}</button>
    {/each}
  </div>
  <div class="list">
    {#if rows.length === 0}
      <p class="note empty">No events yet.</p>
    {:else}
      <VirtualList count={rows.length}>
        {#snippet row(i)}
          {@const e = rows[i]}
          {@const f = formatEvent(e, $unitPrefs, launchT)}
          <span class="t mono">{f.tplus ?? f.time}</span>
          <span class="kind">{label(e.kind)}</span>
          <span class="txt">{f.text}</span>
          {#if f.value}<span class="val mono">{f.value}</span>{/if}
          {#if e.synthetic}<span class="syn" title="Derived from simulated data">SIM</span>{/if}
        {/snippet}
      </VirtualList>
    {/if}
  </div>
</div>

<style>
  .events { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; padding: 6px 8px; border-bottom: 1px solid var(--line); }
  .chip { font: inherit; font-size: 11px; padding: 1px 8px; border-radius: 10px; border: 1px solid var(--line-2); background: transparent; color: var(--muted, inherit); cursor: pointer; }
  .chip.on { color: inherit; border-color: currentColor; }
  .list { flex: 1; min-height: 0; font-size: 12px; }
  .empty { padding: 12px; margin: 0; }
  .t { width: 7.5em; flex: none; padding-left: 8px; }
  .kind { width: 8em; flex: none; text-transform: capitalize; }
  .txt { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .val { flex: none; padding: 0 6px; }
  .syn { flex: none; font-size: 10px; padding: 0 6px; opacity: 0.7; }
</style>

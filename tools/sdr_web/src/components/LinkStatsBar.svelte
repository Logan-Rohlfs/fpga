<script lang="ts">
  import { linkStatsNow } from '../lib/link';
  import Panel from './Panel.svelte';

  const f = $derived($linkStatsNow);
  const parts = $derived(f ? [
    { text: 'from A', n: f.from_a, color: '--ch-a' },
    { text: 'from B only', n: f.from_b, color: '--ch-b' },
    { text: 'neither', n: f.neither_ok, color: '--bad' },
  ].filter((p) => Number.isFinite(p.n)) : []);
  const total = $derived(parts.reduce((sum, p) => sum + p.n, 0) || 1);
</script>

<Panel title="Link statistics" sub="which receiver delivered each telemetry frame" class="wide">
  <div class="pb">
    {#if f}
      <div class="bar" role="img" aria-label={parts.map((p) => `${p.text} ${p.n}`).join(', ')}>
        {#each parts as p (p.text)}<div style="flex: {p.n / total}; background: var({p.color})" title="{p.text}: {p.n}"></div>{/each}
      </div>
      <div class="legend mono">
        {#each parts as p (p.text)}<span style="--c: var({p.color})">{p.text} {p.n} ({((p.n / total) * 100).toFixed(1)}%)</span>{/each}
        <span style="--c: var(--good)">both OK {f.both_ok}</span>
      </div>
    {:else}
      <p class="note">Waiting for LINK_STATS (sent once per second).</p>
    {/if}
  </div>
</Panel>

<style>
  .bar { display: flex; height: 16px; border-radius: 4px; overflow: hidden; gap: 2px; }
  .bar div { min-width: 2px; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 20px; margin-top: 8px; font-size: 12.5px; }
  .legend span::before { content: ''; display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 6px; background: var(--c); }
</style>

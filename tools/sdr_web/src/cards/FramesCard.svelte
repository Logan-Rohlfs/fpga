<script lang="ts">
  // Virtualized raw-frame log, newest first. Text view: one line per frame. Hex view: a header line plus 16-byte hex lines
  // with the trailing CRC bytes highlighted.
  import VirtualList from '../components/VirtualList.svelte';
  import { type FrameFilter, crcSpan, filterFrames, frameLabel, hexGroups } from '../lib/cards/frames';
  import { cardStatus } from '../lib/cards/status';
  import { droppedFrames, frames, role } from '../lib/link';

  let { config }: { id: string; config: Record<string, unknown> } = $props();

  let localView = $state<string | null>(null);   // the text/hex toggle is a local view choice over the configured default
  const view = $derived(localView ?? (config.view === 'hex' ? 'hex' : 'text'));
  const filter = $derived((['all', 'A', 'B', 'best'].includes(config.filter as string) ? config.filter : 'all') as FrameFilter);

  type Line = { head: true; text: string; bad: boolean; syn: boolean } | { head: false; pre: string; crc: string };
  function hexLine(group: string, offset: number, span: [number, number]): Line {
    const bytes = group.match(/../g) ?? [];
    const pre: string[] = [];
    const crc: string[] = [];
    bytes.forEach((b, i) => ((offset + i >= span[0] && offset + i < span[1]) ? crc : pre).push(b));
    return { head: false, pre: pre.join(' '), crc: crc.length ? ` ${crc.join(' ')}` : '' };
  }

  const items = $derived(filterFrames($frames, filter).reverse());
  const mixed = $derived(items.some((m) => m.record.synthetic) && items.some((m) => !m.record.synthetic));
  const report = cardStatus();
  $effect(() => {
    const newest = items[0];
    report(newest ? { synthetic: newest.record.synthetic, flight: newest.record.fields?.apex?.kind === 'FLIGHT', age: null } : null);
  });
  const lines = $derived.by<Line[]>(() => {
    if (view !== 'hex') return [];
    const out: Line[] = [];
    for (const m of items) {
      const l = frameLabel(m);
      out.push({ head: true, text: l.text, bad: l.crcBad, syn: l.synthetic });
      const raw = m.record.raw ?? '';
      const span = crcSpan(raw.length / 2);
      hexGroups(raw).forEach((g, gi) => out.push(hexLine(g, gi * 16, span)));
    }
    return out;
  });
  const count = $derived(view === 'hex' ? lines.length : items.length);
  const showDropped = $derived($role?.budget === 'viewer' && $droppedFrames > 0);
</script>

<div class="frames">
  <div class="bar">
    <div class="seg" role="group" aria-label="Frame view">
      <button class:on={view === 'text'} aria-pressed={view === 'text'} onclick={() => { localView = 'text'; }}>Text</button>
      <button class:on={view === 'hex'} aria-pressed={view === 'hex'} onclick={() => { localView = 'hex'; }}>Hex</button>
    </div>
    {#if showDropped}<span class="note">{$droppedFrames} frames not shown at viewer rate</span>{/if}
  </div>
  <div class="list mono">
    {#if count === 0}
      <p class="note empty">No frames yet.</p>
    {:else}
      <VirtualList {count}>
        {#snippet row(i)}
          {#if view === 'hex'}
            {@const l = lines[i]}
            {#if l.head}
              <span class="head" class:bad={l.bad}>{l.text}</span>{#if mixed && l.syn}<span class="syn" title="Simulated data">SIM</span>{/if}
            {:else}
              <span class="hex">{l.pre}<span class="crc">{l.crc}</span></span>
            {/if}
          {:else}
            {@const l = frameLabel(items[i])}
            <span class="head" class:bad={l.crcBad}>{l.text}</span>{#if mixed && l.synthetic}<span class="syn" title="Simulated data">SIM</span>{/if}
          {/if}
        {/snippet}
      </VirtualList>
    {/if}
  </div>
</div>

<style>
  .frames { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .bar { display: flex; align-items: center; gap: 10px; padding: 6px 8px; border-bottom: 1px solid var(--line); }
  .seg { display: flex; gap: 2px; }
  .seg button { font: inherit; font-size: 11px; padding: 1px 10px; border-radius: 4px; border: 1px solid var(--line-2); background: transparent; color: var(--muted); cursor: pointer; }
  .seg button.on { color: inherit; border-color: currentColor; }
  .list { flex: 1; min-height: 0; font-size: 12px; }
  .empty { padding: 12px; margin: 0; }
  .head, .hex { padding: 0 8px; }
  .syn { flex: none; font-size: 10px; padding: 0 6px; opacity: 0.7; }
  .bad { color: var(--bad); }
  .hex { color: var(--muted); }
  .crc { color: var(--brand); }
</style>

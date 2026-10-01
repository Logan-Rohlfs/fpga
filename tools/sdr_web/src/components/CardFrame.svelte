<script lang="ts">
  // The chrome around every card: header (title, status chips, edit-mode buttons) and visibility reporting
  // to the draw scheduler. The scheduler skips cards that are scrolled out of view or on a hidden tab.
  import type { Snippet } from 'svelte';
  import { onMount } from 'svelte';
  import CardBadges from '../cards/CardBadges.svelte';
  import { headerChips, provideCardStatus } from '../lib/cards/status';
  import { scheduler } from '../lib/frame';
  import { flightSchema, hello, stats } from '../lib/link';

  let { id, title, compact = false, editing = false, showSettings = false, onsettings, onremove, onheaderdown, children }: {
    id: string; title: string; compact?: boolean; editing?: boolean; showSettings?: boolean;
    onsettings?: () => void; onremove?: () => void; onheaderdown?: (e: PointerEvent) => void;
    children: Snippet;
  } = $props();

  // The card inside reports what it shows; the header turns that into the SIMULATED/REPLAY, EMULATED and stale chips.
  const status = provideCardStatus();
  const chips = $derived(headerChips($status, $stats?.source ?? $hello?.source, $flightSchema));

  let root: HTMLElement;
  let intersecting = true;

  function report() {
    scheduler.setVisible(id, intersecting && !document.hidden);
  }
  onMount(() => {
    let io: IntersectionObserver | undefined;
    if (typeof IntersectionObserver !== 'undefined') {
      io = new IntersectionObserver((entries) => {
        intersecting = entries[entries.length - 1].isIntersecting;
        report();
      });
      io.observe(root);
    }
    document.addEventListener('visibilitychange', report);
    return () => {
      io?.disconnect();
      scheduler.setVisible(id, true);   // do not leave a stale hidden flag behind
      document.removeEventListener('visibilitychange', report);
    };
  });
</script>

<section class="panel frame" class:editing bind:this={root} aria-label={title}>
  <header class="ph" class:compact class:grab={editing} role="presentation" onpointerdown={editing ? onheaderdown : undefined}>
    {#if editing}<span class="grip" aria-hidden="true">⋮⋮</span>{/if}
    <h2>{title}</h2>
    <CardBadges {chips} />
    {#if editing || showSettings}
      <div class="right">
        {#if onsettings}<button class="icon" aria-label="{editing ? 'Settings' : 'View settings'} for {title}"
          title={editing ? 'Settings' : 'View settings'} onclick={onsettings} onpointerdown={(e) => e.stopPropagation()}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8.6 1.5h2.8l.4 2.3 1.5.8 2.2-.9 1.4 2.4-1.8 1.5v1.7l1.8 1.5-1.4 2.4-2.2-.9-1.5.8-.4 2.3H8.6l-.4-2.3-1.5-.8-2.2.9-1.4-2.4 1.8-1.5V7.6L3.1 6.1l1.4-2.4 2.2.9 1.5-.8z"/><circle cx="10" cy="10" r="2.6"/></svg>
        </button>{/if}
        {#if editing && onremove}<button class="icon" aria-label="Remove {title}" title="Remove card" onclick={onremove}
          onpointerdown={(e) => e.stopPropagation()}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15"/></svg>
        </button>{/if}
      </div>
    {/if}
  </header>
  <div class="body">{@render children()}</div>
</section>

<style>
  .frame { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
  .body { flex: 1; min-height: 0; overflow: auto; position: relative; }
  .editing { border-style: dashed; border-color: var(--line-2); }
  .grab { cursor: grab; touch-action: none; user-select: none; }
  .grip { color: var(--faint); font: 14px var(--f-mono); letter-spacing: -2px; }
  /* One line, always: the title keeps its room, then the badges shrink (and shorten, see CardBadges), then clip. */
  .ph { flex-wrap: nowrap; align-items: center; min-height: 38px; padding-top: 6px; padding-bottom: 6px; container-type: inline-size; }
  .ph h2 { flex: 0 1 auto; min-width: 4.5em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ph :global(.chips) { flex: 0 100 auto; }
  .right { flex: none; gap: 2px; }
  /* Compact (Value cards): the header is the card's label line, so the value gets the height. */
  .ph.compact { border-bottom: 0; min-height: 0; padding: 5px 6px 0 12px; }
  .ph.compact h2 { font: 500 12.5px var(--f-ui); letter-spacing: 0.01em; text-transform: none; color: var(--muted); }
  .ph.compact .icon { width: 22px; height: 22px; }
  .icon { display: grid; place-items: center; width: 26px; height: 26px; padding: 0; border: 1px solid transparent; border-radius: 5px;
    background: none; color: var(--muted); cursor: pointer; }
  .icon:hover { color: var(--fg); border-color: var(--line-2); background: var(--panel-2); }
  .icon svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linejoin: round; stroke-linecap: round; }
</style>

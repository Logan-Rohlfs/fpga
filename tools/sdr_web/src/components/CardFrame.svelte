<script lang="ts">
  // The chrome around every card: header (title, badge and stale slots, edit-mode buttons) and visibility reporting
  // to the draw scheduler. The scheduler skips cards that are scrolled out of view or on a hidden tab.
  import type { Snippet } from 'svelte';
  import { onMount } from 'svelte';
  import { scheduler } from '../lib/frame';

  let { id, title, editing = false, showSettings = false, onsettings, onremove, onheaderdown, badge, stale, children }: {
    id: string; title: string; editing?: boolean; showSettings?: boolean;
    onsettings?: () => void; onremove?: () => void; onheaderdown?: (e: PointerEvent) => void;
    badge?: Snippet; stale?: Snippet; children: Snippet;
  } = $props();

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
  <header class="ph" class:grab={editing} role="presentation" onpointerdown={editing ? onheaderdown : undefined}>
    {#if editing}<span class="grip" aria-hidden="true">⋮⋮</span>{/if}
    <h2>{title}</h2>
    {#if badge}{@render badge()}{/if}
    {#if stale}{@render stale()}{/if}
    {#if editing || showSettings}
      <div class="right">
        {#if onsettings}<button class="btn" aria-label="Settings for {title}" onclick={onsettings}
          onpointerdown={(e) => e.stopPropagation()}>{editing ? 'Settings' : 'View settings'}</button>{/if}
        {#if editing && onremove}<button class="btn" aria-label="Remove {title}" onclick={onremove}
          onpointerdown={(e) => e.stopPropagation()}>Remove</button>{/if}
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
  .ph { flex-wrap: nowrap; align-items: center; }
  .ph h2 { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .right .btn { padding: 2px 8px; font-size: 12.5px; }
</style>

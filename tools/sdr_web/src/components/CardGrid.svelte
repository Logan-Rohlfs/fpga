<script lang="ts">
  // Cards reorder by dragging their header and resize from the corner (or with arrow keys on the handle).
  // The layout is saved per device in localStorage.
  import { onMount, untrack } from 'svelte';
  import type { CardDef } from '../lib/cards';
  import { type CardLayout, loadLayout, move, resize, saveLayout } from '../lib/layout';

  const ROW_PX = 118;   // matches grid-auto-rows below
  const GAP_PX = 12;

  let { cards, storageKey }: { cards: CardDef[]; storageKey: string } = $props();

  const defaults = (): CardLayout[] => cards.map(({ id, w, h }) => ({ id, w, h }));
  // The storage key is fixed per page, so reading it once at startup is intended.
  let layout = $state<CardLayout[]>(untrack(() => loadLayout(storageKey, defaults())));
  let editing = $state(false);
  let dragId = $state<string | null>(null);
  let grid: HTMLDivElement;
  let cols = $state(4);
  onMount(() => {
    const ro = new ResizeObserver(() => { cols = columns(); });
    ro.observe(grid);
    return () => ro.disconnect();
  });
  function moveBy(id: string, direction: number) {
    const index = layout.findIndex(c => c.id === id);
    const target = layout[index + direction];
    if (target) commit(move(layout, id, target.id, direction > 0));
  }
  const byId = $derived(new Map(cards.map((c) => [c.id, c])));

  const columns = () => getComputedStyle(grid).gridTemplateColumns.split(' ').length;
  function commit(next: CardLayout[]) {
    layout = next;
    saveLayout(storageKey, next);
  }

  function dragStart(e: DragEvent, id: string) {
    dragId = id;
    e.dataTransfer?.setData('text/plain', id);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  }
  function dragOver(e: DragEvent, id: string) {
    if (!dragId || dragId === id) return;
    e.preventDefault();
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const after = (e.clientY - r.top) / r.height + (e.clientX - r.left) / r.width > 1;
    layout = move(layout, dragId, id, after);
  }
  function dragEnd() {
    dragId = null;
    saveLayout(storageKey, layout);
  }

  function startResize(e: PointerEvent, card: CardLayout) {
    e.preventDefault();
    const handle = e.currentTarget as HTMLElement;
    handle.setPointerCapture(e.pointerId);
    const cols = columns();
    const colW = grid.clientWidth / cols;
    const x0 = e.clientX;
    const y0 = e.clientY;
    const onMove = (ev: PointerEvent) => {
      layout = resize(layout, card.id, card.w + Math.round((ev.clientX - x0) / colW),
        card.h + Math.round((ev.clientY - y0) / (ROW_PX + GAP_PX)), cols);
    };
    const onUp = () => {
      handle.removeEventListener('pointermove', onMove);
      handle.removeEventListener('pointerup', onUp);
      handle.removeEventListener('pointercancel', onUp);
      saveLayout(storageKey, layout);
    };
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
    handle.addEventListener('pointercancel', onUp);
  }
  function resizeKey(e: KeyboardEvent, card: CardLayout) {
    const d = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[e.key];
    if (!d) return;
    e.preventDefault();
    commit(resize(layout, card.id, card.w + d[0], card.h + d[1], columns()));
  }
</script>

<div class="bar">
  <button class="btn" aria-pressed={editing} onclick={() => (editing = !editing)}>{editing ? 'Done' : 'Edit layout'}</button>
  <button class="btn" onclick={() => commit(defaults())}>Reset layout</button>
  <p class="note">In edit mode, drag a card by its header and resize it from the corner. The layout is saved on this device.</p>
</div>

<div class="cards" class:editing bind:this={grid}>
  {#each layout as item (item.id)}
    {@const def = byId.get(item.id)}
    {#if def}
      <section class="panel card" class:dragging={dragId === item.id} aria-label={def.title}
        style="grid-column: span {Math.min(item.w, cols)}; grid-row: span {item.h}" draggable={editing}
        ondragstart={(e) => dragStart(e, item.id)} ondragover={(e) => dragOver(e, item.id)} ondragend={dragEnd}>
        <header class="ph">
          {#if editing}<span class="grip" aria-hidden="true">⋮⋮</span>{/if}
          <h2>{def.title}</h2><span class="sub">{def.sub}</span>
          {#if editing}<div class="right">
            <button class="btn" aria-label="Move {def.title} earlier" onclick={() => moveBy(item.id, -1)}>↑</button>
            <button class="btn" aria-label="Move {def.title} later" onclick={() => moveBy(item.id, 1)}>↓</button>
          </div>{/if}
        </header>
        <div class="pb body"><def.component /></div>
        {#if editing}
          <div class="rs" role="button" tabindex="0" aria-label="Resize {def.title} with arrow keys or by dragging"
            onpointerdown={(e) => startResize(e, item)} onkeydown={(e) => resizeKey(e, item)}></div>
        {/if}
      </section>
    {/if}
  {/each}
</div>

<style>
  .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
  .cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); grid-auto-rows: 118px; grid-auto-flow: dense; gap: 12px; }
  .card { position: relative; display: flex; flex-direction: column; overflow: hidden; }
  .body { flex: 1; overflow: auto; min-height: 0; }
  .editing .card { border-style: dashed; border-color: var(--line-2); cursor: grab; }
  .card.dragging { opacity: 0.45; }
  .grip { color: var(--faint); font: 14px var(--f-mono); letter-spacing: -2px; }
  .rs { position: absolute; right: 2px; bottom: 2px; width: 18px; height: 18px; cursor: nwse-resize; touch-action: none;
    background: linear-gradient(135deg, transparent 50%, var(--line-2) 50% 60%, transparent 60% 70%, var(--line-2) 70% 80%, transparent 80%); }
  @media (max-width: 1100px) { .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 600px) {
    .cards { grid-template-columns: minmax(0, 1fr); grid-auto-rows: auto; }
    .card { grid-column: auto !important; grid-row: auto !important; min-height: 140px; }
  }
</style>

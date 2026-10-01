<script lang="ts">
  // The 12-column card grid. All geometry lives in lib/grid.ts; this component measures the DOM, handles pointer and
  // keyboard input and reports the finished layout through `onchange`. Edit mode needs a desktop-width window.
  import type { Component } from 'svelte';
  import PlaceholderCard from '../cards/PlaceholderCard.svelte';
  import { loadComponent } from '../lib/cards/loader';
  import { REGISTRY, cardTitle, minOfType, sanitizeConfig, type Config } from '../lib/cards/registry';
  import {
    COLS, GAP_PX, ROW_PX, type GridCard, addCard, colWidth, compact, modeForWidth, moveCard, newCardId, pxToGrid, reflow,
    removeCard, resizeCard,
  } from '../lib/grid';
  import CardFrame from './CardFrame.svelte';
  import CardSettings from './CardSettings.svelte';

  // `edit` is owned by the caller (the preset bar's Edit/Done); editing also needs a desktop-width window.
  let { cards, editable, edit = false, onchange }: { cards: GridCard[]; editable: boolean; edit?: boolean; onchange: (cards: GridCard[]) => void } = $props();

  let innerWidth = $state(typeof window === 'undefined' ? 1200 : window.innerWidth);
  let preview = $state<GridCard[] | null>(null);
  let drag = $state<{ id: string; px: number; py: number } | null>(null);
  let settingsId = $state<string | null>(null);
  let addType = $state('plot');
  let grid: HTMLDivElement;
  // Resolved card components by type. Loaded once per type (memoized), so layout changes never remount a card.
  let loaded = $state<Record<string, Component<any>>>({});
  $effect(() => {
    if (!edit) settingsId = null;
  });
  $effect(() => {
    for (const t of new Set(cards.map((c) => c.type))) {
      if (loaded[t]) continue;
      loadComponent(t)?.then((c) => { loaded[t] = c; }, (err) => console.error('card load failed', t, err));
    }
  });

  const mode = $derived(modeForWidth(innerWidth));
  const cols = $derived(mode === 'desktop' ? COLS : mode === 'tablet' ? 6 : 1);
  const editing = $derived(editable && edit && mode === 'desktop');
  const shown = $derived(
    preview ?? (mode === 'desktop' ? cards : reflow(cards, mode === 'tablet' ? 6 : 1, minOfType)),
  );
  const placeholder = $derived(drag && preview ? preview.find((c) => c.id === drag!.id) : undefined);
  const settingsCard = $derived(cards.find((c) => c.id === settingsId));

  const cell = (c: GridCard) => `grid-column: ${c.x + 1} / span ${c.w}; grid-row: ${c.y + 1} / span ${c.h}`;
  const sizeOf = (id: string) => minOfType(cards.find((c) => c.id === id)?.type ?? '');

  function finish(next: GridCard[] | null) {
    preview = null;
    drag = null;
    if (next && JSON.stringify(next) !== JSON.stringify(cards)) onchange(next);
  }

  function startDrag(e: PointerEvent, card: GridCard) {
    if (e.button !== 0) return;
    e.preventDefault();
    const handle = e.currentTarget as HTMLElement;
    handle.setPointerCapture(e.pointerId);
    const colW = colWidth(grid.clientWidth);
    const x0 = e.clientX;
    const y0 = e.clientY;
    const onMove = (ev: PointerEvent) => {
      const { dx, dy } = pxToGrid(ev.clientX - x0, ev.clientY - y0, colW);
      drag = { id: card.id, px: ev.clientX - x0, py: ev.clientY - y0 };
      preview = moveCard(cards, card.id, card.x + dx, card.y + dy);
    };
    const end = (commit: boolean) => {
      handle.removeEventListener('pointermove', onMove);
      handle.removeEventListener('pointerup', onUp);
      handle.removeEventListener('pointercancel', onCancel);
      finish(commit ? preview : null);
    };
    const onUp = () => end(true);
    const onCancel = () => end(false);
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
    handle.addEventListener('pointercancel', onCancel);
  }

  function startResize(e: PointerEvent, card: GridCard) {
    if (e.button !== 0) return;
    e.preventDefault();
    const handle = e.currentTarget as HTMLElement;
    handle.setPointerCapture(e.pointerId);
    const colW = colWidth(grid.clientWidth);
    const x0 = e.clientX;
    const y0 = e.clientY;
    const min = minOfType(card.type);
    const onMove = (ev: PointerEvent) => {
      const { dx, dy } = pxToGrid(ev.clientX - x0, ev.clientY - y0, colW);
      preview = resizeCard(cards, card.id, card.w + dx, card.h + dy, min.w, min.h);
    };
    const end = (commit: boolean) => {
      handle.removeEventListener('pointermove', onMove);
      handle.removeEventListener('pointerup', onUp);
      handle.removeEventListener('pointercancel', onCancel);
      finish(commit ? preview : null);
    };
    const onUp = () => end(true);
    const onCancel = () => end(false);
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
    handle.addEventListener('pointercancel', onCancel);
  }

  function onKey(e: KeyboardEvent, card: GridCard) {
    if (e.target !== e.currentTarget) return;   // keys inside a card's own controls are theirs
    const d = ({ ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] } as Record<string, number[]>)[e.key];
    if (!d) return;
    e.preventDefault();
    const min = sizeOf(card.id);
    onchange(e.shiftKey
      ? resizeCard(cards, card.id, card.w + d[0], card.h + d[1], min.w, min.h)
      : moveCard(cards, card.id, card.x + d[0], card.y + d[1]));
  }

  function remove(id: string) {
    if (settingsId === id) settingsId = null;
    onchange(compact(removeCard(cards, id)));
  }

  function add() {
    const meta = REGISTRY[addType];
    if (!meta) return;
    const fresh: GridCard = {
      id: newCardId(cards, addType), type: addType, x: 0, y: 0, w: meta.min.w, h: meta.min.h, title: null,
      config: JSON.parse(JSON.stringify(meta.defaults)) as Config,
    };
    onchange(addCard(cards, fresh, meta.min.w, meta.min.h));
  }

  function setSettings(id: string, next: { title: string | null; config: Config }) {
    onchange(cards.map((c) => (c.id === id ? { ...c, title: next.title, config: next.config } : c)));
  }

  function onWindowKey(e: KeyboardEvent) {
    if (e.key === 'Escape' && settingsId) settingsId = null;
  }
</script>

<svelte:window bind:innerWidth onkeydown={onWindowKey} />

{#if editable}
  <div class="bar">
    {#if mode === 'desktop'}
      {#if editing}
        <label class="add">Card type
          <select bind:value={addType}>
            {#each Object.values(REGISTRY) as m (m.type)}<option value={m.type}>{m.title}</option>{/each}
          </select>
        </label>
        <button class="btn" onclick={add}>Add card</button>
        <p class="note">Drag a card by its header, resize from the corner. With a card focused: arrows move it, Shift+arrows resize it.</p>
      {/if}
    {:else if edit}
      <p class="note">Widen the window to edit the layout.</p>
    {/if}
  </div>
{/if}

<div class="cards" class:editing bind:this={grid}
  style="grid-template-columns: repeat({cols}, minmax(0, 1fr)); grid-auto-rows: {ROW_PX}px; gap: {GAP_PX}px">
  {#if placeholder}<div class="slot" style={cell(placeholder)} aria-hidden="true"></div>{/if}
  {#each shown as card (card.id)}
    {@const meta = REGISTRY[card.type]}
    {@const dragging = drag?.id === card.id}
    {@const at = dragging ? (cards.find((c) => c.id === card.id) ?? card) : card}
    <!-- Focusable only in edit mode, so the arrow keys can move and resize the card. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="cell" class:dragging style="{cell(at)}{dragging ? `; transform: translate(${drag!.px}px, ${drag!.py}px)` : ''}"
      role={editing ? 'group' : undefined} tabindex={editing ? 0 : undefined}
      aria-label={editing ? `${cardTitle(card)}: arrow keys move, Shift and arrows resize` : undefined}
      onkeydown={editing ? (e) => onKey(e, card) : undefined}>
      <CardFrame id={card.id} title={cardTitle(card)} {editing} showSettings={!editable && !!meta}
        onsettings={meta ? () => (settingsId = card.id) : undefined} onremove={() => remove(card.id)}
        onheaderdown={(e) => startDrag(e, card)}>
        {#if meta?.component}
          {@const Card = loaded[card.type]}
          {#if Card}<Card id={card.id} config={sanitizeConfig(card.type, card.config)} />{/if}
        {:else}
          <PlaceholderCard type={card.type} known={!!meta} />
        {/if}
      </CardFrame>
      {#if editing}
        <div class="rs" role="button" tabindex="0" aria-label="Resize {cardTitle(card)} by dragging"
          onpointerdown={(e) => startResize(e, card)}></div>
      {/if}
    </div>
  {/each}
</div>

{#if settingsCard}
  <div class="settings panel" role="dialog" aria-label="Settings for {cardTitle(settingsCard)}">
    <header class="ph">
      <h2>{cardTitle(settingsCard)}</h2>
      <div class="right"><button class="btn" onclick={() => (settingsId = null)}>Close</button></div>
    </header>
    <div class="pb">
      <CardSettings type={settingsCard.type} title={settingsCard.title} config={sanitizeConfig(settingsCard.type, settingsCard.config)}
        readonly={!editing} onchange={(next) => setSettings(settingsCard.id, next)} />
    </div>
  </div>
{/if}

<style>
  .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
  .add { display: inline-flex; align-items: center; gap: 6px; font-size: 13.5px; color: var(--muted); }
  .add select { background: var(--bg); border: 1px solid var(--line-2); border-radius: 4px; padding: 3px 7px; }
  .cards { display: grid; position: relative; }
  .cell { position: relative; min-width: 0; min-height: 0; }
  .cell.dragging { z-index: 5; opacity: 0.85; pointer-events: none; box-shadow: 0 8px 24px rgb(0 0 0 / 0.35); }
  .slot { border: 2px dashed var(--brand); border-radius: 8px; background: color-mix(in srgb, var(--brand) 10%, transparent); }
  .rs { position: absolute; right: 2px; bottom: 2px; width: 18px; height: 18px; cursor: nwse-resize; touch-action: none;
    background: linear-gradient(135deg, transparent 50%, var(--line-2) 50% 60%, transparent 60% 70%, var(--line-2) 70% 80%, transparent 80%); }
  .settings { position: fixed; top: 70px; right: 16px; width: min(380px, calc(100vw - 32px)); max-height: calc(100vh - 100px);
    overflow: auto; z-index: 15; box-shadow: 0 8px 24px rgb(0 0 0 / 0.35); }
</style>

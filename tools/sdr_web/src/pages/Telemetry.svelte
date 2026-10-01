<script lang="ts">
  // Shows a preset through sanitizeGrid. Everyone can pick a layout or follow the Operator's live one. The Operator edits
  // a working copy that stays until it is saved or explicitly discarded; the server confirms every write.
  import CardGrid from '../components/CardGrid.svelte';
  import PresetBar from '../components/PresetBar.svelte';
  import { cardChannels } from '../lib/cards/registry';
  import type { GridCard } from '../lib/grid';
  import { deletePreset, notify, presets, role, savePreset, setDefaultPreset, setLivePreset } from '../lib/link';
  import {
    type Preset, choose, chosenStore, displayedPreset, editStatus, followStore, makeWorkingCopy, serverState, settleWorking, slugify,
    toWire, uniqueId,
  } from '../lib/presets';
  import { telemetryChannels } from '../lib/view';

  const operator = $derived($role?.role === 'admin');
  const displayed = $derived(displayedPreset($presets, $followStore, $chosenStore));
  let working = $state<Preset | null>(null);
  let edit = $state(false);
  const shown = $derived(working ?? displayed);
  const status = $derived(editStatus(working, $presets));
  const cards = $derived<GridCard[]>(shown?.cards ?? []);
  // What a write is waiting on: the server's `presets` broadcast is the only confirmation.
  let pendingSave: { id: string; name: string } | null = null;
  let pendingSaveTimer: ReturnType<typeof setTimeout> | null = null;
  const server = $derived(serverState($presets, shown?.id ?? null));
  let pendingAs = $state<{ id: string; name: string } | null>(null);
  let pendingAsTimer: ReturnType<typeof setTimeout> | null = null;
  let staleKey = '';

  function clearPendingSave() {
    pendingSave = null;
    if (pendingSaveTimer) clearTimeout(pendingSaveTimer);
    pendingSaveTimer = null;
  }
  function clearPendingAs() {
    pendingAs = null;
    if (pendingAsTimer) clearTimeout(pendingAsTimer);
    pendingAsTimer = null;
  }

  // The Operator role can be lost (taken over, logged out): drop edit state, never send from a viewer.
  $effect(() => {
    if (!operator) {
      working = null;
      edit = false;
      clearPendingSave();
      clearPendingAs();
    }
  });

  // The server's copy now matches the working copy: its save landed (or the same edit was made elsewhere).
  $effect(() => {
    const w = working;
    if (w && settleWorking(w, $presets) === null) {
      if (pendingSave?.id === w.id) notify(`Saved "${pendingSave.name}".`);
      clearPendingSave();
      working = null;
    }
  });

  // Save as landed: the new preset exists on the server, so show it and drop the working copy.
  $effect(() => {
    if (pendingAs && $presets?.items.some((p) => p.id === pendingAs!.id)) {
      choose(pendingAs.id);
      notify(`Saved "${pendingAs.name}".`);
      working = null;
      clearPendingAs();
    }
  });

  // Never drop unsaved edits silently when the server's copy moves underneath them.
  $effect(() => {
    const key = working && status.stale ? `${working.id}:${status.stale}:${status.saved?.revision ?? 'x'}` : '';
    if (key && key !== staleKey) {
      notify(
        status.stale === 'deleted'
          ? `"${working!.name}" was deleted on the server. Your edits are kept; use Save as to keep them.`
          : `"${working!.name}" changed on the server while you were editing. Your edits are kept; saving will be refused.`,
        'warn', 12000,
      );
    }
    staleKey = key;
  });

  $effect(() => {
    telemetryChannels.set(cardChannels(cards));
  });

  /** True when it is fine to move away from the current working copy. Confirms before discarding real edits. */
  function leave(): boolean {
    if (working && status.dirty && !confirm('Discard your unsaved layout changes?')) return false;
    working = null;
    return true;
  }

  const select = (id: string) => { if (id && leave()) choose(id); };
  function follow(on: boolean) {
    if (!on) {
      if (displayed) choose(displayed.id);
      else followStore.set(false);
    } else if (leave()) followStore.set(true);
  }
  function edited(next: GridCard[]) {
    const base = working ?? (displayed ? makeWorkingCopy(displayed) : null);
    if (base) working = { ...base, cards: next };
  }
  function save() {
    if (!working || !status.saved || status.builtin) return;
    clearPendingSave();
    pendingSave = { id: working.id, name: working.name };
    pendingSaveTimer = setTimeout(clearPendingSave, 8000);   // a refusal arrives as an error notice, not a broadcast
    savePreset(toWire(working), working.revision);
  }
  function saveAs(name: string) {
    const base = working ?? displayed;
    if (!base) return;
    const id = uniqueId(slugify(name), $presets?.items.map((p) => p.id) ?? []);
    clearPendingAs();
    pendingAs = { id, name };
    pendingAsTimer = setTimeout(clearPendingAs, 8000);   // a refusal arrives as an error notice, not a broadcast
    savePreset(toWire(base, name, id), null);
  }
  function discard() {
    if (confirm('Discard your unsaved layout changes?')) {
      clearPendingSave();
      working = null;
    }
  }
  function remove() {
    const id = shown?.id;
    if (id && server.canDelete && confirm(`Delete the layout "${shown!.name}"?`)) deletePreset(id);
  }
</script>

{#if !$presets}
  <p class="note">Waiting for the card layout from the server.</p>
{:else if !shown}
  <p class="note">The server has no preset to show.</p>
{:else}
  <PresetBar entries={$presets.items} shownId={shown.id} liveId={$presets.live} defaultId={$presets.default}
    follow={$followStore} {operator} {edit} dirty={status.dirty} stale={status.stale}
    saved={server.saved} builtin={server.builtin} canDelete={server.canDelete}
    saveAsPending={!!pendingAs}
    onselect={select} onfollow={follow} onedit={(on) => (edit = on)} onsave={save} onsaveas={saveAs} ondiscard={discard}
    ondelete={remove} onsetlive={() => setLivePreset(shown.id)} onsetdefault={() => setDefaultPreset(shown.id)} />
  <CardGrid {cards} editable={operator} {edit} onchange={edited} />
{/if}

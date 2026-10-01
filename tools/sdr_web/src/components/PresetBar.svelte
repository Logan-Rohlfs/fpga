<script lang="ts">
  // Preset selector, Follow toggle and (for the Operator) edit controls. All decisions live in Telemetry and lib/presets.ts;
  // this only shows state and reports intent. Operator actions are enforced by the server as well.
  import type { Stale } from '../lib/presets';

  interface Entry { id: string; name: string; builtin: boolean }
  let {
    entries, shownId, liveId, defaultId, follow, operator, edit, dirty, stale, saved, builtin, saveAsPending,
    onselect, onfollow, onedit, onsave, onsaveas, ondiscard, ondelete, onsetlive, onsetdefault,
  }: {
    entries: Entry[]; shownId: string | null; liveId: string; defaultId: string; follow: boolean; operator: boolean;
    edit: boolean; dirty: boolean; stale: Stale; saved: boolean; builtin: boolean; saveAsPending: boolean;
    onselect: (id: string) => void; onfollow: (on: boolean) => void; onedit: (on: boolean) => void; onsave: () => void;
    onsaveas: (name: string) => void; ondiscard: () => void; ondelete: () => void; onsetlive: () => void; onsetdefault: () => void;
  } = $props();

  const liveName = $derived(entries.find((e) => e.id === liveId)?.name ?? liveId);
  let naming = $state(false);
  let name = $state('');

  function submitName(e: SubmitEvent) {
    e.preventDefault();
    const text = name.trim();
    if (!text) return;
    naming = false;
    onsaveas(text);
  }
</script>

<div class="bar">
  <label class="pick">Layout
    <select value={shownId ?? ''} onchange={(e) => onselect(e.currentTarget.value)}>
      {#each entries as p (p.id)}<option value={p.id}>{p.name}{p.builtin ? ' (built in)' : ''}</option>{/each}
    </select>
  </label>
  <label class="follow"><input type="checkbox" checked={follow} onchange={(e) => onfollow(e.currentTarget.checked)} />
    Follow operator</label>
  <span class="live" title="The layout the Operator is showing to viewers">Live: {liveName}</span>

  {#if operator}
    <span class="sep" aria-hidden="true"></span>
    <button class="btn" aria-pressed={edit} onclick={() => onedit(!edit)}>{edit ? 'Done' : 'Edit'}</button>
    {#if dirty}<span class="dirty">Unsaved changes</span>{/if}
    <button class="btn primary" disabled={!dirty || !saved || builtin} onclick={onsave}
      title={builtin ? 'Built-in layouts are read-only. Use Save as.' : undefined}>Save</button>
    {#if naming}
      <form class="name" onsubmit={submitName}>
        <input bind:value={name} maxlength="40" placeholder="Layout name" aria-label="New layout name" />
        <button class="btn primary" type="submit" disabled={!name.trim()}>Save</button>
        <button class="btn" type="button" onclick={() => (naming = false)}>Cancel</button>
      </form>
    {:else}
      <button class="btn" disabled={saveAsPending} onclick={() => { name = ''; naming = true; }}>Save as…</button>
    {/if}
    {#if dirty}<button class="btn" onclick={ondiscard}>Discard</button>{/if}
    <button class="btn" disabled={!saved || dirty || shownId === liveId} onclick={onsetlive}
      title={dirty ? 'Save first' : undefined}>Show to viewers</button>
    <button class="btn" disabled={!saved || dirty || shownId === defaultId} onclick={onsetdefault}>Make default</button>
    <button class="btn" disabled={!saved || builtin || shownId === defaultId} onclick={ondelete}
      title={shownId === defaultId ? 'Choose another default first' : undefined}>Delete</button>
  {/if}
</div>
{#if stale === 'changed'}
  <p class="warn" role="status">This layout was changed on the server while you were editing. Your edits are kept, but saving
    will be refused. Use Save as to keep them, or Discard to take the server's version.</p>
{:else if stale === 'deleted'}
  <p class="warn" role="status">This layout no longer exists on the server. Your edits are kept. Use Save as to keep them.</p>
{/if}

<style>
  .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
  .pick, .follow { display: inline-flex; align-items: center; gap: 6px; font-size: 13.5px; color: var(--muted); }
  .pick select, .name input { background: var(--bg); border: 1px solid var(--line-2); border-radius: 4px; padding: 3px 7px; }
  .live { font-size: 13px; color: var(--muted); }
  .dirty { font-size: 13px; color: var(--warn); }
  .sep { width: 1px; align-self: stretch; background: var(--line-2); }
  .name { display: inline-flex; gap: 6px; align-items: center; }
  .warn { margin: 0 0 12px; padding: 8px 12px; border-left: 3px solid var(--warn); font-size: 13.5px; background: var(--panel-2); }
</style>

<script lang="ts">
  // Preset selector, Follow toggle and (for the Operator) edit controls. All decisions live in Telemetry and lib/presets.ts;
  // this only shows state and reports intent. Operator actions are enforced by the server as well.
  import type { Stale } from '../lib/presets';

  interface Entry { id: string; name: string; builtin: boolean }
  let {
    entries, autoSwitch, shownId, liveId, defaultId, follow, operator, edit, dirty, stale, saved, builtin, canDelete, saveAsPending,
    onselect, onfollow, onedit, onsave, onsaveas, ondiscard, ondelete, onsetlive, onsetdefault, onautoswitch, onfullscreen,
  }: {
    entries: Entry[]; autoSwitch: boolean; shownId: string | null; liveId: string; defaultId: string; follow: boolean; operator: boolean;
    edit: boolean; dirty: boolean; stale: Stale; saved: boolean; builtin: boolean; canDelete: boolean; saveAsPending: boolean;
    onselect: (id: string) => void; onfollow: (on: boolean) => void; onedit: (on: boolean) => void; onsave: () => void;
    onsaveas: (name: string) => void; ondiscard: () => void; ondelete: () => void; onsetlive: () => void; onsetdefault: () => void; onautoswitch: (on: boolean) => void;
    onfullscreen: () => void;
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
  {#if autoSwitch && !operator}<span class="live" title="The Operator's layout changes on flight events">Auto-switch on</span>{/if}

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
    <label class="follow" title="Change the live layout on flight events, using the live layout's triggers">
      <input type="checkbox" checked={autoSwitch} onchange={(e) => onautoswitch(e.currentTarget.checked)} />
      Auto-switch</label>
    <button class="btn" disabled={!canDelete} onclick={ondelete}
      title={shownId === defaultId ? 'Choose another default first' : undefined}>Delete</button>
  {/if}
  <button class="btn full" onclick={onfullscreen} title="Show only the cards, filling the screen (F). Esc or F exits.">
    <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 7.5V3h4.5M12.5 3H17v4.5M17 12.5V17h-4.5M7.5 17H3v-4.5"/></svg>
    Full screen</button>
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
  .full { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; }
  .full svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
  .name { display: inline-flex; gap: 6px; align-items: center; }
  .warn { margin: 0 0 12px; padding: 8px 12px; border-left: 3px solid var(--warn); font-size: 13.5px; background: var(--panel-2); }
</style>

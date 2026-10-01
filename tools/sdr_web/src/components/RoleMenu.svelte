<script lang="ts">
  import { link, role, takeover } from '../lib/link';
  import { clockTime } from '../lib/format';
  import { roleLabel } from '../lib/receiver';

  const LABEL_KEY = 'sdr.adminLabel';
  const loadLabel = () => { try { return localStorage.getItem(LABEL_KEY) ?? ''; } catch { return ''; } };
  const saveLabel = (v: string) => { try { localStorage.setItem(LABEL_KEY, v); } catch { /* optional */ } };

  let open = $state(false);
  let label = $state(loadLabel());
  let password = $state('');
  let waiting = $state(false);
  const isAdmin = $derived($role?.role === 'admin');

  $effect(() => { if ($takeover) open = true; });
  $effect(() => { if (waiting && isAdmin) { open = false; waiting = false; password = ''; } });

  function submit(e: SubmitEvent) {
    e.preventDefault();
    saveLabel(label);
    waiting = true;
    link.login(password, label);
  }
  function confirmTakeover() {
    waiting = true;
    link.login(password, label, true);
    takeover.set(null);
  }
  function cancelTakeover() {
    takeover.set(null);
    password = '';
    open = false;
  }
</script>

<div class="role">
  <button class="btn" class:admin={isAdmin} aria-expanded={open} onclick={() => (open = !open)}>
    {roleLabel($role?.role)}{#if !isAdmin && $role?.admin}<span class="muted"> · Operator: {$role.admin.label}</span>{/if}
  </button>
  {#if open}
    <div class="pop panel pb stack" role="dialog" aria-label="Role">
      {#if isAdmin && $role?.admin}
        <p>You are Operator as <b>{$role.admin.label}</b> since {clockTime($role.admin.since)}.</p>
        <button class="btn" onclick={() => { link.logout(); open = false; }}>Switch to Viewer</button>
      {:else if $takeover}
        <p>Operator is held by <b>{$takeover.held_by}</b> since {clockTime($takeover.since)}. Take over? They will become a Viewer.</p>
        <div class="row">
          <button class="btn primary" onclick={confirmTakeover}>Take over</button>
          <button class="btn" onclick={cancelTakeover}>Cancel</button>
        </div>
      {:else if $role && !$role.can_admin}
        <p class="note">No Operator password is set on the server, so only the server machine can become Operator.
          Set one there with <code>./sdr setup --gui-password</code>.</p>
      {:else}
        <form class="stack" onsubmit={submit}>
          <label for="role-label">Your name</label>
          <input id="role-label" bind:value={label} maxlength="32" autocomplete="nickname" placeholder="groundstation" />
          <label for="role-password">Operator password</label>
          <input id="role-password" type="password" bind:value={password} autocomplete="current-password" />
          <button class="btn primary" type="submit">Log in as Operator</button>
        </form>
      {/if}
    </div>
  {/if}
</div>

<style>
  .role { position: relative; }
  .btn.admin { background: var(--brand); border-color: var(--brand); color: #fff; }
  .pop { position: absolute; right: 0; top: calc(100% + 6px); width: min(320px, calc(100vw - 32px)); z-index: 15; box-shadow: 0 8px 24px #0006; }
  .pop p { margin: 0; }
  input { background: var(--bg); border: 1px solid var(--line-2); border-radius: 4px; padding: 5px 8px; }
  label { font-size: 13px; color: var(--muted); }
</style>

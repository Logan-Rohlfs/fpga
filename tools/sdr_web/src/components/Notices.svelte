<script lang="ts">
  import { notices } from '../lib/link';
</script>

<div class="notices" aria-live="polite">
  {#each $notices as n (n.id)}
    <div class="notice panel" class:warn={n.kind === 'warn'}>{n.text}</div>
  {/each}
</div>

<style>
  .notices { position: fixed; right: 16px; bottom: calc(16px + env(safe-area-inset-bottom, 0px)); display: grid; gap: 8px; z-index: 20; max-width: min(420px, calc(100vw - 32px)); }
  .notice { padding: 10px 14px; font-size: 14px; border-left: 3px solid var(--muted); }
  .notice.warn { border-left-color: var(--warn); }
</style>

<script lang="ts">
  // The synthetic/replay badge and the stale chip every flight-fed card shows (spec section 12).
  import { badgeLabel, staleText } from '../lib/cards/value';
  let { badge, age }: { badge: 'REPLAY' | 'SIMULATED' | null; age: number | null } = $props();
  const label = $derived(badge ? badgeLabel(badge) : null);
</script>

{#if label || age !== null}
  <div class="chips">
    {#if label}<span class="tag" title={label.title}>{label.text}</span>{/if}
    {#if age !== null}<span class="chip warn" role="status">{staleText(age)}</span>{/if}
  </div>
{/if}

<style>
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
</style>

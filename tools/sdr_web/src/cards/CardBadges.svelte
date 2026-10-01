<script lang="ts">
  // Header chips from lib/cards/status.ts headerChips (spec section 12): one place renders them for every card.
  // The badges are short ("SIM", "EMU") so they never crowd the title; the full wording is in the tooltip, and the
  // status bar's SIMULATED pill names the source.
  import type { HeaderChips } from '../lib/cards/status';
  let { chips }: { chips: HeaderChips } = $props();
</script>

{#if chips.badge || chips.emulated || chips.stale}
  <div class="chips">
    {#if chips.badge}<span class="tag syn" title="{chips.badge.text}: {chips.badge.title}">SIM</span>{/if}
    {#if chips.emulated}<span class="tag emu" title="{chips.emulated.text}: {chips.emulated.title}">EMU</span>{/if}
    {#if chips.stale}<span class="chip warn" role="status">{chips.stale}</span>{/if}
  </div>
{/if}

<style>
  .chips { display: flex; gap: 6px; flex-wrap: nowrap; min-width: 0; overflow: hidden; }
  .chips > * { white-space: nowrap; }
  .tag.syn { color: var(--synth); border-color: color-mix(in srgb, var(--synth) 50%, transparent); }
</style>

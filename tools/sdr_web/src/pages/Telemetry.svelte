<script lang="ts">
  // Shows the server's live preset through sanitizeGrid. Local edits stay a working copy until Task 11 adds
  // save and preset selection; nothing here talks to the server yet.
  import CardGrid from '../components/CardGrid.svelte';
  import { cardChannels, minOfType, sanitizeConfig } from '../lib/cards/registry';
  import { type GridCard, sanitizeGrid } from '../lib/grid';
  import { presets, role } from '../lib/link';
  import { telemetryChannels } from '../lib/view';

  const live = $derived($presets?.items.find((p) => p.id === $presets?.live));
  const fromServer = $derived<GridCard[]>(
    live ? sanitizeGrid(live.cards, minOfType).map((c) => ({ ...c, config: sanitizeConfig(c.type, c.config) })) : [],
  );
  // The working copy follows the live preset's identity and revision; local edits replace it until then.
  let edits = $state<{ key: string; cards: GridCard[] } | null>(null);
  const key = $derived(live ? `${live.id}@${live.revision}` : '');
  const cards = $derived(edits && edits.key === key ? edits.cards : fromServer);

  $effect(() => {
    telemetryChannels.set(cardChannels(cards));
  });
</script>

{#if !$presets}
  <p class="note">Waiting for the card layout from the server.</p>
{:else if !live}
  <p class="note">The server has no preset to show.</p>
{:else}
  <CardGrid {cards} editable={$role?.role === 'admin'} onchange={(next) => (edits = { key, cards: next })} />
{/if}

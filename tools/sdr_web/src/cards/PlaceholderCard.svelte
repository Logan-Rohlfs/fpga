<script lang="ts">
  // Stands in for a card whose component has not landed (known type) or that this build does not know (newer server).
  let { type, known }: { type: string; known: boolean } = $props();
</script>

<p class="note placeholder">{known ? 'Card not implemented yet' : `Unsupported card type '${type}'`}</p>

<style>
  .placeholder { padding: 12px; margin: 0; display: grid; place-items: center; height: 100%; text-align: center; }
</style>

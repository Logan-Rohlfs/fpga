<script lang="ts" generics="T extends string">
  let { label, options, value, disabled = false, onselect }:
    { label: string; options: { value: T; text: string }[]; value: T; disabled?: boolean; onselect: (v: T) => void } =
    $props();
</script>

<div class="seg" role="group" aria-label={label}>
  {#each options as o (o.value)}
    <button type="button" aria-pressed={o.value === value} {disabled} onclick={() => onselect(o.value)}>{o.text}</button>
  {/each}
</div>

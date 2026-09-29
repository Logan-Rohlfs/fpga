<script lang="ts">
  let { id, label, value, options, disabled = false, oncommit }:
    { id: string; label: string; value: number; options: readonly number[]; disabled?: boolean;
      oncommit: (v: number) => void } = $props();
</script>

<div class="field">
  <label for={id}>{label}</label>
  <select {id} {disabled} value={String(value)} onchange={(e) => oncommit(Number(e.currentTarget.value))}>
    {#each options as o (o)}<option value={String(o)}>{o}</option>{/each}
  </select>
</div>

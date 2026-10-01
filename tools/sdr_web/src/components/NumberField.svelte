<script lang="ts">
  // Shows `value / scale`; commits `input * scale` on change (Enter or blur). The server validates.
  let { id, label, value, scale = 1, digits = 0, step = 1, disabled = false, oncommit }:
    { id: string; label: string; value: number; scale?: number; digits?: number; step?: number; disabled?: boolean;
      oncommit: (v: number) => void } = $props();

  function commit(e: Event & { currentTarget: HTMLInputElement }) {
    const v = e.currentTarget.valueAsNumber;
    if (Number.isFinite(v)) oncommit(v * scale);
    e.currentTarget.value = (value / scale).toFixed(digits);
  }
</script>

<div class="field">
  <label for={id}>{label}</label>
  <input {id} type="number" {step} {disabled} value={(value / scale).toFixed(digits)} onchange={commit} />
</div>

<script lang="ts">
  // SDR++-style frequency readout: scroll a digit, click its upper/lower half, or use ↑/↓ when focused.
  import { onMount } from 'svelte';

  let { hz, stepHz, revision, disabled = false, onchange }:
    { hz: number; stepHz: number; revision?: object; disabled?: boolean; onchange: (hz: number) => void } = $props();

  let pending = $state<number | null>(null);
  let box: HTMLDivElement;

  $effect(() => {
    void revision;
    void hz;          // a server update replaces local, not-yet-echoed edits
    pending = null;
  });
  const shown = $derived(pending ?? hz);
  const digits = $derived(String(Math.max(0, Math.round(shown))).padStart(9, '0').split(''));
  const places = $derived(digits.map((_, i) => digits.length - i - 1));
  const lead = $derived(digits.findIndex((d) => d !== '0'));

  function bump(place: number, dir: number) {
    if (disabled) return;
    pending = shown + dir * Math.max(10 ** place, stepHz);
    onchange(pending);
  }
  function click(e: MouseEvent, place: number) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    bump(place, e.clientY < r.top + r.height / 2 ? 1 : -1);
  }
  function key(e: KeyboardEvent, place: number) {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    bump(place, e.key === 'ArrowUp' ? 1 : -1);
  }

  onMount(() => {
    const wheel = (e: WheelEvent) => {
      const el = (e.target as HTMLElement).closest<HTMLElement>('[data-place]');
      if (!el || disabled) return;
      e.preventDefault();
      bump(Number(el.dataset.place), e.deltaY < 0 ? 1 : -1);
    };
    box.addEventListener('wheel', wheel, { passive: false });
    return () => box.removeEventListener('wheel', wheel);
  });
</script>

<div class="digits" class:disabled bind:this={box}>
  {#each places as place, i (place)}
    <span class="d" class:lead={lead < 0 || i < lead} data-place={place} role="spinbutton" tabindex={disabled ? -1 : 0}
      aria-label="LO digit for 10^{place} Hz" aria-valuenow={Number(digits[i])} aria-valuemin={0} aria-valuemax={9}
      aria-disabled={disabled} onclick={(e) => click(e, place)} onkeydown={(e) => key(e, place)}>{digits[i]}</span>
    {#if place === 6}<span class="sep">.</span>{:else if place > 0 && place % 3 === 0}<span class="sep"> </span>{/if}
  {/each}
  <span class="unit">MHz</span>
</div>

<style>
  .digits { display: inline-flex; align-items: baseline; font: 500 30px/1.1 var(--f-mono); color: var(--lo); user-select: none; }
  .d { padding: 0 1px; border-radius: 3px; cursor: ns-resize; }
  .d:hover, .d:focus-visible { background: color-mix(in srgb, var(--lo) 18%, transparent); outline: none; }
  .d.lead { color: color-mix(in srgb, var(--lo) 40%, var(--bg)); }
  .disabled .d { cursor: default; }
  .disabled .d:hover { background: none; }
  .sep { color: var(--faint); padding: 0 1px; }
  .unit { font: 14px var(--f-ui); color: var(--muted); margin-left: 6px; }
  @media (max-width: 600px) { .digits { font-size: 24px; } }
</style>

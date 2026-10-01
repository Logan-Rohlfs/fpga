<script lang="ts">
  // Fixed-row-height windowed list: only the visible rows (plus overscan) are in the DOM.
  import type { Snippet } from 'svelte';
  import { windowRange } from '../lib/virtual';

  let { count, rowH = 22, row }: { count: number; rowH?: number; row: Snippet<[number]> } = $props();

  let scrollTop = $state(0);
  let viewportH = $state(0);
  const win = $derived(windowRange(scrollTop, viewportH, rowH, count));
  const indices = $derived(Array.from({ length: win.end - win.start }, (_, i) => win.start + i));
</script>

<div class="vl" bind:clientHeight={viewportH} onscroll={(e) => { scrollTop = e.currentTarget.scrollTop; }}>
  <div style="height:{win.padTop}px"></div>
  {#each indices as i (i)}
    <div class="vrow" style="height:{rowH}px">{@render row(i)}</div>
  {/each}
  <div style="height:{win.padBottom}px"></div>
</div>

<style>
  .vl { height: 100%; overflow-y: auto; overflow-x: hidden; }
  .vrow { overflow: hidden; white-space: nowrap; box-sizing: border-box; display: flex; align-items: center; }
</style>

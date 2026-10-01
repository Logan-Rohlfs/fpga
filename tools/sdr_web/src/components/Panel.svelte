<script lang="ts">
  import type { Snippet } from 'svelte';

  // `swatch` is a CSS color token (e.g. '--ch-a') shown before the title to identify a channel.
  let { title, sub = '', swatch = '', actions, children, class: cls = '' }:
    { title: string; sub?: string; swatch?: string; actions?: Snippet; children: Snippet; class?: string } = $props();
</script>

<section class="panel {cls}" aria-label={title}>
  <header class="ph">
    {#if swatch}<span class="swatch" style="background: var({swatch})" aria-hidden="true"></span>{/if}
    <h2>{title}</h2>
    {#if sub}<span class="sub">{sub}</span>{/if}
    {#if actions}<div class="right">{@render actions()}</div>{/if}
  </header>
  {@render children()}
</section>

<style>
  .swatch { width: 10px; height: 10px; border-radius: 2px; align-self: center; }
</style>

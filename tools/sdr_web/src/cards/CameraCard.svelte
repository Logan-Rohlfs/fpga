<script lang="ts">
  import { cameraState, cameraUrlOk } from '../lib/cards/camera';

  let { config }: { id?: string; config: { url: string | null; mode: string; fit: string } } = $props();

  let errored = $state(false);
  let onScreen = $state(true);
  let tabShown = $state(typeof document === 'undefined' ? true : !document.hidden);
  let box: HTMLDivElement | undefined = $state();

  const status = $derived(cameraState(config.url, errored));
  // The stream is only pulled while the card is on screen, to save hotspot bandwidth.
  const src = $derived(status === 'ok' && onScreen && tabShown && cameraUrlOk(config.url) ? config.url : undefined);

  // A new URL gets a fresh chance.
  $effect(() => {
    void config.url;
    errored = false;
  });

  $effect(() => {
    if (!box || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) onScreen = e.isIntersecting;
    });
    io.observe(box);
    return () => io.disconnect();
  });

  $effect(() => {
    const on = () => (tabShown = !document.hidden);
    document.addEventListener('visibilitychange', on);
    return () => document.removeEventListener('visibilitychange', on);
  });
</script>

<div class="cam" bind:this={box}>
  <div class="view">
    {#if status === 'empty'}
      <p class="note msg">No video source. The operator can set a stream URL in card settings.</p>
    {:else if status === 'error'}
      <p class="note msg">Video source unreachable: {config.url}</p>
    {:else if !src}
      <!-- The element is removed entirely so the browser drops the connection. -->
      <p class="note msg">Stream paused while this card is off screen.</p>
    {:else if config.mode === 'video'}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video {src} autoplay muted playsinline style:object-fit={config.fit} onerror={() => (errored = true)}></video>
    {:else}
      <img {src} alt="Camera stream" style:object-fit={config.fit} onerror={() => (errored = true)} />
    {/if}
  </div>
  <p class="note foot">Each viewer pulls this stream directly.</p>
</div>

<style>
  .cam { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .view { flex: 1; min-height: 0; display: grid; place-items: center; background: #000; }
  .view img, .view video { width: 100%; height: 100%; display: block; }
  .msg { margin: 0; padding: 12px; text-align: center; overflow-wrap: anywhere; }
  .foot { margin: 0; padding: 4px 8px; font-size: 0.8em; }
</style>

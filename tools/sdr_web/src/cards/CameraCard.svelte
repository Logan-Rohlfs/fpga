<script lang="ts">
  import { get } from 'svelte/store';
  import {
    type DemoPlayback, cameraState, cameraUrlOk, demoPlayback, mediaNameOk, mediaUrl, needsSeek,
  } from '../lib/cards/camera';
  import { eventsStore, serverNow } from '../lib/link';

  let { config }: {
    id?: string;
    config: { url: string | null; mode: string; fit: string; media: string | null; launch_offset_s: number };
  } = $props();

  let errored = $state(false);
  let onScreen = $state(true);
  let tabShown = $state(typeof document === 'undefined' ? true : !document.hidden);
  let box: HTMLDivElement | undefined = $state();
  let video: HTMLVideoElement | undefined = $state();
  let demo: DemoPlayback = $state({ phase: 'pad', time: 0, tPlus: null });

  const isDemo = $derived(config.mode === 'demo');
  const status = $derived(
    isDemo ? (!mediaNameOk(config.media) ? 'empty' : errored ? 'error' : 'ok') : cameraState(config.url, errored),
  );
  const target = $derived(isDemo ? (mediaNameOk(config.media) ? mediaUrl(config.media) : undefined)
    : cameraUrlOk(config.url) ? config.url : undefined);
  // The stream is only pulled while the card is on screen, to save hotspot bandwidth.
  const src = $derived(status === 'ok' && onScreen && tabShown ? target : undefined);

  // A new source gets a fresh chance.
  $effect(() => {
    void [config.url, config.mode, config.media];
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

  /** Demo mode: hold the pad frame until LAUNCH, then play in step with the time since it. */
  function sync(): void {
    const v = video;
    if (!v || !isDemo) return;
    const duration = Number.isFinite(v.duration) ? v.duration : null;
    demo = demoPlayback(get(eventsStore), serverNow(), config.launch_offset_s, duration);
    if (v.readyState < HTMLMediaElement.HAVE_METADATA) return;
    if (needsSeek(v.currentTime, demo.time)) v.currentTime = demo.time;
    if (demo.phase === 'flight') {
      if (v.paused) v.play().catch(() => {});
    } else if (!v.paused) v.pause();
  }

  // Events (launch, reset) apply at once; the tick corrects drift and runs the T+ readout.
  $effect(() => {
    void $eventsStore;
    void config.launch_offset_s;
    sync();
  });
  $effect(() => {
    if (!isDemo || !video) return;
    const tick = setInterval(sync, 250);
    return () => clearInterval(tick);
  });

  const demoLabel = $derived(
    demo.phase === 'pad' ? 'Waiting for launch' : demo.phase === 'ended' ? `End of clip · T+${demo.tPlus?.toFixed(0)} s`
      : `T+${demo.tPlus?.toFixed(1)} s`,
  );
</script>

<div class="cam" bind:this={box}>
  <div class="view">
    {#if status === 'empty' && isDemo}
      <p class="note msg">No demo clip set. The operator can name a .mp4 or .webm file in .sdr/media in card settings.</p>
    {:else if status === 'empty'}
      <p class="note msg">No video source. The operator can set a stream URL in card settings.</p>
    {:else if status === 'error' && isDemo}
      <p class="note msg">Demo clip not found on the server: .sdr/media/{config.media}</p>
    {:else if status === 'error'}
      <p class="note msg">Video source unreachable: {config.url}</p>
    {:else if !src}
      <!-- The element is removed entirely so the browser drops the connection. -->
      <p class="note msg">Stream paused while this card is off screen.</p>
    {:else if isDemo}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video bind:this={video} {src} muted playsinline preload="auto" style:object-fit={config.fit}
        onloadedmetadata={sync} onerror={() => (errored = true)}></video>
      <span class="tag demo">Demo clip · not live</span>
      <span class="clock">{demoLabel}</span>
    {:else if config.mode === 'video'}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video {src} autoplay muted playsinline style:object-fit={config.fit} onerror={() => (errored = true)}></video>
    {:else}
      <img {src} alt="Camera stream" style:object-fit={config.fit} onerror={() => (errored = true)} />
    {/if}
  </div>
  {#if isDemo}
    <p class="note foot">Recorded demo footage, synced to LAUNCH; it loops on each flight reset. Each viewer downloads it from this server.</p>
  {:else}
    <p class="note foot">Each viewer pulls this stream directly.</p>
  {/if}
</div>

<style>
  .cam { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .view { position: relative; flex: 1; min-height: 0; display: grid; place-items: center; background: #000; }
  .view img, .view video { width: 100%; height: 100%; display: block; }
  .msg { margin: 0; padding: 12px; text-align: center; overflow-wrap: anywhere; }
  .foot { margin: 0; padding: 4px 8px; font-size: 0.8em; }
  .demo { position: absolute; top: 8px; left: 8px; color: var(--synth); border-color: var(--synth); background: rgb(0 0 0 / 0.6); }
  .clock {
    position: absolute; bottom: 8px; left: 8px; padding: 1px 6px; border-radius: 3px;
    background: rgb(0 0 0 / 0.6); color: #fff; font: 600 12px var(--f-mono, monospace); font-variant-numeric: tabular-nums;
  }
</style>

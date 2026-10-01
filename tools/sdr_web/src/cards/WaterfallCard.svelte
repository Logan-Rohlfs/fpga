<script lang="ts">
  // Scrolling waterfall for one channel. Rows keep filling while frozen (the scheduler skips drawing only).
  // Axis comes from each row's f0_hz/bin_hz/bins; the bin count is never assumed.
  import { onMount } from 'svelte';
  import { PAD, makeAxis } from '../lib/axis';
  import { niceStep, rowSpan, scaleLimits, viewerRateNote } from '../lib/cards/spectral';
  import { cssVar, drawFreqTicks, fitCanvas } from '../lib/draw';
  import { scheduler } from '../lib/frame';
  import { onSpectrum, onSpectrumReset, role } from '../lib/link';
  import { appearanceVersion } from '../lib/theme';
  import type { Channel, SpectrumMsg } from '../lib/types';
  import { WaterfallImage } from '../lib/waterfall';

  let { id, config }: { id: string; config: Record<string, unknown> } = $props();
  const channel = $derived(config.channel as Channel);
  const scale = $derived(config.scale);

  const ROWS = 200;
  let cv: HTMLCanvasElement;
  let image: WaterfallImage | null = null;
  let last: SpectrumMsg | null = null;
  let synth = $state(false);
  let bins = $state(0);
  let rate = $derived(viewerRateNote($role?.budget ?? 'operator'));

  const limits = () => scaleLimits(scale, last);
  const dirty = () => scheduler.markDirty(id);

  function draw() {
    const { ctx, w, h } = fitCanvas(cv);
    ctx.fillStyle = cssVar('--wf-bg');
    ctx.fillRect(0, 0, w, h);
    if (!last || !image) {
      ctx.fillStyle = cssVar('--muted');
      ctx.font = '14px "Jost", system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(`Waiting for channel ${channel} spectrum…`, w / 2, h / 2);
      return;
    }
    const axisH = 18;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(image.canvas, PAD.left, 0, w - PAD.left - PAD.right, h - axisH);
    const [f0, f1] = rowSpan(last);
    const a = makeAxis(f0, f1, w);
    const step = niceStep(f1 - f0, Math.max(2, Math.floor(w / 90)));
    const kHz = step >= 1000;
    drawFreqTicks(ctx, a, h - 4, step, (f) => (kHz ? (f / 1e3).toFixed(step >= 1e4 ? 0 : 1) : f.toFixed(0)), kHz ? 'kHz' : 'Hz');
    const [low, high] = limits();
    ctx.fillStyle = cssVar('--faint');
    ctx.font = '11px "JetBrains Mono", ui-monospace, monospace';
    ctx.textAlign = 'right';
    ctx.fillText(`${high}`, PAD.left - 6, 12);
    ctx.fillText(`${low}`, PAD.left - 6, h - axisH - 2);
    ctx.fillText('dBFS', PAD.left - 6, (h - axisH) / 2);
  }

  $effect(() => {
    void channel;
    image = null;
    last = null;
    synth = false;
    bins = 0;
    dirty();
  });
  $effect(() => {
    void $appearanceVersion;
    void scale;
    dirty();
  });

  onMount(() => {
    const unregister = scheduler.register(id, draw);
    const off = onSpectrum((m) => {
      if (m.channel !== channel) return;
      if (!image || image.bins !== m.bins) image = new WaterfallImage(m.bins, ROWS);
      last = m;
      synth = m.synthetic;
      bins = m.bins;
      const [low, high] = limits();
      image.push(m.db10, low, high);
      dirty();
    });
    const offReset = onSpectrumReset((ch) => {
      if (ch !== channel) return;
      image = null;
      last = null;
      dirty();
    });
    const ro = new ResizeObserver(dirty);
    ro.observe(cv);
    dirty();
    return () => {
      off();
      offReset();
      ro.disconnect();
      unregister();
    };
  });
</script>

<div class="card">
  <canvas bind:this={cv} aria-label="Channel {channel} waterfall, dBFS"></canvas>
  <footer>
    {#if synth}<span class="pill synth" title="SYNTHETIC stand-in data, not an RF measurement">SIMULATED</span>{/if}
    <span class="note">Ch {channel}, dBFS{bins ? `, ${bins} bins` : ''}</span>
    {#if rate}<span class="note">{rate}</span>{/if}
  </footer>
</div>

<style>
  .card { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  canvas { flex: 1; min-height: 0; width: 100%; display: block; }
  footer { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 4px 8px; }
</style>

<script lang="ts">
  import { appearanceVersion } from '../lib/theme';
  // Live IF spectrum trace over a scrolling waterfall for one channel.
  // Colours come from the server's auto scale unless the viewer chose a manual scale.
  import { onMount } from 'svelte';
  import { PAD, makeAxis, xOf } from '../lib/axis';
  import { type Overlay, cssVar, drawBands, drawDbGrid, drawFreqTicks, drawLines, drawTrace, fitCanvas } from '../lib/draw';
  import { onSpectrum } from '../lib/link';
  import type { Channel, SpectrumMsg } from '../lib/types';
  import { scaleOverride } from '../lib/view';
  import { WaterfallImage } from '../lib/waterfall';

  let { channel, colorVar, overlays = [], draggable = false, ondrag, ondragend, onrow, rows = 200 }: {
    channel: Channel; colorVar: string; overlays?: Overlay[]; draggable?: boolean;
    ondrag?: (deltaHz: number) => void; ondragend?: () => void; onrow?: (m: SpectrumMsg) => void; rows?: number;
  } = $props();

  let traceCv: HTMLCanvasElement;
  let fallCv: HTMLCanvasElement;
  let image: WaterfallImage | null = null;
  let last: SpectrumMsg | null = null;
  let dirty = true;
  let dragX: number | null = null;

  function limits(): [number, number] {
    const s = $scaleOverride;
    if (s.mode === 'manual') return [s.low, s.high];
    return last ? [last.low, last.high] : [-120, -60];
  }

  function axisFor(width: number) {
    if (!last) return makeAxis(0, 1, width);
    const f0 = last.f0_hz - last.bin_hz / 2;
    return makeAxis(f0, f0 + last.bins * last.bin_hz, width);
  }

  function draw() {
    const t = fitCanvas(traceCv);
    const a = axisFor(t.w);
    const [low, high] = limits();
    const top = 8;
    const bot = t.h - 18;
    t.ctx.clearRect(0, 0, t.w, t.h);
    if (last) {
      drawDbGrid(t.ctx, a, top, bot, low, high);
      drawBands(t.ctx, a, top, bot, overlays);
      drawTrace(t.ctx, top, bot, last, low, high, colorVar, (f) => xOf(a, f));
      drawLines(t.ctx, a, top, bot, overlays);
      drawFreqTicks(t.ctx, a, t.h - 4, 10e3, (f) => (f / 1e3).toFixed(0), 'kHz');
    } else {
      t.ctx.fillStyle = cssVar('--muted');
      t.ctx.font = '14px "Jost", system-ui, sans-serif';
      t.ctx.textAlign = 'center';
      t.ctx.fillText(`Waiting for channel ${channel} spectrum…`, t.w / 2, t.h / 2);
    }
    const f = fitCanvas(fallCv);
    f.ctx.fillStyle = cssVar('--wf-bg');
    f.ctx.fillRect(0, 0, f.w, f.h);
    if (image) {
      f.ctx.imageSmoothingEnabled = false;
      f.ctx.drawImage(image.canvas, PAD.left, 0, f.w - PAD.left - PAD.right, f.h);
    }
    if (last) drawLines(f.ctx, axisFor(f.w), 0, f.h, overlays.filter((o) => o.onFall), false);
  }

  $effect(() => {
    void channel;   // a new channel starts a fresh picture
    image = null;
    last = null;
    dirty = true;
  });
  $effect(() => {
    void $appearanceVersion;
    void overlays;
    void $scaleOverride;
    dirty = true;
  });

  onMount(() => {
    const off = onSpectrum((m) => {
      if (m.channel !== channel) return;
      if (!image || image.bins !== m.bins || last?.f0_hz !== m.f0_hz || last?.bin_hz !== m.bin_hz) image = new WaterfallImage(m.bins, rows);
      last = m;
      const [low, high] = limits();
      image.push(m.db10, low, high);
      dirty = true;
      onrow?.(m);
    });
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (dirty) {
        dirty = false;
        draw();
      }
    };
    raf = requestAnimationFrame(loop);
    const ro = new ResizeObserver(() => (dirty = true));
    ro.observe(traceCv);
    return () => {
      off();
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  });

  function down(e: PointerEvent) {
    if (!draggable) return;
    dragX = e.clientX;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent) {
    if (!draggable || dragX === null || !last) return;
    const a = axisFor(traceCv.clientWidth);
    ondrag?.(((e.clientX - dragX) * (a.f1 - a.f0)) / (a.width - a.left - a.right));
    dragX = e.clientX;
  }
  function up() {
    if (dragX !== null) ondragend?.();
    dragX = null;
  }
</script>

<!-- Dragging is a pointer shortcut; the NCO field in the control rail is the keyboard path. -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="wf" class:drag={draggable} role="img" aria-label="Channel {channel} IF spectrum and waterfall"
  onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
  <canvas class="trace" bind:this={traceCv}></canvas>
  <canvas class="fall" bind:this={fallCv}></canvas>
</div>

<style>
  .wf { display: grid; }
  .trace { display: block; width: 100%; height: 130px; }
  .fall { display: block; width: 100%; height: 220px; }
  .drag { cursor: ew-resize; touch-action: none; }
</style>

<script lang="ts">
  import { appearanceVersion } from '../lib/theme';
  // RF-domain frequency plan. Only the IF span the FPGA reports is measured and drawn as a trace;
  // everything else is hatched as "not observed". The image band is hatched in the "bad" colour.
  import { onMount } from 'svelte';
  import { ifToRf, makeAxis, xOf } from '../lib/axis';
  import { cssVar, drawFreqTicks, drawTrace, fitCanvas, hatch, withAlpha } from '../lib/draw';
  import { mhz } from '../lib/format';
  import type { SpectrumMsg, TuningMsg } from '../lib/types';
  import { scaleOverride } from '../lib/view';

  const SPAN_HZ = 300e3;            // shown either side of the nominal carrier
  const LABEL = '600 11px "Jost", system-ui, sans-serif';

  let { t, row, colorVar, disabled, ontune }:
    { t: TuningMsg; row: SpectrumMsg | null; colorVar: string; disabled: boolean; ontune: (loHz: number) => void } =
    $props();

  let cv: HTMLCanvasElement;
  let dragX: number | null = null;
  let dragLo = 0;

  const axis = (width: number) => makeAxis(t.state.carrier_hz - SPAN_HZ, t.state.carrier_hz + SPAN_HZ, width);

  function draw() {
    if (!cv) return;
    const { ctx, w, h } = fitCanvas(cv);
    const s = t.state;
    const d = t.derived;
    const a = axis(w);
    const X = (f: number) => xOf(a, f);
    const rf = (f: number) => ifToRf(d.lo_hz, s.injection, f);
    const span = (f0: number, f1: number): [number, number] => {
      const p = rf(f0);
      const q = rf(f1);
      return [Math.min(p, q), Math.max(p, q)];
    };
    const reference = row?.rf_reference;
    const measuredRf = (f: number) => reference ? ifToRf(reference.lo_hz, reference.injection, f) : NaN;
    const top = 22;
    const bot = h - 20;
    const panel = cssVar('--panel');
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.beginPath();
    ctx.rect(a.left, 0, w - a.left - a.right, h);
    ctx.clip();

    hatch(ctx, a.left, w - a.right, top, bot, cssVar('--line'));
    const img: [number, number] = [d.image_hz - s.window_hz, d.image_hz + s.window_hz];
    ctx.fillStyle = panel;
    ctx.fillRect(X(img[0]), top, X(img[1]) - X(img[0]), bot - top);
    hatch(ctx, X(img[0]), X(img[1]), top, bot, withAlpha(cssVar('--bad'), 0.45));
    if (row && reference) {
      const seen = [measuredRf(row.f0_hz - row.bin_hz / 2), measuredRf(row.f0_hz + (row.bins - 0.5) * row.bin_hz)].sort((a, b) => a - b);
      ctx.fillStyle = panel;
      ctx.fillRect(X(seen[0]), top, X(seen[1]) - X(seen[0]), bot - top);
    }
    const win = span(s.target_if_hz - s.window_hz, s.target_if_hz + s.window_hz);
    const ifColor = cssVar('--if');
    ctx.fillStyle = withAlpha(ifColor, 0.11);
    ctx.fillRect(X(win[0]), top, X(win[1]) - X(win[0]), bot - top);
    ctx.strokeStyle = withAlpha(ifColor, 0.55);
    ctx.lineWidth = 1;
    ctx.strokeRect(X(win[0]) + 0.5, top + 0.5, X(win[1]) - X(win[0]) - 1, bot - top - 1);
    if (row && reference) {
      const sc = $scaleOverride;
      const [low, high] = sc.mode === 'manual' ? [sc.low, sc.high] : [row.low, row.high];
      drawTrace(ctx, top, bot, row, low, high, colorVar, (f) => X(measuredRf(f)));
    }
    const fg = cssVar('--fg');
    const c = s.carrier_hz;
    ctx.strokeStyle = withAlpha(fg, 0.6);
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(Math.round(X(c)) + 0.5, top);
    ctx.lineTo(Math.round(X(c)) + 0.5, bot);
    ctx.stroke();
    ctx.setLineDash([]);
    const loColor = cssVar('--lo');
    const xl = Math.round(X(d.lo_hz)) + 0.5;
    ctx.strokeStyle = loColor;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(xl, top - 6);
    ctx.lineTo(xl, bot);
    ctx.stroke();
    ctx.lineWidth = 1;
    ctx.fillStyle = loColor;
    ctx.beginPath();
    ctx.moveTo(xl - 6, top - 12);
    ctx.lineTo(xl + 6, top - 12);
    ctx.lineTo(xl, top - 3);
    ctx.fill();
    ctx.restore();

    ctx.font = LABEL;
    ctx.textAlign = 'center';
    const clampX = (x: number) => Math.min(w - a.right - 34, Math.max(a.left + 34, x));
    const label = (text: string, x: number, y: number, color: string, boxed = false) => {
      const cx = clampX(x);
      if (boxed) {   // keeps the label readable where it sits over the trace
        const half = ctx.measureText(text).width / 2 + 4;
        ctx.fillStyle = panel;
        ctx.fillRect(cx - half, y - 11, half * 2, 15);
      }
      ctx.fillStyle = color;
      ctx.fillText(text, cx, y);
    };
    label('LO', xl + (xl > X(c) ? 14 : -14), top - 8, loColor);
    label('IMAGE', (X(img[0]) + X(img[1])) / 2, top - 8, cssVar('--bad'));
    label('IF WINDOW', (X(win[0]) + X(win[1])) / 2, top - 8, ifColor);
    label(`TX ${mhz(c, 3)}`, X(c), bot - 6, cssVar('--muted'), true);
    drawFreqTicks(ctx, a, h - 4, 100e3, (f) => (f / 1e6).toFixed(1), 'MHz');
  }

  $effect(() => {
    void $appearanceVersion;
    void t;
    void row;
    void $scaleOverride;
    draw();
  });

  onMount(() => {
    const wheel = (e: WheelEvent) => {
      if (disabled) return;
      e.preventDefault();
      ontune(t.derived.lo_hz + (e.deltaY < 0 ? 1 : -1) * Math.max(t.derived.lo_step_hz, 1e3));
    };
    cv.addEventListener('wheel', wheel, { passive: false });
    const ro = new ResizeObserver(draw);
    ro.observe(cv);
    return () => {
      cv.removeEventListener('wheel', wheel);
      ro.disconnect();
    };
  });

  function down(e: PointerEvent) {
    if (disabled) return;
    dragX = e.clientX;
    dragLo = t.derived.lo_hz;
    cv.setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent) {
    if (disabled || dragX === null) return;
    const a = axis(cv.clientWidth);
    dragLo += ((e.clientX - dragX) * (a.f1 - a.f0)) / (a.width - a.left - a.right);
    dragX = e.clientX;
    ontune(dragLo);
  }
  const up = () => (dragX = null);
</script>

<canvas bind:this={cv} class:drag={!disabled} aria-label="RF frequency plan: LO, IF window and image band"
  onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}></canvas>

<style>
  canvas { display: block; width: 100%; height: 170px; }
  .drag { cursor: ew-resize; touch-action: none; }
</style>

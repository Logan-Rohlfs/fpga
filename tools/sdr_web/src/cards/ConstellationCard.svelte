<script lang="ts">
  // I/Q scatter of the last `persistence` snapshots, or instantaneous frequency against sample index.
  // inst_freq is display math on a received snapshot, using that snapshot's own sample_rate_hz; not frequency planning.
  import { onMount } from 'svelte';
  import { instFreq, lastSnaps, niceStep } from '../lib/cards/spectral';
  import { cssVar, drawConstellation, fitCanvas } from '../lib/draw';
  import { scheduler } from '../lib/frame';
  import { iqSnapMeta, iqSnaps } from '../lib/link';
  import { appearanceVersion } from '../lib/theme';
  import type { Channel } from '../lib/types';

  let { id, config }: { id: string; config: Record<string, unknown> } = $props();
  const channel = $derived(config.channel as Channel);
  const mode = $derived(config.mode as string);
  const persistence = $derived(typeof config.persistence === 'number' ? config.persistence : 4);
  const metaList = $derived($iqSnapMeta[channel] ?? []);
  const newest = $derived(metaList[metaList.length - 1]);
  const fs = $derived(newest?.sample_rate_hz ?? 0);
  const colorVar = $derived(channel === 'A' ? '--ch-a' : '--ch-b');
  const count = $derived(($iqSnaps[channel] ?? []).length);

  let cv: HTMLCanvasElement;
  const dirty = () => scheduler.markDirty(id);

  function message(ctx: CanvasRenderingContext2D, w: number, h: number, text: string) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = cssVar('--muted');
    ctx.font = '14px "Jost", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(text, w / 2, h / 2);
  }

  function drawInstFreq(ctx: CanvasRenderingContext2D, w: number, h: number, snap: [number, number][]) {
    const f = instFreq(snap, fs);
    if (!f.length) return message(ctx, w, h, 'Snapshot too short');
    const left = 48;
    const top = 8;
    const bot = h - 18;
    let lo = Math.min(...f);
    let hi = Math.max(...f);
    const pad = Math.max(1, (hi - lo) * 0.1);
    lo -= pad;
    hi += pad;
    const y = (v: number) => bot - ((v - lo) / (hi - lo)) * (bot - top);
    const x = (n: number) => left + (n / Math.max(1, f.length - 1)) * (w - left - 10);
    ctx.clearRect(0, 0, w, h);
    ctx.font = '11px "JetBrains Mono", ui-monospace, monospace';
    const step = niceStep(hi - lo, 4);
    ctx.textAlign = 'right';
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      const yy = Math.round(y(v)) + 0.5;
      ctx.strokeStyle = cssVar('--line');
      ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(w - 10, yy); ctx.stroke();
      ctx.fillStyle = cssVar('--faint');
      ctx.fillText((v / 1e3).toFixed(step >= 1e3 ? 0 : 2), left - 6, yy + 4);
    }
    ctx.beginPath();
    f.forEach((v, n) => (n ? ctx.lineTo(x(n), y(v)) : ctx.moveTo(x(n), y(v))));
    ctx.strokeStyle = cssVar(colorVar);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = cssVar('--muted');
    ctx.textAlign = 'center';
    ctx.fillText('sample index', (left + w) / 2, h - 4);
    ctx.textAlign = 'left';
    ctx.fillStyle = cssVar('--faint');
    ctx.fillText('kHz', 4, top + 6);
  }

  function draw() {
    const { ctx, w, h } = fitCanvas(cv);
    const snaps = lastSnaps($iqSnaps[channel], persistence);
    if (!snaps.length) return message(ctx, w, h, `Waiting for channel ${channel} I/Q…`);
    if (mode === 'inst_freq') {
      if (!(fs > 0)) return message(ctx, w, h, 'sample rate unavailable');
      return drawInstFreq(ctx, w, h, snaps[snaps.length - 1]);
    }
    const size = Math.min(w, h);
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate((w - size) / 2, (h - size) / 2);
    drawConstellation(ctx, size, snaps, colorVar);
    ctx.restore();
  }

  $effect(() => {
    void $iqSnaps;
    void channel;
    void mode;
    void persistence;
    void fs;
    void $iqSnapMeta;
    void $appearanceVersion;
    dirty();
  });

  onMount(() => {
    const unregister = scheduler.register(id, draw);
    const ro = new ResizeObserver(dirty);
    ro.observe(cv);
    dirty();
    return () => {
      ro.disconnect();
      unregister();
    };
  });
</script>

<div class="card">
  <canvas bind:this={cv}
    aria-label={mode === 'inst_freq' ? `Channel ${channel} instantaneous frequency` : `Channel ${channel} I/Q constellation`}></canvas>
  <footer>
    {#if newest?.synthetic}<span class="pill synth" title="SYNTHETIC stand-in data, not an RF measurement">SIMULATED</span>{/if}
    <span class="note">Ch {channel}, {mode === 'inst_freq' ? 'inst. frequency' : 'I/Q'}, {Math.min(count, persistence)} of {persistence} snapshots</span>
  </footer>
</div>

<style>
  .card { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  canvas { flex: 1; min-height: 0; width: 100%; display: block; }
  footer { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 4px 8px; }
</style>

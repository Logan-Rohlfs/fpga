<script lang="ts">
  // Latest spectrum trace per channel (dBFS) with an optional decaying peak-hold trace.
  // Axes follow each message's f0_hz/bin_hz/bins; the bin count is never assumed.
  import { onMount } from 'svelte';
  import { PAD, makeAxis, xOf } from '../lib/axis';
  import { PeakHold, niceStep, rowSpan } from '../lib/cards/spectral';
  import { cssVar, drawDbGrid, drawFreqTicks, drawTrace, fitCanvas } from '../lib/draw';
  import { scheduler } from '../lib/frame';
  import { cardStatus } from '../lib/cards/status';
  import { staleAge } from '../lib/cards/value';
  import { onSpectrum, onSpectrumReset, serverNow } from '../lib/link';
  import { appearanceVersion } from '../lib/theme';
  import type { Channel, SpectrumMsg } from '../lib/types';

  let { id, config }: { id: string; config: Record<string, unknown> } = $props();
  const shown = $derived<Channel[]>(config.channel === 'both' ? ['A', 'B'] : [config.channel as Channel]);
  const hold = $derived(config.peak_hold === true);
  const decayS = $derived(typeof config.peak_decay_s === 'number' ? config.peak_decay_s : 10);

  const COLOR: Record<Channel, string> = { A: '--ch-a', B: '--ch-b' };
  let cv: HTMLCanvasElement;
  const rows: Partial<Record<Channel, SpectrumMsg>> = {};
  let peaks: Record<Channel, PeakHold> = { A: new PeakHold(10), B: new PeakHold(10) };
  let peakRows: Partial<Record<Channel, Float32Array>> = {};
  const report = cardStatus();
  let bins = $state(0);
  const dirty = () => scheduler.markDirty(id);

  function draw() {
    const { ctx, w, h } = fitCanvas(cv);
    ctx.clearRect(0, 0, w, h);
    const live = shown.map((c) => rows[c]).filter((r): r is SpectrumMsg => !!r);
    const newest = Math.max(...live.map((r) => r.t_us / 1e6));
    report(live.length
      ? { synthetic: live.some((r) => r.synthetic), flight: false, age: staleAge(newest, serverNow(), 2) }
      : null);
    if (!live.length) {
      ctx.fillStyle = cssVar('--muted');
      ctx.font = '14px "Jost", system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Waiting for spectrum…', w / 2, h / 2);
      return;
    }
    const spans = live.map(rowSpan);
    const a = makeAxis(Math.min(...spans.map((s) => s[0])), Math.max(...spans.map((s) => s[1])), w);
    const low = Math.min(...live.map((r) => r.low));
    const high = Math.max(...live.map((r) => r.high));
    const top = 8;
    const bot = h - 18;
    drawDbGrid(ctx, a, top, bot, low, high);
    for (const c of shown) {
      const row = rows[c];
      if (!row) continue;
      drawTrace(ctx, top, bot, row, low, high, COLOR[c], (f) => xOf(a, f));
      const p = hold ? peakRows[c] : undefined;
      if (p) {
        const y = (v: number) => bot - ((Math.min(high, Math.max(low, v / 10)) - low) / (high - low)) * (bot - top);
        ctx.beginPath();
        for (let k = 0; k < p.length; k++) {
          const x = xOf(a, row.f0_hz + k * row.bin_hz);
          if (k) ctx.lineTo(x, y(p[k])); else ctx.moveTo(x, y(p[k]));
        }
        ctx.strokeStyle = cssVar(COLOR[c]);
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    const step = niceStep(a.f1 - a.f0, Math.max(2, Math.floor(w / 90)));
    const kHz = step >= 1000;
    drawFreqTicks(ctx, a, h - 4, step, (f) => (kHz ? (f / 1e3).toFixed(step >= 1e4 ? 0 : 1) : f.toFixed(0)), kHz ? 'kHz' : 'Hz');
    ctx.fillStyle = cssVar('--faint');
    ctx.font = '11px "JetBrains Mono", ui-monospace, monospace';
    ctx.textAlign = 'right';
    ctx.fillText('dBFS', PAD.left - 6, top + 2);
  }

  $effect(() => {
    // New settings restart the hold; the traces redraw from the latest rows.
    peaks = { A: new PeakHold(decayS), B: new PeakHold(decayS) };
    peakRows = {};
    void hold;
    void shown;
    dirty();
  });
  $effect(() => {
    void $appearanceVersion;
    dirty();
  });

  onMount(() => {
    const unregister = scheduler.register(id, draw);
    const off = onSpectrum((m) => {
      if (!shown.includes(m.channel)) return;
      rows[m.channel] = m;
      peakRows[m.channel] = peaks[m.channel].update(m.db10, serverNow());
      bins = m.bins;
      dirty();
    });
    const offReset = onSpectrumReset((ch) => {
      delete rows[ch];
      delete peakRows[ch];
      peaks[ch].reset();
      const rest = Object.values(rows);
      bins = rest.length ? rest[0].bins : 0;
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
  <canvas bind:this={cv} aria-label="Spectrum, dBFS"></canvas>
  <footer>
    {#each shown as c (c)}<span class="note key" style="color: var({COLOR[c]})">Ch {c}</span>{/each}
    <span class="note">dBFS{bins ? `, ${bins} bins` : ''}{hold ? `, peak hold ${decayS ? `${decayS} s decay` : 'no decay'}` : ''}</span>
  </footer>
</div>

<style>
  .card { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  canvas { flex: 1; min-height: 0; width: 100%; display: block; }
  footer { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 4px 8px; }
  .key { font-weight: 600; }
</style>

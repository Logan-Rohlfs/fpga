<script lang="ts">
  // Time-series plot (uPlot). One instance per card. Pause/Live and scrub change only the view; ingestion never stops,
  // so pressing Live shows no gap. Draws go through the shared scheduler, only when the data changed and the card is visible.
  import { onMount, untrack } from 'svelte';
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import { cssVar } from '../lib/draw';
  import { scheduler } from '../lib/frame';
  import { dataVersion, eventsStore, flightSchema, flightStores, metricsStores, serverNow } from '../lib/link';
  import { appearanceVersion } from '../lib/theme';
  import { unitFor, unitLabel, unitPrefs } from '../lib/units';
  import {
    type PlotInput, type PlotSeries, type ViewState, axesFor, buildData, columnOf, eventMarkers, expandSeries, quantityOf, storeFor, viewRange,
  } from '../lib/cards/plot';

  let { id, config }: { id: string; config: Record<string, unknown> } = $props();

  const PALETTE = ['--if', '--lo', '--good', '--synth', '--warn', '--brand'];

  let host: HTMLDivElement;
  let plot: uPlot | null = null;
  let view: ViewState = $state({ paused: false, pausedAt: null, offsetS: 0 });
  let range: [number, number] = [0, 1];
  let markers: { t: number; label: string }[] = [];
  let dragX: number | null = null;

  const series = $derived(expandSeries(config.series as PlotSeries[]));
  const windowS = $derived(config.window_s as number);
  const cardUnits = $derived(config.units as Record<string, string>);
  const axes = $derived(axesFor(series, $flightSchema));
  const showEvents = $derived(config.show_events === true);
  const yFixed = $derived(config.y !== 'auto' ? (config.y as { min: number; max: number }) : null);
  // Anything that needs a new uPlot instance (series, axes, labels, colours), not just new data.
  const buildKey = $derived(JSON.stringify([series, windowS, cardUnits, config.y, $unitPrefs, $flightSchema?.version, $appearanceVersion]));

  function inputs(): PlotInput[] {
    const stores = { flight: flightStores, metrics: metricsStores };
    const out: PlotInput[] = [];
    for (const s of series) {
      const store = storeFor(s, stores);
      const q = quantityOf(s.field, $flightSchema);
      const col = columnOf(s.field, $flightSchema);
      if (store && q && col >= 0) out.push({ store, col, quantity: q });
    }
    return out;
  }

  function label(s: PlotSeries): string {
    const f = $flightSchema?.fields.find((x) => x.key === s.field);
    const name = f?.label ?? ({ 'm.rssi': 'RSSI', 'm.noise': 'Noise', 'm.snr': 'SNR', 'm.df': 'Freq. offset' } as Record<string, string>)[s.field] ?? s.field;
    return s.source === 'best' ? name : `${name} (${s.source})`;
  }

  function destroy() {
    plot?.destroy();
    plot = null;
  }

  function build() {
    destroy();
    if (!host || !axes.ok || !series.length) return;
    const qs = axes.quantities;
    const muted = cssVar('--muted');
    const grid = { stroke: cssVar('--line'), width: 1 };
    const axisFont = `11px ${cssVar('--f-mono') || 'monospace'}`;
    const unitOf = (q: string) => unitLabel(q, unitFor(q, cardUnits, $unitPrefs));
    const opts: uPlot.Options = {
      width: Math.max(host.clientWidth, 50), height: Math.max(host.clientHeight - 40, 50),
      cursor: { drag: { x: false, y: false } },
      scales: {
        x: { time: true, range: () => range },
        ...Object.fromEntries(qs.map((q, i) => [q, {
          range: (_u: uPlot, lo: number, hi: number): [number, number] => {
            if (i === 0 && yFixed) return [yFixed.min, yFixed.max];
            if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
            const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1;
            return [lo - pad, hi + pad];
          },
        }])),
      },
      axes: [
        { stroke: muted, grid, ticks: grid, font: axisFont },
        ...qs.map((q, i) => ({
          scale: q, side: i === 0 ? 3 : 1, stroke: muted, font: axisFont, label: unitOf(q), labelFont: axisFont,
          grid: i === 0 ? grid : { show: false }, ticks: grid, size: 60,
        })),
      ],
      series: [
        {},
        ...series.map((s, i) => {
          const q = quantityOf(s.field, $flightSchema) ?? qs[0];
          return {
            label: label(s), scale: q, stroke: cssVar(PALETTE[i % PALETTE.length]), width: 1.5, spanGaps: true, points: { show: false },
            dash: s.source === 'B' ? [6, 4] : undefined,
          };
        }),
      ],
      legend: { show: true },
      hooks: { draw: [drawMarkers] },
    };
    plot = new uPlot(opts, [[], ...series.map(() => [])] as uPlot.AlignedData, host);
    attachScrub(plot.over);
    scheduler.markDirty(id);
  }

  function drawMarkers(u: uPlot) {
    if (!showEvents || !markers.length) return;
    const { ctx, bbox } = u;
    ctx.save();
    ctx.strokeStyle = cssVar('--warn');
    ctx.fillStyle = cssVar('--warn');
    ctx.font = `11px ${cssVar('--f-mono') || 'monospace'}`;
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    for (const m of markers) {
      const x = Math.round(u.valToPos(m.t, 'x', true));
      if (x < bbox.left || x > bbox.left + bbox.width) continue;
      ctx.beginPath();
      ctx.moveTo(x, bbox.top);
      ctx.lineTo(x, bbox.top + bbox.height);
      ctx.stroke();
      ctx.fillText(m.label, x + 3, bbox.top + 12);
    }
    ctx.restore();
  }

  function dataStart(ins: PlotInput[]): number {
    let t0 = Infinity;
    for (const i of ins) if (i.store.length) t0 = Math.min(t0, i.store.timeAt(0));
    return t0;
  }

  function draw() {
    if (!plot) return;
    const ins = inputs();
    const now = serverNow();
    range = viewRange(view, now, windowS, dataStart(ins));
    // Scrubbing past the oldest data clamps; keep the stored offset in step so the drag does not wind up.
    if (view.paused && view.pausedAt !== null) view.offsetS = Math.max(0, view.pausedAt - range[1]);
    const data = ins.length === series.length
      ? buildData(ins, range[0], range[1], $unitPrefs, cardUnits)
      : [[], ...series.map(() => [])];
    markers = showEvents ? eventMarkers($eventsStore, range[0], range[1]) : [];
    plot.setData(data as uPlot.AlignedData, true);
  }

  function resize() {
    if (!plot || !host) return;
    const legend = plot.root.querySelector<HTMLElement>('.u-legend');
    plot.setSize({ width: Math.max(host.clientWidth, 50), height: Math.max(host.clientHeight - (legend?.offsetHeight ?? 24) - 30, 50) });
  }

  function attachScrub(over: HTMLElement) {
    over.addEventListener('pointerdown', (e) => {
      if (!view.paused) return;
      dragX = e.clientX;
      over.setPointerCapture(e.pointerId);
    });
    over.addEventListener('pointermove', (e) => {
      if (dragX === null || !view.paused) return;
      const w = over.clientWidth || 1;
      const secPerPx = (range[1] - range[0]) / w;
      // Dragging right pulls older data into view.
      view.offsetS = Math.max(0, view.offsetS + (e.clientX - dragX) * secPerPx);
      dragX = e.clientX;
      scheduler.markDirty(id);
    });
    const end = () => { dragX = null; };
    over.addEventListener('pointerup', end);
    over.addEventListener('pointercancel', end);
  }

  function pause() {
    view = { paused: true, pausedAt: serverNow(), offsetS: 0 };
    scheduler.markDirty(id);
  }
  function live() {
    view = { paused: false, pausedAt: null, offsetS: 0 };
    scheduler.markDirty(id);
  }

  onMount(() => {
    const off = scheduler.register(id, draw);
    const ro = new ResizeObserver(() => { resize(); scheduler.markDirty(id); });
    ro.observe(host);
    return () => { off(); ro.disconnect(); destroy(); };
  });

  $effect(() => {
    void buildKey;
    untrack(build);
  });
  $effect(() => {
    void $dataVersion;
    void $eventsStore;
    void showEvents;
    untrack(() => scheduler.markDirty(id));
  });
</script>

<div class="plotcard">
  <div class="bar">
    <button class="btn" aria-pressed={view.paused} onclick={pause} disabled={view.paused}>Pause</button>
    <button class="btn" aria-pressed={!view.paused} onclick={live} disabled={!view.paused}>Live</button>
    <span class="note">{view.paused ? 'Paused: drag the plot to scrub' : 'Live'}</span>
  </div>
  {#if !axes.ok}
    <p class="note err">{axes.error}</p>
  {/if}
  <div class="host" class:scrub={view.paused} class:hide={!axes.ok} bind:this={host}></div>
</div>

<style>
  .plotcard { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .bar { display: flex; align-items: center; gap: 8px; padding: 6px 8px; flex: none; }
  .bar .btn { padding: 2px 9px; font-size: 13px; }
  .host { flex: 1; min-height: 0; padding: 0 6px 6px; }
  .host.scrub :global(.u-over) { cursor: grab; }
  .hide { display: none; }
  .err { padding: 12px; color: var(--bad); }
  .host :global(.uplot) { font-family: var(--f-mono); }
  .host :global(.u-legend) { color: var(--muted); font-size: 12px; }
</style>

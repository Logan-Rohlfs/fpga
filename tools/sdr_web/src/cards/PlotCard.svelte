<script lang="ts">
  // Time-series plot (uPlot). One instance per card. Pause/Live and scrub change only the view; ingestion never stops,
  // so pressing Live shows no gap. Draws go through the shared scheduler, only when the data changed and the card is visible.
  import { onMount, untrack } from 'svelte';
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import { cssVar } from '../lib/draw';
  import { scheduler } from '../lib/frame';
  import { dataVersion, eventsStore, flightSchema, flightStores, metricsStores, segmentStart, serverNow } from '../lib/link';
  import { clampToSegment, segmentFloor } from '../lib/cards/segment';
  import { appearanceVersion } from '../lib/theme';
  import { unitFor, unitLabel, unitPrefs } from '../lib/units';
  import {
    type PlotInput, type PlotSeries, type ViewState, axesFor, buildData, clockLabel, columnOf, eventMarkers, expandSeries, layoutMarkerLabels, markerLabel,
    plotSize, quantityOf, scaleKeyOf,
    storeFor, viewRange, yRanges,
  } from '../lib/cards/plot';
  import { cardStatus } from '../lib/cards/status';
  import { staleAge } from '../lib/cards/value';

  let { id, config }: { id: string; config: Record<string, unknown> } = $props();

  const PALETTE = ['--if', '--lo', '--good', '--synth', '--warn', '--brand'];

  let host: HTMLDivElement;
  let plot: uPlot | null = null;
  let view: ViewState = $state({ paused: false, pausedAt: null, offsetS: 0 });
  let range: [number, number] = [0, 1];
  // Y ranges per quantity, recomputed from the visible window on every draw (lib/cards/plot.ts yRanges).
  let ranges: Record<string, [number, number]> = {};
  let markers: { t: number; label: string }[] = [];
  let dragX: number | null = null;
  const report = cardStatus();

  /** Header status: SYNTHETIC if any series' newest row is; stale after 1 s (flight) or 3 s (link metrics only). */
  function reportStatus(ins: PlotInput[], now: number) {
    let newest = -Infinity;
    let synthetic = false;
    for (const i of ins) {
      const l = i.store.latest();
      if (!l) continue;
      newest = Math.max(newest, l.t);
      synthetic ||= !!(l.flags & 1);
    }
    const flightFields = series.filter((s) => !s.field.startsWith('m.')).map((s) => s.field);
    report(Number.isFinite(newest)
      ? { synthetic, flight: flightFields.length > 0, age: staleAge(newest, now, flightFields.length ? 1 : 3), fields: flightFields }
      : null);
  }

  const series = $derived(expandSeries(config.series as PlotSeries[]));
  const windowS = $derived(config.window_s as number);
  const cardUnits = $derived(config.units as Record<string, string>);
  const axes = $derived(axesFor(series, $flightSchema));
  const showEvents = $derived(config.show_events === true);
  const yFixed = $derived(config.y !== 'auto' ? (config.y as { min: number | null; max: number | null }) : null);
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
      ...sizeNow(24),
      cursor: { drag: { x: false, y: false } },
      scales: {
        x: { time: true, range: () => range },
        ...Object.fromEntries(qs.map((q) => [q, { range: (): [number, number] => ranges[q] ?? [0, 1] }])),
      },
      axes: [
        { stroke: muted, grid, ticks: grid, font: axisFont, space: 70, values: (_u: uPlot, splits: number[]) => splits.map(clockLabel) },
        ...qs.map((q, i) => ({
          scale: q, side: i === 0 ? 3 : 1, stroke: muted, font: axisFont, label: unitOf(q), labelFont: axisFont,
          grid: i === 0 ? grid : { show: false }, ticks: grid, size: 60,
        })),
      ],
      series: [
        {},
        ...series.map((s, i) => {
          const q = scaleKeyOf(s.field, $flightSchema, qs);
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
    resize();   // now that the legend exists, fit around its real height
    scheduler.markDirty(id);
  }

  /**
   * Event markers: a dashed neutral line per event and a small label chip beside it. Chips stack in up to three lanes
   * so close events stay readable; a label with no free lane is dropped (its line stays). Neutral (--fg) lines and a
   * panel-coloured chip keep the markers distinct from every series colour.
   */
  function drawMarkers(u: uPlot) {
    if (!showEvents || !markers.length) return;
    const { ctx, bbox } = u;
    const dpr = devicePixelRatio || 1;
    const fontPx = Math.round(10.5 * dpr);
    const padX = Math.round(4 * dpr);
    const laneH = Math.round(15 * dpr);
    ctx.save();
    ctx.font = `600 ${fontPx}px ${cssVar('--f-ui') || 'sans-serif'}`;
    const items = markers.map((m) => {
      const text = markerLabel(m.label);
      return { x: Math.round(u.valToPos(m.t, 'x', true)), w: ctx.measureText(text).width + padX * 2, text };
    });
    const slots = layoutMarkerLabels(items, bbox.left, bbox.left + bbox.width, 3, Math.round(3 * dpr));
    const fg = cssVar('--fg');
    ctx.strokeStyle = fg;
    ctx.globalAlpha = 0.45;
    ctx.setLineDash([3 * dpr, 3 * dpr]);
    ctx.lineWidth = dpr;
    for (const it of items) {
      if (it.x < bbox.left || it.x > bbox.left + bbox.width) continue;
      ctx.beginPath();
      ctx.moveTo(it.x + 0.5, bbox.top);
      ctx.lineTo(it.x + 0.5, bbox.top + bbox.height);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';   // uPlot leaves the axis alignment set
    items.forEach((it, i) => {
      const slot = slots[i];
      if (slot.lane === null || it.x < bbox.left || it.x > bbox.left + bbox.width) return;
      const gap = Math.round(3 * dpr);
      const x0 = slot.side === 'right' ? it.x + gap : it.x - gap - it.w;
      const y0 = bbox.top + Math.round(4 * dpr) + slot.lane * (laneH + Math.round(2 * dpr));
      ctx.fillStyle = cssVar('--panel');
      ctx.strokeStyle = cssVar('--muted');
      ctx.lineWidth = dpr;
      ctx.beginPath();
      ctx.roundRect(x0, y0, it.w, laneH, 3 * dpr);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = fg;
      ctx.fillText(it.text, x0 + padX, y0 + laneH / 2 + dpr * 0.5);
    });
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
    reportStatus(ins, now);
    const floor = segmentFloor(config.segment, $segmentStart);
    range = clampToSegment(viewRange(view, now, windowS, Math.max(dataStart(ins), floor)), floor);
    // Scrubbing past the oldest data clamps; keep the stored offset in step so the drag does not wind up.
    if (view.paused && view.pausedAt !== null) view.offsetS = Math.max(0, view.pausedAt - range[1]);
    const data = ins.length === series.length
      ? buildData(ins, range[0], range[1], $unitPrefs, cardUnits)
      : [[], ...series.map(() => [])];
    markers = showEvents ? eventMarkers($eventsStore, range[0], range[1]) : [];
    ranges = yRanges(data, series.map((s) => scaleKeyOf(s.field, $flightSchema, axes.quantities)), yFixed);
    plot.setData(data as uPlot.AlignedData, true);
  }

  /** Plot canvas size inside the host (its 6 px side padding excluded), leaving the legend's height free. */
  function sizeNow(legendH: number) {
    return plotSize(host.clientWidth - 12, host.clientHeight, legendH);
  }

  function resize() {
    if (!plot || !host) return;
    const legend = plot.root.querySelector<HTMLElement>('.u-legend');
    plot.setSize(sizeNow(legend?.offsetHeight ?? 24));
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
    void config.segment;
    void $segmentStart;
    untrack(() => scheduler.markDirty(id));
  });
</script>

<div class="plotcard">
  <div class="bar">
    <div class="seg" role="group" aria-label="Plot view">
      <button aria-pressed={!view.paused} onclick={live}>Live</button>
      <button aria-pressed={view.paused} onclick={pause}>Pause</button>
    </div>
    {#if view.paused}<span class="note">Drag the plot to scrub</span>{/if}
  </div>
  {#if !axes.ok}
    <p class="note err">{axes.error}</p>
  {/if}
  <div class="host" class:scrub={view.paused} class:hide={!axes.ok} bind:this={host}></div>
</div>

<style>
  .plotcard { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .bar { display: flex; align-items: center; gap: 8px; padding: 6px 8px; flex: none; }
  .bar .seg button { padding: 2px 10px; font-size: 12px; }
  .host { flex: 1; min-height: 0; padding: 0 6px 6px; }
  .host.scrub :global(.u-over) { cursor: grab; }
  .hide { display: none; }
  .err { padding: 12px; color: var(--bad); }
  .host :global(.uplot) { font-family: var(--f-mono); }
  .host :global(.u-legend) { color: var(--muted); font-size: 12px; }
</style>

/** Pure logic behind the Plot card: axis grouping, store lookup, view range, event markers and uPlot data. */
import { METRIC_FIELDS } from '../link';
import type { SeriesStore } from '../series';
import type { Channel, FlightSchema, GuiEvent } from '../types';
import { type UnitPrefs, convert, unitFor } from '../units';

export interface PlotSeries { field: string; source: string }
export type PlotData = (number | null)[][];

const METRIC_QUANTITY: Record<string, string> = { 'm.rssi': 'power_dbfs', 'm.noise': 'power_dbfs', 'm.snr': 'power_db', 'm.df': 'frequency' };
const MARKER_KINDS = ['launch', 'burnout', 'apogee', 'landing', 'flight_reset'];

/** The quantity a series field measures, or null when unknown. */
export function quantityOf(field: string, schema: FlightSchema | null): string | null {
  if (field.startsWith('m.')) return METRIC_QUANTITY[field] ?? null;
  return schema?.fields.find((f) => f.key === field)?.quantity ?? null;
}

/** The uPlot scale key a series is drawn on: its quantity, or the first axis' quantity when its field has none. One rule for build() and yRanges. */
export function scaleKeyOf(field: string, schema: FlightSchema | null, axisQuantities: string[]): string {
  return quantityOf(field, schema) ?? axisQuantities[0] ?? '';
}

/** Distinct quantities in series order. A plot has at most two value axes (left and right). */
export function axesFor(series: PlotSeries[], schema: FlightSchema | null): { quantities: string[]; ok: boolean; error?: string } {
  const quantities: string[] = [];
  for (const s of series) {
    const q = quantityOf(s.field, schema);
    if (q === null) return { quantities, ok: false, error: `Unknown field '${s.field}'` };
    if (!quantities.includes(q)) quantities.push(q);
  }
  if (quantities.length > 2) return { quantities, ok: false, error: 'A plot can show at most two different quantities' };
  return { quantities, ok: true };
}

/** `both` becomes an A series and a B series; others pass through. */
export function expandSeries(series: PlotSeries[]): PlotSeries[] {
  return series.flatMap((s) => (s.source === 'both' ? [{ ...s, source: 'A' }, { ...s, source: 'B' }] : [s]));
}

export interface PlotStores {
  flight: { best?: SeriesStore; A?: SeriesStore; B?: SeriesStore };
  metrics: Record<Channel, SeriesStore>;
}

/** The ring a series reads, or null when its origin is not subscribed. Link metrics have no `best`; it reads channel A. */
export function storeFor(s: PlotSeries, stores: PlotStores): SeriesStore | null {
  if (s.field.startsWith('m.')) return stores.metrics[s.source === 'B' ? 'B' : 'A'] ?? null;
  const origin = s.source === 'A' || s.source === 'B' ? s.source : 'best';
  return stores.flight[origin] ?? null;
}

/** Column of a field inside its store, or -1. */
export function columnOf(field: string, schema: FlightSchema | null): number {
  if (field.startsWith('m.')) return (METRIC_FIELDS as readonly string[]).indexOf(field.slice(2));
  return schema?.fields.findIndex((f) => f.key === field) ?? -1;
}

export interface ViewState { paused: boolean; pausedAt: number | null; offsetS: number }

/** Visible time span. Live follows now; paused holds the pause time minus the scrub offset, clamped to the data. */
export function viewRange(state: ViewState, nowS: number, windowS: number, dataT0: number): [number, number] {
  const end = state.paused ? (state.pausedAt ?? nowS) : nowS;
  const lo = Number.isFinite(dataT0) ? Math.min(dataT0, end) : end;
  const span = windowS > 0 ? windowS : Math.max(end - lo, 1);
  if (!state.paused) return [windowS > 0 ? end - span : lo, end];
  let t1 = end - Math.max(0, state.offsetS);
  let t0 = t1 - span;
  if (t0 < lo) {
    t0 = lo;
    t1 = Math.min(end, lo + span);
  }
  return [t0, t1];
}

/** Flight milestones (launch, burnout, apogee, landing, flight_reset) inside [t0, t1]. */
export function eventMarkers(events: readonly GuiEvent[], t0: number, t1: number): { t: number; label: string }[] {
  const out: { t: number; label: string }[] = [];
  for (const e of events) {
    if (e.category === 'flight' && MARKER_KINDS.includes(e.kind) && e.t >= t0 && e.t <= t1) out.push({ t: e.t, label: e.kind });
  }
  return out;
}

export interface PlotInput { store: SeriesStore; col: number; quantity: string }

/** uPlot AlignedData: [times, ...series] in display units on the union of all series' times, with nulls where one has no row. */
export function buildData(
  inputs: PlotInput[], t0: number, t1: number, prefs: UnitPrefs, cardUnits: Record<string, string> | undefined,
): PlotData {
  const times: Float64Array[] = [];
  const values: Float64Array[] = [];
  for (const inp of inputs) {
    const w = inp.store.windowFrom(t0);   // buffers are reused per store, so copy out before the next call
    let n = w.n;
    while (n > 0 && w.t[n - 1] > t1) n--;
    const unit = unitFor(inp.quantity, cardUnits, prefs);
    const col = w.cols[inp.col];
    const t = w.t.slice(0, n);
    const v = new Float64Array(n);
    for (let i = 0; i < n; i++) v[i] = col ? (unit ? convert(col[i], inp.quantity, unit) : col[i]) : NaN;
    times.push(t);
    values.push(v);
  }
  if (inputs.length === 1) {
    return [Array.from(times[0]), Array.from(values[0], (x) => (Number.isFinite(x) ? x : null))];
  }
  const union = [...new Set(times.flatMap((t) => Array.from(t)))].sort((a, b) => a - b);
  const out: PlotData = [union];
  inputs.forEach((_, k) => {
    const col: (number | null)[] = new Array(union.length).fill(null);
    let j = 0;
    for (let i = 0; i < union.length && j < times[k].length; i++) {
      if (times[k][j] === union[i]) {
        col[i] = Number.isFinite(values[k][j]) ? values[k][j] : null;
        j++;
      }
    }
    out.push(col);
  });
  return out;
}

const Y_PAD = 0.06;   // fraction of the span added above and below

/**
 * Y range per quantity that tightly frames the plotted (visible-window) data with a small pad. `data` is the
 * uPlot AlignedData from buildData; `quantities[i]` is the quantity of series i (data column i + 1). A quantity
 * with no finite value gets [0, 1]. `fixed` (the config's manual y) applies to the first quantity only.
 */
export function yRanges(
  data: PlotData, quantities: string[], fixed: { min: number; max: number } | null,
): Record<string, [number, number]> {
  const lo: Record<string, number> = {};
  const hi: Record<string, number> = {};
  quantities.forEach((q, i) => {
    for (const v of data[i + 1] ?? []) {
      if (v === null || !Number.isFinite(v)) continue;
      lo[q] = Math.min(lo[q] ?? Infinity, v);
      hi[q] = Math.max(hi[q] ?? -Infinity, v);
    }
  });
  const out: Record<string, [number, number]> = {};
  quantities.forEach((q, i) => {
    if (q in out) return;
    if (i === 0 && fixed) { out[q] = [fixed.min, fixed.max]; return; }
    if (!(q in lo)) { out[q] = [0, 1]; return; }
    const pad = (hi[q] - lo[q]) * Y_PAD || Math.abs(hi[q]) * Y_PAD || 1;
    out[q] = [lo[q] - pad, hi[q] + pad];
  });
  return out;
}

/** Canvas size for a plot host, leaving room for the legend below it (one formula for build and resize). */
export function plotSize(hostW: number, hostH: number, legendH: number): { width: number; height: number } {
  return { width: Math.max(Math.floor(hostW), 50), height: Math.max(Math.floor(hostH - legendH - 6), 50) };
}

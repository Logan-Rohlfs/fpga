/** Pure helpers for the link / channel quality card (spec section 6). */
import type { SeriesStore } from '../series';

const GOOD = 4;   // METRIC_FIELDS index of crc_good
const BAD = 5;    // METRIC_FIELDS index of crc_bad

/** Counter increase over the first `n` samples. A negative step is a restart from 0, so the new value is added. */
export function deltaOver(ts: ArrayLike<number>, vs: ArrayLike<number>, n: number, windowS: number, nowS: number): number | null {
  const t0 = nowS - windowS;
  let prev = NaN;
  let sum = 0;
  let seen = 0;
  for (let i = 0; i < n; i++) {
    if (!(ts[i] >= t0) || ts[i] > nowS) continue;
    const v = vs[i];
    if (!Number.isFinite(v)) continue;
    if (seen > 0) sum += v >= prev ? v - prev : v;
    prev = v;
    seen++;
  }
  return seen >= 2 ? sum : null;
}

function span(ts: ArrayLike<number>, n: number, windowS: number, nowS: number): number {
  let first = NaN;
  let last = NaN;
  for (let i = 0; i < n; i++) {
    if (ts[i] < nowS - windowS || ts[i] > nowS) continue;
    if (Number.isNaN(first)) first = ts[i];
    last = ts[i];
  }
  return last - first;
}

/** Good frames per second over the window; null with fewer than two samples. */
export function frameRate(store: SeriesStore, windowS: number, nowS: number): number | null {
  const w = store.windowFrom(nowS - windowS);
  const d = deltaOver(w.t, w.cols[GOOD], w.n, windowS, nowS);
  const dt = span(w.t, w.n, windowS, nowS);
  return d === null || !(dt > 0) ? null : d / dt;
}

/** crc_bad / (crc_good + crc_bad) over the window; null with no samples or no frames. */
export function badRatio(store: SeriesStore, windowS: number, nowS: number): number | null {
  const w = store.windowFrom(nowS - windowS);
  const g = deltaOver(w.t, w.cols[GOOD], w.n, windowS, nowS);
  const b = deltaOver(w.t, w.cols[BAD], w.n, windowS, nowS);
  if (g === null || b === null || g + b <= 0) return null;
  return b / (g + b);
}

/** Fractions of the frames the combiner took from each channel over the window. */
export function combinerShare(
  ring: readonly { t: number; from_a: number; from_b: number }[], windowS: number, nowS: number,
): { a: number; b: number } | null {
  const ts = ring.map((p) => p.t);
  const a = deltaOver(ts, ring.map((p) => p.from_a), ring.length, windowS, nowS);
  const b = deltaOver(ts, ring.map((p) => p.from_b), ring.length, windowS, nowS);
  if (a === null || b === null || a + b <= 0) return null;
  return { a: a / (a + b), b: b / (a + b) };
}

/** Unit text for power values. dBFS is relative to full scale, not calibrated dBm. */
export function powerLabel(unit: string | undefined, compact = false): string {
  if (!unit || unit === 'dBFS') return compact ? 'dBFS' : 'dBFS (relative)';
  return unit;
}

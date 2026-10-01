/** Pure helpers for the spectrum-family cards (waterfall, spectrum, constellation). */
import type { Budget } from '../types';

/** Per-bin peak hold. Decay 0 holds forever; otherwise a held bin falls linearly back to the current value over `decayS`. */
export class PeakHold {
  private out = new Float32Array(0);
  private start = new Float32Array(0);
  private t0 = new Float64Array(0);

  constructor(readonly decayS: number) {}

  update(db: ArrayLike<number>, tS: number): Float32Array {
    const n = db.length;
    if (this.out.length !== n) {
      this.out = new Float32Array(n);
      this.start = new Float32Array(n);
      this.t0 = new Float64Array(n);
      for (let k = 0; k < n; k++) { this.out[k] = this.start[k] = db[k]; this.t0[k] = tS; }
      return this.out;
    }
    for (let k = 0; k < n; k++) {
      if (this.decayS <= 0) {
        if (db[k] > this.start[k]) this.start[k] = db[k];
        this.out[k] = this.start[k];
        continue;
      }
      const f = Math.min(1, Math.max(0, (tS - this.t0[k]) / this.decayS));
      const decayed = this.start[k] + (db[k] - this.start[k]) * f;
      if (db[k] >= decayed) {
        this.start[k] = db[k];
        this.t0[k] = tS;
        this.out[k] = db[k];
      } else {
        this.out[k] = decayed;
      }
    }
    return this.out;
  }

  reset(): void {
    this.out = new Float32Array(0);
    this.start = new Float32Array(0);
    this.t0 = new Float64Array(0);
  }
}

/** Instantaneous frequency in Hz from consecutive I/Q pairs: atan2 of z[n]·conj(z[n-1]), times fs/2π. Length n - 1. */
export function instFreq(iq: [number, number][], fs: number): Float32Array {
  const out = new Float32Array(Math.max(0, iq.length - 1));
  for (let n = 1; n < iq.length; n++) {
    const [i0, q0] = iq[n - 1];
    const [i1, q1] = iq[n];
    out[n - 1] = (Math.atan2(q1 * i0 - i1 * q0, i1 * i0 + q1 * q0) * fs) / (2 * Math.PI);
  }
  return out;
}

/** Footer note for waterfall rows on a viewer connection, or null for operators. */
export function viewerRateNote(budget: Budget): string | null {
  return budget === 'viewer' ? 'rows at viewer rate (5 Hz)' : null;
}

/** dBFS display limits: a manual scale from the card config, else the row's server auto scale, else a fallback. */
export function scaleLimits(scale: unknown, row: { low: number; high: number } | null): [number, number] {
  if (typeof scale === 'object' && scale !== null) {
    const s = scale as { low?: unknown; high?: unknown };
    if (typeof s.low === 'number' && typeof s.high === 'number' && s.low < s.high) return [s.low, s.high];
  }
  return row ? [row.low, row.high] : [-120, -60];
}

/** Frequency axis edges for a row: bins are centred on f0_hz + k·bin_hz, so the edges sit half a bin outside. */
export function rowSpan(row: { f0_hz: number; bin_hz: number; bins: number }): [number, number] {
  const f0 = row.f0_hz - row.bin_hz / 2;
  return [f0, f0 + row.bins * row.bin_hz];
}

/** A tick step (1, 2 or 5 times a power of ten) giving roughly `target` ticks across a span. */
export function niceStep(span: number, target = 6): number {
  if (!(span > 0)) return 1;
  const raw = span / target;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

/** The newest `n` snapshots (n clamped to 1..4). */
export function lastSnaps<T>(snaps: readonly T[] | undefined, n: number): T[] {
  const keep = Math.min(4, Math.max(1, Math.floor(n) || 1));
  return (snaps ?? []).slice(-keep);
}

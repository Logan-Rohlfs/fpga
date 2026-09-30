/** Columnar ring of timestamped rows: Float64 time, one Float32 column per field (spec 11.1). */
export interface SeriesWindow { t: Float64Array; cols: Float32Array[]; n: number }

export class SeriesStore {
  readonly fieldCount: number;
  readonly capacity: number;
  /** Increments on every append or clear. */
  version = 0;
  private ts: Float64Array;
  private fl: Uint8Array;
  private cols: Float32Array[];
  private start = 0;
  private count = 0;
  private win: SeriesWindow | null = null;

  constructor(fieldCount: number, capacity = 36000) {
    this.fieldCount = fieldCount;
    this.capacity = capacity;
    this.ts = new Float64Array(capacity);
    this.fl = new Uint8Array(capacity);
    this.cols = Array.from({ length: fieldCount }, () => new Float32Array(capacity));
  }

  get length(): number {
    return this.count;
  }

  /** Append one row; `values[offset .. offset + fieldCount)` are its fields. */
  append(t: number, flags: number, values: ArrayLike<number>, offset = 0): void {
    let slot: number;
    if (this.count < this.capacity) {
      slot = (this.start + this.count) % this.capacity;
      this.count++;
    } else {
      slot = this.start;
      this.start = (this.start + 1) % this.capacity;
    }
    this.ts[slot] = t;
    this.fl[slot] = flags;
    for (let k = 0; k < this.fieldCount; k++) {
      const x = values[offset + k];
      this.cols[k][slot] = x ?? NaN;
    }
    this.version++;
  }

  clear(): void {
    this.start = 0;
    this.count = 0;
    this.version++;
  }

  private slot(i: number): number {
    return (this.start + i) % this.capacity;
  }

  /** Time of row i, 0 = oldest. */
  timeAt(i: number): number {
    return this.ts[this.slot(i)];
  }

  valueAt(i: number, field: number): number {
    return this.cols[field][this.slot(i)];
  }

  flagsAt(i: number): number {
    return this.fl[this.slot(i)];
  }

  latest(): { t: number; flags: number; values: Float32Array } | null {
    if (!this.count) return null;
    const s = this.slot(this.count - 1);
    return { t: this.ts[s], flags: this.fl[s], values: Float32Array.from(this.cols, (c) => c[s]) };
  }

  /** Rows with t >= t0, oldest first, copied into buffers reused by the next call. */
  windowFrom(t0: number): SeriesWindow {
    if (!this.win) {
      this.win = {
        t: new Float64Array(this.capacity),
        cols: Array.from({ length: this.fieldCount }, () => new Float32Array(this.capacity)),
        n: 0,
      };
    }
    // Times are appended in order, so binary-search the first row at or after t0.
    let lo = 0;
    let hi = this.count;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.timeAt(mid) < t0) lo = mid + 1;
      else hi = mid;
    }
    const w = this.win;
    w.n = this.count - lo;
    for (let i = 0; i < w.n; i++) {
      const s = this.slot(lo + i);
      w.t[i] = this.ts[s];
      for (let k = 0; k < this.fieldCount; k++) w.cols[k][i] = this.cols[k][s];
    }
    return w;
  }
}

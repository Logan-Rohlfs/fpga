import { describe, expect, it } from 'vitest';
import { SeriesStore } from './series';

describe('SeriesStore', () => {
  it('wraps at capacity, keeping the newest rows', () => {
    const s = new SeriesStore(2, 4);
    for (let i = 0; i < 6; i++) s.append(i, i & 1, [i * 10, i * 100]);
    expect(s.length).toBe(4);
    expect(s.timeAt(0)).toBe(2);
    expect(s.valueAt(0, 1)).toBe(200);
    expect(s.timeAt(3)).toBe(5);
    expect(s.latest()).toEqual({ t: 5, flags: 1, values: new Float32Array([50, 500]) });
  });

  it('returns a window oldest first across the wrap', () => {
    const s = new SeriesStore(1, 4);
    for (let i = 0; i < 6; i++) s.append(i, 0, [i]);
    const w = s.windowFrom(3);
    expect(w.n).toBe(3);
    expect(Array.from(w.t.subarray(0, w.n))).toEqual([3, 4, 5]);
    expect(Array.from(w.cols[0].subarray(0, w.n))).toEqual([3, 4, 5]);
    expect(s.windowFrom(-Infinity).n).toBe(4);
    expect(s.windowFrom(99).n).toBe(0);
  });

  it('reads values at an offset of a row-major batch', () => {
    const s = new SeriesStore(2, 8);
    const batch = new Float32Array([1, 2, 3, 4]);
    s.append(0, 0, batch, 0);
    s.append(1, 0, batch, 2);
    expect(s.valueAt(1, 0)).toBe(3);
    expect(s.valueAt(1, 1)).toBe(4);
  });

  it('is empty with no latest row, and counts versions', () => {
    const s = new SeriesStore(1, 4);
    expect(s.latest()).toBeNull();
    const v0 = s.version;
    s.append(1, 0, [1]);
    expect(s.version).toBe(v0 + 1);
    s.clear();
    expect(s.version).toBe(v0 + 2);
    expect(s.length).toBe(0);
    expect(s.latest()).toBeNull();
  });
});

import { describe, expect, it } from 'vitest';
import { windowRange } from './virtual';

describe('windowRange', () => {
  it('empty list', () => {
    expect(windowRange(0, 300, 20, 0)).toEqual({ start: 0, end: 0, padTop: 0, padBottom: 0 });
  });
  it('top is clamped at zero', () => {
    const r = windowRange(0, 100, 20, 1000, 8);
    expect(r.start).toBe(0);
    expect(r.end).toBe(5 + 8);
    expect(r.padTop).toBe(0);
  });
  it('middle applies overscan both sides', () => {
    const r = windowRange(2000, 100, 20, 1000, 8);
    expect(r.start).toBe(100 - 8);
    expect(r.end).toBe(105 + 8);
  });
  it('bottom is clamped at count and past-the-end scroll is safe', () => {
    const r = windowRange(1e9, 100, 20, 50, 8);
    expect(r.end).toBe(50);
    expect(r.start).toBeLessThanOrEqual(50);
    expect(r.padBottom).toBe(0);
  });
  it('padding plus rows always equals the full height', () => {
    for (const [top, count] of [[0, 1000], [777, 1000], [5000, 1000], [1e6, 40], [30, 3]]) {
      const r = windowRange(top, 120, 18, count, 8);
      expect(r.padTop + (r.end - r.start) * 18 + r.padBottom).toBe(count * 18);
    }
  });
  it('non-finite scroll or viewport never yields NaN', () => {
    for (const [top, h] of [[NaN, 100], [0, NaN], [Infinity, 100], [NaN, NaN]]) {
      const r = windowRange(top, h, 20, 100, 8);
      for (const v of Object.values(r)) expect(Number.isFinite(v)).toBe(true);
      expect(r.padTop + (r.end - r.start) * 20 + r.padBottom).toBe(2000);
    }
  });
});

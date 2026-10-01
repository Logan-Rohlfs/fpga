import { describe, expect, it } from 'vitest';
import { SeriesStore } from '../series';
import { badRatio, combinerShare, deltaOver, frameRate, powerLabel } from './linkq';

function store(rows: [number, number, number][]): SeriesStore {
  const s = new SeriesStore(6, 64);
  for (const [t, good, bad] of rows) s.append(t, 0, [0, 0, 0, 0, good, bad]);
  return s;
}

describe('linkq', () => {
  it('rates frames per second', () => {
    const s = store(Array.from({ length: 11 }, (_, i) => [100 + i, i * 20, 0] as [number, number, number]));
    expect(frameRate(s, 10, 110)).toBeCloseTo(20);
  });
  it('counts across a counter reset', () => {
    expect(deltaOver([0, 1, 2], [100, 150, 3], 3, 10, 2)).toBe(53);
    expect(deltaOver([0, 1, 2, 3], [0, 150, 3, 3], 4, 10, 3)).toBe(153);
  });
  it('computes bad ratio', () => {
    const s = store([[0, 0, 0], [10, 190, 10]]);
    expect(badRatio(s, 10, 10)).toBeCloseTo(0.05);
  });
  it('computes combiner share', () => {
    const ring = [{ t: 0, from_a: 0, from_b: 0 }, { t: 10, from_a: 70, from_b: 30 }];
    const r = combinerShare(ring, 10, 10)!;
    expect(r.a).toBeCloseTo(0.7);
    expect(r.b).toBeCloseTo(0.3);
  });
  it('gives null for empty input', () => {
    const s = new SeriesStore(6, 8);
    expect(frameRate(s, 10, 10)).toBeNull();
    expect(badRatio(s, 10, 10)).toBeNull();
    expect(combinerShare([], 10, 10)).toBeNull();
  });
  it('labels power units', () => {
    expect(powerLabel('dBFS')).toBe('dBFS (relative)');
    expect(powerLabel('dBFS', true)).toBe('dBFS');
    expect(powerLabel('dBm')).toBe('dBm');
    expect(powerLabel(undefined)).toBe('dBFS (relative)');
  });
});

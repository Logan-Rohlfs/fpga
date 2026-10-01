import { describe, expect, it } from 'vitest';
import { PeakHold, instFreq, lastSnaps, niceStep, rowSpan, scaleLimits, viewerRateNote } from './spectral';

describe('PeakHold', () => {
  it('keeps the max and decays to the current value after decayS', () => {
    const p = new PeakHold(10);
    p.update([0, 0], 0);
    expect(Array.from(p.update([-60, -60], 0))).toEqual([0, 0]);
    expect(p.update([-60, -60], 5)[0]).toBeCloseTo(-30);
    expect(p.update([-60, -60], 10)[0]).toBeCloseTo(-60);
    expect(p.update([-60, -60], 20)[0]).toBeCloseTo(-60);
  });
  it('a new maximum replaces the held value', () => {
    const p = new PeakHold(10);
    p.update([-50], 0);
    expect(p.update([-20], 1)[0]).toBe(-20);
  });
  it('decay 0 holds forever', () => {
    const p = new PeakHold(0);
    p.update([-10, -90], 0);
    expect(Array.from(p.update([-80, -95], 1e6))).toEqual([-10, -90]);
  });
  it('follows a change in bin count and resets', () => {
    const p = new PeakHold(0);
    p.update([1, 2, 3], 0);
    expect(p.update([5, 5, 5, 5], 1).length).toBe(4);
    p.reset();
    expect(Array.from(p.update([-1], 2))).toEqual([-1]);
  });
});

describe('instFreq', () => {
  it('gives the tone frequency for a pure tone', () => {
    const fs = 1e6;
    const iq: [number, number][] = [];
    for (let n = 0; n < 64; n++) iq.push([Math.cos((2 * Math.PI * 1000 * n) / fs), Math.sin((2 * Math.PI * 1000 * n) / fs)]);
    const f = instFreq(iq, fs);
    expect(f.length).toBe(63);
    for (const v of f) expect(v).toBeCloseTo(1000, 0);
  });
  it('is negative for a negative tone', () => {
    const iq: [number, number][] = [[1, 0], [Math.cos(-0.1), Math.sin(-0.1)]];
    expect(instFreq(iq, 2 * Math.PI)[0]).toBeCloseTo(-0.1, 5);
  });
  it('empty and single inputs give an empty array', () => {
    expect(instFreq([], 1e6).length).toBe(0);
    expect(instFreq([[1, 1]], 1e6).length).toBe(0);
  });
});

describe('viewerRateNote', () => {
  it('mentions 5 Hz for viewers only', () => {
    expect(viewerRateNote('viewer')).toContain('5 Hz');
    expect(viewerRateNote('operator')).toBeNull();
  });
});

describe('display helpers', () => {
  it('scaleLimits prefers a valid manual scale, then the row, then a fallback', () => {
    expect(scaleLimits({ low: -100, high: -40 }, { low: -120, high: -60 })).toEqual([-100, -40]);
    expect(scaleLimits('auto', { low: -120, high: -60 })).toEqual([-120, -60]);
    expect(scaleLimits({ low: 1, high: 0 }, null)).toEqual([-120, -60]);
  });
  it('rowSpan follows bins, whatever the count', () => {
    expect(rowSpan({ f0_hz: 0, bin_hz: 10, bins: 128 })).toEqual([-5, 1275]);
    expect(rowSpan({ f0_hz: 100, bin_hz: 2, bins: 256 })).toEqual([99, 611]);
  });
  it('niceStep picks 1-2-5 steps', () => {
    expect(niceStep(60000)).toBe(10000);
    expect(niceStep(0)).toBe(1);
  });
  it('lastSnaps clamps persistence', () => {
    expect(lastSnaps([1, 2, 3, 4], 2)).toEqual([3, 4]);
    expect(lastSnaps([1, 2], 9)).toEqual([1, 2]);
    expect(lastSnaps(undefined, 1)).toEqual([]);
  });
});

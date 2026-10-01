import { describe, expect, it } from 'vitest';
import { clampToSegment, firstRowFrom, segmentFloor } from './segment';

describe('segmentFloor', () => {
  it('only the current segment has a floor', () => {
    expect(segmentFloor('current', 42)).toBe(42);
    expect(segmentFloor('current', null)).toBe(-Infinity);
    expect(segmentFloor('all', 42)).toBe(-Infinity);
  });
});

describe('firstRowFrom', () => {
  const times = [1, 2, 3, 10, 11];
  const store = { length: times.length, timeAt: (i: number) => times[i] };
  it('finds the first row at or after the floor', () => {
    expect(firstRowFrom(store, -Infinity)).toBe(0);
    expect(firstRowFrom(store, 3)).toBe(2);
    expect(firstRowFrom(store, 4)).toBe(3);
    expect(firstRowFrom(store, 99)).toBe(5);
  });
});

describe('clampToSegment', () => {
  it('moves the view start up to the floor, never past the end', () => {
    expect(clampToSegment([0, 60], 20)).toEqual([20, 60]);
    expect(clampToSegment([30, 60], 20)).toEqual([30, 60]);
    expect(clampToSegment([0, 60], -Infinity)).toEqual([0, 60]);
    expect(clampToSegment([0, 60], 61)).toEqual([0, 60]);
  });
});

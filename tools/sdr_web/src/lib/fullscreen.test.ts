import { describe, expect, it } from 'vitest';
import { fitRowPx } from './fullscreen';

describe('fitRowPx', () => {
  it('stretches rows so the layout fills the available height', () => {
    // 20 rows and 19 gaps of 8 px in 568 px: (568 - 152) / 20 = 20.8
    expect(fitRowPx(568, 20, 8)).toBe(20);
  });
  it('never shrinks below the minimum (the page scrolls instead) or grows past the maximum', () => {
    expect(fitRowPx(300, 80, 8)).toBe(12);
    expect(fitRowPx(5000, 4, 8)).toBe(80);
  });
  it('falls back to the normal row for an empty layout, and the minimum with no measured height', () => {
    expect(fitRowPx(800, 0, 8)).toBe(16);
    expect(fitRowPx(0, 10, 8)).toBe(12);
  });
});

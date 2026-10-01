import { afterEach, describe, expect, it, vi } from 'vitest';
import { PAD, fOf, ifToRf, makeAxis, ticks, xOf } from './axis';
import { LUT } from './colormap';
import { hex32, khz, mhz, signedKhz } from './format';
import { createCoalescer } from './throttle';
import { paintRow } from './waterfall';

describe('format', () => {
  it('formats radio units', () => {
    expect(mhz(441.38e6, 3)).toBe('441.380');
    expect(khz(110400)).toBe('110.4 kHz');
    expect(signedKhz(-10400)).toBe('−10.4 kHz');
    expect(signedKhz(10400)).toBe('+10.4 kHz');
    expect(hex32(0x1999999a)).toBe('0x1999999A');
  });
});

describe('axis', () => {
  it('maps frequency to pixels and back', () => {
    const a = makeAxis(50e3, 150e3, 454);
    expect(xOf(a, 50e3)).toBe(PAD.left);
    expect(xOf(a, 150e3)).toBe(454 - PAD.right);
    expect(fOf(a, xOf(a, 123e3))).toBeCloseTo(123e3, 6);
    expect(ticks(50e3, 150e3, 25e3)).toEqual([50e3, 75e3, 100e3, 125e3, 150e3]);
  });
  it('maps IF to RF for either injection side', () => {
    expect(ifToRf(441.38e6, 'low', 100e3)).toBe(441.48e6);
    expect(ifToRf(441.58e6, 'high', 100e3)).toBe(441.48e6);
  });
});

describe('colormap and waterfall rows', () => {
  it('runs dark to bright', () => {
    const lum = (i: number) => LUT[i * 3] * 0.2126 + LUT[i * 3 + 1] * 0.7152 + LUT[i * 3 + 2] * 0.0722;
    expect(LUT.length).toBe(768);
    expect(lum(0)).toBeLessThan(lum(128));
    expect(lum(128)).toBeLessThan(lum(255));
  });
  it('paints clamped RGBA pixels', () => {
    const out = new Uint8ClampedArray(3 * 4);
    paintRow(out, [-1300, -900, -400], -120, -50);   // below, middle, above the scale
    expect([out[0], out[1], out[2], out[3]]).toEqual([LUT[0], LUT[1], LUT[2], 255]);
    expect([out[8], out[9], out[10]]).toEqual([LUT[765], LUT[766], LUT[767]]);
    expect(out[4]).toBe(LUT[Math.round((30 / 70) * 255) * 3]);
  });
});

describe('coalescer', () => {
  afterEach(() => vi.useRealTimers());
  it('sends the first update now and merges the rest per interval', () => {
    vi.useFakeTimers();
    const sent: object[] = [];
    const c = createCoalescer<Record<string, number>>((m) => sent.push(m), 33);
    c.push({ lo_hz: 1 });
    c.push({ lo_hz: 2 });
    c.push({ nco_hz: 3 });
    expect(sent).toEqual([{ lo_hz: 1 }]);
    vi.advanceTimersByTime(33);
    expect(sent).toEqual([{ lo_hz: 1 }, { lo_hz: 2, nco_hz: 3 }]);
  });
});

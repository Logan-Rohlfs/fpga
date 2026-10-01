import { describe, expect, it } from 'vitest';
import { SeriesStore } from '../series';
import type { FlightSchema } from '../types';
import { enu, gpsValid, tileXY } from '../geo';
import { altitudeColor, cameraOffset, darken, edgeAverage, fitDistance, followAzimuth, groundProjection, groundTiles, trackSphere, trackPoints } from './traj';

const keys = ['gps_fix', 'lat_deg', 'lon_deg', 'alt_agl_m'];
const schema: FlightSchema = { version: 1, fields: keys.map((key) => ({ key, label: key, quantity: 'x' })) };
const PAD: [number, number] = [32.9, -106.9];

function store(rows: number[][]): SeriesStore {
  const s = new SeriesStore(keys.length, 64);
  rows.forEach((r, i) => s.append(i, 0, r));
  return s;
}

describe('trackPoints', () => {
  it('starts from a row index', () => {
    const t = trackPoints(store([[0, 65.7, 123.2, 10], [0, 65.7, 123.2, 250], [0, 65.7, 123.2, 40]]), schema, PAD, 1, 2);
    expect(t.points.length).toBe(3);
    expect(t.maxAlt).toBe(40);
  });
  it('is a column over the pad when no row has valid GPS', () => {
    const t = trackPoints(store([[0, 65.7, 123.2, 10], [0, 65.7, 123.2, 250]]), schema, PAD, 2);
    expect(t.mode).toBe('column');
    expect(t.points.length).toBe(6);
    for (let i = 0; i < 2; i++) {
      expect(t.points[i * 3]).toBe(0);
      expect(t.points[i * 3 + 2]).toBe(0);
    }
    expect(t.points[1]).toBe(20);
    expect(t.points[4]).toBe(500);
    expect(t.maxAlt).toBe(250);
  });

  it('maps north to -z for valid rows and skips invalid ones', () => {
    const t = trackPoints(store([[0, 1, 1, 5], [3, PAD[0] + 0.01, PAD[1], 100]]), schema, PAD, 1);
    expect(t.mode).toBe('track');
    expect(t.points.length).toBe(3);
    expect(Math.abs(t.points[0])).toBeLessThan(2); // the Float32 store limits lat/lon to about a metre
    expect(t.points[1]).toBe(100);
    expect(Math.abs(t.points[2] + 1105)).toBeLessThan(2);
  });

  it('skips valid-GPS rows with no altitude instead of plotting them at 0', () => {
    const t = trackPoints(store([[3, PAD[0] + 0.01, PAD[1], NaN], [3, PAD[0] + 0.01, PAD[1], 50]]), schema, PAD, 1);
    expect(t.mode).toBe('track');
    expect(t.points.length).toBe(3);
    expect(t.points[1]).toBe(50);
  });

  it('is an empty column for an empty store', () => {
    const t = trackPoints(store([]), schema, PAD, 1);
    expect(t.mode).toBe('column');
    expect(t.points.length).toBe(0);
  });
});

describe('gpsValid and enu', () => {
  it('accepts fixes 2-4 only, with sane non-zero coordinates', () => {
    expect(gpsValid(3, 32, -106)).toBe(true);
    expect(gpsValid(1, 32, -106)).toBe(false);
    expect(gpsValid(0, 32, -106)).toBe(false);
    expect(gpsValid(3, 0, 0)).toBe(false);
    expect(gpsValid(3, 91, 0)).toBe(false);
    expect(gpsValid(3, NaN, 0)).toBe(false);
  });
  it('projects east and north metres', () => {
    expect(enu(33, -107, 32, -107).north).toBeCloseTo(110540, 3);
    expect(enu(32, -106, 32, -107).east).toBeCloseTo(111320 * Math.cos((32 * Math.PI) / 180), 3);
  });
});

describe('groundTiles', () => {
  it('covers +-4 km around the pad', () => {
    const g = groundTiles(PAD);
    expect(g.z).toBe(15);
    expect(g.sizeM).toBeGreaterThanOrEqual(8000);
    expect(g.x1).toBeGreaterThanOrEqual(g.x0);
    expect(g.y1).toBeGreaterThanOrEqual(g.y0);
    expect(g.originEast).toBeLessThanOrEqual(-4000);
    expect(g.originNorth).toBeGreaterThanOrEqual(4000);
    const pad = tileXY(PAD[0], PAD[1], 15);
    expect(pad.x).toBeGreaterThanOrEqual(g.x0);
    expect(pad.x).toBeLessThanOrEqual(g.x1);
    expect(pad.y).toBeGreaterThanOrEqual(g.y0);
    expect(pad.y).toBeLessThanOrEqual(g.y1);
  });
});

describe('altitudeColor', () => {
  it('differs between low and high and stays in range', () => {
    expect(altitudeColor(0)).not.toEqual(altitudeColor(1));
    for (const t of [-1, 0, 0.3, 1, 2, NaN]) for (const c of altitudeColor(t)) expect(c >= 0 && c <= 1).toBe(true);
  });
});

describe('camera framing', () => {
  it('bounds the track and the pad, with a minimum radius so launch starts close', () => {
    const s = trackSphere(new Float32Array([0, 0, 0, 0, 1000, 0]), 50);
    expect(s.center).toEqual([0, 500, 0]);
    expect(s.r).toBeCloseTo(500);
    const tiny = trackSphere(new Float32Array([0, 2, 0]), 50);
    expect(tiny.r).toBe(50);
    expect(trackSphere(new Float32Array(0), 50)).toEqual({ center: [0, 0, 0], r: 50 });
  });

  it('includes the pad even before the track leaves it', () => {
    const s = trackSphere(new Float32Array([400, 0, 0]), 10);
    expect(s.center[0]).toBeCloseTo(200);
    expect(s.r).toBeCloseTo(200);
  });

  it('backs off far enough to fit the sphere in the narrower field of view', () => {
    const wide = fitDistance(100, 50, 2, 1);
    expect(wide).toBeCloseTo(100 / Math.sin((25 * Math.PI) / 180));
    // a tall, narrow card is limited by its horizontal field of view, so it must back off further
    expect(fitDistance(100, 50, 0.5, 1)).toBeGreaterThan(wide);
    expect(fitDistance(100, 50, 2, 1.3)).toBeCloseTo(wide * 1.3);
  });

  it('places the camera at an azimuth and elevation around the target', () => {
    const [x, y, z] = cameraOffset(0, 0, 10);
    expect([x, y, z].map((v) => +v.toFixed(6))).toEqual([0, 0, 10]);
    const up = cameraOffset(Math.PI / 2, Math.PI / 6, 10);
    expect(up[0]).toBeCloseTo(10 * Math.cos(Math.PI / 6));
    expect(up[1]).toBeCloseTo(5);
    expect(up[2]).toBeCloseTo(0);
  });

  it('looks side-on: perpendicular to the drift, on the side nearest the current view', () => {
    // drift due east (+x): side-on views are from +z (az 0) or -z (az pi)
    const pts = new Float32Array([0, 0, 0, 500, 1000, 0]);
    expect(followAzimuth(pts, 0.3, 50)).toBeCloseTo(0);
    expect(followAzimuth(pts, 2.9, 50)).toBeCloseTo(Math.PI);
  });

  it('keeps the previous azimuth while the drift is too small to have a direction', () => {
    const pts = new Float32Array([0, 0, 0, 10, 2000, 5]);
    expect(followAzimuth(pts, 1.234, 50)).toBe(1.234);
  });
});

describe('edgeAverage', () => {
  it('averages the border band and skips transparent (not loaded) pixels', () => {
    const w = 4, h = 4;
    const data = new Uint8ClampedArray(w * h * 4);
    for (let i = 0; i < w * h; i++) data.set([100, 50, 0, 255], i * 4);
    data.set([200, 200, 200, 0], 0);   // a border pixel with no tile yet
    data.set([255, 255, 255, 255], (1 * w + 1) * 4);   // interior pixel, outside a 1 px band
    expect(edgeAverage(data, w, h, 1)).toEqual([100, 50, 0]);
  });
  it('is null when no border tile has loaded', () => {
    expect(edgeAverage(new Uint8ClampedArray(2 * 2 * 4), 2, 2, 1)).toBeNull();
  });
});

describe('ground trace helpers', () => {
  it('flattens the track onto the ground', () => {
    expect(Array.from(groundProjection(new Float32Array([1, 500, -2, 3, 900, 4]), 0.5))).toEqual([1, 0.5, -2, 3, 0.5, 4]);
  });
  it('darkens a colour toward black', () => {
    expect(darken([200, 100, 50], 0.5)).toEqual([100, 50, 25]);
    expect(darken([200, 100, 50], 0)).toEqual([200, 100, 50]);
    expect(darken([200, 100, 50], 2)).toEqual([0, 0, 0]);
  });
});

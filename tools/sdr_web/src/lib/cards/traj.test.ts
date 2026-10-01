import { describe, expect, it } from 'vitest';
import { SeriesStore } from '../series';
import type { FlightSchema } from '../types';
import { enu, gpsValid, tileXY } from '../geo';
import { altitudeColor, groundTiles, trackPoints } from './traj';

const keys = ['gps_fix', 'lat_deg', 'lon_deg', 'alt_agl_m'];
const schema: FlightSchema = { version: 1, fields: keys.map((key) => ({ key, label: key, quantity: 'x' })) };
const PAD: [number, number] = [32.9, -106.9];

function store(rows: number[][]): SeriesStore {
  const s = new SeriesStore(keys.length, 64);
  rows.forEach((r, i) => s.append(i, 0, r));
  return s;
}

describe('trackPoints', () => {
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

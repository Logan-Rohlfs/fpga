import { describe, expect, it } from 'vitest';
import {
  boundsFor, distanceKm, enu, footerText, gpsStatus, gpsValid, graticule, layerPlan, makeSeeder, niceStep, resolveSite, rowValid,
  tileXY, validTrack, framingBounds, needsRefit, nearestSite, lastFix, type Bounds, type LatLon, type SiteInfo,
} from './geo';
import { SeriesStore } from './series';
import type { FlightSchema } from './types';

const schema: FlightSchema = {
  version: 1,
  fields: [
    { key: 'gps_fix', label: 'GPS fix', quantity: 'enum_signed', enum_map: { '0': 'SEARCHING', '3': '3D fix' } },
    { key: 'gps_sats', label: 'Sats', quantity: 'count' },
    { key: 'lat_deg', label: 'Lat', quantity: 'coordinate' },
    { key: 'lon_deg', label: 'Lon', quantity: 'coordinate' },
  ],
};

const site: SiteInfo = {
  id: 'seymour', name: 'Seymour, TX', center: [33.4986975, -99.3329862], pad: [33.4986975, -99.3329862],
  outer_radius_km: 20, inner_radius_km: 5, outer_max_z: 13,
  layers: { imagery: { min_z: 5, max_z: 17 }, topo: { min_z: 5, max_z: 11 } },
};

describe('gpsValid', () => {
  it('rejects the demo, DR, zero and non-finite positions', () => {
    expect(gpsValid(0, 65.7, 123.2)).toBe(false);
    expect(gpsValid(1, 33.5, -99.3)).toBe(false);
    expect(gpsValid(3, 0, 0)).toBe(false);
    expect(gpsValid(3, NaN, 1)).toBe(false);
    expect(gpsValid(3, 91, 0)).toBe(false);
    expect(gpsValid(3, 10, 181)).toBe(false);
  });
  it('accepts 2D, 3D and 3D+DR fixes', () => {
    for (const fix of [2, 3, 4]) expect(gpsValid(fix, 33.5, -99.3)).toBe(true);
    expect(gpsValid(3, 0, 12)).toBe(true);
  });
  it('rowValid wraps it', () => {
    expect(rowValid({ gps_fix: 3, lat_deg: 33.5, lon_deg: -99.3 })).toBe(true);
    expect(rowValid({ gps_fix: 0, lat_deg: 33.5, lon_deg: -99.3 })).toBe(false);
  });
});

describe('tile and local math', () => {
  it('tileXY matches the Python tile math', () => {
    expect(tileXY(33.4986975, -99.3329862, 10)).toEqual({ x: 229, y: 410 });
  });
  it('enu follows spec 13.7: 0.01 degrees east at 33.5 is 928.3 m, 0.01 north is 1105.4 m', () => {
    const e = enu(33.5, -99.29, 33.5, -99.3);
    expect(e.east).toBeCloseTo(928.3, 0);
    expect(Math.abs(e.north)).toBeLessThan(1e-6);
    const n = enu(33.51, -99.3, 33.5, -99.3);
    expect(n.north).toBeCloseTo(1105.4, 1);
    expect(Math.abs(n.east)).toBeLessThan(1e-6);
  });
  it('distanceKm', () => {
    expect(distanceKm([0, 0], [0, 0])).toBe(0);
    expect(distanceKm([0, 0], [0, 1])).toBeCloseTo(111.19, 1);
  });
  it('boundsFor is the maps.bbox box', () => {
    const [[s, w], [n, e]] = boundsFor([33.5, -99.3], 5);
    expect(n - s).toBeCloseTo(2 * 5 / 111.32, 9);
    expect(e - w).toBeGreaterThan(n - s);
  });
});

describe('validTrack and gpsStatus', () => {
  const store = new SeriesStore(4, 100);
  store.append(1, 0, [0, 0, 65.7, 123.2]);
  store.append(2, 0, [3, 9, 33.5, -99.3]);
  store.append(3, 0, [1, 9, 33.6, -99.3]);
  store.append(4, 0, [3, 9, 33.7, -99.2]);
  it('skips invalid rows', () => {
    const t = validTrack(store, schema);
    expect(t.length).toBe(2);
    expect(t[0][0]).toBeCloseTo(33.5, 4);
    expect(t[1][0]).toBeCloseTo(33.7, 4);
  });
  it('starts from a row index', () => {
    expect(validTrack(store, schema, Infinity, 2).length).toBe(1);
    expect(validTrack(store, schema, Infinity, 4)).toEqual([]);
  });
  it('is empty without a schema and thins long tracks keeping the newest point', () => {
    expect(validTrack(store, null)).toEqual([]);
    const big = new SeriesStore(4, 1000);
    for (let i = 0; i < 500; i++) big.append(i, 0, [3, 9, 33 + i * 1e-4, -99]);
    const thin = validTrack(big, schema, 50);
    expect(thin.length).toBeLessThanOrEqual(51);
    expect(thin[thin.length - 1][0]).toBeCloseTo(33 + 499e-4, 4);
  });
  it('describes the newest row', () => {
    expect(gpsStatus(Float32Array.from([0, 0, 65.7, 123.2]), schema)).toEqual(
      { valid: false, position: null, text: 'GPS position invalid: fix SEARCHING, 0 sats.' });
    const ok = gpsStatus(Float32Array.from([3, 9, 33.5, -99.3]), schema);
    expect(ok.valid).toBe(true);
    expect(ok.text).toBe('GPS: 3D fix, 9 sats');
    expect(gpsStatus(null, schema).valid).toBe(false);
  });
});

describe('sites and zoom plan', () => {
  it('resolves null to the first site and unknown ids too', () => {
    expect(resolveSite([site], null)).toBe(site);
    expect(resolveSite([site], 'nope')).toBe(site);
    expect(resolveSite([], null)).toBeNull();
  });
  it('base maxNativeZoom is the site outer_max_z, capped by a shallower layer', () => {
    expect(layerPlan(site, 'imagery')).toMatchObject({ available: true, baseMaxNative: 13, detailMaxNative: 17, minZoom: 5 });
    expect(layerPlan(site, 'topo')).toMatchObject({ baseMaxNative: 11, detailMaxNative: null });
    expect(layerPlan({ ...site, outer_max_z: null }, 'imagery')).toMatchObject({ baseMaxNative: null, detailMaxNative: 17 });
    expect(layerPlan({ ...site, layers: {} }, 'topo').available).toBe(false);
  });
  it('footer: distance over 50 km and the fetch hint', () => {
    expect(footerText({ site, layerAvailable: true, position: [33.55, -99.3] })).toBe('');
    expect(footerText({ site, layerAvailable: true, position: [31, -103.5] })).toMatch(/^Position is \d+ km from Seymour, TX$/);
    expect(footerText({ site, layerAvailable: false, position: null })).toContain('./sdr maps fetch --site seymour');
    expect(footerText({ site: null, layerAvailable: false, position: null })).toContain('--site <id>');
  });
});

describe('graticule', () => {
  it('picks 1-2-5 steps', () => {
    expect(niceStep(1, 5)).toBeCloseTo(0.2);
    expect(niceStep(0.07, 6)).toBeCloseTo(0.02);
    expect(niceStep(10, 5)).toBe(2);
  });
  it('lines fall on multiples of the step inside the view', () => {
    const g = graticule([[33.4, -99.4], [33.6, -99.2]], 4);
    expect(g.step).toBeCloseTo(0.05);
    expect(g.lats[0]).toBeCloseTo(33.4);
    expect(g.lats[g.lats.length - 1]).toBeCloseTo(33.6);
    expect(g.lons.every((l) => l >= -99.4 - 1e-9 && l <= -99.2 + 1e-9)).toBe(true);
    expect(g.lats.length).toBe(5);
  });
});

describe('makeSeeder', () => {
  it('seeds first and on value changes only', () => {
    const seed = makeSeeder<string | null>();
    expect(seed(null)).toBe(true);
    expect(seed(null)).toBe(false);
    expect(seed('ttu')).toBe(true);
    expect(seed('ttu')).toBe(false);
    expect(seed(null)).toBe(true);
  });
});

describe('map framing', () => {
  const PAD: LatLon = [31.0, -103.5];

  it('frames the pad alone at the minimum radius', () => {
    const b = framingBounds([], PAD, 0.6);
    expect(distanceKm(PAD, [b[1][0], PAD[1]])).toBeCloseTo(0.6, 2);
    expect(distanceKm(PAD, [PAD[0], b[1][1]])).toBeCloseTo(0.6, 2);
  });

  it('frames the whole path and the pad, centred, with the minimum as a floor', () => {
    const far: LatLon = [31.02, -103.48];   // about 2.9 km north-east
    const b = framingBounds([[31.005, -103.495], far], PAD, 0.6);
    expect(b[0][0]).toBeLessThanOrEqual(PAD[0]);
    expect(b[0][1]).toBeLessThanOrEqual(PAD[1]);
    expect(b[1][0]).toBeGreaterThanOrEqual(far[0]);
    expect(b[1][1]).toBeGreaterThanOrEqual(far[1]);
  });

  it('refits when the path leaves the inner view or the view is much larger than needed', () => {
    const view: Bounds = [[30.9, -103.6], [31.1, -103.4]];
    expect(needsRefit(view, [[30.99, -103.51], [31.01, -103.49]])).toBe(true);    // view far too large
    expect(needsRefit(view, [[30.95, -103.55], [31.05, -103.45]])).toBe(false);   // fits well
    expect(needsRefit(view, [[30.95, -103.55], [31.11, -103.45]])).toBe(true);    // runs off the top
  });
});

describe('site auto-detection', () => {
  const mk = (id: string, pad: LatLon, r = 20): SiteInfo => ({ id, name: id, center: pad, pad, outer_radius_km: r, inner_radius_km: 5 });
  const seymour = mk('seymour', [33.4987, -99.333]);
  const pecos = mk('irec-pecos', [31.0427, -103.5316]);
  const ttu = mk('ttu', [33.584, -101.875]);
  const all = [seymour, pecos, ttu];

  it('picks the site nearest the GPS fix, within its map radius', () => {
    expect(nearestSite(all, [31.06, -103.52])).toBe(pecos);
    expect(nearestSite(all, [33.52, -99.30])).toBe(seymour);
    expect(nearestSite(all, [40.0, -105.0])).toBeNull();   // nowhere near a registered site
    expect(nearestSite([], [31.06, -103.52])).toBeNull();
  });

  it('auto (null or unknown id) follows the fix, an explicit id wins, and no fix falls back', () => {
    expect(resolveSite(all, null, [31.06, -103.52])).toBe(pecos);
    expect(resolveSite(all, 'ttu', [31.06, -103.52])).toBe(ttu);
    expect(resolveSite(all, null, null)).toBe(seymour);
    expect(resolveSite(all, null, null, 'irec-pecos')).toBe(pecos);   // last detected site, kept through a GPS dropout
    expect(resolveSite(all, null, [40, -105], 'irec-pecos')).toBe(pecos);
  });

  it('finds the newest valid fix', () => {
    const s = new SeriesStore(4, 16);
    const sch: FlightSchema = { version: 1, fields: ['gps_fix', 'lat_deg', 'lon_deg', 'x'].map((key) => ({ key, label: key, quantity: 'x' })) };
    s.append(1, 0, [3, 31.05, -103.53, 0]);
    s.append(2, 0, [0, 0, 0, 0]);
    const fix = lastFix(s, sch)!;
    expect(fix[0]).toBeCloseTo(31.05, 4);
    expect(fix[1]).toBeCloseTo(-103.53, 4);
    expect(lastFix(new SeriesStore(4, 16), sch)).toBeNull();
  });
});

import { describe, expect, it } from 'vitest';
import { SeriesStore } from '../series';
import type { FlightSchema, GuiEvent } from '../types';
import type { UnitPrefs } from '../units';
import { axesFor, buildData, eventMarkers, expandSeries, storeFor, viewRange } from './plot';

const schema: FlightSchema = {
  version: 1,
  fields: [
    { key: 'alt_agl_m', label: 'Altitude', quantity: 'length' },
    { key: 'pred_apogee_m', label: 'Predicted apogee', quantity: 'length' },
    { key: 'vel_mps', label: 'Velocity', quantity: 'speed' },
    { key: 'accel_mps2', label: 'Acceleration', quantity: 'acceleration' },
  ],
};
const best = (field: string) => ({ field, source: 'best' });

describe('axesFor', () => {
  it('rejects more than two quantities', () => {
    const r = axesFor([best('alt_agl_m'), best('vel_mps'), best('accel_mps2')], schema);
    expect(r.ok).toBe(false);
    expect(r.error).toBeTruthy();
  });
  it('shares one axis between fields of the same quantity', () => {
    expect(axesFor([best('alt_agl_m'), best('pred_apogee_m')], schema)).toEqual({ quantities: ['length'], ok: true });
  });
  it('maps metric fields to their quantities', () => {
    const r = axesFor([best('m.rssi'), best('m.noise'), best('m.snr')], schema);
    expect(r.quantities).toEqual(['power_dbfs', 'power_db']);
    expect(r.ok).toBe(true);
    expect(axesFor([best('m.df')], schema).quantities).toEqual(['frequency']);
  });
  it('reports an unknown field', () => {
    expect(axesFor([best('nope')], schema).ok).toBe(false);
  });
});

describe('storeFor and expandSeries', () => {
  const stores = {
    flight: { best: new SeriesStore(4, 8), A: new SeriesStore(4, 8) },
    metrics: { A: new SeriesStore(6, 8), B: new SeriesStore(6, 8) },
  };
  it('picks flight and metric stores', () => {
    expect(storeFor({ field: 'alt_agl_m', source: 'best' }, stores)).toBe(stores.flight.best);
    expect(storeFor({ field: 'alt_agl_m', source: 'A' }, stores)).toBe(stores.flight.A);
    expect(storeFor({ field: 'alt_agl_m', source: 'B' }, stores)).toBeNull();
    expect(storeFor({ field: 'm.rssi', source: 'B' }, stores)).toBe(stores.metrics.B);
    expect(storeFor({ field: 'm.rssi', source: 'best' }, stores)).toBe(stores.metrics.A);
  });
  it('expands both into A then B', () => {
    expect(expandSeries([{ field: 'alt_agl_m', source: 'both' }, best('vel_mps')])).toEqual([
      { field: 'alt_agl_m', source: 'A' }, { field: 'alt_agl_m', source: 'B' }, best('vel_mps')]);
  });
});

describe('viewRange', () => {
  const live = { paused: false, pausedAt: null, offsetS: 0 };
  it('live ends at now', () => {
    expect(viewRange(live, 100, 30, 0)).toEqual([70, 100]);
  });
  it('live all-data starts at the data start', () => {
    expect(viewRange(live, 100, 0, 40)).toEqual([40, 100]);
  });
  it('paused is fixed at the pause time minus the offset', () => {
    expect(viewRange({ paused: true, pausedAt: 90, offsetS: 0 }, 200, 30, 0)).toEqual([60, 90]);
    expect(viewRange({ paused: true, pausedAt: 90, offsetS: 10 }, 200, 30, 0)).toEqual([50, 80]);
  });
  it('scrub clamps at the data start keeping the span', () => {
    expect(viewRange({ paused: true, pausedAt: 90, offsetS: 500 }, 200, 30, 50)).toEqual([50, 80]);
  });
  it('negative offset cannot pass the pause time', () => {
    expect(viewRange({ paused: true, pausedAt: 90, offsetS: -5 }, 200, 30, 0)).toEqual([60, 90]);
  });
});

describe('eventMarkers', () => {
  const ev = (kind: string, t: number, category: 'flight' | 'link' = 'flight'): GuiEvent => ({
    id: t, t, kind, category, text: kind, channel: null, value: null, quantity: null, segment: 0, synthetic: false });
  it('keeps milestone kinds inside the range', () => {
    const out = eventMarkers([ev('launch', 5), ev('phase', 6), ev('apogee', 20), ev('landing', 50), ev('flight_reset', 8),
      ev('burnout', 9), ev('source_switch', 7, 'link'), ev('max_velocity', 10)], 5, 20);
    expect(out.map((m) => m.t)).toEqual([5, 20, 8, 9]);
    expect(out[0].label).toBe('launch');
  });
});

describe('buildData', () => {
  const prefs = (system: 'metric' | 'imperial'): UnitPrefs => ({ system, overrides: {} });
  it('converts to feet for imperial', () => {
    const s = new SeriesStore(4, 8);
    s.append(1, 0, [100, 0, 0, 0]);
    s.append(2, 0, [200, 0, 0, 0]);
    const d = buildData([{ store: s, col: 0, quantity: 'length' }], 0, 10, prefs('imperial'), {});
    expect(d[0]).toEqual([1, 2]);
    expect(d[1][0]).toBeCloseTo(328.084, 2);
    const m = buildData([{ store: s, col: 0, quantity: 'length' }], 0, 10, prefs('metric'), {});
    expect(m[1]).toEqual([100, 200]);
  });
  it('merges A and B on a union axis with nulls', () => {
    const a = new SeriesStore(1, 8);
    const b = new SeriesStore(1, 8);
    a.append(1, 0, [10]); a.append(3, 0, [30]);
    b.append(2, 0, [20]); b.append(3, 0, [31]);
    const d = buildData([{ store: a, col: 0, quantity: 'count' }, { store: b, col: 0, quantity: 'count' }], 0, 10, prefs('metric'), {});
    expect(d[0]).toEqual([1, 2, 3]);
    expect(d[1]).toEqual([10, null, 30]);
    expect(d[2]).toEqual([null, 20, 31]);
  });
  it('clips to the range and nulls NaN; same store twice is safe', () => {
    const s = new SeriesStore(2, 8);
    s.append(1, 0, [1, 5]); s.append(2, 0, [NaN, 6]); s.append(9, 0, [3, 7]);
    const d = buildData([{ store: s, col: 0, quantity: 'count' }, { store: s, col: 1, quantity: 'count' }], 1, 5, prefs('metric'), {});
    expect(d[0]).toEqual([1, 2]);
    expect(d[1]).toEqual([1, null]);
    expect(d[2]).toEqual([5, 6]);
  });
  it('is empty without series', () => {
    expect(buildData([], 0, 1, prefs('metric'), {})).toEqual([[]]);
  });
});

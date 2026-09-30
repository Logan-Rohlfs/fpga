import { beforeEach, describe, expect, it } from 'vitest';
import catalogue from './units.catalogue.json';
import { convert, format, loadUnitPrefs, saveUnitPrefs, toSI, unitFor, unitLabel } from './units';

const metric = { system: 'metric' as const, overrides: {} };
const imperial = { system: 'imperial' as const, overrides: {} };

describe('unitFor', () => {
  it('card override beats viewer override beats system', () => {
    const prefs = { system: 'imperial' as const, overrides: { length: 'km' } };
    expect(unitFor('length', { length: 'm' }, prefs)).toBe('m');
    expect(unitFor('length', undefined, prefs)).toBe('km');
    expect(unitFor('length', {}, imperial)).toBe('ft');
    expect(unitFor('length', undefined, metric)).toBe('m');
  });
  it('ignores override ids that are not units of the quantity', () => {
    expect(unitFor('length', { length: 'nope' }, imperial)).toBe('ft');
  });
  it('returns null for dimensionless and unknown quantities', () => {
    for (const q of ['count', 'enum', 'enum_signed', 'bits', 'mystery']) expect(unitFor(q, undefined, imperial)).toBeNull();
  });
});

describe('convert', () => {
  it('handles offsets', () => {
    expect(convert(0, 'temperature', '°F')).toBe(32);
    expect(convert(100, 'temperature', '°F')).toBeCloseTo(212, 9);
  });
  it('round-trips every catalogue unit', () => {
    for (const [q, def] of Object.entries(catalogue.quantities)) {
      for (const u of def.units) {
        for (const x of [-40, 0, 1, 1234.5]) expect(toSI(convert(x, q, u.id), q, u.id)).toBeCloseTo(x, 6);
      }
    }
  });
});

describe('format', () => {
  it('formats non-finite as a dash', () => {
    expect(format(NaN, 'length', 'ft', 1)).toBe('—');
    expect(format(Infinity, 'length', 'ft', 1)).toBe('—');
  });
  it('converts and rounds', () => {
    expect(format(1234.5, 'length', 'ft', 0)).toBe('4050');
    expect(format(3, 'count', null, 0)).toBe('3');
  });
  it('labels', () => {
    expect(unitLabel('length', 'ft')).toBe('ft');
    expect(unitLabel('count', null)).toBe('');
  });
});

describe('prefs storage', () => {
  beforeEach(() => { delete (globalThis as { localStorage?: unknown }).localStorage; });
  it('falls back to metric without storage', () => {
    expect(loadUnitPrefs()).toEqual({ system: 'metric', overrides: {} });
    expect(() => saveUnitPrefs(imperial)).not.toThrow();
  });
  it('round-trips through localStorage', () => {
    const m = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v),
    };
    saveUnitPrefs({ system: 'imperial', overrides: { length: 'km' } });
    expect(loadUnitPrefs()).toEqual({ system: 'imperial', overrides: { length: 'km' } });
    m.set('sdr.units', '{bad');
    expect(loadUnitPrefs().system).toBe('metric');
  });
});

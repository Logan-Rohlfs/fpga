import { describe, expect, it } from 'vitest';
import { SeriesStore } from '../series';
import type { FlightSchema } from '../types';
import { MinMax, badgeFor, decodeBits, fieldIndex, gpsFixLabel, noFlightNotice, staleAge, thresholdLevel, timeInPhase } from './value';

const HEALTH = { '0': 'imu', '1': 'highg', '2': 'baro', '3': 'mag', '4': 'gps', '5': 'radio', '6': 'qspi', '7': 'sd' };
const schema: FlightSchema = {
  version: 1,
  fields: [
    { key: 'seq', label: 'Seq', quantity: 'count' },
    { key: 'phase', label: 'Phase', quantity: 'enum', enum: ['IDLE', 'ARMED', 'BOOST'] },
    { key: 'gps_fix', label: 'GPS fix', quantity: 'enum_signed', enum_map: { '-1': 'OFFLINE', '0': 'SEARCHING', '3': '3D' } },
  ],
};

describe('value helpers', () => {
  it('fieldIndex finds a key or returns -1', () => {
    expect(fieldIndex(schema, 'phase')).toBe(1);
    expect(fieldIndex(schema, 'nope')).toBe(-1);
    expect(fieldIndex(null, 'phase')).toBe(-1);
  });

  it('thresholdLevel: the highest above <= value wins', () => {
    const th = [{ above: 3000, level: 'warn' as const }, { above: 3200, level: 'bad' as const }];
    expect(thresholdLevel(3100, th)).toBe('warn');
    expect(thresholdLevel(3200, th)).toBe('bad');
    expect(thresholdLevel(2999, th)).toBeNull();
    expect(thresholdLevel(NaN, th)).toBeNull();
    expect(thresholdLevel(3300, [...th].reverse())).toBe('bad');
  });

  it('MinMax ignores non-finite values and resets', () => {
    const m = new MinMax();
    m.push(NaN);
    m.push(Infinity);
    expect(m.min).toBeNull();
    m.push(5);
    m.push(-2);
    m.push(NaN);
    m.push(9);
    expect([m.min, m.max]).toEqual([-2, 9]);
    m.reset();
    expect([m.min, m.max]).toEqual([null, null]);
  });

  it('timeInPhase scans back to the latest change', () => {
    const s = new SeriesStore(3, 100);
    const phases = [0, 0, 1, 1, 1, 1];
    const times = [0, 2.5, 5, 5.5, 6.5, 7.5];
    phases.forEach((p, i) => s.append(times[i], 0, [i, p, 0]));
    expect(timeInPhase(s, 1)).toBe(2.5);
    expect(timeInPhase(new SeriesStore(3, 10), 1)).toBeNull();
    expect(timeInPhase(s, -1)).toBeNull();
  });

  it('decodeBits names and sets each bit', () => {
    const bits = decodeBits(0x90, HEALTH);
    expect(bits.map((b) => b.name)).toEqual(['imu', 'highg', 'baro', 'mag', 'gps', 'radio', 'qspi', 'sd']);
    expect(bits.filter((b) => b.on).map((b) => b.name)).toEqual(['gps', 'sd']);
  });

  it('gpsFixLabel maps known values and flags unknown ones', () => {
    expect(gpsFixLabel(schema, 0)).toBe('SEARCHING');
    expect(gpsFixLabel(schema, -1)).toBe('OFFLINE');
    expect(gpsFixLabel(schema, 9)).toBe('UNKNOWN (9)');
    expect(gpsFixLabel(null, 3)).toBe('UNKNOWN (3)');
  });

  it('staleAge is null when fresh', () => {
    expect(staleAge(null, 10, 1)).toBeNull();
    expect(staleAge(9.5, 10, 1)).toBeNull();
    expect(staleAge(8, 10, 1)).toBe(2);
  });

  it('badgeFor labels synthetic data by profile', () => {
    expect(badgeFor(1, 'apex_demo')).toBe('REPLAY');
    expect(badgeFor(1, 'default')).toBe('SIMULATED');
    expect(badgeFor(0, 'default')).toBeNull();
    expect(badgeFor(null, 'default')).toBeNull();
    expect(badgeFor(1, 'unknown')).toBe('SIMULATED');
  });

  it('noFlightNotice appears after 5 s with other frames arriving', () => {
    const base = { flightRows: 0, otherFramesPerS: 3, waitedS: 6 };
    expect(noFlightNotice(base)).toBe('No FLIGHT frames from this source');
    expect(noFlightNotice({ ...base, waitedS: 4 })).toBeNull();
    expect(noFlightNotice({ ...base, otherFramesPerS: 0 })).toBeNull();
    expect(noFlightNotice({ ...base, flightRows: 2 })).toBeNull();
  });
});

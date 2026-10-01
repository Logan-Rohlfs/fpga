import { describe, expect, it } from 'vitest';
import type { FlightSchema, SourceState } from '../types';
import { headerChips, sameStatus } from './status';

const schema: FlightSchema = {
  version: 1,
  fields: [
    { key: 'lat_deg', label: 'Latitude', quantity: 'coordinate' },
    { key: 'alt_agl_m', label: 'Altitude AGL', quantity: 'length' },
  ],
};
const demo = (kind: SourceState['kind'] = 'serial'): SourceState => ({
  kind, state: 'running', detail: '', responds_to_tuning: false,
  profile: {
    id: 'apex_demo', label: 'demo', emulated_fields: ['lat_deg'], emulated_note: 'GPS is emulated.',
    replay_note: 'Descent at 4x.',
  },
});
const plain: SourceState = { kind: 'sim', state: 'running', detail: '', responds_to_tuning: true };

describe('headerChips', () => {
  it('shows nothing without a status or for measured fresh data', () => {
    expect(headerChips(null, plain, schema)).toEqual({ badge: null, emulated: null, stale: null });
    expect(headerChips({ synthetic: false, flight: true, age: null }, demo(), schema).badge).toBeNull();
  });

  it('labels synthetic data SIMULATED outside the demo profile and for non-flight cards', () => {
    expect(headerChips({ synthetic: true, flight: true, age: null }, plain, schema).badge?.text).toBe('SIMULATED');
    expect(headerChips({ synthetic: true, flight: false, age: null }, demo(), schema).badge?.text).toBe('SIMULATED');
  });

  it('labels demo flight data as a replay, worded per source', () => {
    const board = headerChips({ synthetic: true, flight: true, age: null }, demo(), schema).badge!;
    expect(board.text).toBe('REPLAY · SIMULATED ADC');
    expect(board.title).toContain('through the real receiver');
    expect(board.title).toContain('Descent at 4x.');
    const host = headerChips({ synthetic: true, flight: true, age: null }, demo('demo'), schema).badge!;
    expect(host.text).toBe('REPLAY · SIMULATED ADC');
    expect(host.title).toContain('no FPGA');
  });

  it('marks emulated fields only when the card shows one', () => {
    const shows = headerChips({ synthetic: true, flight: true, age: null, fields: ['alt_agl_m', 'lat_deg'] }, demo(), schema);
    expect(shows.emulated?.text).toBe('EMULATED');
    expect(shows.emulated?.title).toBe('GPS is emulated. Emulated here: Latitude.');
    expect(headerChips({ synthetic: true, flight: true, age: null, fields: ['alt_agl_m'] }, demo(), schema).emulated).toBeNull();
    expect(headerChips({ synthetic: true, flight: true, age: null, fields: ['lat_deg'] }, plain, schema).emulated).toBeNull();
  });

  it('adds the stale chip', () => {
    expect(headerChips({ synthetic: false, flight: true, age: 3.21 }, plain, schema).stale).toBe('stale 3.2 s');
  });
});

describe('sameStatus', () => {
  it('compares by value', () => {
    const a = { synthetic: true, flight: true, age: null, fields: ['x'] };
    expect(sameStatus(a, { ...a, fields: ['x'] })).toBe(true);
    expect(sameStatus(a, { ...a, age: 1 })).toBe(false);
    expect(sameStatus(null, a)).toBe(false);
    expect(sameStatus(null, null)).toBe(true);
  });
});

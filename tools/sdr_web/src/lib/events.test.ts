import { describe, expect, it } from 'vitest';
import { ALL_EVENT_KINDS, FLIGHT_CATEGORY_KINDS, LINK_KINDS, filterEvents, formatEvent, lastLaunch } from './events';
import type { GuiEvent } from './types';

let nextId = 1;
const ev = (kind: string, t: number, extra: Partial<GuiEvent> = {}): GuiEvent => ({
  id: nextId++, t, kind, category: (LINK_KINDS as readonly string[]).includes(kind) ? 'link' : 'flight', text: kind,
  channel: null, value: null, quantity: null, segment: 0, synthetic: false, ...extra,
});
const imperial = { system: 'imperial' as const, overrides: {} };
const metric = { system: 'metric' as const, overrides: {} };

describe('kind lists', () => {
  it('all = flight category + link', () => {
    expect(ALL_EVENT_KINDS).toEqual([...FLIGHT_CATEGORY_KINDS, ...LINK_KINDS]);
  });
});

describe('filterEvents', () => {
  const items = [ev('launch', 10), ev('signal_loss', 11), ev('apogee', 20), ev('crc_burst', 21)];
  it('filters by category first', () => {
    expect(filterEvents(items, 'flight', null, false).map(e => e.kind)).toEqual(['launch', 'apogee']);
    expect(filterEvents(items, 'link', null, false).map(e => e.kind)).toEqual(['signal_loss', 'crc_burst']);
  });
  it('then by kinds', () => {
    expect(filterEvents(items, 'flight', new Set(['apogee', 'crc_burst']), false).map(e => e.kind)).toEqual(['apogee']);
  });
  it('orders newest first without mutating the input', () => {
    const out = filterEvents(items, 'flight', null, true);
    expect(out.map(e => e.kind)).toEqual(['apogee', 'launch']);
    expect(items[0].kind).toBe('launch');
  });
});

describe('lastLaunch', () => {
  it('returns the latest launch time or null', () => {
    expect(lastLaunch([ev('apogee', 5)])).toBeNull();
    expect(lastLaunch([ev('launch', 10), ev('landing', 30), ev('launch', 100)])).toBe(100);
  });
});

describe('formatEvent', () => {
  it('T+ relative to launch', () => {
    const f = formatEvent(ev('burnout', 22.3), metric, 10);
    expect(f.tplus).toBe('T+12.3 s');
    expect(formatEvent(ev('burnout', 7), metric, 10).tplus).toBe('T-3.0 s');
    expect(formatEvent(ev('burnout', 22.3), metric, null).tplus).toBeNull();
  });
  it('formats the value through units', () => {
    const e = ev('apogee', 30, { value: 1234.5, quantity: 'length' });
    expect(formatEvent(e, imperial, 10).value).toBe('4050 ft');
    expect(formatEvent(e, metric, 10).value).toBe('1235 m');
  });
  it('null value stays null; non-finite is a dash', () => {
    expect(formatEvent(ev('launch', 10), metric, 10).value).toBeNull();
    expect(formatEvent(ev('apogee', 10, { value: NaN, quantity: 'length' }), metric, 10).value).toBe('— m');
  });
  it('carries text and a clock time', () => {
    const f = formatEvent(ev('phase', 3725.5, { text: 'COAST → DESCENT' }), metric, null);
    expect(f.text).toBe('COAST → DESCENT');
    expect(f.time).toBe('1:02:05.5');
  });
});

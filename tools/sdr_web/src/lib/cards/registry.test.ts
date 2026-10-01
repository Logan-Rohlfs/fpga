import { describe, expect, it } from 'vitest';
import type { GridCard } from '../grid';
import types from './card-types.json';
import { REGISTRY, cardChannels, minOfType, sanitizeConfig } from './registry';

const presetFiles = import.meta.glob<{ cards: { id: string; type: string; config: Record<string, unknown> }[] }>(
  '../../../../sdr_cli/presets/*.json', { eager: true, import: 'default' });

const card = (id: string, type: string, config: Record<string, unknown> = {}): GridCard =>
  ({ id, type, x: 0, y: 0, w: 3, h: 3, title: null, config });

describe('registry', () => {
  it('covers exactly the card types the server accepts', () => {
    expect(Object.keys(REGISTRY).sort()).toEqual([...types.types].sort());
  });

  it('every meta carries a matching type, min sizes and a phone minimum', () => {
    for (const [type, meta] of Object.entries(REGISTRY)) {
      expect(meta.type).toBe(type);
      expect(meta.min.w).toBeGreaterThanOrEqual(1);
      expect(meta.min.h).toBeGreaterThanOrEqual(1);
      expect(meta.phoneMinH).toBeGreaterThanOrEqual(meta.min.h);
      expect(Array.isArray(meta.settings)).toBe(true);
    }
  });

  it('uses the spec minimum sizes', () => {
    // 24-column grid, 16 px rows (spec section 7)
    expect(REGISTRY.plot.min).toEqual({ w: 5, h: 8 });
    expect(REGISTRY.number.min).toEqual({ w: 2, h: 3 });
    expect(REGISTRY.map.min).toEqual({ w: 4, h: 6 });
    expect(REGISTRY.trajectory3d.min).toEqual({ w: 4, h: 6 });
    expect(REGISTRY.constellation.min).toEqual({ w: 3, h: 5 });
  });

  it('sanitize({}) equals the defaults for every type', () => {
    for (const meta of Object.values(REGISTRY)) expect(meta.sanitize({})).toEqual(meta.defaults);
  });

  it('sanitize tolerates non-objects', () => {
    for (const meta of Object.values(REGISTRY)) {
      expect(meta.sanitize(null)).toEqual(meta.defaults);
      expect(meta.sanitize('x')).toEqual(meta.defaults);
      expect(meta.sanitize([1])).toEqual(meta.defaults);
    }
  });

  it('plot sanitize drops unknown keys and restores bad values', () => {
    const out = REGISTRY.plot.sanitize({ junk: 1, window_s: 'x' });
    expect(out).not.toHaveProperty('junk');
    expect(out.window_s).toBe(REGISTRY.plot.defaults.window_s);
  });

  it('keeps valid values and rejects out-of-range ones', () => {
    expect(REGISTRY.plot.sanitize({ window_s: 120 }).window_s).toBe(120);
    expect(REGISTRY.plot.sanitize({ window_s: 7 }).window_s).toBe(60);
    expect(REGISTRY.plot.sanitize({ series: [] }).series).toEqual([{ field: 'alt_agl_m', source: 'best' }]);
    expect((REGISTRY.plot.sanitize({ series: new Array(9).fill({ field: 'a', source: 'A' }) }).series as unknown[]).length).toBe(6);
    expect(REGISTRY.number.sanitize({ digits: 9 }).digits).toBe(null);
    expect(REGISTRY.number.sanitize({ digits: 2 }).digits).toBe(2);
    expect(REGISTRY.camera.sanitize({ url: 'ftp://x' }).url).toBe(null);
    expect(REGISTRY.camera.sanitize({ url: 'http://x/y' }).url).toBe('http://x/y');
    expect(REGISTRY.camera.sanitize({ mode: 'demo', media: 'a.webm', launch_offset_s: 12.5 }))
      .toMatchObject({ mode: 'demo', media: 'a.webm', launch_offset_s: 12.5 });
    expect(REGISTRY.camera.sanitize({ media: '../x.mp4', launch_offset_s: 601 }))
      .toMatchObject({ media: 'l3_flight_onboard.mp4', launch_offset_s: 9 });
    expect(REGISTRY.camera.sanitize({ media: null }).media).toBe(null);
    expect(REGISTRY.link.sanitize({ channels: ['B', 'Z'] }).channels).toEqual(['B']);
    expect(REGISTRY.link.sanitize({ channels: [] }).channels).toEqual(['A', 'B']);
  });

  it('sanitizeConfig dispatches by type and passes unknown types through untouched', () => {
    expect(sanitizeConfig('plot', { junk: 1 })).toEqual(REGISTRY.plot.defaults);
    const cfg = { anything: [1, 2] };
    expect(sanitizeConfig('from-the-future', cfg)).toBe(cfg);
  });

  it('sanitize keeps every value a shipped builtin preset sets (it may add defaults for omitted keys)', () => {
    const files = Object.entries(presetFiles);
    expect(files.length).toBeGreaterThan(0);
    for (const [name, preset] of files) {
      for (const c of preset.cards) expect(sanitizeConfig(c.type, c.config), `${name}:${c.id}`).toMatchObject(c.config);
    }
  });

  it('channels per type', () => {
    expect(REGISTRY.plot.channels({ series: [{ field: 'alt_agl_m', source: 'A' }] })).toEqual(['flight.A', 'events']);
    expect(REGISTRY.plot.channels({ series: [{ field: 'alt_agl_m', source: 'best' }], show_events: false, segment: 'all' })).toEqual(['flight']);
    expect(REGISTRY.plot.channels({ series: [{ field: 'alt_agl_m', source: 'best' }], show_events: false })).toEqual(['flight', 'events']);
    expect(REGISTRY.map.channels({ source: 'A' })).toEqual(['flight.A', 'events']);
    expect(REGISTRY.map.channels({ source: 'A', segment: 'all' })).toEqual(['flight.A']);
    expect(REGISTRY.trajectory3d.channels({})).toEqual(['flight', 'events']);
    expect(REGISTRY.trajectory3d.sanitize({})).toMatchObject({ camera: 'follow', orbit_dps: 6 });
    expect(REGISTRY.trajectory3d.sanitize({ camera: 'orbit', orbit_dps: 12 })).toMatchObject({ camera: 'orbit', orbit_dps: 12 });
    expect(REGISTRY.trajectory3d.sanitize({ camera: 'spin', orbit_dps: 99 })).toMatchObject({ camera: 'follow', orbit_dps: 6 });
    for (const t of ['plot', 'map', 'trajectory3d'] as const) {
      expect(REGISTRY[t].sanitize({}).segment, t).toBe('current');
      expect(REGISTRY[t].sanitize({ segment: 'all' }).segment, t).toBe('all');
      expect(REGISTRY[t].sanitize({ segment: 'bogus' }).segment, t).toBe('current');
    }
    expect(REGISTRY.plot.channels({ series: [{ field: 'm.rssi', source: 'B' }], show_events: false, segment: 'all' })).toEqual(['link']);
    expect(REGISTRY.plot.sanitize({ series: [{ field: 'alt_agl_m', source: 'both' }] }).series)
      .toEqual([{ field: 'alt_agl_m', source: 'both' }]);
    expect(REGISTRY.plot.channels({ series: [{ field: 'alt_agl_m', source: 'both' }], show_events: false, segment: 'all' }))
      .toEqual(['flight.A', 'flight.B']);
    expect(REGISTRY.waterfall.channels({ channel: 'B' })).toEqual(['spectrum.B']);
    expect(REGISTRY.camera.channels({})).toEqual([]);
    expect(REGISTRY.camera.channels({ mode: 'demo' })).toEqual(['events']);
    expect(REGISTRY.number.channels({ source: 'both' })).toEqual(['flight.A', 'flight.B']);
    expect(REGISTRY.spectrum.channels({})).toEqual(['spectrum.A', 'spectrum.B']);
    expect(REGISTRY.constellation.channels({ channel: 'B' })).toEqual(['iq.B']);
    expect(REGISTRY.events.channels({})).toEqual(['events']);
    expect(REGISTRY.link.channels({})).toEqual(['link']);
    expect(REGISTRY.frames.channels({})).toEqual(['frames']);
    expect(REGISTRY.state.channels({})).toEqual(['flight']);
  });

  it('cardChannels is the union over cards, tolerating unknown types', () => {
    const out = cardChannels([
      card('a', 'waterfall', { channel: 'B' }), card('b', 'link'), card('c', 'waterfall', { channel: 'B' }),
      card('d', 'from-the-future'), card('e', 'camera'),
    ]);
    expect(out).toEqual(['link', 'spectrum.B']);
  });

  it('minOfType falls back for unknown types', () => {
    expect(minOfType('plot')).toEqual({ w: 5, h: 8, phoneMinH: REGISTRY.plot.phoneMinH });
    expect(minOfType('from-the-future').w).toBeGreaterThanOrEqual(1);
  });
});

describe('plot y range', () => {
  const y = (v: unknown) => REGISTRY.plot.sanitize({ y: v }).y;
  it('accepts auto, a full range, or one fixed end', () => {
    expect(y('auto')).toBe('auto');
    expect(y({ min: 0, max: 100 })).toEqual({ min: 0, max: 100 });
    expect(y({ min: 0, max: null })).toEqual({ min: 0, max: null });
    expect(y({ min: 0 })).toEqual({ min: 0, max: null });
  });
  it('falls back to auto for an empty or inverted range', () => {
    expect(y({ min: null, max: null })).toBe('auto');
    expect(y({ min: 5, max: 1 })).toBe('auto');
    expect(y({ min: 'x', max: 1 })).toBe('auto');
  });
});

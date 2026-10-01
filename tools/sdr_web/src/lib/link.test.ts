import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import golden from './wire.golden.json';
import {
  FRAMES_MAX, LinkClient, dataVersion, droppedFrames, eventsStore, segmentStart, flightSchema, flightStores, frames,
  frozen, handleMessage, hello, iqSnapMeta, iqSnaps, latestMetrics, linkStatsNow, linkStatsRing, metricsNow, metricsStores, metricsTail,
  onSpectrum, onSpectrumReset,
  eventsView, framesView, frozenView, powerUnit, presets, resetState, role, serverNow, setFrameScheduler, status, subscribed, synthetic, tuning,
} from './link';
import type { FlightSchema, GuiEvent, HelloMsg, RecordMsg } from './types';

const F = 3;
const schema: FlightSchema = {
  version: 1,
  fields: [
    { key: 'seq', label: 'Seq', quantity: 'count', digits: 0 },
    { key: 'phase', label: 'Phase', quantity: 'enum', enum: ['IDLE', 'ARMED'] },
    { key: 'alt_agl_m', label: 'Altitude AGL', quantity: 'length', digits: 1 },
  ],
};

const record = (type: string, fields: Record<string, unknown>, text = type, t = 1): RecordMsg => ({
  type: 'record', text,
  record: { t, type, seq: 1, flags: 1, synthetic: true, fields, raw: null },
});

/** Test-only FLIGHT_ROWS encoder (spec 3.4). */
function flightRows(origin: number, rows: { t: number; values: number[] }[], fieldCount = F): ArrayBuffer {
  const size = 10 + 4 * fieldCount;
  const buf = new ArrayBuffer(8 + rows.length * size);
  const v = new DataView(buf);
  v.setUint8(0, 2); v.setUint8(1, 1); v.setUint8(2, origin);
  v.setUint16(4, fieldCount, true); v.setUint16(6, rows.length, true);
  rows.forEach((r, i) => {
    const o = 8 + i * size;
    v.setFloat64(o, r.t, true);
    v.setUint8(o + 8, 1);
    r.values.forEach((x, k) => v.setFloat32(o + 10 + 4 * k, x, true));
  });
  return buf;
}

function hexToBuffer(hex: string): ArrayBuffer {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out.buffer;
}
const spectrumB = hexToBuffer((golden as { name: string; hex: string }[]).find((v) => v.name === 'spectrum_no_rf')!.hex);

const helloMsg = (): HelloMsg => ({
  type: 'hello', server_version: '0.1.0', protocol_version: 2,
  source: { kind: 'sim', state: 'running', detail: '', responds_to_tuning: true },
  role: { type: 'role', role: 'viewer', budget: 'viewer', admin: null, can_admin: true, reason: 'connect' },
  budget: 'viewer',
  tuning: { type: 'tuning', state: {} as never, derived: { lo_hz: 441.38e6 } as never },
  flight_schema: schema, channels: ['flight', 'events'], sites: [],
});

const event = (id: number, kind = 'phase', prev_phase: string | null = kind === 'flight_reset' ? 'LANDED' : null): GuiEvent => ({
  id, t: id, kind, category: 'flight', text: `e${id}`, channel: null, value: null, quantity: null, segment: 0,
  synthetic: true, prev_phase,
});

let frameCallbacks: (() => void)[] = [];
beforeEach(() => {
  frameCallbacks = [];
  setFrameScheduler((cb) => { frameCallbacks.push(cb); });
  resetState();
  handleMessage(helloMsg());
});
afterEach(() => { vi.restoreAllMocks(); });
const runFrame = () => { const cbs = frameCallbacks; frameCallbacks = []; cbs.forEach((cb) => cb()); };

describe('handleMessage', () => {
  it('stores hello, role, tuning and the flight schema', () => {
    expect(get(role)?.role).toBe('viewer');
    expect(get(tuning)?.derived.lo_hz).toBe(441.38e6);
    expect(get(flightSchema)).toEqual(schema);
    expect(get(hello)?.budget).toBe('viewer');
  });

  it('routes records into stores and history', () => {
    handleMessage(record('STATUS', { version: 2 }));
    handleMessage(record('CHAN_METRICS', {
      channel: 'B', rssi_dbm: -80, noise_dbm: -100, snr_db: 30, freq_offset_hz: 12, crc_good: 5, crc_bad: 1, power_unit: 'dBFS',
    }, 'm', 7));
    handleMessage(record('IQ_SNAPSHOT', { channel: 'A', iq: [[1, 2]] }));
    expect(get(status)?.fields.version).toBe(2);
    expect(latestMetrics('B')).toEqual({ t: 7, rssi: -80, noise: -100, snr: 30, df: 12, crc_good: 5, crc_bad: 1, synthetic: true });
    expect(latestMetrics('A')).toBeNull();
    expect(get(powerUnit)).toBe('dBFS');
    expect(metricsTail('B', 0, 300)).toEqual([-80]);
    runFrame();
    expect(get(metricsNow).B?.rssi).toBe(-80);
    expect(get(iqSnaps).A).toEqual([[[1, 2]]]);
    expect(get(iqSnapMeta).A).toEqual([{ sample_rate_hz: null, synthetic: true }]);
    handleMessage(record('IQ_SNAPSHOT', { channel: 'A', iq: [[3, 4]], sample_rate_hz: 100000 }));
    expect(get(iqSnapMeta).A?.[1].sample_rate_hz).toBe(100000);
    const m = metricsStores.B;
    expect(m.length).toBe(1);
    expect(m.timeAt(0)).toBe(7);
    expect(Array.from(m.latest()!.values)).toEqual([-80, -100, 30, 12, 5, 1]);
  });

  it('bounds the frames ring, oldest first', () => {
    for (let i = 0; i < FRAMES_MAX + 5; i++) handleMessage(record('CHAN_FRAME', { channel: 'A' }, `f${i}`));
    const ring = get(frames);
    expect(ring.length).toBe(FRAMES_MAX);
    expect(ring[ring.length - 1].text).toBe(`f${FRAMES_MAX + 4}`);
  });

  it('stores the presets message and clears it on reset', () => {
    expect(get(presets)).toBeNull();
    const msg = {
      type: 'presets' as const, items: [{ schema: 1, id: 'flight', name: 'Flight', revision: 1, builtin: true,
        grid: { cols: 12 }, cards: [], triggers: [] }],
      live: 'flight', default: 'flight', auto_switch: false,
    };
    handleMessage(msg);
    expect(get(presets)).toEqual(msg);
    resetState();
    expect(get(presets)).toBeNull();
  });

  it('keeps receiving while frozen; freeze only stops drawing', () => {
    const rows: number[] = [];
    const off = onSpectrum((m) => rows.push(m.row));
    frozen.set(true);
    handleMessage(spectrumB);
    handleMessage(record('STATUS', { version: 9 }));
    handleMessage({ type: 'history', channel: 'flight', count: 1 });
    handleMessage(flightRows(2, [{ t: 1, values: [1, 1, 5] }]));
    off();
    expect(rows).toEqual([7]);
    expect(get(status)?.fields.version).toBe(9);
    expect(flightStores.best.length).toBe(1);
  });

  it('fills a flight store from a history marker and a binary batch', () => {
    handleMessage({ type: 'history', channel: 'flight', count: 2 });
    handleMessage(flightRows(2, [{ t: 10, values: [1, 1, 5] }, { t: 11, values: [2, 1, 6] }]));
    expect(flightStores.best.length).toBe(2);
    expect(flightStores.best.valueAt(1, 2)).toBe(6);
  });

  it('treats a second history marker as a hard reset', () => {
    handleMessage({ type: 'history', channel: 'flight', count: 2 });
    handleMessage(flightRows(2, [{ t: 10, values: [1, 1, 5] }, { t: 11, values: [2, 1, 6] }]));
    handleMessage(flightRows(2, [{ t: 12, values: [3, 1, 7] }]));
    handleMessage({ type: 'history', channel: 'flight', count: 1 });
    expect(flightStores.best.length).toBe(0);
    handleMessage(flightRows(2, [{ t: 12, values: [3, 1, 7] }]));
    expect(flightStores.best.length).toBe(1);
  });

  it('drops flight rows whose field count differs from the schema', () => {
    handleMessage(flightRows(2, [{ t: 10, values: [1, 1, 5, 9] }], 4));
    expect(flightStores.best.length).toBe(0);
  });

  it('ignores A/B flight rows unless subscribed', () => {
    handleMessage(flightRows(0, [{ t: 10, values: [1, 1, 5] }]));
    expect(flightStores.A).toBeUndefined();
  });

  it('resets frames and spectrum on their history markers', () => {
    handleMessage(record('CHAN_FRAME', { channel: 'A' }, 'old'));
    const resets: string[] = [];
    const off = onSpectrumReset((ch) => resets.push(ch));
    handleMessage({ type: 'history', channel: 'frames', count: 0 });
    handleMessage({ type: 'history', channel: 'spectrum.B', count: 120 });
    off();
    expect(get(frames)).toEqual([]);
    expect(resets).toEqual(['B']);
  });

  it('segmentStart follows the newest flight_reset and clears on a reset snapshot and resetState', () => {
    expect(get(segmentStart)).toBeNull();
    handleMessage({ type: 'events', items: [event(5, 'flight_reset'), event(6)], reset: false });
    expect(get(segmentStart)).toBe(5);
    handleMessage({ type: 'events', items: [event(90, 'flight_reset')], reset: false });
    handleMessage({ type: 'events', items: [event(91)], reset: false });
    expect(get(segmentStart)).toBe(90);
    handleMessage({ type: 'events', items: [event(95, 'flight_reset', 'COAST')], reset: false });   // a mid-flight reboot
    expect(get(segmentStart)).toBe(90);
    handleMessage({ type: 'events', items: [event(1)], reset: true });
    expect(get(segmentStart)).toBeNull();
    handleMessage({ type: 'events', items: [event(7, 'flight_reset')], reset: true });
    expect(get(segmentStart)).toBe(7);
    resetState();
    expect(get(segmentStart)).toBeNull();
  });

  it('replaces events on reset and appends otherwise, capped at 2000', () => {
    handleMessage({ type: 'events', items: [event(1), event(2)], reset: false });
    handleMessage({ type: 'events', items: [event(3)], reset: true });
    expect(get(eventsStore).map((e) => e.id)).toEqual([3]);
    handleMessage({ type: 'events', items: [event(4, 'signal_loss')], reset: false });
    expect(get(eventsStore).map((e) => e.id)).toEqual([3, 4]);
    handleMessage({ type: 'events', items: Array.from({ length: 2005 }, (_, i) => event(10 + i)), reset: false });
    const all = get(eventsStore);
    expect(all.length).toBe(2000);
    expect(all[all.length - 1].id).toBe(2014);
  });

  it('rebuilds a metrics store from metrics_history, nulls as NaN', () => {
    handleMessage(record('CHAN_METRICS', {
      channel: 'A', rssi_dbm: -1, noise_dbm: -1, snr_db: 1, freq_offset_hz: 1, crc_good: 1, crc_bad: 1,
    }));
    handleMessage({
      type: 'metrics_history', channel: 'A', t: [1, 2], rssi: [-70, -71], noise: [-90, null], snr: [20, 19],
      df: [0, 5], crc_good: [1, 2], crc_bad: [0, 0], power_unit: 'dBm', synthetic: [false, true],
    });
    expect(latestMetrics('A')?.synthetic).toBe(true);
    const m = metricsStores.A;
    expect(m.length).toBe(2);
    expect(m.valueAt(0, 0)).toBe(-70);
    expect(Number.isNaN(m.valueAt(1, 1))).toBe(true);
    expect(metricsTail('A', 0, 1)).toEqual([-71]);
    expect(get(powerUnit)).toBe('dBm');
  });

  it('keeps every LINK_STATS count and exposes the newest point', () => {
    handleMessage(record('LINK_STATS', { from_a: 3, from_b: 1, neither_ok: 2, both_ok: 9 }, 'ls', 5));
    expect(get(linkStatsNow)).toEqual({ t: 5, from_a: 3, from_b: 1, neither_ok: 2, both_ok: 9 });
  });

  it('keeps the last 600 LINK_STATS', () => {
    for (let i = 0; i < 605; i++) handleMessage(record('LINK_STATS', { from_a: i, from_b: 2 * i }, 'ls', i));
    handleMessage(record('LINK_STATS', { from_a: 0, from_b: 0 }, 'ls', 604));   // repeated after a reconnect
    const ring = get(linkStatsRing);
    expect(ring.length).toBe(600);
    expect(ring[0]).toEqual({ t: 5, from_a: 5, from_b: 10, neither_ok: NaN, both_ok: NaN });
    expect(ring[599]).toEqual({ t: 604, from_a: 604, from_b: 1208, neither_ok: NaN, both_ok: NaN });
  });

  it('counts dropped frames and tracks the subscribed set', () => {
    handleMessage({ type: 'dropped', channel: 'frames', count: 3 });
    handleMessage({ type: 'dropped', channel: 'frames', count: 2 });
    handleMessage({ type: 'subscribed', channels: ['events', 'flight'] });
    expect(get(droppedFrames)).toBe(5);
    expect(get(subscribed)).toEqual(['events', 'flight']);
  });

  it('bumps dataVersion at most once per animation frame', () => {
    const v0 = get(dataVersion);
    handleMessage(flightRows(2, [{ t: 1, values: [1, 1, 5] }]));
    handleMessage(flightRows(2, [{ t: 2, values: [1, 1, 5] }]));
    expect(get(dataVersion)).toBe(v0);
    expect(frameCallbacks.length).toBe(1);
    runFrame();
    expect(get(dataVersion)).toBe(v0 + 1);
    handleMessage({ type: 'events', items: [event(1)], reset: false });
    runFrame();
    expect(get(dataVersion)).toBe(v0 + 2);
  });

  it('estimates server time from received rows', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1000_000);
    handleMessage(record('STATUS', { version: 1 }, 's', 1010));
    expect(serverNow()).toBeCloseTo(1010, 6);
  });

  it('ignores snapshot rows for the server clock', () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1000_000);
    handleMessage(flightRows(2, [{ t: 1010, values: [1, 1, 5] }]));
    now.mockReturnValue(1010_000);   // well past the hold time
    handleMessage({ type: 'history', channel: 'flight', count: 2 });
    handleMessage(flightRows(2, [{ t: 900, values: [1, 1, 5] }, { t: 901, values: [1, 1, 5] }]));
    expect(serverNow()).toBeCloseTo(1020, 6);
    handleMessage(flightRows(2, [{ t: 1030, values: [1, 1, 5] }]));
    expect(serverNow()).toBeCloseTo(1030, 6);
  });

  it('marks data synthetic when any row of a batch is', () => {
    const buf = flightRows(2, [{ t: 1, values: [1, 1, 5] }, { t: 2, values: [1, 1, 5] }]);
    new DataView(buf).setUint8(8 + 22 + 8, 0);   // second row not synthetic; the first still is
    handleMessage(buf);
    expect(get(synthetic)).toBe(true);
  });

  it('holds a frozen view while frozen and catches up after', () => {
    const view = frozenView(status);
    const seen: (number | undefined)[] = [];
    const off = view.subscribe((r) => seen.push(r?.fields.version));
    handleMessage(record('STATUS', { version: 1 }));
    frozen.set(true);
    handleMessage(record('STATUS', { version: 2 }));
    expect(get(view)?.fields.version).toBe(1);
    expect(get(frozenView(status))?.fields.version).toBe(2);   // a reader mounted while frozen starts current
    frozen.set(false);
    off();
    expect(seen).toEqual([undefined, 1, 2]);
  });

  it('freezes the raw frames and events views while ingestion continues', () => {
    const fOff = framesView.subscribe(() => {});
    const eOff = eventsView.subscribe(() => {});
    handleMessage(record('CHAN_FRAME', { channel: 'A' }));
    const before = get(framesView).length;
    const evBefore = get(eventsView).length;
    frozen.set(true);
    handleMessage(record('CHAN_FRAME', { channel: 'A' }));
    handleMessage({ type: 'events', reset: false, items: [event(99)] });
    expect(get(frames).length).toBe(before + 1);
    expect(get(eventsStore).length).toBe(evBefore + 1);
    expect(get(framesView).length).toBe(before);
    expect(get(eventsView).length).toBe(evBefore);
    frozen.set(false);
    expect(get(framesView).length).toBe(before + 1);
    expect(get(eventsView).length).toBe(evBefore + 1);
    fOff(); eOff();
  });

  it('resetState clears every store', () => {
    handleMessage({ type: 'history', channel: 'flight', count: 1 });
    handleMessage(flightRows(2, [{ t: 1, values: [1, 1, 5] }]));
    handleMessage({ type: 'events', items: [event(1)], reset: true });
    handleMessage(record('LINK_STATS', { from_a: 1, from_b: 1 }));
    handleMessage(record('CHAN_METRICS', { channel: 'A', rssi_dbm: -1, snr_db: 1 }));
    handleMessage({ type: 'dropped', channel: 'frames', count: 3 });
    handleMessage({ type: 'subscribed', channels: ['flight'] });
    handleMessage(record('CHAN_FRAME', { channel: 'A' }));
    handleMessage({
      type: 'metrics_history', channel: 'B', t: [], rssi: [], noise: [], snr: [], df: [], crc_good: [], crc_bad: [],
      power_unit: 'dBFS (relative)',
    });
    frozen.set(true);
    expect(get(powerUnit)).toBe('dBFS (relative)');
    resetState();
    expect(get(powerUnit)).toBeNull();
    expect(flightStores.best.length).toBe(0);
    expect(flightStores.A).toBeUndefined();
    expect(metricsStores.A.length).toBe(0);
    expect(get(eventsStore)).toEqual([]);
    expect(get(linkStatsRing)).toEqual([]);
    expect(get(droppedFrames)).toBe(0);
    expect(get(subscribed)).toEqual([]);
    expect(get(frames)).toEqual([]);
    expect(get(flightSchema)).toBeNull();
    expect(get(frozen)).toBe(false);
  });
});

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 1;
  binaryType = 'blob';
  sent: any[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  constructor(public url: string) { Socket.instances.push(this); }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
}

describe('LinkClient subscriptions', () => {
  let client: LinkClient;
  const subs = (s: Socket) => s.sent.filter((m) => m.type === 'subscribe').map((m) => m.channels);
  beforeEach(() => {
    vi.useFakeTimers(); vi.stubGlobal('WebSocket', Socket); Socket.instances = [];
    client = new LinkClient(); client.start('ws://test/ws'); Socket.instances[0].onopen?.();
  });
  afterEach(() => { client.stop(); vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('receives binary frames as ArrayBuffers', () => {
    expect(Socket.instances[0].binaryType).toBe('arraybuffer');
    const rows: number[] = [];
    const off = onSpectrum((m) => rows.push(m.row));
    Socket.instances[0].onmessage?.({ data: spectrumB });
    off();
    expect(rows).toEqual([7]);
  });

  it('debounces by 250 ms and sends only on change', () => {
    client.setSubscriptions(['flight', 'events']);
    vi.advanceTimersByTime(100);
    client.setSubscriptions(['events', 'flight', 'link']);
    vi.advanceTimersByTime(249);
    expect(subs(Socket.instances[0])).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(subs(Socket.instances[0])).toEqual([['events', 'flight', 'link']]);
    client.setSubscriptions(['link', 'flight', 'events']);
    vi.advanceTimersByTime(300);
    expect(subs(Socket.instances[0])).toHaveLength(1);
  });

  it('re-sends the set after a reconnect', () => {
    client.setSubscriptions(['events', 'flight']);
    vi.advanceTimersByTime(250);
    Socket.instances[0].close();
    vi.advanceTimersByTime(500);
    Socket.instances[1].onopen?.();
    expect(subs(Socket.instances[1])).toEqual([['events', 'flight']]);
  });

  it('allocates A/B flight stores only while subscribed', () => {
    client.setSubscriptions(['events', 'flight', 'flight.A']);
    expect(flightStores.A).toBeUndefined();
    vi.advanceTimersByTime(250);
    expect(flightStores.A?.fieldCount).toBe(F);
    handleMessage(flightRows(0, [{ t: 10, values: [1, 1, 5] }]));
    expect(flightStores.A?.length).toBe(1);
    client.setSubscriptions(['events', 'flight']);
    vi.advanceTimersByTime(250);
    expect(flightStores.A).toBeUndefined();
  });

  it('keeps an A/B store when removed and re-added within the debounce', () => {
    client.setSubscriptions(['events', 'flight', 'flight.A']);
    vi.advanceTimersByTime(250);
    handleMessage(flightRows(0, [{ t: 10, values: [1, 1, 5] }]));
    client.setSubscriptions(['events', 'flight']);
    vi.advanceTimersByTime(100);
    client.setSubscriptions(['events', 'flight', 'flight.A']);
    vi.advanceTimersByTime(300);
    expect(subs(Socket.instances[0])).toHaveLength(1);
    expect(flightStores.A?.length).toBe(1);
  });
});

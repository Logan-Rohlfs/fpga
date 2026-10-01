/** The one WebSocket connection and the stores every component reads. */
import { type Readable, derived, get, readable, writable } from 'svelte/store';
import { latestSegmentStart } from './events';
import { SeriesStore } from './series';
import { createCoalescer } from './throttle';
import type {
  Channel, ClientMsg, FlightSchema, GuiEvent, HelloMsg, MetricsHistoryMsg, PresetsMsg, RecordJson, RecordMsg, RoleMsg, ServerMsg,
  SpectrumMsg, StatsMsg, TakeoverMsg, TuningChanges, TuningMsg,
} from './types';
import { type FlightOrigin, type FlightRows, decodeBinary } from './wire';

export interface Notice { id: number; text: string; kind: 'info' | 'warn' }
export interface LinkStatsPoint { t: number; from_a: number; from_b: number; neither_ok: number; both_ok: number }
/** The newest CHAN_METRICS sample of one channel, from its metrics ring. */
export interface MetricsSample {
  t: number; rssi: number; noise: number; snr: number; df: number; crc_good: number; crc_bad: number; synthetic: boolean;
}

export const SPARK_POINTS = 300;         // 30 s of CHAN_METRICS at 10 Hz (Tune sparklines)
export const FRAMES_MAX = 200;
export const EVENTS_MAX = 2000;
export const LINK_STATS_MAX = 600;
export const METRICS_MAX = 600;
export const FLIGHT_MAX = 36000;
/** Field order of metricsStores rows. */
export const METRIC_FIELDS = ['rssi', 'noise', 'snr', 'df', 'crc_good', 'crc_bad'] as const;
const DEFAULT_FLIGHT_FIELDS = 20;       // until hello.flight_schema arrives
const SUBSCRIBE_DEBOUNCE_MS = 250;
const SERVER_OFFSET_HOLD_S = 5;
const TOKEN_KEY = 'sdr.adminToken';

export const connection = writable<'connecting' | 'open' | 'closed'>('connecting');
export const hello = writable<HelloMsg | null>(null);
export const role = writable<RoleMsg | null>(null);
export const tuning = writable<TuningMsg | null>(null);
export const stats = writable<StatsMsg | null>(null);
export const status = writable<RecordJson | null>(null);
export const iqSnaps = writable<Partial<Record<Channel, [number, number][][]>>>({});
/** Per-snapshot metadata, index-aligned with `iqSnaps`: the snapshot's own sample rate (null if absent) and SYNTHETIC flag. */
export interface IqSnapMeta { sample_rate_hz: number | null; synthetic: boolean }
export const iqSnapMeta = writable<Partial<Record<Channel, IqSnapMeta[]>>>({});
export const presets = writable<PresetsMsg | null>(null);
export const takeover = writable<TakeoverMsg | null>(null);
export const notices = writable<Notice[]>([]);
/** Read only by drawing code. Ingestion never stops, so freezing leaves no gaps. */
export const frozen = writable(false);
export const synthetic = writable(false);

export const flightSchema = writable<FlightSchema | null>(null);
/** One ring per flight origin. A and B exist only while `flight.A` / `flight.B` are subscribed. */
export const flightStores: { best: SeriesStore; A?: SeriesStore; B?: SeriesStore } = {
  best: new SeriesStore(DEFAULT_FLIGHT_FIELDS, FLIGHT_MAX),
};
/** Per-channel link metrics, fields in METRIC_FIELDS order. */
export const metricsStores: Record<Channel, SeriesStore> = {
  A: new SeriesStore(METRIC_FIELDS.length, METRICS_MAX),
  B: new SeriesStore(METRIC_FIELDS.length, METRICS_MAX),
};
export const linkStatsRing = writable<LinkStatsPoint[]>([]);
/** Power unit of the newest metrics (metrics_history or live CHAN_METRICS); null until one arrives. */
export const powerUnit = writable<string | null>(null);
export const eventsStore = writable<GuiEvent[]>([]);
/** Server-clock time of the newest flight_reset (a new flight segment, such as each demo loop); null until one is seen. */
export const segmentStart = writable<number | null>(null);
/** The last FRAMES_MAX `frames` records, oldest first. */
export const frames = writable<RecordMsg[]>([]);
/** Bumped at most once per animation frame after any ring or store above changes. */
export const dataVersion = writable(0);
export const droppedFrames = writable(0);
export const subscribed = writable<string[]>([]);

/** Follows `src`, but holds its last value while the display is frozen. For display readers only. */
export function frozenView<T>(src: Readable<T>): Readable<T> {
  return readable(get(src), (set) => {
    let isFrozen = false;
    let started = false;
    const offFrozen = frozen.subscribe((f) => {
      isFrozen = f;
      if (!f && started) set(get(src));
    });
    // A reader that mounts while frozen still starts from the current value.
    const offSrc = src.subscribe((value) => {
      if (!isFrozen || !started) set(value);
    });
    started = true;
    return () => {
      offFrozen();
      offSrc();
    };
  });
}
export const statusView = frozenView(status);
export const iqSnapsView = frozenView(iqSnaps);
export const statsView = frozenView(stats);
/** Raw-frame log and event log for display; ingestion continues while frozen. */
export const framesView = frozenView(frames);
export const eventsView = frozenView(eventsStore);

/** The newest sample in a channel's metrics ring, or null when it is empty. */
export function latestMetrics(ch: Channel): MetricsSample | null {
  const l = metricsStores[ch].latest();
  if (!l) return null;
  const v = l.values;
  return { t: l.t, rssi: v[0], noise: v[1], snr: v[2], df: v[3], crc_good: v[4], crc_bad: v[5], synthetic: !!(l.flags & 1) };
}
/** Latest metrics per channel for display; follows the rings (once per frame) and holds while frozen. */
export const metricsNow = frozenView(derived(dataVersion, () => ({ A: latestMetrics('A'), B: latestMetrics('B') })));
/** Newest LINK_STATS point for display; holds while frozen. */
export const linkStatsNow = frozenView(derived(linkStatsRing, (ring) => ring[ring.length - 1] ?? null));
/** The last `n` values of one metrics field (METRIC_FIELDS index), oldest first, for sparklines. */
export function metricsTail(ch: Channel, field: number, n: number): number[] {
  const store = metricsStores[ch];
  const out: number[] = [];
  for (let i = Math.max(0, store.length - n); i < store.length; i++) out.push(store.valueAt(i, field));
  return out;
}

const spectrumListeners = new Set<(m: SpectrumMsg) => void>();
export function onSpectrum(fn: (m: SpectrumMsg) => void): () => void {
  spectrumListeners.add(fn);
  return () => spectrumListeners.delete(fn);
}
const spectrumResetListeners = new Set<(ch: Channel) => void>();
/** A `history` marker for spectrum.X: discard drawn rows; the snapshot rows follow. */
export function onSpectrumReset(fn: (ch: Channel) => void): () => void {
  spectrumResetListeners.add(fn);
  return () => spectrumResetListeners.delete(fn);
}

let noticeId = 0;
export function notify(text: string, kind: Notice['kind'] = 'info', ms = 6000): void {
  const id = ++noticeId;
  notices.update((n) => [...n, { id, text, kind }]);
  setTimeout(() => notices.update((n) => n.filter((x) => x.id !== id)), ms);
}

function saveToken(token: string) {
  try { sessionStorage.setItem(TOKEN_KEY, token); } catch { /* no session storage */ }
}
function loadToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function clearToken() {
  try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* no session storage */ }
}

// ---- dataVersion: one bump per animation frame, scheduled lazily so importing in node never touches rAF.
export type FrameScheduler = (cb: () => void) => void;
const defaultScheduler: FrameScheduler = (cb) => {
  if (typeof globalThis.requestAnimationFrame === 'function') globalThis.requestAnimationFrame(() => cb());
  else setTimeout(cb, 16);
};
let scheduler: FrameScheduler = defaultScheduler;
let bumpPending = false;
/** Test hook: replace the frame scheduler (null restores requestAnimationFrame). */
export function setFrameScheduler(fn: FrameScheduler | null): void {
  scheduler = fn ?? defaultScheduler;
  bumpPending = false;
}
function bumpData(): void {
  if (bumpPending) return;
  bumpPending = true;
  scheduler(() => {
    bumpPending = false;
    dataVersion.update((v) => v + 1);
  });
}

// ---- server clock: later cards pass serverNow() as "now" so relative times survive clock skew.
let serverNowOffset: number | null = null;
let serverOffsetAt = 0;
/** Rows still expected in each channel's snapshot (after its `history` marker). */
const snapshotRemaining = new Map<string, number>();
/** Count `n` rows against a channel's snapshot; true when they are all snapshot (historic) rows. */
function inSnapshot(channel: string, n: number): boolean {
  const left = snapshotRemaining.get(channel) ?? 0;
  if (left <= 0) return false;
  snapshotRemaining.set(channel, Math.max(0, left - n));
  return true;
}
/** Record a live server timestamp. Callers skip snapshot rows, so old history never drags the offset back. */
function noteServerTime(t: number): void {
  if (!Number.isFinite(t)) return;
  const now = Date.now() / 1000;
  const offset = t - now;
  if (serverNowOffset === null || offset > serverNowOffset || now - serverOffsetAt > SERVER_OFFSET_HOLD_S) {
    serverNowOffset = offset;
    serverOffsetAt = now;
  }
}
/** Best estimate of the server's wall clock, epoch seconds. */
export function serverNow(): number {
  return Date.now() / 1000 + (serverNowOffset ?? 0);
}

// ---- flight stores
let schemaReconnectRequested = false;

function flightFieldCount(): number {
  return get(flightSchema)?.fields.length ?? flightStores.best.fieldCount;
}

/** Keep A/B stores allocated exactly while their channels are wanted. */
function allocateFlightStores(channels: string[]): void {
  for (const o of ['A', 'B'] as const) {
    if (channels.includes(`flight.${o}`)) {
      if (!flightStores[o]) flightStores[o] = new SeriesStore(flightFieldCount(), FLIGHT_MAX);
    } else {
      delete flightStores[o];
    }
  }
}

function setSchema(schema: FlightSchema | null | undefined): void {
  flightSchema.set(schema ?? null);
  const f = schema?.fields.length;
  if (!f) return;
  if (flightStores.best.fieldCount !== f) flightStores.best = new SeriesStore(f, FLIGHT_MAX);
  for (const o of ['A', 'B'] as const) {
    if (flightStores[o] && flightStores[o].fieldCount !== f) flightStores[o] = new SeriesStore(f, FLIGHT_MAX);
  }
}

function applyFlight(origin: FlightOrigin, fieldCount: number, rows: FlightRows): void {
  if (fieldCount !== flightFieldCount()) {
    // Only a stale tab against a newer server can see this; a fresh hello brings the new schema.
    // Reconnect once per page load, so an inconsistent server cannot cause a reconnect loop.
    if (!schemaReconnectRequested) {
      schemaReconnectRequested = true;
      console.warn(`Flight rows have ${fieldCount} fields, schema has ${flightFieldCount()}; reconnecting`);
      link.reconnectSocket();
    }
    return;
  }
  const historic = inSnapshot(origin === 'best' ? 'flight' : `flight.${origin}`, rows.n);
  const store = flightStores[origin];
  if (!store) return;
  let anySynthetic = false;
  for (let i = 0; i < rows.n; i++) {
    store.append(rows.t[i], rows.flags[i], rows.values, i * fieldCount);
    anySynthetic ||= !!(rows.flags[i] & 1);
  }
  if (anySynthetic) synthetic.set(true);
  if (rows.n && !historic) noteServerTime(rows.t[rows.n - 1]);
  bumpData();
}

function applySpectrum(msg: SpectrumMsg): void {
  synthetic.update((seen) => seen || msg.synthetic);
  if (!inSnapshot(`spectrum.${msg.channel}`, 1)) noteServerTime(msg.t_us / 1e6);
  for (const fn of spectrumListeners) fn(msg);
}

function applyBinary(buf: ArrayBuffer): void {
  const d = decodeBinary(buf);
  if (d.kind === 'spectrum') applySpectrum(d.msg);
  else applyFlight(d.origin, d.fieldCount, d.rows);
}

// ---- JSON records and snapshots
const num = (x: unknown): number => (typeof x === 'number' ? x : NaN);

function applyRecord(msg: RecordMsg): void {
  const r = msg.record;
  synthetic.update((seen) => seen || r.synthetic);
  const isFrame = r.type === 'CHAN_FRAME' || r.type === 'BEST_TELEM';
  if (!(isFrame && inSnapshot('frames', 1))) noteServerTime(r.t);
  switch (r.type) {
    case 'STATUS': status.set(r); break;
    case 'LINK_STATS':
      linkStatsRing.update((ring) => {
        if (ring.length && r.t <= ring[ring.length - 1].t) return ring;   // a reconnect repeats the latest record
        const f = r.fields;
        return [...ring, {
          t: r.t, from_a: num(f.from_a), from_b: num(f.from_b), neither_ok: num(f.neither_ok), both_ok: num(f.both_ok),
        }].slice(-LINK_STATS_MAX);
      });
      bumpData();
      break;
    case 'CHAN_METRICS': {
      const ch = r.fields.channel as Channel;
      if (metricsStores[ch]) {
        const f = r.fields;
        if (typeof f.power_unit === 'string') powerUnit.set(f.power_unit);
        metricsStores[ch].append(r.t, r.synthetic ? 1 : 0, [
          num(f.rssi_dbm), num(f.noise_dbm), num(f.snr_db), num(f.freq_offset_hz), num(f.crc_good), num(f.crc_bad),
        ]);
        bumpData();
      }
      break;
    }
    case 'IQ_SNAPSHOT': {
      const ch = r.fields.channel as Channel;
      iqSnaps.update((s) => ({ ...s, [ch]: [...(s[ch] ?? []), r.fields.iq].slice(-4) }));
      const rate = r.fields.sample_rate_hz;
      const entry: IqSnapMeta = { sample_rate_hz: typeof rate === 'number' && rate > 0 ? rate : null, synthetic: r.synthetic };
      iqSnapMeta.update((s) => ({ ...s, [ch]: [...(s[ch] ?? []), entry].slice(-4) }));
      break;
    }
  }
  if (isFrame) {
    frames.update((l) => [...l, msg].slice(-FRAMES_MAX));
    bumpData();
  }
}

function applyMetricsHistory(msg: MetricsHistoryMsg): void {
  const store = metricsStores[msg.channel];
  if (!store) return;
  if (msg.power_unit !== null) powerUnit.set(msg.power_unit);
  store.clear();
  const cols = [msg.rssi, msg.noise, msg.snr, msg.df, msg.crc_good, msg.crc_bad];
  const row = new Array<number>(cols.length);
  for (let i = 0; i < msg.t.length; i++) {
    for (let k = 0; k < cols.length; k++) row[k] = cols[k]?.[i] ?? NaN;
    store.append(msg.t[i], msg.synthetic?.[i] ? 1 : 0, row);
  }
  bumpData();
}

/** A `history` marker is a hard reset of that channel's store; its snapshot rows follow. */
function resetChannel(channel: string, count: number): void {
  snapshotRemaining.set(channel, count);
  const [kind, sub] = channel.split('.') as [string, Channel | undefined];
  switch (kind) {
    case 'flight':
      if (!sub) flightStores.best.clear();
      else flightStores[sub]?.clear();
      break;
    case 'frames':
      frames.set([]);
      break;
    case 'spectrum':
      if (sub === 'A' || sub === 'B') for (const fn of spectrumResetListeners) fn(sub);
      break;
    case 'iq':
      if (sub === 'A' || sub === 'B') { iqSnaps.update((s) => ({ ...s, [sub]: [] })); iqSnapMeta.update((s) => ({ ...s, [sub]: [] })); }
      break;
    case 'events':
      eventsStore.set([]);
      segmentStart.set(null);
      break;
    case 'link':
      for (const ch of ['A', 'B'] as Channel[]) metricsStores[ch].clear();
      linkStatsRing.set([]);
      break;
  }
  bumpData();
}

export function handleMessage(msg: ServerMsg | ArrayBuffer): void {
  if (msg instanceof ArrayBuffer) {
    applyBinary(msg);
    return;
  }
  switch (msg.type) {
    case 'hello':
      hello.set(msg); role.set(msg.role); tuning.set(msg.tuning);
      setSchema(msg.flight_schema);
      break;
    case 'tuning': tuning.set(msg); break;
    case 'stats': stats.set(msg); break;
    case 'role':
      role.set(msg);
      if (msg.token) saveToken(msg.token);
      else if (msg.role === 'viewer') clearToken();
      if (msg.reason === 'taken_over') notify(`${msg.by ?? 'Someone'} took over Operator. You are now a Viewer.`, 'warn', 10000);
      break;
    case 'takeover_required': takeover.set(msg); break;
    case 'error': notify(msg.text, 'warn'); break;
    case 'record': applyRecord(msg); break;
    case 'subscribed': subscribed.set(msg.channels); break;
    case 'history': resetChannel(msg.channel, msg.count); break;
    case 'events':
      if (msg.reset) {
        eventsStore.set(msg.items.slice(-EVENTS_MAX));
        segmentStart.set(latestSegmentStart(msg.items));
      } else {
        eventsStore.update((l) => [...l, ...msg.items].slice(-EVENTS_MAX));
        const s = latestSegmentStart(msg.items);
        if (s !== null) segmentStart.set(s);
      }
      bumpData();
      break;
    case 'metrics_history': applyMetricsHistory(msg); break;
    case 'dropped': droppedFrames.update((n) => n + msg.count); break;
    case 'presets': presets.set(msg); break;
    case 'notice': notify(msg.text); break;
  }
}

/** Test helper: back to a fresh page state. */
export function resetState(): void {
  [hello, role, tuning, stats, status, takeover, flightSchema, presets, powerUnit].forEach((s) => s.set(null));
  iqSnaps.set({});
  iqSnapMeta.set({});
  frames.set([]);
  frozen.set(false);
  synthetic.set(false);
  for (const ch of ['A', 'B'] as Channel[]) metricsStores[ch].clear();
  flightStores.best = new SeriesStore(DEFAULT_FLIGHT_FIELDS, FLIGHT_MAX);
  delete flightStores.A;
  delete flightStores.B;
  schemaReconnectRequested = false;
  linkStatsRing.set([]);
  eventsStore.set([]);
  segmentStart.set(null);
  droppedFrames.set(0);
  subscribed.set([]);
  dataVersion.set(0);
  bumpPending = false;
  serverNowOffset = null;
  serverOffsetAt = 0;
  snapshotRemaining.clear();
}

export function defaultUrl(loc: Location = window.location): string {
  return `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}/ws`;
}

export class LinkClient {
  private ws: WebSocket | null = null;
  private retryMs = 500;
  private stopped = true;
  private url = '';
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private tuner = createCoalescer<TuningChanges>((changes) => this.send({ type: 'tune', changes }));
  private wanted: string[] | null = null;
  private sentKey: string | null = null;   // subscription set sent on the current socket
  private subTimer: ReturnType<typeof setTimeout> | null = null;

  start(url = defaultUrl()): void {
    if (!this.stopped) return;
    this.url = url;
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    if (this.subTimer) clearTimeout(this.subTimer);
    this.subTimer = null;
    this.tuner.cancel();
    const ws = this.ws;
    this.ws = null;
    ws?.close();
    connection.set('closed');
    role.set(null);
  }

  private open(): void {
    if (this.stopped) return;
    this.retryTimer = null;
    connection.set('connecting');
    const ws = new WebSocket(this.url);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    this.sentKey = null;
    ws.onopen = () => {
      if (this.ws !== ws || this.stopped) return;
      connection.set('open');
      this.retryMs = 500;
      const token = loadToken();
      if (token) this.send({ type: 'resume', token });
      this.flushSubscriptions();   // a new socket starts with no subscriptions
    };
    ws.onmessage = (e) => {
      if (this.ws !== ws || this.stopped) return;
      try {
        handleMessage(e.data instanceof ArrayBuffer ? e.data : JSON.parse(e.data as string) as ServerMsg);
      } catch (err) {
        console.error('Unreadable server message', err);
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.tuner.cancel();
      role.set(null);
      takeover.set(null);
      connection.set('closed');
      if (this.stopped) return;
      this.retryTimer = setTimeout(() => this.open(), this.retryMs);
      this.retryMs = Math.min(8000, this.retryMs * 2);
    };
  }

  send(msg: ClientMsg): void {
    // Operator-only; the server enforces it too. A viewer's UI never sends these.
    if ((msg.type === 'tune' || msg.type.startsWith('preset_')) && get(role)?.role !== 'admin') return;
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  login(password: string, label: string, takeover = false): void {
    this.send({ type: 'login', password, label, takeover });
  }

  logout(): void {
    this.tuner.cancel();
    role.set(null);
    clearToken();
    this.send({ type: 'logout' });
  }

  tune(changes: TuningChanges): void {
    if (get(connection) === 'open' && get(role)?.role === 'admin') this.tuner.push(changes);
  }

  /** Channels this page needs. Sent 250 ms after the last change, only if different, and again after reconnect. */
  setSubscriptions(channels: string[]): void {
    const next = [...new Set(channels)].sort();
    this.wanted = next;
    if (this.subTimer) clearTimeout(this.subTimer);
    this.subTimer = setTimeout(() => {
      this.subTimer = null;
      this.flushSubscriptions();
    }, SUBSCRIBE_DEBOUNCE_MS);
  }

  private flushSubscriptions(): void {
    if (!this.wanted || this.ws?.readyState !== WebSocket.OPEN) return;
    const key = this.wanted.join(',');
    if (key === this.sentKey) return;
    this.sentKey = key;
    // Store lifetime follows what the server was told, so a quick remove/re-add keeps its rows.
    allocateFlightStores(this.wanted);
    this.send({ type: 'subscribe', channels: this.wanted });
  }

  /** Drop the socket and let the normal retry reconnect for a fresh hello and snapshots. */
  reconnectSocket(): void {
    this.ws?.close();
  }

  reconnectSource(): void {
    this.send({ type: 'reconnect_source' });
  }
}

export const link = new LinkClient();

// Preset writes. Each only sends; the outcome is the server's `presets` broadcast or an `error` notice.
export const savePreset = (preset: unknown, baseRevision: number | null): void =>
  link.send({ type: 'preset_save', preset, base_revision: baseRevision });
export const deletePreset = (id: string): void => link.send({ type: 'preset_delete', id });
export const setLivePreset = (id: string): void => link.send({ type: 'preset_set_live', id });
export const setDefaultPreset = (id: string): void => link.send({ type: 'preset_set_default', id });
export const setAutoSwitch = (enabled: boolean): void => link.send({ type: 'preset_auto_switch', enabled });

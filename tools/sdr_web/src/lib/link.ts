/** The one WebSocket connection and the stores every component reads. */
import { get, writable } from 'svelte/store';
import { Ring } from './ring';
import { createCoalescer } from './throttle';
import type {
  Channel, ClientMsg, HelloMsg, RecordJson, RecordMsg, RoleMsg, ServerMsg, SpectrumMsg, StatsMsg, TakeoverMsg,
  TuningChanges, TuningMsg,
} from './types';

export interface Notice { id: number; text: string; kind: 'info' | 'warn' }

export const HISTORY = 300;              // 30 s of CHAN_METRICS at 10 Hz
export const FRAME_LOG_MAX = 200;
const TOKEN_KEY = 'sdr.adminToken';

export const connection = writable<'connecting' | 'open' | 'closed'>('connecting');
export const hello = writable<HelloMsg | null>(null);
export const role = writable<RoleMsg | null>(null);
export const tuning = writable<TuningMsg | null>(null);
export const stats = writable<StatsMsg | null>(null);
export const status = writable<RecordJson | null>(null);
export const linkStats = writable<RecordJson | null>(null);
export const best = writable<RecordJson | null>(null);
export const metrics = writable<Partial<Record<Channel, RecordJson>>>({});
export const iqSnaps = writable<Partial<Record<Channel, [number, number][][]>>>({});
export const frameLog = writable<string[]>([]);
export const takeover = writable<TakeoverMsg | null>(null);
export const notices = writable<Notice[]>([]);
export const frozen = writable(false);
export const synthetic = writable(false);
export const history: Record<Channel, { rssi: Ring; snr: Ring }> = {
  A: { rssi: new Ring(HISTORY), snr: new Ring(HISTORY) },
  B: { rssi: new Ring(HISTORY), snr: new Ring(HISTORY) },
};
export const historyVersion = writable(0);

const spectrumListeners = new Set<(m: SpectrumMsg) => void>();
export function onSpectrum(fn: (m: SpectrumMsg) => void): () => void {
  spectrumListeners.add(fn);
  return () => spectrumListeners.delete(fn);
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

function applyRecord(msg: RecordMsg): void {
  const r = msg.record;
  synthetic.update(seen => seen || r.synthetic);
  switch (r.type) {
    case 'STATUS': status.set(r); break;
    case 'LINK_STATS': linkStats.set(r); break;
    case 'BEST_TELEM': best.set(r); break;
    case 'CHAN_METRICS': {
      const ch = r.fields.channel as Channel;
      metrics.update((m) => ({ ...m, [ch]: r }));
      if (history[ch]) {
        history[ch].rssi.push(r.fields.rssi_dbm);
        history[ch].snr.push(r.fields.snr_db);
        historyVersion.update((v) => v + 1);
      }
      break;
    }
    case 'IQ_SNAPSHOT': {
      const ch = r.fields.channel as Channel;
      iqSnaps.update((s) => ({ ...s, [ch]: [...(s[ch] ?? []), r.fields.iq].slice(-4) }));
      break;
    }
    case 'CHAN_FRAME': frameLog.update((l) => [msg.text, ...l].slice(0, FRAME_LOG_MAX)); break;
  }
}

export function handleMessage(msg: ServerMsg): void {
  switch (msg.type) {
    case 'hello': hello.set(msg); role.set(msg.role); tuning.set(msg.tuning); break;
    case 'tuning': tuning.set(msg); break;
    case 'stats': stats.set(msg); break;
    case 'role':
      role.set(msg);
      if (msg.token) saveToken(msg.token);
      else if (msg.role === 'viewer') clearToken();
      if (msg.reason === 'taken_over') notify(`${msg.by ?? 'Someone'} took over Admin. You are now a Viewer.`, 'warn', 10000);
      break;
    case 'takeover_required': takeover.set(msg); break;
    case 'error': notify(msg.text, 'warn'); break;
    case 'spectrum':
      if (get(frozen)) return;
      synthetic.update(seen => seen || msg.synthetic);
      for (const fn of spectrumListeners) fn(msg);
      break;
    case 'record':
      if (!get(frozen)) applyRecord(msg);
      break;
  }
}

/** Test helper: back to a fresh page state. */
export function resetState(): void {
  [hello, role, tuning, stats, status, linkStats, best, takeover].forEach((s) => s.set(null));
  metrics.set({});
  iqSnaps.set({});
  frameLog.set([]);
  frozen.set(false);
  synthetic.set(false);
  for (const ch of ['A', 'B'] as Channel[]) { history[ch].rssi.clear(); history[ch].snr.clear(); }
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
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws || this.stopped) return;
      connection.set('open');
      this.retryMs = 500;
      const token = loadToken();
      if (token) this.send({ type: 'resume', token });
    };
    ws.onmessage = (e) => {
      if (this.ws !== ws || this.stopped) return;
      try {
        handleMessage(JSON.parse(e.data as string) as ServerMsg);
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
    if (msg.type === 'tune' && get(role)?.role !== 'admin') return;
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

  reconnectSource(): void {
    this.send({ type: 'reconnect_source' });
  }
}

export const link = new LinkClient();

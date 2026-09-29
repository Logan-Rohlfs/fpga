import { get } from 'svelte/store';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  FRAME_LOG_MAX, frameLog, frozen, handleMessage, history, iqSnaps, metrics, onSpectrum, resetState, role, status, tuning,
} from './link';
import type { RecordMsg, SpectrumMsg } from './types';

const record = (type: string, fields: Record<string, unknown>, text = type): RecordMsg => ({
  type: 'record', text,
  record: { t: 1, type, seq: 1, flags: 1, synthetic: true, fields, raw: null },
});
const spectrum: SpectrumMsg = {
  type: 'spectrum', channel: 'A', row: 0, t_us: 0, f0_hz: 50000, bin_hz: 390.625, bins: 2, db10: [-1000, -500],
  low: -110, high: -45, synthetic: true,
};

describe('handleMessage', () => {
  beforeEach(() => resetState());

  it('stores hello, role and tuning', () => {
    handleMessage({
      type: 'hello', server_version: '0.1.0', protocol_version: 2,
      source: { kind: 'sim', state: 'running', detail: '', responds_to_tuning: true },
      role: { type: 'role', role: 'viewer', admin: null, can_admin: true, reason: 'connect' },
      tuning: { type: 'tuning', state: {} as never, derived: { lo_hz: 441.38e6 } as never },
    });
    expect(get(role)?.role).toBe('viewer');
    expect(get(tuning)?.derived.lo_hz).toBe(441.38e6);
  });

  it('routes records into stores and history', () => {
    handleMessage(record('STATUS', { version: 2 }));
    handleMessage(record('CHAN_METRICS', { channel: 'B', rssi_dbm: -80, snr_db: 30 }));
    handleMessage(record('IQ_SNAPSHOT', { channel: 'A', iq: [[1, 2]] }));
    expect(get(status)?.fields.version).toBe(2);
    expect(get(metrics).B?.fields.rssi_dbm).toBe(-80);
    expect(history.B.rssi.values()).toEqual([-80]);
    expect(get(iqSnaps).A).toEqual([[[1, 2]]]);
  });

  it('bounds the frame log, newest first', () => {
    for (let i = 0; i < FRAME_LOG_MAX + 5; i++) handleMessage(record('CHAN_FRAME', { channel: 'A' }, `f${i}`));
    const log = get(frameLog);
    expect(log.length).toBe(FRAME_LOG_MAX);
    expect(log[0]).toBe(`f${FRAME_LOG_MAX + 4}`);
  });

  it('delivers spectrum rows to listeners and honours freeze', () => {
    const rows: SpectrumMsg[] = [];
    const off = onSpectrum((m) => rows.push(m));
    handleMessage(spectrum);
    frozen.set(true);
    handleMessage(spectrum);
    handleMessage(record('STATUS', { version: 9 }));
    off();
    expect(rows.length).toBe(1);
    expect(get(status)).toBeNull();
  });
});

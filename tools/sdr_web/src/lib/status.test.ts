import { describe, expect, it } from 'vitest';
import { connectionBanner, sourcePillText } from './status';
import type { SourceState } from './types';

const serial = (state: string, extra: Partial<SourceState> = {}): SourceState => ({
  kind: 'serial', state, detail: '/dev/ttyUSB1 @ 1000000 baud', responds_to_tuning: false, ...extra,
});

describe('connectionBanner', () => {
  it('reports an unreachable server whatever the source says', () => {
    for (const source of [undefined, serial('running'), serial('busy')]) {
      const banner = connectionBanner('closed', source);
      expect(banner?.text.startsWith('Server unreachable')).toBe(true);
      expect(banner?.level).toBe('bad');
    }
    expect(connectionBanner('connecting', undefined)?.text).toBe(
      'Server unreachable. Retrying the connection to the GUI server.');
  });

  it('tells a waiting board UART apart from a dead server', () => {
    const banner = connectionBanner('open', serial('waiting'));
    expect(banner?.text.startsWith('Server up. Waiting for board UART ')).toBe(true);
    expect(banner?.level).toBe('warn');
    expect(connectionBanner('open', serial('waiting', { port: '/dev/ttyUSB1' }))?.text).toBe(
      'Server up. Waiting for board UART /dev/ttyUSB1.');
  });

  it('shows a busy port as bad, with the detail', () => {
    const detail = '/dev/ttyUSB1 is held by another process (another ./sdr gui, ./sdr tui or receive?). Close it; retrying.';
    const banner = connectionBanner('open', serial('busy', { port: '/dev/ttyUSB1', detail }));
    expect(banner?.level).toBe('bad');
    expect(banner?.text).toBe(`Server up. Board UART /dev/ttyUSB1 is held by another process: ${detail}`);
    expect(banner?.text).toContain(detail);
  });

  it('counts down to the next reconnect', () => {
    const banner = connectionBanner('open', serial('reconnecting', { port: '/dev/ttyUSB1', retry_in_s: 2 }));
    expect(banner?.text).toBe('Server up. Reconnecting to /dev/ttyUSB1 in 2 s.');
    expect(banner?.text).toContain('in 2 s');
    expect(banner?.level).toBe('warn');
    expect(connectionBanner('open', serial('reconnecting', { port: 'COM4', retry_in_s: 0.5 }))?.text).toContain('in 0.5 s');
  });

  it('shows nothing while running', () => {
    expect(connectionBanner('open', serial('running'))).toBeNull();
    expect(connectionBanner('open', { kind: 'sim', state: 'running', detail: 'host simulator', responds_to_tuning: true })).toBeNull();
    expect(connectionBanner('open', undefined)).toBeNull();
  });

  it('keeps the v1 source note for other states', () => {
    const banner = connectionBanner('open', { kind: 'replay', state: 'ended', detail: 'demo.bin', responds_to_tuning: false });
    expect(banner).toEqual({ text: 'Source ended: demo.bin. Showing last received data.', level: 'info' });
  });
});

describe('sourcePillText', () => {
  it('names each serial state in words', () => {
    expect(sourcePillText(serial('running'))).toBe('connected');
    expect(sourcePillText(serial('waiting'))).toBe('waiting for port');
    expect(sourcePillText(serial('busy'))).toBe('port busy');
    expect(sourcePillText(serial('reconnecting', { retry_in_s: 4 }))).toBe('reconnecting in 4 s');
    expect(sourcePillText(serial('reconnecting'))).toBe('reconnecting');
  });

  it('keeps the v1 kind · state text otherwise', () => {
    expect(sourcePillText({ kind: 'sim', state: 'running', detail: '', responds_to_tuning: true })).toBe('sim · running');
    expect(sourcePillText({ kind: 'replay', state: 'ended', detail: '', responds_to_tuning: false })).toBe('replay · ended');
    expect(sourcePillText(serial('down'))).toBe('serial · down');
    expect(sourcePillText(undefined)).toBe('no source');
  });
});

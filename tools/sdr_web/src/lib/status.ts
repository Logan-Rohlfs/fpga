import type { SourceState } from './types';

export type Connection = 'connecting' | 'open' | 'closed';
export interface Banner { text: string; level: 'bad' | 'warn' | 'info' }

/** Seconds as short text: 2, 0.5, 8. */
const seconds = (s: number) => String(Math.round(s * 10) / 10);
const port = (source: SourceState) => source.port || source.detail;
const sentence = (text: string) => text.replace(/[.\s]+$/, '');

/**
 * The page banner (spec 18): tells an unreachable GUI server apart from a missing, busy or
 * reconnecting board UART. Null when there is nothing to report.
 */
export function connectionBanner(connection: Connection, source: SourceState | undefined): Banner | null {
  if (connection !== 'open') return { text: 'Server unreachable. Retrying the connection to the GUI server.', level: 'bad' };
  if (!source || source.state === 'running') return null;
  if (source.kind === 'serial') {
    if (source.state === 'waiting') return { text: `Server up. Waiting for board UART ${port(source)}.`, level: 'warn' };
    if (source.state === 'busy') {
      return { text: `Server up. Board UART ${port(source)} is held by another process: ${sentence(source.detail)}.`, level: 'bad' };
    }
    if (source.state === 'reconnecting') {
      const when = source.retry_in_s === undefined ? '' : ` in ${seconds(source.retry_in_s)} s`;
      return { text: `Server up. Reconnecting to ${port(source)}${when}.`, level: 'warn' };
    }
  }
  return { text: `Source ${source.state}: ${source.detail}. Showing last received data.`, level: source.state === 'down' ? 'bad' : 'info' };
}

/** The StatusBar source pill: serial states in words, otherwise the v1 `kind · state`. */
export function sourcePillText(source: SourceState | undefined): string {
  if (!source) return 'no source';
  if (source.kind === 'serial') {
    if (source.state === 'running') return 'connected';
    if (source.state === 'waiting') return 'waiting for port';
    if (source.state === 'busy') return 'port busy';
    if (source.state === 'reconnecting') {
      return source.retry_in_s === undefined ? 'reconnecting' : `reconnecting in ${seconds(source.retry_in_s)} s`;
    }
  }
  return `${source.kind} · ${source.state}`;
}

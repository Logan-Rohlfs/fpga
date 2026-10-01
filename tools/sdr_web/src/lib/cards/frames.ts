/** Raw-frame card helpers: filtering, hex layout, CRC span and row labels. */
import type { RecordMsg } from '../types';

export type FrameFilter = 'all' | 'A' | 'B' | 'best';

/** Keep BEST_TELEM for 'best', CHAN_FRAME on that channel for 'A'/'B', everything for 'all'. */
export function filterFrames(items: readonly RecordMsg[], filter: FrameFilter): RecordMsg[] {
  if (filter === 'all') return items.slice();
  if (filter === 'best') return items.filter((m) => m.record.type === 'BEST_TELEM');
  return items.filter((m) => m.record.type === 'CHAN_FRAME' && m.record.fields.channel === filter);
}

/** Split a hex string into rows of groupBytes bytes (the last row may be shorter). */
export function hexGroups(rawHex: string, groupBytes = 16): string[] {
  const step = Math.max(1, Math.floor(groupBytes)) * 2;
  const out: string[] = [];
  for (let i = 0; i < rawHex.length; i += step) out.push(rawHex.slice(i, i + step));
  return out;
}

/** [start, end) byte range of the trailing two-byte CRC. */
export function crcSpan(frameLen: number): [number, number] {
  const n = Math.max(0, Math.floor(frameLen));
  return [Math.max(0, n - 2), n];
}

/** One-line text for a frame row and whether it failed its CRC (record field or parsed APEX frame). */
export function frameLabel(r: RecordMsg): { text: string; crcBad: boolean } {
  const f = r.record.fields;
  const crcBad = f.crc_ok === false || f.apex?.crc_ok === false;
  const base = r.text || r.record.type;
  return { text: crcBad && !/CRC-BAD/.test(base) ? `${base} CRC-BAD` : base, crcBad };
}

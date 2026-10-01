import { describe, expect, it } from 'vitest';
import { crcSpan, filterFrames, frameLabel, hexGroups } from './frames';
import type { RecordMsg } from '../types';

const rec = (type: string, fields: Record<string, unknown> = {}, text = 'x'): RecordMsg => ({
  type: 'record', text, record: { t: 0, type, seq: 0, flags: 0, synthetic: false, fields, raw: null },
});

describe('filterFrames', () => {
  const items = [rec('BEST_TELEM'), rec('CHAN_FRAME', { channel: 'A' }), rec('CHAN_FRAME', { channel: 'B' })];
  it('best keeps only BEST_TELEM', () => expect(filterFrames(items, 'best')).toEqual([items[0]]));
  it('A and B select the channel', () => {
    expect(filterFrames(items, 'A')).toEqual([items[1]]);
    expect(filterFrames(items, 'B')).toEqual([items[2]]);
  });
  it('all keeps everything in a new array', () => {
    const out = filterFrames(items, 'all');
    expect(out).toEqual(items);
    expect(out).not.toBe(items);
  });
});

describe('hexGroups', () => {
  it('splits 44 bytes into 16, 16, 12', () => {
    expect(hexGroups('00'.repeat(44)).map((g) => g.length / 2)).toEqual([16, 16, 12]);
  });
  it('handles empty input', () => expect(hexGroups('')).toEqual([]));
});

describe('crcSpan', () => {
  it('is the last two bytes', () => {
    expect(crcSpan(44)).toEqual([42, 44]);
    expect(crcSpan(1)).toEqual([0, 1]);
  });
});

describe('frameLabel', () => {
  it('flags CRC-BAD from fields.crc_ok', () => expect(frameLabel(rec('CHAN_FRAME', { crc_ok: false }, 'a')))
    .toEqual({ text: 'a CRC-BAD', crcBad: true }));
  it('flags CRC-BAD from apex.crc_ok', () => expect(frameLabel(rec('BEST_TELEM', { apex: { crc_ok: false } }, 'b')).crcBad).toBe(true));
  it('does not duplicate an existing marker', () => expect(frameLabel(rec('BEST_TELEM', { crc_ok: false }, 'b CRC-BAD')).text).toBe('b CRC-BAD'));
  it('is good otherwise', () => expect(frameLabel(rec('BEST_TELEM', { crc_ok: true }, 'ok'))).toEqual({ text: 'ok', crcBad: false }));
});

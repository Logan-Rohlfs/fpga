import { describe, expect, it } from 'vitest';
import golden from './wire.golden.json';
import { decodeBinary } from './wire';

function hexToBuffer(hex: string): ArrayBuffer {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out.buffer;
}

/** Test-only SPECTRUM_ROW encoder (spec 3.4). */
function spectrumRow(db10: number[], flags = 0, rfLo = NaN, injection = 255): ArrayBuffer {
  const buf = new ArrayBuffer(52 + 2 * db10.length);
  const v = new DataView(buf);
  v.setUint8(0, 1); v.setUint8(1, 1); v.setUint8(2, 0); v.setUint8(3, flags);
  v.setUint32(4, 9, true); v.setUint16(8, db10.length, true);
  v.setFloat64(12, 2.5, true); v.setFloat64(20, 1000, true);
  v.setFloat32(28, 100, true); v.setFloat32(32, -90, true); v.setFloat32(36, -10, true);
  v.setFloat64(40, rfLo, true); v.setUint8(48, injection);
  db10.forEach((d, k) => v.setInt16(52 + 2 * k, d, true));
  return buf;
}

const nullNaN = (x: number) => (Number.isNaN(x) ? null : x);

describe('decodeBinary golden vectors', () => {
  for (const vec of golden as { name: string; hex: string; expect: Record<string, any> }[]) {
    it(vec.name, () => {
      const out = decodeBinary(hexToBuffer(vec.hex));
      if (out.kind === 'spectrum') {
        expect({ ...out.msg, db10: Array.from(out.msg.db10) }).toEqual(vec.expect);
      } else {
        const { rows, fieldCount, origin } = out;
        const decoded = [];
        for (let i = 0; i < rows.n; i++) {
          decoded.push({
            t: rows.t[i], flags: rows.flags[i],
            values: Array.from(rows.values.subarray(i * fieldCount, (i + 1) * fieldCount), nullNaN),
          });
        }
        expect({ kind: 'flight', origin, fieldCount, n: rows.n, rows: decoded }).toEqual(vec.expect);
      }
    });
  }
});

describe('decodeBinary', () => {
  it('round-trips spectrum db10 values', () => {
    const out = decodeBinary(spectrumRow([-900, -100, 0]));
    expect(out.kind).toBe('spectrum');
    if (out.kind !== 'spectrum') return;
    expect(out.msg.db10).toBeInstanceOf(Int16Array);
    expect(Array.from(out.msg.db10)).toEqual([-900, -100, 0]);
    expect(out.msg.t_us).toBe(2500000);
  });

  it('has no rf_reference when flag bit1 is clear', () => {
    const out = decodeBinary(spectrumRow([1], 0x04, 441e6, 0));
    expect(out.kind === 'spectrum' && out.msg.rf_reference).toBeNull();
  });

  it('decodes the ARMED phase index', () => {
    const vec = (golden as { name: string; hex: string }[]).find((v) => v.name === 'flight_single_best')!;
    const out = decodeBinary(hexToBuffer(vec.hex));
    expect(out.kind === 'flight' && out.rows.values[1]).toBe(1);   // PHASE_ENUM.index('ARMED')
  });

  it('rejects unknown kinds and versions', () => {
    expect(() => decodeBinary(new Uint8Array([9, 1]).buffer)).toThrow();
    expect(() => decodeBinary(new Uint8Array([1, 2]).buffer)).toThrow();
  });
});

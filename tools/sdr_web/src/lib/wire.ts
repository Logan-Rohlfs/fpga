/** Binary GUI frames (spec 3.4). Mirrors tools/sdr_cli/gui_wire.py; wire.golden.json pins both sides. */
import type { Channel, Injection, SpectrumMsg } from './types';

export const KIND_SPECTRUM = 0x01;
export const KIND_FLIGHT = 0x02;
export const WIRE_VERSION = 1;
const SPECTRUM_HEADER = 52;
const FLIGHT_HEADER = 8;
const CHANNELS: Channel[] = ['A', 'B'];
const INJECTIONS: Injection[] = ['low', 'high'];
export type FlightOrigin = 'A' | 'B' | 'best';
const ORIGINS: FlightOrigin[] = ['A', 'B', 'best'];

export const FLAG_SYNTHETIC = 0x01;
const FLAG_RF_REFERENCE = 0x02;
const FLAG_RF_INFERRED = 0x04;

/** Rows of one FLIGHT_ROWS message. `values` is row-major N×F in flight_schema order. */
export interface FlightRows { t: Float64Array; flags: Uint8Array; values: Float32Array; n: number }

export type Decoded =
  | { kind: 'spectrum'; msg: SpectrumMsg }
  | { kind: 'flight'; origin: FlightOrigin; fieldCount: number; rows: FlightRows };

export function decodeBinary(buf: ArrayBuffer): Decoded {
  const v = new DataView(buf);
  if (buf.byteLength < 2) throw new Error('binary frame too short');
  const kind = v.getUint8(0);
  const version = v.getUint8(1);
  if (version !== WIRE_VERSION) throw new Error(`unsupported binary version ${version}`);
  if (kind === KIND_SPECTRUM) return { kind: 'spectrum', msg: decodeSpectrum(v) };
  if (kind === KIND_FLIGHT) return decodeFlight(v);
  throw new Error(`unknown binary kind ${kind}`);
}

function decodeSpectrum(v: DataView): SpectrumMsg {
  if (v.byteLength < SPECTRUM_HEADER) throw new Error('spectrum header too short');
  const channel = CHANNELS[v.getUint8(2)];
  if (!channel) throw new Error('bad spectrum channel');
  const flags = v.getUint8(3);
  const bins = v.getUint16(8, true);
  if (v.byteLength !== SPECTRUM_HEADER + 2 * bins) throw new Error('spectrum length mismatch');
  const t = v.getFloat64(12, true);
  const db10 = new Int16Array(bins);
  for (let k = 0; k < bins; k++) db10[k] = v.getInt16(SPECTRUM_HEADER + 2 * k, true);
  const injection = INJECTIONS[v.getUint8(48)];
  const rf_reference = flags & FLAG_RF_REFERENCE && injection
    ? { lo_hz: v.getFloat64(40, true), injection, inferred: !!(flags & FLAG_RF_INFERRED) }
    : null;
  return {
    type: 'spectrum', channel, row: v.getUint32(4, true), t_us: Math.round(t * 1e6),
    f0_hz: v.getFloat64(20, true), bin_hz: v.getFloat32(28, true), bins, db10,
    low: v.getFloat32(32, true), high: v.getFloat32(36, true), synthetic: !!(flags & FLAG_SYNTHETIC), rf_reference,
  };
}

function decodeFlight(v: DataView): Decoded {
  if (v.byteLength < FLIGHT_HEADER) throw new Error('flight header too short');
  const origin = ORIGINS[v.getUint8(2)];
  if (!origin) throw new Error('bad flight origin');
  const fieldCount = v.getUint16(4, true);
  const n = v.getUint16(6, true);
  const size = 10 + 4 * fieldCount;
  if (v.byteLength !== FLIGHT_HEADER + n * size) throw new Error('flight length mismatch');
  const rows: FlightRows = { t: new Float64Array(n), flags: new Uint8Array(n), values: new Float32Array(n * fieldCount), n };
  for (let i = 0; i < n; i++) {
    const o = FLIGHT_HEADER + i * size;
    rows.t[i] = v.getFloat64(o, true);
    rows.flags[i] = v.getUint8(o + 8);
    for (let k = 0; k < fieldCount; k++) rows.values[i * fieldCount + k] = v.getFloat32(o + 10 + 4 * k, true);
  }
  return { kind: 'flight', origin, fieldCount, rows };
}

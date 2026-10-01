/** Pure helpers behind the value cards (Number, State, GPS, Health). */
import type { SeriesStore } from '../series';
import type { FlightSchema } from '../types';

export type Level = 'good' | 'warn' | 'bad';

export function fieldIndex(schema: FlightSchema | null, key: string): number {
  return schema ? schema.fields.findIndex((f) => f.key === key) : -1;
}

/** The level of the highest threshold whose `above` is <= the value, or null below all of them. */
export function thresholdLevel(si: number, thresholds: { above: number; level: Level }[]): Level | null {
  if (!Number.isFinite(si)) return null;
  let best: { above: number; level: Level } | null = null;
  for (const t of thresholds) if (si >= t.above && (!best || t.above > best.above)) best = t;
  return best ? best.level : null;
}

export class MinMax {
  min: number | null = null;
  max: number | null = null;
  push(v: number): void {
    if (!Number.isFinite(v)) return;
    if (this.min === null || v < this.min) this.min = v;
    if (this.max === null || v > this.max) this.max = v;
  }
  reset(): void {
    this.min = null;
    this.max = null;
  }
}

/** Seconds from the first row of the current phase to the latest row, found by scanning back. Null if unknown. */
export function timeInPhase(store: SeriesStore, phaseIdx: number): number | null {
  const n = store.length;
  if (n === 0 || phaseIdx < 0) return null;
  const phase = store.valueAt(n - 1, phaseIdx);
  if (!Number.isFinite(phase)) return null;
  let first = n - 1;
  while (first > 0 && store.valueAt(first - 1, phaseIdx) === phase) first--;
  return store.timeAt(n - 1) - store.timeAt(first);
}

/** One entry per named bit, in bit order, for a bit-field value. */
export function decodeBits(value: number, bits: Record<string, string>): { name: string; on: boolean }[] {
  const v = Number.isFinite(value) ? Math.trunc(value) : 0;
  return Object.keys(bits)
    .map(Number)
    .filter((b) => Number.isInteger(b) && b >= 0 && b < 31)
    .sort((a, b) => a - b)
    .map((b) => ({ name: bits[String(b)], on: ((v >> b) & 1) === 1 }));
}

export function gpsFixLabel(schema: FlightSchema | null, v: number): string {
  const map = schema?.fields.find((f) => f.key === 'gps_fix')?.enum_map;
  const label = Number.isFinite(v) ? map?.[String(Math.trunc(v))] : undefined;
  return label ?? `UNKNOWN (${Number.isFinite(v) ? Math.trunc(v) : '?'})`;
}

/** Seconds since the newest sample when that exceeds the limit; null when fresh (or no data). */
export function staleAge(latestT: number | null, nowS: number, limitS: number): number | null {
  if (latestT === null) return null;
  const age = nowS - latestT;
  return age > limitS ? age : null;
}

/** Badge for SYNTHETIC-flagged data: replay of the demo ROM, otherwise simulated. */
export function badgeFor(latestFlags: number | null, profileId: string): 'REPLAY' | 'SIMULATED' | null {
  if (latestFlags === null || !(latestFlags & 1)) return null;
  return profileId === 'apex_demo' ? 'REPLAY' : 'SIMULATED';
}

/** The "no FLIGHT frames" hint: after 5 s with no flight rows while other frames still arrive (spec 12). */
export function noFlightNotice(o: { flightRows: number; otherFramesPerS: number; waitedS: number }): string | null {
  return o.flightRows === 0 && o.otherFramesPerS > 0 && o.waitedS >= 5 ? 'No FLIGHT frames from this source' : null;
}

/** Badge text and tooltip (spec section 12); the demo replay is labelled as such. */
export function badgeLabel(badge: 'REPLAY' | 'SIMULATED'): { text: string; title: string } {
  return badge === 'REPLAY'
    ? { text: 'REPLAY · SIMULATED ADC', title: 'Replayed IREC 2026 flight through the real receiver; the ADC input is simulated' }
    : { text: 'SIMULATED', title: 'Simulated data, not a measurement' };
}

export const staleText = (age: number): string => `stale ${age.toFixed(1)} s`;

/** Frames per second arriving on any channel, ignoring negative or non-finite rates. */
export function otherFramesPerS(rates: Record<string, number> | null | undefined): number {
  let sum = 0;
  for (const r of Object.values(rates ?? {})) if (Number.isFinite(r) && r > 0) sum += r;
  return sum;
}

export function flightKey(source: unknown): 'best' | 'A' | 'B' {
  return source === 'A' || source === 'B' ? source : 'best';
}

export function sourceLabel(source: unknown): string {
  return source === 'both' ? 'A and B' : source === 'A' || source === 'B' ? `channel ${source}` : 'best';
}

export function formatMmSs(s: number): string {
  const t = Math.max(0, Math.floor(s));
  return `${Math.floor(t / 60).toString().padStart(2, '0')}:${(t % 60).toString().padStart(2, '0')}`;
}

/** Colour level for a fix the schema names; unknown enum values get none. */
export function gpsFixLevel(schema: FlightSchema | null, v: number): Level | null {
  const map = schema?.fields.find((f) => f.key === 'gps_fix')?.enum_map;
  if (!map || !Number.isFinite(v) || !(String(Math.trunc(v)) in map)) return null;
  return v >= 3 ? 'good' : v >= 1 ? 'warn' : 'bad';
}

export interface MinMaxCursor { t: number; seq: number }
export const newCursor = (): MinMaxCursor => ({ t: -Infinity, seq: -Infinity });

/**
 * Feed every row newer than the cursor to `mm`. Time or seq going backwards (a flight reset) resets `mm` and
 * rescans the whole store.
 */
export function pushNewRows(store: SeriesStore, field: number, seqField: number, mm: MinMax, cursor: MinMaxCursor): void {
  const n = store.length;
  if (n === 0 || field < 0) return;
  const lastT = store.timeAt(n - 1);
  const lastSeq = seqField >= 0 ? store.valueAt(n - 1, seqField) : NaN;
  if (lastT < cursor.t || (Number.isFinite(lastSeq) && lastSeq < cursor.seq)) {
    mm.reset();
    cursor.t = -Infinity;
    cursor.seq = -Infinity;
  }
  let first = n;
  while (first > 0 && store.timeAt(first - 1) > cursor.t) first--;
  for (let i = first; i < n; i++) mm.push(store.valueAt(i, field));
  cursor.t = lastT;
  if (Number.isFinite(lastSeq)) cursor.seq = lastSeq;
}

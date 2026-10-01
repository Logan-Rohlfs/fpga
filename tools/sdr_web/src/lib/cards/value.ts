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

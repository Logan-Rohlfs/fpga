/** "Current segment" filtering shared by the Plot, Map and 3D trajectory cards (spec section 7). A flight segment starts at the newest flight_reset. */
import type { GuiEvent } from '../types';

export type Segment = 'current' | 'all';

/** Server-clock time of the newest flight_reset in `events`, or null when there is none. */
export function latestSegmentStart(events: readonly GuiEvent[]): number | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].category === 'flight' && events[i].kind === 'flight_reset') return events[i].t;
  }
  return null;
}

/** Earliest row time to show: -Infinity for `all` (or when no segment has started), else the segment start. */
export function segmentFloor(segment: unknown, start: number | null): number {
  return segment === 'all' || start === null ? -Infinity : start;
}

/** Index of the first row with t >= floor (rows are oldest first); `length` when none. 0 for an infinite-negative floor. */
export function firstRowFrom(store: { length: number; timeAt(i: number): number }, floor: number): number {
  if (floor === -Infinity) return 0;
  let lo = 0;
  let hi = store.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (store.timeAt(mid) < floor) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Start a [t0, t1] view no earlier than `floor`. A floor at or after the end (clock skew) is ignored. */
export function clampToSegment(range: [number, number], floor: number): [number, number] {
  return floor > range[0] && floor < range[1] ? [floor, range[1]] : range;
}

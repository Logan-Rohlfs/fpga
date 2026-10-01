/** Event-log filtering and formatting. Derivation is server-side (sdr_cli/events.py); keep these lists in step. */
import type { GuiEvent } from './types';
import { type UnitPrefs, format, unitFor, unitLabel } from './units';

export const FLIGHT_CATEGORY_KINDS = ['phase', 'launch', 'burnout', 'apogee', 'max_velocity', 'landing', 'flight_reset'] as const;
export const LINK_KINDS = ['signal_loss', 'reacquire', 'crc_burst', 'source_switch', 'source_state'] as const;
export const ALL_EVENT_KINDS = [...FLIGHT_CATEGORY_KINDS, ...LINK_KINDS] as const;

/** Category first, then kinds (null = every kind). Input is oldest-first; the result is a new array. */
export function filterEvents(
  items: readonly GuiEvent[], category: 'flight' | 'link', kinds: Set<string> | null, newestFirst: boolean,
): GuiEvent[] {
  const out = items.filter(e => e.category === category && (kinds === null || kinds.has(e.kind)));
  return newestFirst ? out.reverse() : out;
}

/** Server-clock time of the newest flight_reset that followed LANDED (the start of the current display
 * segment), or null. A reset from BOOST/COAST/DESCENT is a reboot mid-flight and must not hide the track. */
export function latestSegmentStart(items: readonly GuiEvent[]): number | null {
  for (let i = items.length - 1; i >= 0; i--) if (items[i].category === 'flight' && items[i].kind === 'flight_reset' && items[i].prev_phase === 'LANDED') return items[i].t;
  return null;
}

export function lastLaunch(items: readonly GuiEvent[]): number | null {
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'launch') return items[i].t;
  return null;
}

function clock(t: number): string {
  const tenths = Math.floor(Math.max(0, t) * 10);
  const s = Math.floor(tenths / 10) % 60;
  const m = Math.floor(tenths / 600) % 60;
  const h = Math.floor(tenths / 36000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${h}:${pad(m)}:${pad(s)}.${tenths % 10}`;
}

export function formatEvent(
  e: GuiEvent, prefs: UnitPrefs, launchT: number | null,
): { time: string; tplus: string | null; text: string; value: string | null } {
  let tplus: string | null = null;
  if (launchT !== null) {
    const dt = e.t - launchT;
    tplus = `T${dt < 0 ? '-' : '+'}${Math.abs(dt).toFixed(1)} s`;
  }
  let value: string | null = null;
  if (e.value !== null) {
    const q = e.quantity ?? '';
    const unit = q ? unitFor(q, undefined, prefs) : null;
    const label = unitLabel(q, unit);
    value = format(e.value, q, unit, Math.abs(e.value) >= 100 ? 0 : 1) + (label ? ` ${label}` : '');
  }
  return { time: clock(e.t), tplus, text: e.text, value };
}

/**
 * Card header labelling (spec section 12), one mechanism for every card: a card reports what it shows through
 * `cardStatus()`, and CardFrame turns that into header chips with `headerChips()`.
 */
import { getContext, setContext } from 'svelte';
import { type Writable, writable } from 'svelte/store';
import type { FlightSchema, ReceiverProfile, SourceState } from '../types';
import { staleText } from './value';

export interface CardStatus {
  /** The newest row or record the card shows has the SYNTHETIC flag. */
  synthetic: boolean;
  /** The card shows flight data (FLIGHT rows, flight events or frames carrying them). */
  flight: boolean;
  /** Seconds the newest shown data is past its stale limit, or null when fresh or absent. */
  age: number | null;
  /** Flight-schema keys the card displays (for the emulated-field chip). */
  fields?: string[];
}
export interface Chip { text: string; title: string }
export interface HeaderChips { badge: Chip | null; emulated: Chip | null; stale: string | null }

const SIM_BADGE = 'SIM FLIGHT · SIMULATED ADC';
const SIM_BOARD = 'RocketPy simulation of the IREC 2026 competition flight (Pecos TX) through the real receiver; the ADC input is simulated';
const SIM_HOST = 'RocketPy simulation of the IREC 2026 competition flight (Pecos TX) replayed by the host demo source (no FPGA); signal metrics are modelled';

/** Header chips for a card status under the current source. */
export function headerChips(status: CardStatus | null, source: SourceState | undefined, schema: FlightSchema | null): HeaderChips {
  const none: HeaderChips = { badge: null, emulated: null, stale: null };
  if (!status) return none;
  const profile: ReceiverProfile | undefined = source?.profile;
  const replay = status.synthetic && status.flight && profile?.id === 'apex_demo';
  let badge: Chip | null = null;
  if (replay) {
    const base = source?.kind === 'demo' ? (profile?.badge_title_host ?? SIM_HOST) : (profile?.badge_title ?? SIM_BOARD);
    badge = { text: profile?.badge ?? SIM_BADGE, title: [base, profile?.replay_note].filter(Boolean).join('. ') };
  } else if (status.synthetic) {
    badge = { text: 'SIMULATED', title: 'Simulated data, not a measurement' };
  }
  let emulated: Chip | null = null;
  const shown = (status.fields ?? []).filter((k) => profile?.emulated_fields?.includes(k));
  if (replay && shown.length) {
    const label = (k: string) => schema?.fields.find((f) => f.key === k)?.label ?? k;
    emulated = {
      text: 'EMULATED',
      title: `${profile?.emulated_note ?? 'Emulated fields'} Emulated here: ${shown.map(label).join(', ')}.`,
    };
  }
  return { badge, emulated, stale: status.age === null ? null : staleText(status.age) };
}

/** The same fields in the same order, so an unchanged report causes no re-render. */
export function sameStatus(a: CardStatus | null, b: CardStatus | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  const fa = a.fields ?? [];
  const fb = b.fields ?? [];
  return a.synthetic === b.synthetic && a.flight === b.flight && a.age === b.age
    && fa.length === fb.length && fa.every((k, i) => k === fb[i]);
}

const KEY = Symbol('card-status');

/** CardFrame: create the store its card reports into. */
export function provideCardStatus(): Writable<CardStatus | null> {
  const store = writable<CardStatus | null>(null);
  setContext(KEY, store);
  return store;
}

/** A card: the reporter for its frame's header (a no-op outside a CardFrame). Call during component init. */
export function cardStatus(): (s: CardStatus | null) => void {
  const store = getContext<Writable<CardStatus | null> | undefined>(KEY);
  let last: CardStatus | null = null;
  return (s) => {
    if (!store || sameStatus(last, s)) return;
    last = s;
    store.set(s);
  };
}

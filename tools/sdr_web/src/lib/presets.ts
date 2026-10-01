/** Preset selection, follow-the-operator and working-copy logic (spec section 6). Pure helpers plus two persisted stores. */
import { type Writable, get, writable } from 'svelte/store';
import { minOfType, sanitizeConfig } from './cards/registry';
import { type GridCard, sanitizeGrid } from './grid';
import type { PresetItem, PresetsMsg } from './types';

export type Trigger = Record<string, unknown>;
export interface Preset {
  schema: 1; id: string; name: string; revision: number; grid: { cols: 24 }; cards: GridCard[]; triggers: Trigger[];
}

const FOLLOW_KEY = 'sdr.presets.follow';
const CHOSEN_KEY = 'sdr.presets.chosen';

/** A per-device preference: storage that is missing or throws never breaks the store, it just does not persist. */
function persisted<T>(key: string, fallback: T, parse: (raw: string) => T | undefined, show: (v: T) => string | null): Writable<T> {
  let initial = fallback;
  try {
    const raw = localStorage.getItem(key);
    if (raw !== null) initial = parse(raw) ?? fallback;
  } catch { /* no storage */ }
  const store = writable<T>(initial);
  const out: Writable<T> = {
    set(v) {
      store.set(v);
      try {
        const text = show(v);
        if (text === null) localStorage.removeItem(key);
        else localStorage.setItem(key, text);
      } catch { /* per-device convenience only */ }
    },
    update(fn) { out.set(fn(get(store))); },
    subscribe: store.subscribe,
  };
  return out;
}

export const followStore = persisted<boolean>(FOLLOW_KEY, true, (r) => (r === 'false' ? false : r === 'true' ? true : undefined),
  (v) => String(v));
export const chosenStore = persisted<string | null>(CHOSEN_KEY, null, (r) => (r ? r : undefined), (v) => v);

/** Pick a preset by hand. That ends following the operator. */
export function choose(id: string): void {
  chosenStore.set(id);
  followStore.set(false);
}

/** Server item -> sanitized preset. Cards are untrusted until sanitizeGrid and sanitizeConfig. */
export function toPreset(item: PresetItem): Preset {
  return {
    schema: 1, id: item.id, name: item.name, revision: item.revision, grid: { cols: 24 },
    cards: sanitizeGrid(item.cards, minOfType).map((c) => ({ ...c, config: sanitizeConfig(c.type, c.config) })),
    triggers: Array.isArray(item.triggers) ? (JSON.parse(JSON.stringify(item.triggers)) as Trigger[]) : [],
  };
}

/** Follow shows the live preset. A chosen id that no longer exists falls back to live, then to the default. */
export function displayedPreset(msg: PresetsMsg | null, follow: boolean, chosenId: string | null): Preset | null {
  if (!msg) return null;
  const find = (id: string | null) => (id === null ? undefined : msg.items.find((p) => p.id === id));
  const item = (follow ? undefined : find(chosenId)) ?? find(msg.live) ?? find(msg.default);
  return item ? toPreset(item) : null;
}

export function makeWorkingCopy(p: Preset): Preset {
  return JSON.parse(JSON.stringify(p)) as Preset;
}

function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o).sort().filter((k) => o[k] !== undefined).map((k) => `${JSON.stringify(k)}:${canonical(o[k])}`).join(',')}}`;
  }
  return JSON.stringify(v) ?? 'null';
}

/** True when the working copy differs from the saved one. Key order and revision do not count. */
export function isDirty(working: Preset, saved: Preset | null): boolean {
  if (!saved) return true;
  const body = (p: Preset) => canonical({ id: p.id, name: p.name, grid: p.grid, cards: p.cards, triggers: p.triggers });
  return body(working) !== body(saved);
}

export type Stale = 'changed' | 'deleted' | null;
export interface EditStatus { saved: Preset | null; builtin: boolean; dirty: boolean; stale: Stale }

/** How a working copy relates to the server's current copy of the same preset. */
export function editStatus(working: Preset | null, msg: PresetsMsg | null): EditStatus {
  const item = working && msg ? msg.items.find((p) => p.id === working.id) : undefined;
  const saved = item ? toPreset(item) : null;
  if (!working) return { saved, builtin: !!item?.builtin, dirty: false, stale: null };
  const dirty = isDirty(working, saved);
  const stale: Stale = !dirty ? null : !saved ? 'deleted' : saved.revision !== working.revision ? 'changed' : null;
  return { saved, builtin: !!item?.builtin, dirty, stale };
}

/** Drop a working copy once the server's copy matches it (its own save landed). Otherwise keep it. */
export function settleWorking(working: Preset | null, msg: PresetsMsg | null): Preset | null {
  if (!working || !msg) return working;
  const { saved, dirty } = editStatus(working, msg);
  return saved && !dirty ? null : working;
}

export function slugify(name: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '');
  return slug || 'preset';
}

/** `base`, or `base-2`, `base-3`... the first id not in `taken`, still within 40 characters. */
export function uniqueId(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) {
    const suffix = `-${n}`;
    const id = base.slice(0, 40 - suffix.length).replace(/-+$/, '') + suffix;
    if (!used.has(id)) return id;
  }
}

/** The body sent with preset_save. The server assigns the revision, so it is left out. */
export function toWire(p: Preset, name: string = p.name, id: string = p.id): Omit<Preset, 'revision'> {
  return { schema: 1, id, name, grid: { cols: 24 }, cards: p.cards, triggers: p.triggers };
}

/** What the server holds for `id`: whether it exists, whether it is builtin, and whether Delete may be offered. */
export function serverState(msg: PresetsMsg | null, id: string | null): { saved: boolean; builtin: boolean; canDelete: boolean } {
  const item = msg && id ? msg.items.find((p) => p.id === id) : undefined;
  return { saved: !!item, builtin: !!item?.builtin, canDelete: !!item && !item.builtin && msg!.default !== id };
}

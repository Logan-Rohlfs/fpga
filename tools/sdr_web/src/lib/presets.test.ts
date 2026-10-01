import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { PresetItem, PresetsMsg } from './types';

const item = (id: string, over: Partial<PresetItem> = {}): PresetItem => ({
  schema: 1, id, name: id, revision: 1, builtin: false, grid: { cols: 24 }, triggers: [],
  cards: [{ id: 'n1', type: 'number', x: 0, y: 0, w: 3, h: 2, title: null, config: {} }], ...over,
});
const msg = (live = 'a', items = [item('a'), item('b'), item('flight', { builtin: true })]): PresetsMsg =>
  ({ type: 'presets', items, live, default: 'flight', auto_switch: false });

const clearStorage = () => { delete (globalThis as { localStorage?: unknown }).localStorage; };
beforeEach(() => { clearStorage(); vi.resetModules(); });
afterEach(clearStorage);
const load = () => import('./presets');

describe('displayedPreset', () => {
  it('follow shows live', async () => {
    const { displayedPreset } = await load();
    expect(displayedPreset(msg('a'), true, 'b')?.id).toBe('a');
  });
  it('follow off shows the chosen id', async () => {
    const { displayedPreset } = await load();
    expect(displayedPreset(msg('a'), false, 'b')?.id).toBe('b');
  });
  it('a deleted chosen id falls back to live, then default', async () => {
    const { displayedPreset } = await load();
    expect(displayedPreset(msg('a'), false, 'gone')?.id).toBe('a');
    expect(displayedPreset(msg('gone'), false, 'gone')?.id).toBe('flight');
    expect(displayedPreset(msg('a'), false, null)?.id).toBe('a');
  });
  it('null message gives null', async () => {
    const { displayedPreset } = await load();
    expect(displayedPreset(null, true, null)).toBeNull();
  });
});

describe('stores', () => {
  it('choose turns follow off', async () => {
    const { choose, followStore, chosenStore } = await load();
    expect(get(followStore)).toBe(true);
    choose('b');
    expect(get(followStore)).toBe(false);
    expect(get(chosenStore)).toBe('b');
  });
  it('work when localStorage throws', async () => {
    const boom = () => { throw new Error('denied'); };
    (globalThis as { localStorage?: unknown }).localStorage = { getItem: boom, setItem: boom, removeItem: boom };
    const { choose, followStore, chosenStore } = await load();
    expect(get(followStore)).toBe(true);
    expect(() => choose('b')).not.toThrow();
    expect(get(followStore)).toBe(false);
    expect(get(chosenStore)).toBe('b');
  });
  it('persists and restores through localStorage', async () => {
    const m = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k),
    };
    const first = await load();
    first.choose('b');
    expect(m.get('sdr.presets.follow')).toBe('false');
    vi.resetModules();
    const second = await load();
    expect(get(second.followStore)).toBe(false);
    expect(get(second.chosenStore)).toBe('b');
  });
});

describe('working copy', () => {
  it('isDirty sees a moved card and ignores key order and revision', async () => {
    const { toPreset, makeWorkingCopy, isDirty } = await load();
    const saved = toPreset(item('a'));
    const w = makeWorkingCopy(saved);
    expect(isDirty(w, saved)).toBe(false);
    const reordered = { ...w, revision: 9, cards: w.cards.map((c) => Object.fromEntries(Object.entries(c).reverse())) } as typeof w;
    expect(isDirty(reordered, saved)).toBe(false);
    w.cards[0].x = 4;
    expect(isDirty(w, saved)).toBe(true);
    expect(isDirty(w, null)).toBe(true);
  });
  it('editStatus reports a revision change under unsaved edits and a deletion', async () => {
    const { toPreset, makeWorkingCopy, editStatus } = await load();
    const w = makeWorkingCopy(toPreset(item('a')));
    w.cards[0].x = 4;
    expect(editStatus(w, msg('a')).stale).toBeNull();
    expect(editStatus(w, msg('a', [item('a', { revision: 2 })])).stale).toBe('changed');
    expect(editStatus(w, msg('a', [item('b')])).stale).toBe('deleted');
    expect(editStatus(w, msg('a')).builtin).toBe(false);
  });
  it('settleWorking drops the copy once the server matches it, keeps it otherwise', async () => {
    const { toPreset, makeWorkingCopy, settleWorking } = await load();
    const w = makeWorkingCopy(toPreset(item('a')));
    w.cards[0].x = 4;
    expect(settleWorking(w, msg('a'))).toBe(w);
    const landed = item('a', { revision: 2, cards: [{ id: 'n1', type: 'number', x: 4, y: 0, w: 3, h: 2, title: null, config: {} }] });
    expect(settleWorking(w, msg('a', [landed]))).toBeNull();
  });
});

describe('ids', () => {
  it('slugify matches the server id pattern', async () => {
    const { slugify } = await load();
    expect(slugify('Pad Camera #2')).toBe('pad-camera-2');
    expect(slugify('!!!')).toBe('preset');
    const long = slugify('x'.repeat(80));
    expect(long).toMatch(/^[a-z0-9][a-z0-9-]{0,39}$/);
    expect(long.length).toBe(40);
  });
  it('uniqueId avoids taken ids within 40 characters', async () => {
    const { uniqueId } = await load();
    expect(uniqueId('pad', ['flight'])).toBe('pad');
    expect(uniqueId('pad', ['pad', 'pad-2'])).toBe('pad-3');
    const base = 'x'.repeat(40);
    const id = uniqueId(base, [base]);
    expect(id.length).toBeLessThanOrEqual(40);
    expect(id).not.toBe(base);
  });
});

describe('toWire', () => {
  it('omits the revision and applies a new id and name', async () => {
    const { toPreset, toWire } = await load();
    const w = toWire(toPreset(item('a', { revision: 4 })), 'Copy', 'copy');
    expect(w).not.toHaveProperty('revision');
    expect(w).toMatchObject({ schema: 1, id: 'copy', name: 'Copy', grid: { cols: 24 } });
  });
});

describe('serverState', () => {
  it('works with no working copy, for builtin, default and plain presets', async () => {
    const { serverState } = await load();
    const m = msg('a');
    expect(serverState(m, 'a')).toEqual({ saved: true, builtin: false, canDelete: true });
    expect(serverState(m, 'flight')).toEqual({ saved: true, builtin: true, canDelete: false });
    expect(serverState(m, 'gone')).toEqual({ saved: false, builtin: false, canDelete: false });
    expect(serverState(null, 'a').canDelete).toBe(false);
    expect(serverState({ ...m, default: 'a' }, 'a').canDelete).toBe(false);
  });
});

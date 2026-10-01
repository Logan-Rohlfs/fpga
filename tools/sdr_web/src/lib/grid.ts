/** 12-column card grid model (spec section 8). Pure functions: every one returns new arrays and never mutates its input. */
export interface GridCard {
  id: string; type: string; x: number; y: number; w: number; h: number; title: string | null; config: Record<string, unknown>;
}

export const COLS = 12;
export const ROW_PX = 40;
export const GAP_PX = 8;
export const MAX_Y = 500;
export const MAX_H = 24;
export const DESKTOP_MIN_PX = 1100;
export const TABLET_MIN_PX = 600;

export interface MinSize { w: number; h: number; phoneMinH?: number }
export type MinOf = (type: string) => MinSize;
export type Mode = 'desktop' | 'tablet' | 'phone';

export function collides(a: GridCard, b: GridCard): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

const byYX = (a: GridCard, b: GridCard) => a.y - b.y || a.x - b.x;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function readingOrder(cards: readonly GridCard[]): GridCard[] {
  return cards.map((c) => ({ ...c })).sort(byYX);
}

/** Place a card below whatever it overlaps in `placed`, moving it down only. */
function pushDown(c: GridCard, placed: readonly GridCard[]): GridCard {
  const out = { ...c };
  for (let hit = placed.find((p) => collides(out, p)); hit; hit = placed.find((p) => collides(out, p))) {
    out.y = hit.y + hit.h;
  }
  return out;
}

/** Place cards in reading order, each pushed below any card already placed. Cards keep their input order. */
function resolve(cards: readonly GridCard[], fixed: readonly GridCard[] = [], gravity = false): GridCard[] {
  const placed: GridCard[] = [...fixed];
  const result = new Map<string, GridCard>();
  const order = cards.map((c, i) => ({ c, i })).sort((a, b) => byYX(a.c, b.c) || a.i - b.i);
  for (const { c } of order) {
    let next = pushDown(c, placed);
    if (gravity) {
      while (next.y > 0 && !placed.some((p) => collides({ ...next, y: next.y - 1 }, p))) next = { ...next, y: next.y - 1 };
    }
    placed.push(next);
    result.set(next.id, next);
  }
  return cards.map((c) => result.get(c.id)!);
}

/** Vertical gravity: each card, in (y, x) order, moves up while it does not collide. */
export function compact(cards: readonly GridCard[]): GridCard[] {
  return resolve(cards, [], true);
}

function settle(cards: readonly GridCard[], moved: GridCard): GridCard[] {
  const others = cards.filter((c) => c.id !== moved.id);
  const placed = resolve(others, [moved]);
  const all = cards.map((c) => (c.id === moved.id ? moved : placed.find((p) => p.id === c.id)!));
  return compact(all);
}

export function moveCard(cards: readonly GridCard[], id: string, x: number, y: number): GridCard[] {
  const card = cards.find((c) => c.id === id);
  if (!card) return cards.map((c) => ({ ...c }));
  const moved = { ...card, x: clamp(Math.round(x), 0, COLS - card.w), y: clamp(Math.round(y), 0, MAX_Y) };
  return settle(cards, moved);
}

export function resizeCard(
  cards: readonly GridCard[], id: string, w: number, h: number, minW: number, minH: number,
): GridCard[] {
  const card = cards.find((c) => c.id === id);
  if (!card) return cards.map((c) => ({ ...c }));
  const nw = clamp(Math.round(w), Math.min(minW, COLS), COLS);
  const nh = clamp(Math.round(h), minH, Math.max(minH, MAX_H));
  const resized = { ...card, w: nw, h: nh, x: Math.min(card.x, COLS - nw) };
  return settle(cards, resized);
}

/** Add a card at the first free row, leftmost; the size is raised to the minimum. */
export function addCard(cards: readonly GridCard[], card: GridCard, minW: number, minH: number): GridCard[] {
  const w = clamp(Math.round(card.w), Math.min(minW, COLS), COLS);
  const h = clamp(Math.round(card.h), minH, Math.max(minH, MAX_H));
  const base = cards.map((c) => ({ ...c }));
  for (let y = 0; ; y++) {
    for (let x = 0; x + w <= COLS; x++) {
      const placed = { ...card, x, y, w, h };
      if (!base.some((c) => collides(placed, c))) return [...base, placed];
    }
  }
}

export function removeCard(cards: readonly GridCard[], id: string): GridCard[] {
  return cards.filter((c) => c.id !== id).map((c) => ({ ...c }));
}

/** An id like `plot-3` that is unique among `cards` and fits the server's card id pattern. */
export function newCardId(cards: readonly GridCard[], type: string): string {
  const taken = new Set(cards.map((c) => c.id));
  const stem = type.replace(/[^a-z0-9-]/g, '').slice(0, 18) || 'card';
  for (let n = 1; ; n++) {
    const id = `${stem}-${n}`;
    if (!taken.has(id)) return id;
  }
}

/** Narrow-screen layouts (spec section 8): 6 columns by first-fit packing, or one column in reading order. */
export function reflow(cards: readonly GridCard[], cols: 6 | 1, minOf: MinOf): GridCard[] {
  const ordered = readingOrder(cards);
  if (cols === 1) {
    let y = 0;
    return ordered.map((c) => {
      const min = minOf(c.type);
      const h = Math.max(c.h, min.phoneMinH ?? min.h);
      const out = { ...c, x: 0, y, w: 1, h };
      y += h;
      return out;
    });
  }
  const placed: GridCard[] = [];
  for (const c of ordered) {
    const w = Math.min(6, Math.max(c.w >= 7 ? 6 : 3, Math.ceil(minOf(c.type).w / 2)));
    search: for (let y = 0; ; y++) {
      for (let x = 0; x + w <= 6; x++) {
        const trial = { ...c, x, y, w };
        if (!placed.some((p) => collides(trial, p))) {
          placed.push(trial);
          break search;
        }
      }
    }
  }
  return placed;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const intOr = (v: unknown, fallback: number) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : fallback);

/**
 * Repair a preset's cards for display: drop entries without a string type, fix ids, round and clamp every size,
 * and push overlaps down. A valid authored layout (gaps included) comes back unchanged. Unknown types are kept.
 */
export function sanitizeGrid(cards: unknown, minOf: MinOf): GridCard[] {
  if (!Array.isArray(cards)) return [];
  const used = new Set<string>();
  const kept: GridCard[] = [];
  for (const raw of cards) {
    if (!isObj(raw) || typeof raw.type !== 'string') continue;
    const min = minOf(raw.type);
    const w = clamp(intOr(raw.w, min.w), Math.min(min.w, COLS), COLS);
    const h = clamp(intOr(raw.h, min.h), min.h, Math.max(min.h, MAX_H));
    const title = typeof raw.title === 'string' && raw.title.length >= 1 && raw.title.length <= 40 ? raw.title : null;
    kept.push({
      id: typeof raw.id === 'string' && raw.id ? raw.id : '',
      type: raw.type,
      x: clamp(intOr(raw.x, 0), 0, COLS - w),
      y: clamp(intOr(raw.y, 0), 0, MAX_Y),
      w, h, title,
      config: isObj(raw.config) ? raw.config : {},
    });
  }
  for (const c of kept) {
    if (c.id && !used.has(c.id)) used.add(c.id);
    else c.id = '';
  }
  for (const c of kept) {
    if (c.id) continue;
    c.id = newCardId(kept.filter((k) => k.id), c.type);
    used.add(c.id);
  }
  return resolve(kept);
}

export function modeForWidth(px: number): Mode {
  if (px >= DESKTOP_MIN_PX) return 'desktop';
  return px >= TABLET_MIN_PX ? 'tablet' : 'phone';
}

/** Width of one column in a container of `containerPx` pixels. */
export function colWidth(containerPx: number, cols: number = COLS): number {
  return (containerPx - GAP_PX * (cols - 1)) / cols;
}

/** Pixel drag delta to whole grid cells: `Math.round(dx / (colW + GAP_PX))`. */
export function pxToGrid(dxPx: number, dyPx: number, colW: number): { dx: number; dy: number } {
  return { dx: Math.round(dxPx / (colW + GAP_PX)), dy: Math.round(dyPx / (ROW_PX + GAP_PX)) };
}

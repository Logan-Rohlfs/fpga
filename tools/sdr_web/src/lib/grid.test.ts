import { describe, expect, it } from 'vitest';
import {
  COLS, GAP_PX, ROW_PX, type GridCard, addCard, collides, colWidth, compact, modeForWidth, moveCard, newCardId,
  pxToGrid, readingOrder, reflow, removeCard, resizeCard, sanitizeGrid,
} from './grid';

const card = (id: string, x: number, y: number, w: number, h: number, type = 'number'): GridCard =>
  ({ id, type, x, y, w, h, title: null, config: {} });
const minOf = (type: string) => (type === 'plot' ? { w: 3, h: 4, phoneMinH: 6 } : { w: 2, h: 2, phoneMinH: 3 });

function assertNoOverlap(cards: GridCard[]) {
  for (let i = 0; i < cards.length; i++) {
    for (let j = i + 1; j < cards.length; j++) {
      expect(collides(cards[i], cards[j]), `${cards[i].id} overlaps ${cards[j].id}`).toBe(false);
    }
    expect(cards[i].x).toBeGreaterThanOrEqual(0);
    expect(cards[i].x + cards[i].w).toBeLessThanOrEqual(COLS);
    expect(cards[i].y).toBeGreaterThanOrEqual(0);
  }
}
const byId = (cards: GridCard[], id: string) => cards.find((c) => c.id === id)!;

describe('grid model', () => {
  it('detects collisions', () => {
    expect(collides(card('a', 0, 0, 3, 3), card('b', 2, 2, 3, 3))).toBe(true);
    expect(collides(card('a', 0, 0, 3, 3), card('b', 3, 0, 3, 3))).toBe(false);
    expect(collides(card('a', 0, 0, 3, 3), card('b', 0, 3, 3, 3))).toBe(false);
  });

  it('compact lifts a floating card to y = 0 and keeps input order', () => {
    const out = compact([card('a', 0, 5, 3, 2), card('b', 4, 9, 3, 2), card('c', 0, 12, 3, 2)]);
    expect(out.map((c) => c.id)).toEqual(['a', 'b', 'c']);
    expect(byId(out, 'a').y).toBe(0);
    expect(byId(out, 'b').y).toBe(0);
    expect(byId(out, 'c').y).toBe(2);
  });

  it('does not mutate its input', () => {
    const input = [card('a', 0, 5, 3, 2)];
    compact(input);
    expect(input[0].y).toBe(5);
  });

  it('moveCard onto an occupied cell pushes the other card down without overlaps', () => {
    const start = [card('a', 0, 0, 4, 3), card('b', 4, 0, 4, 3), card('c', 0, 3, 4, 3)];
    const out = moveCard(start, 'b', 0, 0);
    assertNoOverlap(out);
    expect(byId(out, 'b')).toMatchObject({ x: 0, y: 0 });
    expect(byId(out, 'a').y).toBeGreaterThanOrEqual(3);
    expect(byId(out, 'c').y).toBeGreaterThan(byId(out, 'a').y - 1);
  });

  it('moveCard clamps to the grid', () => {
    const out = moveCard([card('a', 0, 0, 4, 3)], 'a', 99, -5);
    expect(byId(out, 'a')).toMatchObject({ x: COLS - 4, y: 0 });
  });

  it('moveCard of an unknown id returns the cards unchanged', () => {
    const start = [card('a', 0, 0, 4, 3)];
    expect(moveCard(start, 'zzz', 3, 3)).toEqual(start);
  });

  it('resizeCard clamps to the minimum and to the grid edge', () => {
    const start = [card('a', 10, 0, 2, 2)];
    const big = resizeCard(start, 'a', 8, 5, 2, 2);
    expect(byId(big, 'a').x + byId(big, 'a').w).toBeLessThanOrEqual(COLS);
    expect(byId(big, 'a').w).toBe(8);
    const small = resizeCard(start, 'a', 0, 0, 2, 2);
    expect(byId(small, 'a')).toMatchObject({ w: 2, h: 2 });
    assertNoOverlap(big);
  });

  it('resizeCard pushes neighbours down', () => {
    const start = [card('a', 0, 0, 3, 2), card('b', 0, 2, 3, 2)];
    const out = resizeCard(start, 'a', 3, 5, 2, 2);
    assertNoOverlap(out);
    expect(byId(out, 'b').y).toBe(5);
  });

  it('addCard uses the first free row, leftmost', () => {
    const start = [card('a', 0, 0, 12, 3), card('b', 12, 0, 12, 2)];
    const out = addCard(start, card('c', 0, 0, 4, 2), 2, 2);
    expect(byId(out, 'c')).toMatchObject({ x: 12, y: 2 });
    assertNoOverlap(out);
    const next = addCard(out, card('d', 0, 0, 24, 2), 2, 2);
    expect(byId(next, 'd')).toMatchObject({ x: 0, y: 4 });
    assertNoOverlap(next);
  });

  it('addCard enforces the minimum size', () => {
    const out = addCard([], card('c', 0, 0, 1, 1), 3, 4);
    expect(out[0]).toMatchObject({ x: 0, y: 0, w: 3, h: 4 });
  });

  it('removeCard drops one card and keeps the rest', () => {
    const out = removeCard([card('a', 0, 0, 3, 3), card('b', 3, 0, 3, 3)], 'a');
    expect(out.map((c) => c.id)).toEqual(['b']);
  });

  it('readingOrder sorts by y then x', () => {
    const out = readingOrder([card('c', 0, 3, 3, 3), card('b', 6, 0, 3, 3), card('a', 0, 0, 3, 3)]);
    expect(out.map((c) => c.id)).toEqual(['a', 'b', 'c']);
  });

  it('newCardId yields a unique valid id', () => {
    const id = newCardId([card('plot-1', 0, 0, 3, 3), card('plot-2', 3, 0, 3, 3)], 'plot');
    expect(id).toBe('plot-3');
    expect(newCardId([], 'trajectory3d')).toMatch(/^[a-z0-9-]{1,24}$/);
  });
});

describe('responsive reflow', () => {
  const authored = [card('a', 0, 0, 16, 3), card('b', 16, 0, 8, 3), card('c', 0, 3, 4, 2)];

  it('maps 24 -> 12 columns: w 16 -> 12 and w 8 -> 6, heights unchanged, no overlaps', () => {
    const out = reflow(authored, 12, minOf);
    expect(byId(out, 'a').w).toBe(12);
    expect(byId(out, 'b').w).toBe(6);
    expect(byId(out, 'a').h).toBe(3);
    assertNoOverlap(out);
    for (const c of out) expect(c.x + c.w).toBeLessThanOrEqual(12);
  });

  it('respects ceil(minW / 2) when narrowing', () => {
    const wide = (type: string) => ({ w: 16, h: 2, phoneMinH: 3 });
    const out = reflow([card('a', 0, 0, 8, 3)], 12, wide);
    expect(out[0].w).toBe(8);
  });

  it('packs first-fit in reading order', () => {
    const out = reflow([card('a', 0, 0, 6, 4), card('b', 6, 0, 6, 2), card('c', 12, 0, 6, 2)], 12, minOf);
    expect(byId(out, 'a')).toMatchObject({ x: 0, y: 0 });
    expect(byId(out, 'b')).toMatchObject({ x: 6, y: 0 });
    expect(byId(out, 'c')).toMatchObject({ x: 6, y: 2 });
  });

  it('single column orders by (y, x) and respects phoneMinH', () => {
    const out = reflow([card('c', 0, 6, 4, 1), card('b', 6, 0, 3, 3), card('a', 0, 0, 3, 2, 'plot')], 1, minOf);
    expect(out.map((c) => c.id)).toEqual(['a', 'b', 'c']);
    expect(out.every((c) => c.x === 0 && c.w === 1)).toBe(true);
    expect(byId(out, 'a').h).toBe(6);
    expect(byId(out, 'c').h).toBe(3);
    expect(out.map((c) => c.y)).toEqual([0, 6, 9]);
  });

  it('modeForWidth follows the spec breakpoints', () => {
    expect(modeForWidth(1100)).toBe('desktop');
    expect(modeForWidth(1099)).toBe('tablet');
    expect(modeForWidth(600)).toBe('tablet');
    expect(modeForWidth(599)).toBe('phone');
  });
});

describe('pixel conversion', () => {
  it('computes the column width from the container', () => {
    expect(colWidth(24 * 100 + 23 * GAP_PX)).toBe(100);
  });
  it('rounds pixel deltas to whole cells', () => {
    const cw = 100;
    expect(pxToGrid(cw + GAP_PX, ROW_PX + GAP_PX, cw)).toEqual({ dx: 1, dy: 1 });
    expect(pxToGrid(0.49 * (cw + GAP_PX), 0.51 * (ROW_PX + GAP_PX), cw)).toEqual({ dx: 0, dy: 1 });
    expect(pxToGrid(-(cw + GAP_PX) * 2.2, -5, cw)).toEqual({ dx: -2, dy: -0 });
  });
});

describe('sanitizeGrid', () => {
  it('returns [] for a non-array', () => {
    expect(sanitizeGrid('nope', minOf)).toEqual([]);
    expect(sanitizeGrid(null, minOf)).toEqual([]);
  });

  it('repairs overlaps, bounds, fractions, missing and duplicate ids and keeps unknown types', () => {
    const out = sanitizeGrid([
      { id: 'a', type: 'number', x: 0, y: 0, w: 4, h: 3, title: null, config: {} },
      { id: 'b', type: 'number', x: 2, y: 1, w: 4, h: 3, title: 'B', config: { k: 1 } },
      { id: 'c', type: 'plot', x: 11, y: 0, w: 4, h: 4, title: null, config: {} },
      { id: 'd', type: 'from-the-future', x: 0.4, y: 2.6, w: 2.5, h: 2.5, title: '', config: 5 },
      { type: 'number', x: 0, y: 0, w: 2, h: 2 },
      { id: 'a', type: 'number', x: 0, y: 0, w: 2, h: 2 },
      { id: 'e', type: 7 },
      'junk',
      null,
    ] as unknown, minOf);
    assertNoOverlap(out);
    expect(out.length).toBe(6);
    expect(new Set(out.map((c) => c.id)).size).toBe(out.length);
    for (const c of out) {
      expect(Number.isInteger(c.x) && Number.isInteger(c.y) && Number.isInteger(c.w) && Number.isInteger(c.h)).toBe(true);
      expect(c.w).toBeGreaterThanOrEqual(minOf(c.type).w);
      expect(c.h).toBeGreaterThanOrEqual(minOf(c.type).h);
      expect(typeof c.config).toBe('object');
      expect(c.title === null || typeof c.title === 'string').toBe(true);
    }
    expect(out.some((c) => c.type === 'from-the-future')).toBe(true);
    expect(byId(out, 'c').x + byId(out, 'c').w).toBeLessThanOrEqual(COLS);
    expect(byId(out, 'b').title).toBe('B');
    expect(byId(out, 'b').config).toEqual({ k: 1 });
  });

  it('leaves a valid authored layout alone, including gaps', () => {
    const valid = [card('a', 0, 0, 3, 3), card('b', 6, 5, 3, 3)];
    expect(sanitizeGrid(valid, minOf)).toEqual(valid);
  });
});

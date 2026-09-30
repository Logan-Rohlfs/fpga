/** Fixed-row-height list windowing. */
export interface WindowRange { start: number; end: number; padTop: number; padBottom: number }

export function windowRange(scrollTop: number, viewportH: number, rowH: number, count: number, overscan = 8): WindowRange {
  if (count <= 0 || rowH <= 0) return { start: 0, end: 0, padTop: 0, padBottom: 0 };
  const top = Math.max(0, scrollTop);
  const first = Math.floor(top / rowH);
  const last = Math.ceil((top + Math.max(0, viewportH)) / rowH);
  const end = Math.min(count, last + overscan);
  const start = Math.min(end, Math.max(0, first - overscan));
  return { start, end, padTop: start * rowH, padBottom: (count - end) * rowH };
}

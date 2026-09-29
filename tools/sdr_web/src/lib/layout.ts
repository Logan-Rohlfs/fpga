/** Telemetry card layout: order + span per card, saved per device. */
export interface CardLayout { id: string; w: number; h: number }

export const MAX_W = 4;
export const MAX_H = 4;

const clampInt = (v: unknown, lo: number, hi: number, fallback: number) =>
  typeof v === 'number' && Number.isFinite(v) ? Math.min(hi, Math.max(lo, Math.round(v))) : fallback;

export function sanitize(saved: unknown, defaults: CardLayout[]): CardLayout[] {
  const byId = new Map(defaults.map((d) => [d.id, d]));
  const seen = new Set<string>();
  const out: CardLayout[] = [];
  if (Array.isArray(saved)) {
    for (const item of saved as Partial<CardLayout>[]) {
      const d = item && typeof item.id === 'string' ? byId.get(item.id) : undefined;
      if (!d || seen.has(d.id)) continue;
      seen.add(d.id);
      out.push({ id: d.id, w: clampInt(item.w, 1, MAX_W, d.w), h: clampInt(item.h, 1, MAX_H, d.h) });
    }
  }
  for (const d of defaults) if (!seen.has(d.id)) out.push({ ...d });
  return out;
}

export function move(layout: CardLayout[], id: string, targetId: string, after: boolean): CardLayout[] {
  if (id === targetId) return layout;
  const card = layout.find((c) => c.id === id);
  const rest = layout.filter((c) => c.id !== id);
  const i = rest.findIndex((c) => c.id === targetId);
  if (!card || i < 0) return layout;
  rest.splice(after ? i + 1 : i, 0, card);
  return rest;
}

export function resize(layout: CardLayout[], id: string, w: number, h: number, cols: number): CardLayout[] {
  return layout.map((c) =>
    c.id === id ? { id, w: clampInt(w, 1, Math.min(MAX_W, cols), c.w), h: clampInt(h, 1, MAX_H, c.h) } : c,
  );
}

export function loadLayout(key: string, defaults: CardLayout[]): CardLayout[] {
  try {
    return sanitize(JSON.parse(localStorage.getItem(key) ?? 'null'), defaults);
  } catch {
    return sanitize(null, defaults);
  }
}

export function saveLayout(key: string, layout: CardLayout[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(layout));
  } catch {
    /* per-device convenience only */
  }
}

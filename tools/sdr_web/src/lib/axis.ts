/** Frequency ↔ pixel mapping shared by every spectrum drawing. */
export interface Axis { f0: number; f1: number; left: number; right: number; width: number }

export const PAD = { left: 44, right: 10 };

export const makeAxis = (f0: number, f1: number, width: number): Axis => ({ f0, f1, left: PAD.left, right: PAD.right, width });
export const xOf = (a: Axis, f: number) => a.left + ((f - a.f0) / (a.f1 - a.f0)) * (a.width - a.left - a.right);
export const fOf = (a: Axis, x: number) => a.f0 + ((x - a.left) / (a.width - a.left - a.right)) * (a.f1 - a.f0);

export function ticks(f0: number, f1: number, step: number): number[] {
  const out: number[] = [];
  for (let k = Math.ceil(f0 / step - 1e-9); k * step <= f1 + 1e-6; k++) out.push(k * step);
  return out;
}

/** Display-only mapping; authoritative LO/IF values come from the server's `derived`. */
export const ifToRf = (loHz: number, injection: 'low' | 'high', ifHz: number) =>
  injection === 'low' ? loHz + ifHz : loHz - ifHz;

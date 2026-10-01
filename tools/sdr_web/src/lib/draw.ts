/** Canvas drawing shared by the waterfall, frequency plan, constellation and sparklines. */
import { type Axis, ticks, xOf } from './axis';

export interface Overlay {
  band?: [number, number]; at?: number; colorVar: string; alpha?: number;
  label?: string; labelBottom?: boolean; dash?: number[]; width?: number; onFall?: boolean;
}

const MONO = '11px "JetBrains Mono", ui-monospace, monospace';
const LABEL = '600 11px "Jost", system-ui, sans-serif';

export const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** '#rrggbb' + alpha → '#rrggbbaa'. */
export function withAlpha(color: string, a: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return color;
  return color + Math.round(Math.min(1, Math.max(0, a)) * 255).toString(16).padStart(2, '0');
}

export function fitCanvas(cv: HTMLCanvasElement): { ctx: CanvasRenderingContext2D; w: number; h: number } {
  const r = window.devicePixelRatio || 1;
  const w = cv.clientWidth;
  const h = cv.clientHeight;
  const W = Math.max(1, Math.round(w * r));
  const H = Math.max(1, Math.round(h * r));
  if (cv.width !== W || cv.height !== H) {
    cv.width = W;
    cv.height = H;
  }
  const ctx = cv.getContext('2d')!;
  ctx.setTransform(r, 0, 0, r, 0, 0);
  return { ctx, w, h };
}

export function drawDbGrid(ctx: CanvasRenderingContext2D, a: Axis, top: number, bot: number, low: number, high: number) {
  const y = (v: number) => bot - ((v - low) / (high - low)) * (bot - top);
  ctx.font = MONO;
  ctx.textAlign = 'right';
  ctx.lineWidth = 1;
  for (let v = Math.ceil(low / 10) * 10; v <= high; v += 10) {
    const yy = Math.round(y(v)) + 0.5;
    ctx.strokeStyle = cssVar('--line');
    ctx.beginPath();
    ctx.moveTo(a.left, yy);
    ctx.lineTo(a.width - a.right, yy);
    ctx.stroke();
    ctx.fillStyle = cssVar('--faint');
    ctx.fillText(String(v), a.left - 6, yy + 4);
  }
}

export function drawBands(ctx: CanvasRenderingContext2D, a: Axis, top: number, bot: number, overlays: Overlay[]) {
  for (const o of overlays) {
    if (!o.band) continue;
    ctx.fillStyle = withAlpha(cssVar(o.colorVar), o.alpha ?? 0.12);
    const x0 = xOf(a, o.band[0]);
    ctx.fillRect(x0, top, xOf(a, o.band[1]) - x0, bot - top);
  }
}

export function drawLines(ctx: CanvasRenderingContext2D, a: Axis, top: number, bot: number, overlays: Overlay[], labels = true) {
  ctx.font = LABEL;
  for (const o of overlays) {
    if (o.at === undefined) continue;
    const x = Math.round(xOf(a, o.at)) + 0.5;
    const color = cssVar(o.colorVar);
    ctx.strokeStyle = color;
    ctx.lineWidth = o.width ?? 1;
    ctx.setLineDash(o.dash ?? []);
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bot);
    ctx.stroke();
    ctx.setLineDash([]);
    if (labels && o.label) {
      const right = x > a.width - 90;
      ctx.fillStyle = color;
      ctx.textAlign = right ? 'right' : 'left';
      ctx.fillText(o.label.toUpperCase(), x + (right ? -4 : 4), o.labelBottom ? bot - 5 : top + 11);
    }
  }
}

export function drawFreqTicks(
  ctx: CanvasRenderingContext2D, a: Axis, y: number, step: number, fmt: (f: number) => string, unit: string,
) {
  ctx.font = MONO;
  ctx.fillStyle = cssVar('--muted');
  ctx.textAlign = 'center';
  for (const f of ticks(a.f0, a.f1, step)) ctx.fillText(fmt(f), xOf(a, f), y);
  ctx.textAlign = 'left';
  ctx.fillStyle = cssVar('--faint');
  ctx.fillText(unit, 4, y);
}

export interface TraceRow { f0_hz: number; bin_hz: number; db10: ArrayLike<number> }

/** Spectrum trace with area fill. `toX` maps an IF frequency to a pixel x. */
export function drawTrace(
  ctx: CanvasRenderingContext2D, top: number, bot: number, row: TraceRow, low: number, high: number,
  colorVar: string, toX: (f: number) => number,
) {
  const y = (db10: number) => bot - ((Math.min(high, Math.max(low, db10 / 10)) - low) / (high - low)) * (bot - top);
  const x = (k: number) => toX(row.f0_hz + k * row.bin_hz);
  const color = cssVar(colorVar);
  ctx.beginPath();
  ctx.moveTo(x(0), bot);
  for (let k = 0; k < row.db10.length; k++) ctx.lineTo(x(k), y(row.db10[k]));
  ctx.lineTo(x(row.db10.length - 1), bot);
  ctx.closePath();
  ctx.fillStyle = withAlpha(color, 0.15);
  ctx.fill();
  ctx.beginPath();
  for (let k = 0; k < row.db10.length; k++) {
    if (k) ctx.lineTo(x(k), y(row.db10[k]));
    else ctx.moveTo(x(k), y(row.db10[k]));
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

export function hatch(ctx: CanvasRenderingContext2D, x0: number, x1: number, top: number, bot: number, color: string) {
  x0 = Math.max(0, x0);
  x1 = Math.min(ctx.canvas.width, x1);
  if (x1 <= x0) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(x0, top, x1 - x0, bot - top);
  ctx.clip();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  for (let x = x0 - (bot - top); x < x1; x += 7) {
    ctx.beginPath();
    ctx.moveTo(x, bot);
    ctx.lineTo(x + (bot - top), top);
    ctx.stroke();
  }
  ctx.restore();
}

/** I/Q scatter: newest snapshot solid, older ones faded (full scale ±32767). */
export function drawConstellation(ctx: CanvasRenderingContext2D, size: number, snaps: [number, number][][], colorVar: string) {
  const c = size / 2;
  const R = size * 0.42;
  const color = cssVar(colorVar);
  ctx.clearRect(0, 0, size, size);
  ctx.strokeStyle = cssVar('--line');
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(c, 4); ctx.lineTo(c, size - 4); ctx.moveTo(4, c); ctx.lineTo(size - 4, c);
  ctx.stroke();
  ctx.setLineDash([2, 4]);
  ctx.beginPath();
  ctx.arc(c, c, R, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  snaps.forEach((snap, j) => {
    ctx.fillStyle = withAlpha(color, j === snaps.length - 1 ? 0.95 : 0.3);
    for (const [i, q] of snap) {
      ctx.beginPath();
      ctx.arc(c + (i / 32767) * R, c - (q / 32767) * R, 2.2, 0, Math.PI * 2);
      ctx.fill();
    }
  });
  ctx.fillStyle = cssVar('--faint');
  ctx.font = MONO;
  ctx.textAlign = 'left';
  ctx.fillText('I', size - 10, c - 4);
  ctx.fillText('Q', c + 4, 12);
}

/** History line with area fill and an emphasized latest point. The y range covers at least `floor`. */
export function drawSparkline(
  ctx: CanvasRenderingContext2D, w: number, h: number, values: readonly number[], colorVar: string,
  floor: [number, number], capacity: number,
) {
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = cssVar('--line');
  ctx.beginPath();
  ctx.moveTo(0, h - 0.5);
  ctx.lineTo(w, h - 0.5);
  ctx.stroke();
  if (values.length < 2) return;
  const lo = Math.min(floor[0], ...values);
  const hi = Math.max(floor[1], ...values);
  const off = capacity - values.length;
  const x = (i: number) => ((i + off) / (capacity - 1)) * (w - 8);
  const y = (v: number) => h - 3 - ((v - lo) / (hi - lo)) * (h - 8);
  const color = cssVar(colorVar);
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.lineTo(x(values.length - 1), h);
  ctx.lineTo(x(0), h);
  ctx.closePath();
  ctx.fillStyle = withAlpha(color, 0.14);
  ctx.fill();
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
  const ex = x(values.length - 1);
  const ey = y(values[values.length - 1]);
  ctx.fillStyle = cssVar('--panel');
  ctx.beginPath(); ctx.arc(ex, ey, 5, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.arc(ex, ey, 3.5, 0, Math.PI * 2); ctx.fill();
}

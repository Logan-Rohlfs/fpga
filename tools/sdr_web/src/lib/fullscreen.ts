/** Telemetry full-screen mode: page chrome hidden, cards stretched to fill the screen. Per viewer, never sent to the server. */
import { writable } from 'svelte/store';

export const fullscreen = writable(false);

const DEFAULT_ROW_PX = 16;

/**
 * Row height that makes a layout of `rows` grid rows fill `availPx` (gaps of `gapPx` between rows), clamped to
 * [minPx, maxPx]. Short layouts stretch; a tall one squeezes only to the minimum (about 80 % of the normal 48 px pitch,
 * so card contents are not clipped) and then scrolls.
 */
export function fitRowPx(availPx: number, rows: number, gapPx: number, minPx = 12, maxPx = 80): number {
  if (rows <= 0) return DEFAULT_ROW_PX;
  const px = Math.floor((availPx - gapPx * (rows - 1)) / rows);
  return Math.min(maxPx, Math.max(minPx, Number.isFinite(px) ? px : minPx));
}

/** Enter full-screen mode, and the browser's own full screen where it is allowed (not every phone browser has it). */
export function enterFullscreen(): void {
  fullscreen.set(true);
  if (typeof document === 'undefined') return;
  const el = document.documentElement;
  if (document.fullscreenEnabled && !document.fullscreenElement && el.requestFullscreen) {
    el.requestFullscreen({ navigationUI: 'hide' }).catch(() => { /* chrome-hiding still works without it */ });
  }
}

export function exitFullscreen(): void {
  fullscreen.set(false);
  if (typeof document !== 'undefined' && document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

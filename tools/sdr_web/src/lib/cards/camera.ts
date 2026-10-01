/** Camera card helpers (spec section 15): URL screening and the empty, error and ok states. */

export const CAMERA_URL_MAX = 500;

/** True for an http or https URL of at most 500 characters. Anything else is never put in a src. */
export function cameraUrlOk(url: unknown): url is string {
  if (typeof url !== 'string' || url.length === 0 || url.length > CAMERA_URL_MAX) return false;
  try {
    const p = new URL(url).protocol;
    return p === 'http:' || p === 'https:';
  } catch {
    return false;
  }
}

export type CameraState = 'empty' | 'error' | 'ok';

export function cameraState(url: unknown, errored: boolean): CameraState {
  if (!cameraUrlOk(url)) return 'empty';
  return errored ? 'error' : 'ok';
}

// ---- demo mode: a local clip from the server's .sdr/media, synced to the LAUNCH event (not a live camera)

export const DEMO_MEDIA = 'l3_flight_onboard.mp4';
/** Liftoff in DEMO_MEDIA: the motor plume first shows at 9.0 s into the file (igniter flicker at 8.4 s). */
export const DEMO_LAUNCH_OFFSET_S = 9;
export const LAUNCH_OFFSET_MAX_S = 600;
/** Before launch the clip holds this far ahead of liftoff, on the pad. */
export const PAD_LEAD_S = 1;
/** Playback this far from the target time is re-seeked; smaller drift is left alone to avoid stutter. */
export const DRIFT_S = 0.5;

const MEDIA_NAME_MAX = 100;
const MEDIA_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:mp4|m4v|webm)$/i;

/** A plain clip file name, as sdr_cli/media.py name_ok accepts. */
export function mediaNameOk(name: unknown): name is string {
  return typeof name === 'string' && name.length <= MEDIA_NAME_MAX && MEDIA_NAME_RE.test(name);
}

export function mediaUrl(name: string): string {
  return `/media/${encodeURIComponent(name)}`;
}

export type DemoPhase = 'pad' | 'flight' | 'ended';
export interface DemoPlayback { phase: DemoPhase; time: number; tPlus: number | null }

/**
 * Where the clip should be at server time `now`. The newest of LAUNCH and flight_reset decides: after a
 * launch the clip plays from `offset` plus the time since it; after a reset (or before any launch) it holds
 * the pad frame, so the clip loops with each replayed flight. `duration` is null until the metadata loads.
 */
export function demoPlayback(
  events: readonly { kind: string; t: number }[], now: number, offset: number, duration: number | null,
): DemoPlayback {
  const end = duration === null ? Infinity : Math.max(0, duration - 0.05);
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.kind === 'flight_reset') break;
    if (e.kind === 'launch') {
      const tPlus = Math.max(0, now - e.t);
      const time = offset + tPlus;
      return time >= end ? { phase: 'ended', time: end, tPlus } : { phase: 'flight', time, tPlus };
    }
  }
  return { phase: 'pad', time: Math.min(end, Math.max(0, offset - PAD_LEAD_S)), tPlus: null };
}

export function needsSeek(current: number, target: number): boolean {
  return Math.abs(current - target) > DRIFT_S;
}

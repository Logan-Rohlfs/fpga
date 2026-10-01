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

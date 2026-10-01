import { describe, expect, it } from 'vitest';
import { cameraState, cameraUrlOk } from './camera';

describe('cameraUrlOk', () => {
  it('accepts http and https', () => {
    expect(cameraUrlOk('http://10.0.0.5:8081/stream')).toBe(true);
    expect(cameraUrlOk('https://cam.example/live.mjpg')).toBe(true);
  });
  it('rejects other schemes, junk and non-strings', () => {
    for (const u of ['javascript:alert(1)', 'file:///etc/passwd', 'ftp://10.0.0.5/x', 'data:text/html,x', 'nope', '', null, undefined, 5]) {
      expect(cameraUrlOk(u)).toBe(false);
    }
  });
  it('limits length to 500 characters', () => {
    const base = 'http://a.example/';
    expect(cameraUrlOk(base + 'x'.repeat(500 - base.length))).toBe(true);
    expect(cameraUrlOk(base + 'x'.repeat(501 - base.length))).toBe(false);
  });
});

describe('cameraState', () => {
  it('is empty without a usable url, even when errored', () => {
    expect(cameraState(null, false)).toBe('empty');
    expect(cameraState('ftp://x/y', true)).toBe('empty');
  });
  it('is error when a valid url failed, else ok', () => {
    expect(cameraState('http://x/y', true)).toBe('error');
    expect(cameraState('http://x/y', false)).toBe('ok');
  });
});

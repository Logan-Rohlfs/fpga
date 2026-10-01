import { describe, expect, it } from 'vitest';
import { DRIFT_S, PAD_LEAD_S, cameraState, cameraUrlOk, demoPlayback, mediaNameOk, mediaUrl, needsSeek } from './camera';

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

describe('mediaNameOk and mediaUrl', () => {
  it('accepts plain clip names with a video extension, as sdr_cli/media.py does', () => {
    for (const n of ['clip.mp4', 'Riding_on_a_Sounding_Rocket.webm', 'a-b.c.m4v', 'X.MP4', 'a'.repeat(96) + '.mp4']) {
      expect(mediaNameOk(n)).toBe(true);
    }
    for (const n of ['', '.mp4', '../x.mp4', 'a/b.mp4', 'clip.mov', 'clip', 'cl ip.mp4', 'é.mp4', 'a'.repeat(97) + '.mp4', null, 5]) {
      expect(mediaNameOk(n)).toBe(false);
    }
  });
  it('builds a same-origin path', () => {
    expect(mediaUrl('clip.mp4')).toBe('/media/clip.mp4');
  });
});

describe('demoPlayback', () => {
  const ev = (kind: string, t: number) => ({ kind, t });
  const OFF = 9;

  it('holds the pad frame before any launch', () => {
    expect(demoPlayback([], 1000, OFF, 270)).toEqual({ phase: 'pad', time: OFF - PAD_LEAD_S, tPlus: null });
    expect(demoPlayback([ev('phase', 990)], 1000, OFF, null).phase).toBe('pad');
  });

  it('plays from the offset plus the time since LAUNCH', () => {
    const p = demoPlayback([ev('phase', 99), ev('launch', 100), ev('burnout', 104)], 112.5, OFF, 270);
    expect(p.phase).toBe('flight');
    expect(p.time).toBeCloseTo(OFF + 12.5);
    expect(p.tPlus).toBeCloseTo(12.5);
  });

  it('returns to the pad frame after a flight reset, and replays on the next launch', () => {
    const loop = [ev('launch', 100), ev('landing', 165), ev('flight_reset', 168)];
    expect(demoPlayback(loop, 169, OFF, 270).phase).toBe('pad');
    const next = demoPlayback([...loop, ev('launch', 172)], 175, OFF, 270);
    expect(next.phase).toBe('flight');
    expect(next.time).toBeCloseTo(OFF + 3);
  });

  it('holds the last frame once the clip runs out', () => {
    const p = demoPlayback([ev('launch', 0)], 500, OFF, 270);
    expect(p.phase).toBe('ended');
    expect(p.time).toBeLessThan(270);
    expect(p.tPlus).toBeCloseTo(500);
  });

  it('clamps clock skew and a pad lead before the start of the clip', () => {
    expect(demoPlayback([ev('launch', 100)], 99, OFF, 270).time).toBeCloseTo(OFF);
    expect(demoPlayback([], 0, 0.5, 270).time).toBe(0);
  });
});

describe('needsSeek', () => {
  it('seeks only past the drift tolerance', () => {
    expect(needsSeek(10, 10 + DRIFT_S / 2)).toBe(false);
    expect(needsSeek(10, 10 + DRIFT_S * 2)).toBe(true);
    expect(needsSeek(10, 10 - DRIFT_S * 2)).toBe(true);
  });
});

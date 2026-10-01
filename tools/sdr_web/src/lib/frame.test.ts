import { describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { bindFrozen, createScheduler } from './frame';

function setup() {
  const queue: (() => void)[] = [];
  const s = createScheduler(cb => { queue.push(cb); });
  const frame = () => { const q = queue.splice(0); q.forEach(cb => cb()); };
  return { s, queue, frame };
}

describe('scheduler', () => {
  it('draws only when dirty and visible', () => {
    const { s, frame } = setup();
    let n = 0;
    s.register('a', () => n++);
    frame(); expect(n).toBe(0);
    s.markDirty('a'); frame(); expect(n).toBe(1);
    frame(); expect(n).toBe(1);
  });
  it('a hidden card stays dirty until visible', () => {
    const { s, frame } = setup();
    let n = 0;
    s.register('a', () => n++);
    s.setVisible('a', false);
    s.markDirty('a'); frame(); expect(n).toBe(0);
    s.setVisible('a', true); frame(); expect(n).toBe(1);
  });
  it('coalesces markDirty into one draw and one raf', () => {
    const { s, queue, frame } = setup();
    let n = 0;
    s.register('a', () => n++);
    s.markDirty('a'); s.markDirty('a'); s.markDirty('a');
    expect(queue.length).toBe(1);
    frame(); expect(n).toBe(1);
  });
  it('frozen suppresses draws and unfreezing draws pending ones', () => {
    const { s, frame } = setup();
    let n = 0;
    s.register('a', () => n++);
    s.setFrozen(true);
    s.markDirty('a'); frame(); expect(n).toBe(0);
    s.setFrozen(false); frame(); expect(n).toBe(1);
  });
  it('ignores unregistered ids and unregistered draws', () => {
    const { s, frame } = setup();
    let n = 0;
    expect(() => { s.markDirty('x'); s.setVisible('x', true); }).not.toThrow();
    const off = s.register('a', () => n++);
    off();
    s.markDirty('a'); frame(); expect(n).toBe(0);
  });
  it('flush runs dirty visible draws once without raf', () => {
    const { s } = setup();
    let n = 0;
    s.register('a', () => n++);
    s.markDirty('a'); s.flush(); s.flush();
    expect(n).toBe(1);
  });
  it('a draw that marks itself dirty redraws next frame, not recursively', () => {
    const { s, frame } = setup();
    let n = 0;
    s.register('a', () => { if (n++ < 1) s.markDirty('a'); });
    s.markDirty('a'); frame(); expect(n).toBe(1);
    frame(); expect(n).toBe(2);
  });
  it('the default scheduler is usable without rAF (node)', async () => {
    const mod = await import('./frame');
    expect(typeof mod.scheduler.markDirty).toBe('function');
  });
  it('a throwing draw does not stop the other cards', () => {
    const { s, frame } = setup();
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    let n = 0;
    s.register('bad', () => { throw new Error('boom'); });
    s.register('good', () => n++);
    s.markDirty('bad'); s.markDirty('good'); frame();
    expect(n).toBe(1);
    expect(err).toHaveBeenCalled();
    err.mockRestore();
    s.markDirty('good'); frame(); expect(n).toBe(2);
  });
});

describe('bindFrozen', () => {
  it('follows the freeze store and resumes pending draws on unfreeze', () => {
    const { s, frame } = setup();
    const frozen = writable(false);
    const off = bindFrozen(frozen, s);
    let n = 0;
    s.register('a', () => n++);
    frozen.set(true);
    s.markDirty('a'); frame(); expect(n).toBe(0);
    frozen.set(false); frame(); expect(n).toBe(1);
    off();
    frozen.set(true);
    s.markDirty('a'); frame(); expect(n).toBe(2);   // unbound: the store no longer drives the scheduler
  });
});

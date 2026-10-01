/** One requestAnimationFrame loop for every canvas card: a draw runs only when dirty, visible and not frozen. */
type Raf = (cb: () => void) => unknown;
interface Entry { draw: () => void; dirty: boolean; visible: boolean }

export interface Scheduler {
  register(id: string, draw: () => void): () => void;
  markDirty(id: string): void;
  setVisible(id: string, visible: boolean): void;
  setFrozen(frozen: boolean): void;
  /** Test hook: run every dirty, visible draw once, synchronously. */
  flush(): void;
}

// Looked up at call time so importing this module in node never touches requestAnimationFrame.
const defaultRaf: Raf = cb => {
  if (typeof globalThis.requestAnimationFrame === 'function') globalThis.requestAnimationFrame(() => cb());
  else setTimeout(cb, 16);
};

export function createScheduler(raf: Raf = defaultRaf): Scheduler {
  const entries = new Map<string, Entry>();
  let frozen = false;
  let queued = false;

  function run(): void {
    if (frozen) return;
    for (const e of [...entries.values()]) {
      if (!e.dirty || !e.visible) continue;
      e.dirty = false;
      try {
        e.draw();
      } catch (err) {
        console.error('card draw failed', err);
      }
    }
  }
  function request(): void {
    if (queued || frozen) return;
    queued = true;
    raf(() => {
      queued = false;
      run();
    });
  }
  function pending(): boolean {
    for (const e of entries.values()) if (e.dirty && e.visible) return true;
    return false;
  }

  return {
    register(id, draw) {
      const entry: Entry = { draw, dirty: false, visible: true };
      entries.set(id, entry);
      return () => { if (entries.get(id) === entry) entries.delete(id); };
    },
    markDirty(id) {
      const e = entries.get(id);
      if (!e) return;
      e.dirty = true;
      if (e.visible) request();
    },
    setVisible(id, visible) {
      const e = entries.get(id);
      if (!e) return;
      e.visible = visible;
      if (visible && e.dirty) request();
    },
    setFrozen(v) {
      frozen = v;
      if (!v && pending()) request();
    },
    flush: run,
  };
}

export const scheduler: Scheduler = createScheduler();

/** Drive `sched` from a freeze store (the Space key / Freeze button). Returns the unsubscribe. */
export function bindFrozen(store: { subscribe(fn: (v: boolean) => void): () => void }, sched: Scheduler = scheduler): () => void {
  return store.subscribe((v) => sched.setFrozen(v));
}

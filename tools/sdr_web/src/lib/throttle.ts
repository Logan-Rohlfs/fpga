/** Merge partial updates and send at most one per interval (drag → `tune`). */
export function createCoalescer<T extends object>(send: (merged: T) => void, intervalMs = 33) {
  let pending: T | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let last = -Infinity;
  const flush = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    if (!pending) return;
    const merged = pending;
    pending = null;
    last = Date.now();
    send(merged);
  };
  return {
    push(update: T) {
      pending = { ...(pending ?? {}), ...update } as T;
      if (timer) return;
      const wait = last + intervalMs - Date.now();
      if (wait <= 0) flush();
      else timer = setTimeout(flush, wait);
    },
    flush,
  };
}

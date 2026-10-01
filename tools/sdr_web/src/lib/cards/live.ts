/** Shared plumbing for the value cards: scheduler registration, data-driven redraws and a 500 ms tick for staleness. */
import { scheduler } from '../frame';
import { dataVersion } from '../link';

export function startLive(id: string, draw: () => void): () => void {
  const off = scheduler.register(id, draw);
  const unsub = dataVersion.subscribe(() => scheduler.markDirty(id));
  const tick = setInterval(() => scheduler.markDirty(id), 500);
  return () => { off(); unsub(); clearInterval(tick); };
}

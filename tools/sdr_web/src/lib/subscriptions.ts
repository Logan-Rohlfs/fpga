/** Channels a page needs (spec 11.3). flight and events stay subscribed so their rings stay complete. */
import type { Channel } from './types';

export type Page = 'tune' | 'telemetry';

export function channelsFor(
  page: Page, opts: { tuneChannel: Channel; cardChannels: string[]; hidden: boolean },
): string[] {
  const set = new Set<string>(['flight', 'events']);
  if (page === 'tune') {
    for (const c of [`spectrum.${opts.tuneChannel}`, 'iq.A', 'iq.B', 'link']) set.add(c);
  } else {
    for (const c of opts.cardChannels) set.add(c);
  }
  const out = [...set].filter((c) => !(opts.hidden && (c.startsWith('spectrum.') || c.startsWith('iq.'))));
  return out.sort();
}

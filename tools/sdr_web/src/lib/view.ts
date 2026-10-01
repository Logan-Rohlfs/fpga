/** Per-viewer display preferences (never sent to the server). */
import { writable } from 'svelte/store';
import type { Channel } from './types';

export type ScaleOverride = { mode: 'auto' } | { mode: 'manual'; low: number; high: number };

export const scaleOverride = writable<ScaleOverride>({ mode: 'auto' });
export const tuneChannel = writable<Channel>('A');

/** Channels the displayed Telemetry preset needs (set by the Telemetry page, read by the subscription effect). */
export const telemetryChannels = writable<string[]>([]);

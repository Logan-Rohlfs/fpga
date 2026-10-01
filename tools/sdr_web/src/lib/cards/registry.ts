/** Card type registry (spec sections 6.2 and 7): per-type defaults, config sanitizing, channels and minimum sizes. */
import type { Component } from 'svelte';
import { FLIGHT_CATEGORY_KINDS, LINK_KINDS } from '../events';
import type { GridCard, MinSize } from '../grid';
import { unitOptions } from '../units';

export type SettingKind = 'select' | 'number' | 'bool' | 'text' | 'field' | 'series' | 'units';
export interface SettingField {
  key: string; label: string; kind: SettingKind;
  options?: { value: string | number; label: string }[];
  min?: number; max?: number;
}

export type Config = Record<string, unknown>;

export interface CardMeta {
  type: string;
  title: string;
  min: { w: number; h: number };
  phoneMinH: number;
  defaults: Config;
  settings: SettingField[];
  sanitize(config: unknown): Config;
  channels(config: unknown): string[];
  /** Title for a card with no preset title, when it depends on the config. */
  titleOf?(config: Config): string;
  /** Lazy card component; undefined until the card's own task lands (PlaceholderCard renders instead). */
  component?: () => Promise<{ default: Component<any> }>;
}

const isObj = (v: unknown): v is Config => typeof v === 'object' && v !== null && !Array.isArray(v);
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

type Validator = (value: unknown, fallback: unknown) => unknown;

const oneOf = (options: readonly unknown[]): Validator => (v, d) => (options.includes(v) ? v : d);
const intIn = (lo: number, hi: number): Validator => (v, d) => (typeof v === 'number' && Number.isInteger(v) && v >= lo && v <= hi ? v : d);
const numIn = (lo: number, hi: number): Validator => (v, d) => (finite(v) && v >= lo && v <= hi ? v : d);
const bool: Validator = (v, d) => (typeof v === 'boolean' ? v : d);
const nullableInt = (lo: number, hi: number): Validator => (v, d) => (v === null ? null : intIn(lo, hi)(v, d));
const text = (max: number): Validator => (v, d) => (typeof v === 'string' && v.length >= 1 && v.length <= max ? v : d);
const nullableText = (max: number): Validator => (v, d) => (v === null ? null : text(max)(v, d));
const SOURCES = ['best', 'A', 'B'] as const;

const url: Validator = (v, d) => (typeof v === 'string' && v.length <= 500 && /^https?:\/\/\S+$/i.test(v) ? v : d);

/** Quantity name to unit id, keeping only pairs the catalogue knows. */
const unitsMap: Validator = (v, d) => {
  if (!isObj(v)) return d;
  const out: Record<string, string> = {};
  for (const [q, u] of Object.entries(v)) if (typeof u === 'string' && unitOptions(q).some((o) => o.id === u)) out[q] = u;
  return out;
};

const seriesList: Validator = (v, d) => {
  if (!Array.isArray(v)) return d;
  const out: { field: string; source: string }[] = [];
  for (const item of v) {
    if (isObj(item) && typeof item.field === 'string' && item.field && item.field.length <= 40 && SOURCES.includes(item.source as never)) {
      out.push({ field: item.field, source: item.source as string });
    }
  }
  return out.length ? out.slice(0, 6) : d;
};

const thresholds: Validator = (v, d) => {
  if (!Array.isArray(v)) return d;
  const out: { above: number; level: string }[] = [];
  for (const item of v) {
    if (isObj(item) && finite(item.above) && ['good', 'warn', 'bad'].includes(item.level as string)) {
      out.push({ above: item.above, level: item.level as string });
    }
  }
  return out.slice(0, 8);
};

const autoOr = (lo: string, hi: string): Validator => (v, d) => {
  if (v === 'auto') return 'auto';
  if (isObj(v) && finite(v[lo]) && finite(v[hi]) && (v[lo] as number) < (v[hi] as number)) return { [lo]: v[lo], [hi]: v[hi] };
  return d;
};

const channelSubset: Validator = (v, d) => {
  if (!Array.isArray(v)) return d;
  const picked = (['A', 'B'] as const).filter((c) => v.includes(c));
  return picked.length ? picked : d;
};

interface Spec {
  type: string; title: string; min: { w: number; h: number }; phoneMinH: number;
  defaults: Config; validators?: Record<string, Validator>;
  finish?(out: Config, input: Config): void;
  channels(config: Config): string[];
  settings?: SettingField[];
  titleOf?(config: Config): string;
  component?: CardMeta['component'];
}

function meta(spec: Spec): CardMeta {
  const sanitize = (config: unknown): Config => {
    const input = isObj(config) ? config : {};
    const out: Config = {};
    for (const [key, def] of Object.entries(spec.defaults)) {
      const fallback = clone(def);
      const check = spec.validators?.[key];
      out[key] = check ? check(input[key], fallback) : fallback;
    }
    spec.finish?.(out, input);
    return out;
  };
  return {
    type: spec.type, title: spec.title, min: spec.min, phoneMinH: spec.phoneMinH, defaults: spec.defaults,
    settings: spec.settings ?? [], sanitize, titleOf: spec.titleOf, component: spec.component,
    channels: (config) => [...new Set(spec.channels(sanitize(config)))],
  };
}

const flightChannels = (source: unknown): string[] =>
  source === 'both' ? ['flight.A', 'flight.B'] : [source === 'A' || source === 'B' ? `flight.${source}` : 'flight'];

const sourceField: SettingField = {
  key: 'source', label: 'Source', kind: 'select',
  options: [{ value: 'best', label: 'Best (combined)' }, { value: 'A', label: 'Channel A' }, { value: 'B', label: 'Channel B' }],
};
const channelField = (both = false): SettingField => ({
  key: 'channel', label: 'Channel', kind: 'select',
  options: [{ value: 'A', label: 'A' }, { value: 'B', label: 'B' }, ...(both ? [{ value: 'both', label: 'Both' }] : [])],
});
const siteLayer: SettingField[] = [
  { key: 'site', label: 'Site id', kind: 'text' },
  { key: 'layer', label: 'Layer', kind: 'select', options: [{ value: 'imagery', label: 'Imagery' }, { value: 'topo', label: 'Topo' }] },
];

const specs: Spec[] = [
  {
    type: 'plot', title: 'Plot', min: { w: 3, h: 4 }, phoneMinH: 7,
    defaults: { series: [{ field: 'alt_agl_m', source: 'best' }], window_s: 60, y: 'auto', show_events: true, units: {} },
    validators: { series: seriesList, window_s: oneOf([10, 30, 60, 120, 300, 0]), y: autoOr('min', 'max'), show_events: bool, units: unitsMap },
    channels: (c) => {
      const series = c.series as { field: string; source: string }[];
      const out: string[] = [];
      let link = false;
      for (const s of series) {
        if (s.field.startsWith('m.')) link = true;
        else out.push(...flightChannels(s.source));
      }
      if (c.show_events) out.push('events');
      if (link) out.push('link');
      return out;
    },
    settings: [
      { key: 'series', label: 'Series', kind: 'series' },
      { key: 'window_s', label: 'Window', kind: 'select', options: [
        { value: 10, label: '10 s' }, { value: 30, label: '30 s' }, { value: 60, label: '60 s' }, { value: 120, label: '2 min' },
        { value: 300, label: '5 min' }, { value: 0, label: 'All' }] },
      { key: 'show_events', label: 'Show events', kind: 'bool' },
      { key: 'units', label: 'Units', kind: 'units' },
    ],
    component: () => import('../../cards/PlotCard.svelte'),
  },
  {
    type: 'number', title: 'Value', min: { w: 2, h: 2 }, phoneMinH: 3,
    defaults: { field: 'alt_agl_m', source: 'best', digits: null, thresholds: [], track_minmax: false, units: {} },
    validators: {
      field: text(40), source: oneOf([...SOURCES, 'both']), digits: nullableInt(0, 3), thresholds, track_minmax: bool, units: unitsMap,
    },
    channels: (c) => flightChannels(c.source),
    component: () => import('../../cards/NumberCard.svelte'),
    settings: [
      { key: 'field', label: 'Field', kind: 'field' },
      { ...sourceField, options: [...sourceField.options!, { value: 'both', label: 'A and B' }] },
      { key: 'digits', label: 'Digits (blank = field default)', kind: 'number', min: 0, max: 3 },
      { key: 'track_minmax', label: 'Track min and max', kind: 'bool' },
      { key: 'units', label: 'Units', kind: 'units' },
    ],
  },
  {
    type: 'state', title: 'Flight state', min: { w: 2, h: 2 }, phoneMinH: 3,
    defaults: { source: 'best', show_time_in_phase: true },
    validators: { source: oneOf(SOURCES), show_time_in_phase: bool },
    channels: (c) => flightChannels(c.source),
    component: () => import('../../cards/StateCard.svelte'),
    settings: [sourceField, { key: 'show_time_in_phase', label: 'Show time in phase', kind: 'bool' }],
  },
  {
    type: 'events', title: 'Events', min: { w: 3, h: 4 }, phoneMinH: 6,
    defaults: { category: 'flight', kinds: [...FLIGHT_CATEGORY_KINDS], newest_first: true },
    validators: { category: oneOf(['flight', 'link']), newest_first: bool },
    finish: (out, input) => {
      const all: readonly string[] = out.category === 'link' ? LINK_KINDS : FLIGHT_CATEGORY_KINDS;
      const picked = Array.isArray(input.kinds) ? all.filter((k) => (input.kinds as unknown[]).includes(k)) : [];
      out.kinds = picked.length ? picked : all.slice();
    },
    channels: () => ['events'],
    component: () => import('../../cards/EventsCard.svelte'),
    titleOf: (c) => (c.category === 'link' ? 'Link events' : 'Flight events'),
    settings: [
      { key: 'category', label: 'Category', kind: 'select', options: [{ value: 'flight', label: 'Flight' }, { value: 'link', label: 'Link' }] },
      { key: 'newest_first', label: 'Newest first', kind: 'bool' },
    ],
  },
  {
    type: 'map', title: 'Map', min: { w: 3, h: 5 }, phoneMinH: 7,
    defaults: { site: null, layer: 'imagery', follow: true, show_track: true, source: 'best' },
    validators: { site: nullableText(40), layer: oneOf(['imagery', 'topo']), follow: bool, show_track: bool, source: oneOf(SOURCES) },
    channels: (c) => flightChannels(c.source),
    settings: [...siteLayer, { key: 'follow', label: 'Follow the vehicle', kind: 'bool' },
      { key: 'show_track', label: 'Show track', kind: 'bool' }, sourceField],
  },
  {
    type: 'trajectory3d', title: '3D trajectory', min: { w: 4, h: 6 }, phoneMinH: 8,
    defaults: { site: null, layer: 'imagery', exaggeration: 1, source: 'best' },
    validators: { site: nullableText(40), layer: oneOf(['imagery', 'topo']), exaggeration: intIn(1, 5), source: oneOf(SOURCES) },
    channels: (c) => flightChannels(c.source),
    component: () => import('../../cards/Trajectory3dCard.svelte'),
    settings: [...siteLayer, { key: 'exaggeration', label: 'Vertical exaggeration', kind: 'number', min: 1, max: 5 }, sourceField],
  },
  {
    type: 'camera', title: 'Camera', min: { w: 3, h: 4 }, phoneMinH: 6,
    defaults: { url: null, mode: 'mjpeg', fit: 'contain' },
    validators: { url: (v, d) => (v === null ? null : url(v, d)), mode: oneOf(['mjpeg', 'video']), fit: oneOf(['contain', 'cover']) },
    channels: () => [],
    component: () => import('../../cards/CameraCard.svelte'),
    settings: [
      { key: 'url', label: 'Stream URL (http or https)', kind: 'text' },
      { key: 'mode', label: 'Mode', kind: 'select', options: [{ value: 'mjpeg', label: 'MJPEG' }, { value: 'video', label: 'Video' }] },
      { key: 'fit', label: 'Fit', kind: 'select', options: [{ value: 'contain', label: 'Contain' }, { value: 'cover', label: 'Cover' }] },
    ],
  },
  {
    type: 'waterfall', title: 'Waterfall', min: { w: 3, h: 3 }, phoneMinH: 5,
    defaults: { channel: 'A', scale: 'auto' },
    validators: { channel: oneOf(['A', 'B']), scale: autoOr('low', 'high') },
    channels: (c) => [`spectrum.${c.channel}`],
    settings: [channelField()],
  },
  {
    type: 'spectrum', title: 'Spectrum', min: { w: 3, h: 3 }, phoneMinH: 5,
    defaults: { channel: 'both', peak_hold: false, peak_decay_s: 10 },
    validators: { channel: oneOf(['A', 'B', 'both']), peak_hold: bool, peak_decay_s: numIn(0, 60) },
    channels: (c) => (c.channel === 'both' ? ['spectrum.A', 'spectrum.B'] : [`spectrum.${c.channel}`]),
    settings: [
      channelField(true),
      { key: 'peak_hold', label: 'Peak hold', kind: 'bool' },
      { key: 'peak_decay_s', label: 'Peak decay (s, 0 = hold)', kind: 'number', min: 0, max: 60 },
    ],
  },
  {
    type: 'constellation', title: 'Constellation', min: { w: 2, h: 3 }, phoneMinH: 5,
    defaults: { channel: 'A', mode: 'iq', persistence: 4 },
    validators: { channel: oneOf(['A', 'B']), mode: oneOf(['iq', 'inst_freq']), persistence: intIn(1, 4) },
    channels: (c) => [`iq.${c.channel}`],
    settings: [
      channelField(),
      { key: 'mode', label: 'Mode', kind: 'select', options: [{ value: 'iq', label: 'I/Q' }, { value: 'inst_freq', label: 'Inst. frequency' }] },
      { key: 'persistence', label: 'Persistence (snapshots)', kind: 'number', min: 1, max: 4 },
    ],
  },
  {
    type: 'link', title: 'Link quality', min: { w: 3, h: 3 }, phoneMinH: 5,
    defaults: { channels: ['A', 'B'], window_s: 10 },
    validators: { channels: channelSubset, window_s: oneOf([5, 10, 30]) },
    channels: () => ['link'],
    component: () => import('../../cards/LinkCard.svelte'),
    settings: [{ key: 'window_s', label: 'Rate window', kind: 'select', options: [
      { value: 5, label: '5 s' }, { value: 10, label: '10 s' }, { value: 30, label: '30 s' }] }],
  },
  {
    type: 'health', title: 'Health and flags', min: { w: 3, h: 3 }, phoneMinH: 5,
    defaults: { source: 'best' }, validators: { source: oneOf(SOURCES) },
    channels: (c) => flightChannels(c.source), settings: [sourceField],
    component: () => import('../../cards/HealthCard.svelte'),
  },
  {
    type: 'gps', title: 'GPS status', min: { w: 2, h: 3 }, phoneMinH: 4,
    defaults: { source: 'best' }, validators: { source: oneOf(SOURCES) },
    channels: (c) => flightChannels(c.source), settings: [sourceField],
    component: () => import('../../cards/GpsCard.svelte'),
  },
  {
    type: 'frames', title: 'Raw frames', min: { w: 3, h: 4 }, phoneMinH: 6,
    defaults: { filter: 'all', view: 'text' },
    validators: { filter: oneOf(['all', 'A', 'B', 'best']), view: oneOf(['text', 'hex']) },
    channels: () => ['frames'],
    component: () => import('../../cards/FramesCard.svelte'),
    settings: [
      { key: 'filter', label: 'Filter', kind: 'select', options: [
        { value: 'all', label: 'All' }, { value: 'A', label: 'Channel A' }, { value: 'B', label: 'Channel B' }, { value: 'best', label: 'Best' }] },
      { key: 'view', label: 'View', kind: 'select', options: [{ value: 'text', label: 'Text' }, { value: 'hex', label: 'Hex' }] },
    ],
  },
];

export const REGISTRY: Record<string, CardMeta> = Object.fromEntries(specs.map((s) => [s.type, meta(s)]));

/** Per-type config defaults and clean-up; an unknown type's config passes through untouched. */
export function sanitizeConfig(type: string, config: unknown): Config {
  const m = REGISTRY[type];
  return m ? m.sanitize(config) : (isObj(config) ? config : {});
}

/** Union of the channels a set of cards needs, sorted. Unknown card types need none. */
export function cardChannels(cards: readonly Pick<GridCard, 'type' | 'config'>[]): string[] {
  const out = new Set<string>();
  for (const c of cards) for (const ch of REGISTRY[c.type]?.channels(c.config) ?? []) out.add(ch);
  return [...out].sort();
}

const FALLBACK_MIN: Required<MinSize> = { w: 2, h: 2, phoneMinH: 3 };

/** Minimum sizes for the grid model; unknown types get a small generic cell so they keep their place. */
export function minOfType(type: string): Required<MinSize> {
  const m = REGISTRY[type];
  return m ? { w: m.min.w, h: m.min.h, phoneMinH: m.phoneMinH } : FALLBACK_MIN;
}

/** The title a card shows: its own, else the type's (which may depend on config), else the raw type. */
export function cardTitle(card: Pick<GridCard, 'type' | 'title' | 'config'>): string {
  if (card.title) return card.title;
  const m = REGISTRY[card.type];
  return m ? (m.titleOf?.(sanitizeConfig(card.type, card.config)) ?? m.title) : card.type;
}

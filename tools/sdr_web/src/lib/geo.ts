/** Map helpers (spec 13): GPS validity, tile and local-frame math, track extraction, graticule. Pure and toolkit-free. */
import type { FlightSchema } from './types';

export type LatLon = [number, number];
export type Bounds = [[number, number], [number, number]];   // [[south, west], [north, east]]

const EARTH_KM = 6371.0088;
const MAX_LAT = 85.0511287798;
const M_PER_DEG_LON = 111320;
const M_PER_DEG_LAT = 110540;
const KM_PER_DEG = 111.32;   // same constant as tools/sdr_cli/maps.py

/** A real horizontal fix (spec 13.5): 2D, 3D or 3D+DR with finite, in-range, not-both-zero coordinates. DR alone (1) is not a fix. */
export function gpsValid(fix: number, lat: number, lon: number): boolean {
  if (![2, 3, 4].includes(fix)) return false;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return false;
  return !(lat === 0 && lon === 0);
}

export interface GpsRow { gps_fix: number; lat_deg: number; lon_deg: number }

/** gpsValid over a decoded row. */
export function rowValid(row: GpsRow): boolean {
  return gpsValid(row.gps_fix, row.lat_deg, row.lon_deg);
}

/** Web Mercator tile indices, identical to maps.tile_xy. */
export function tileXY(lat: number, lon: number, z: number): { x: number; y: number } {
  const n = 2 ** z;
  const la = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
  const rad = (la * Math.PI) / 180;
  const x = Math.floor(((lon + 180) / 360) * n);
  const y = Math.floor(((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n);
  return { x: Math.max(0, Math.min(n - 1, x)), y: Math.max(0, Math.min(n - 1, y)) };
}

/** Bounding box of radius r km around a center, using the same degree-per-km math as maps.bbox. */
export function boundsFor(center: LatLon, radiusKm: number): Bounds {
  const [lat, lon] = center;
  const dlat = radiusKm / KM_PER_DEG;
  const dlon = radiusKm / (KM_PER_DEG * Math.cos((lat * Math.PI) / 180));
  return [[lat - dlat, lon - dlon], [lat + dlat, lon + dlon]];
}

/** Local east/north offset in metres from an origin, exactly the spec 13.7 formula. */
export function enu(lat: number, lon: number, lat0: number, lon0: number): { east: number; north: number } {
  return { east: (lon - lon0) * M_PER_DEG_LON * Math.cos((lat0 * Math.PI) / 180), north: (lat - lat0) * M_PER_DEG_LAT };
}

/** Great-circle distance in km (haversine). */
export function distanceKm(a: LatLon, b: LatLon): number {
  const r = (d: number) => (d * Math.PI) / 180;
  const dlat = r(b[0] - a[0]);
  const dlon = r(b[1] - a[1]);
  const h = Math.sin(dlat / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(dlon / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

interface Rows { length: number; valueAt(i: number, field: number): number }
const NO_INDEX = { fix: -1, lat: -1, lon: -1 };

function indices(schema: FlightSchema | null): { fix: number; lat: number; lon: number } {
  if (!schema) return NO_INDEX;
  const at = (key: string) => schema.fields.findIndex((f) => f.key === key);
  return { fix: at('gps_fix'), lat: at('lat_deg'), lon: at('lon_deg') };
}

/** [lat, lon] of every valid row, oldest first. Invalid rows are skipped, never plotted. maxPoints thins long tracks (the newest row is kept). */
export function validTrack(store: Rows, schema: FlightSchema | null, maxPoints = Infinity): LatLon[] {
  const ix = indices(schema);
  if (ix.fix < 0 || ix.lat < 0 || ix.lon < 0) return [];
  const out: LatLon[] = [];
  for (let i = 0; i < store.length; i++) {
    const lat = store.valueAt(i, ix.lat);
    const lon = store.valueAt(i, ix.lon);
    if (gpsValid(store.valueAt(i, ix.fix), lat, lon)) out.push([lat, lon]);
  }
  if (out.length <= maxPoints || maxPoints < 2) return out;
  const stride = Math.ceil(out.length / (maxPoints - 1));
  const thin = out.filter((_, i) => i % stride === 0);
  const last = out[out.length - 1];
  if (thin[thin.length - 1] !== last) thin.push(last);
  return thin;
}

export interface GpsStatus { valid: boolean; position: LatLon | null; text: string }

/** The always-visible GPS validity line for the newest row (spec 13.5 and 12). */
export function gpsStatus(
  values: ArrayLike<number> | null, schema: FlightSchema | null,
): GpsStatus {
  const ix = indices(schema);
  if (!values || ix.fix < 0) return { valid: false, position: null, text: 'GPS: no data' };
  const fix = values[ix.fix];
  const field = schema!.fields[ix.fix];
  const label = field.enum_map?.[String(fix)] ?? `fix ${fix}`;
  const satIx = schema!.fields.findIndex((f) => f.key === 'gps_sats');
  const sats = satIx >= 0 ? values[satIx] : NaN;
  const satText = Number.isFinite(sats) ? `, ${sats} sats` : '';
  const lat = values[ix.lat];
  const lon = values[ix.lon];
  if (gpsValid(fix, lat, lon)) return { valid: true, position: [lat, lon], text: `GPS: ${label}${satText}` };
  return { valid: false, position: null, text: `GPS position invalid: fix ${label}${satText}.` };
}

// ---- sites and coverage

export interface SiteInfo {
  id: string; name: string; center: LatLon; pad: LatLon; outer_radius_km: number; inner_radius_km: number;
  layers?: Record<string, { min_z: number; max_z: number }>;
  outer_max_z?: number | null;
}

/** The configured site if known, else the first site, else null (spec: null resolves to the first hello.sites entry). */
export function resolveSite(sites: readonly SiteInfo[], id: string | null | undefined): SiteInfo | null {
  return sites.find((s) => s.id === id) ?? sites[0] ?? null;
}

export interface LayerPlan {
  /** False when the site has no downloaded tiles for the layer. */
  available: boolean;
  minZoom: number;
  /** Base layer maxNativeZoom (null: no base layer): the site's outer maximum (ruling C7), bounded by this layer's own deepest zoom. */
  baseMaxNative: number | null;
  /** Detail layer maxNativeZoom, or null when the layer has no zoom 14 or deeper tiles. */
  detailMaxNative: number | null;
  detailBounds: Bounds;
}

const DETAIL_MIN = 14;

/** Zoom limits for one site and layer. The site-wide outer_max_z may exceed a layer that has fewer zooms, so it is capped by that layer's max_z. */
export function layerPlan(site: SiteInfo, layer: string): LayerPlan {
  const cov = site.layers?.[layer];
  const bounds = boundsFor(site.center, site.inner_radius_km);
  if (!cov) return { available: false, minZoom: 0, baseMaxNative: 0, detailMaxNative: null, detailBounds: bounds };
  // No outer-ring tile of this site is downloaded: skip the base layer rather than request tiles that do not exist.
  const outer = site.outer_max_z;
  return {
    available: true,
    minZoom: cov.min_z,
    baseMaxNative: typeof outer === 'number' ? Math.min(outer, cov.max_z) : null,
    detailMaxNative: cov.max_z >= DETAIL_MIN ? cov.max_z : null,
    detailBounds: bounds,
  };
}

/** Footer line: distance from the site when the vehicle is over 50 km away, and the fetch hint for a missing layer. */
export function footerText(opts: { site: SiteInfo | null; layerAvailable: boolean; position: LatLon | null }): string {
  const parts: string[] = [];
  const { site, position } = opts;
  if (site && position) {
    const d = distanceKm(position, site.pad);
    if (d > 50) parts.push(`Position is ${Math.round(d)} km from ${site.name}`);
  }
  if (!opts.layerAvailable) parts.push(`Tiles missing. Run ./sdr maps fetch --site ${site ? site.id : '<id>'} on the server`);
  return parts.join('. ');
}

// ---- graticule (blank-grid fallback when no tiles are downloaded)

const STEPS = [1, 2, 5];

/** A "nice" degree step (1, 2, 5 x 10^n) giving about `target` lines across `span` degrees. */
export function niceStep(span: number, target: number): number {
  const raw = Math.max(span, 1e-9) / Math.max(target, 1);
  const pow = 10 ** Math.floor(Math.log10(raw));
  for (const s of STEPS) if (s * pow >= raw * (1 - 1e-9)) return s * pow;
  return 10 * pow;
}

export interface Graticule { step: number; lats: number[]; lons: number[] }

/** Latitude and longitude line positions covering the view, on multiples of a nice step. */
export function graticule(view: Bounds, target = 6): Graticule {
  const [[s, w], [n, e]] = view;
  const step = niceStep(Math.max(n - s, e - w), target);
  const lines = (lo: number, hi: number): number[] => {
    const out: number[] = [];
    const first = Math.ceil(lo / step - 1e-9);
    const last = Math.floor(hi / step + 1e-9);
    for (let k = first; k <= last && out.length < 100; k++) out.push(Number((k * step).toPrecision(12)));
    return out;
  };
  return { step, lats: lines(s, n), lons: lines(w, e) };
}

/** Seeds local view state from a preset config value: true on the first call and whenever the VALUE changes, never on a new config object that repeats it. */
export function makeSeeder<T>(): (value: T) => boolean {
  let first = true;
  let last: T;
  return (value) => {
    if (!first && Object.is(last, value)) return false;
    first = false;
    last = value;
    return true;
  };
}

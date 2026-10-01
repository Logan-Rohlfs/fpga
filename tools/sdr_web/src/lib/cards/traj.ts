/** Pure helpers for the 3D trajectory card: local ENU track points, ground tile span and altitude colours.
 *  The ENU and tile math here is local to this card; lib/geo.ts (Map card) may replace it after merge. */
import type { FlightSchema } from '../types';
import type { SeriesStore } from '../series';

const M_PER_DEG_LAT = 110540;
const M_PER_DEG_LON = 111320;
const EARTH_CIRCUMFERENCE_M = 40075016.686;
const MAX_LAT = 85.0511287798;

export interface TrackResult {
  mode: 'track' | 'column';
  /** x (east), y (up), z (south) triples. */
  points: Float32Array;
  maxAlt: number;
}

export interface GroundSpan {
  z: number; x0: number; x1: number; y0: number; y1: number;
  /** ENU metres (east, north of the pad) of the north-west corner of tile (x0, y0). */
  originEast: number; originNorth: number;
  /** Ground width of the whole span in metres; every tile is sizeM / (x1 - x0 + 1) wide and tall. */
  sizeM: number;
}

/** Local east and north metres of (lat, lon) from (lat0, lon0). */
export function enu(lat: number, lon: number, lat0: number, lon0: number): { east: number; north: number } {
  return { east: (lon - lon0) * M_PER_DEG_LON * Math.cos((lat0 * Math.PI) / 180), north: (lat - lat0) * M_PER_DEG_LAT };
}

/** A real position fix: 2D, 3D or 3D+DR with in-range coordinates that are not both zero (spec 13.5). */
export function gpsValid(fix: number, lat: number, lon: number): boolean {
  return (fix === 2 || fix === 3 || fix === 4) && Number.isFinite(lat) && Number.isFinite(lon)
    && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && !(lat === 0 && lon === 0);
}

export function tileXY(lat: number, lon: number, z: number): { x: number; y: number } {
  const n = 2 ** z;
  const rad = (Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * Math.PI) / 180;
  const x = Math.floor(((lon + 180) / 360) * n);
  const y = Math.floor(((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n);
  return { x: Math.max(0, Math.min(n - 1, x)), y: Math.max(0, Math.min(n - 1, y)) };
}

/** North-west corner (lat, lon) of a tile. */
function tileCorner(x: number, y: number, z: number): { lat: number; lon: number } {
  const n = 2 ** z;
  return {
    lat: (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI,
    lon: (x / n) * 360 - 180,
  };
}

const fieldIndex = (schema: FlightSchema, key: string): number => schema.fields.findIndex((f) => f.key === key);

/** Track from every row with a valid GPS fix, or a vertical column over the pad when none has one. */
export function trackPoints(store: SeriesStore, schema: FlightSchema, pad: [number, number], exaggeration: number): TrackResult {
  const iFix = fieldIndex(schema, 'gps_fix');
  const iLat = fieldIndex(schema, 'lat_deg');
  const iLon = fieldIndex(schema, 'lon_deg');
  const iAlt = fieldIndex(schema, 'alt_agl_m');
  const n = store.length;
  const alt = (i: number): number => (iAlt >= 0 ? store.valueAt(i, iAlt) : NaN);

  const track: number[] = [];
  let maxAlt = 0;
  if (iFix >= 0 && iLat >= 0 && iLon >= 0) {
    for (let i = 0; i < n; i++) {
      const lat = store.valueAt(i, iLat);
      const lon = store.valueAt(i, iLon);
      if (!gpsValid(store.valueAt(i, iFix), lat, lon)) continue;
      const a = alt(i);
      if (!Number.isFinite(a)) continue;   // shown as decoded: no altitude means no point
      const h = a;
      const p = enu(lat, lon, pad[0], pad[1]);
      track.push(p.east, h * exaggeration, -p.north);
      if (h > maxAlt) maxAlt = h;
    }
  }
  if (track.length) return { mode: 'track', points: Float32Array.from(track), maxAlt };

  const col: number[] = [];
  for (let i = 0; i < n; i++) {
    const a = alt(i);
    if (!Number.isFinite(a)) continue;
    col.push(0, a * exaggeration, 0);
    if (a > maxAlt) maxAlt = a;
  }
  return { mode: 'column', points: Float32Array.from(col), maxAlt };
}

/** Zoom-`z` tiles covering +-halfKm around the pad, with the span's NW corner in ENU metres. */
export function groundTiles(pad: [number, number], z = 15, halfKm = 4): GroundSpan {
  const [lat, lon] = pad;
  const dLat = (halfKm * 1000) / M_PER_DEG_LAT;
  const dLon = (halfKm * 1000) / (M_PER_DEG_LON * Math.cos((lat * Math.PI) / 180));
  const nw = tileXY(lat + dLat, lon - dLon, z);
  const se = tileXY(lat - dLat, lon + dLon, z);
  const corner = tileCorner(nw.x, nw.y, z);
  const o = enu(corner.lat, corner.lon, lat, lon);
  const tileM = (EARTH_CIRCUMFERENCE_M * Math.cos((lat * Math.PI) / 180)) / 2 ** z;
  return { z, x0: nw.x, x1: se.x, y0: nw.y, y1: se.y, originEast: o.east, originNorth: o.north, sizeM: (se.x - nw.x + 1) * tileM };
}

/** Blue (low) through green to red (high) for t in 0..1. */
export function altitudeColor(t: number): [number, number, number] {
  const u = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
  const lo: [number, number, number] = [0.15, 0.45, 1.0];
  const mid: [number, number, number] = [0.2, 0.85, 0.45];
  const hi: [number, number, number] = [1.0, 0.3, 0.15];
  const [a, b, k] = u < 0.5 ? [lo, mid, u * 2] : [mid, hi, (u - 0.5) * 2];
  return [lerp(a[0], b[0], k), lerp(a[1], b[1], k), lerp(a[2], b[2], k)];
}

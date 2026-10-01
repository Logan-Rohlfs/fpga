/** Pure helpers for the 3D trajectory card: local ENU track points, ground tile span and altitude colours.
 *  ENU, GPS validity and tile math come from lib/geo.ts. */
import type { FlightSchema } from '../types';
import type { SeriesStore } from '../series';
import { enu, gpsValid, tileXY } from '../geo';

const M_PER_DEG_LAT = 110540;
const M_PER_DEG_LON = 111320;
const EARTH_CIRCUMFERENCE_M = 40075016.686;

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

/** North-west corner (lat, lon) of a tile. */
function tileCorner(x: number, y: number, z: number): { lat: number; lon: number } {
  const n = 2 ** z;
  return {
    lat: (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI,
    lon: (x / n) * 360 - 180,
  };
}

const fieldIndex = (schema: FlightSchema, key: string): number => schema.fields.findIndex((f) => f.key === key);

/** Track from every row (from row index `from`) with a valid GPS fix, or a vertical column over the pad when none has one. */
export function trackPoints(store: SeriesStore, schema: FlightSchema, pad: [number, number], exaggeration: number, from = 0): TrackResult {
  const iFix = fieldIndex(schema, 'gps_fix');
  const iLat = fieldIndex(schema, 'lat_deg');
  const iLon = fieldIndex(schema, 'lon_deg');
  const iAlt = fieldIndex(schema, 'alt_agl_m');
  const n = store.length;
  const alt = (i: number): number => (iAlt >= 0 ? store.valueAt(i, iAlt) : NaN);

  const track: number[] = [];
  let maxAlt = 0;
  if (iFix >= 0 && iLat >= 0 && iLon >= 0) {
    for (let i = from; i < n; i++) {
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
  for (let i = from; i < n; i++) {
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

// ---- camera framing for the follow and orbit modes (x east, y up, z south, as trackPoints)

export interface Sphere { center: [number, number, number]; r: number }

/** Sphere around the track's bounding box and the pad (the origin), never smaller than `minR` metres. */
export function trackSphere(points: Float32Array, minR: number): Sphere {
  const lo = [0, 0, 0];
  const hi = [0, 0, 0];
  for (let i = 0; i + 2 < points.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      const v = points[i + k];
      if (v < lo[k]) lo[k] = v;
      if (v > hi[k]) hi[k] = v;
    }
  }
  const center: [number, number, number] = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
  const r = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2;
  return { center, r: Math.max(minR, r) };
}

/** Camera distance that fits a sphere of radius r in a perspective view (vertical fov in degrees), times `margin`. */
export function fitDistance(r: number, vfovDeg: number, aspect: number, margin: number): number {
  const halfV = (vfovDeg * Math.PI) / 360;
  const halfH = Math.atan(Math.tan(halfV) * aspect);
  return (r / Math.sin(Math.min(halfV, halfH))) * margin;
}

/** Camera position relative to its target for an azimuth (0 looks from +z, i.e. from the south) and an elevation. */
export function cameraOffset(az: number, el: number, dist: number): [number, number, number] {
  return [Math.sin(az) * Math.cos(el) * dist, Math.sin(el) * dist, Math.cos(az) * Math.cos(el) * dist];
}

const wrapAngle = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));

/**
 * Azimuth for a side-on ("tangential") view of the flight: perpendicular to the pad-to-latest ground drift, on the
 * side closer to `prevAz` so the camera does not flip sides as the track bends. With less than `minDrift` metres of
 * drift there is no meaningful direction, so `prevAz` is kept. The result is the nearest equivalent angle to `prevAz`.
 */
export function followAzimuth(points: Float32Array, prevAz: number, minDrift: number): number {
  const n = points.length;
  if (n < 3) return prevAz;
  const x = points[n - 3];
  const z = points[n - 1];
  if (Math.hypot(x, z) < minDrift) return prevAz;
  const dir = Math.atan2(x, z);
  const a = wrapAngle(dir + Math.PI / 2 - prevAz);
  const b = wrapAngle(dir - Math.PI / 2 - prevAz);
  return prevAz + (Math.abs(a) <= Math.abs(b) ? a : b);
}

/** Mean RGB of the opaque pixels within `band` px of the image edge (transparent pixels are tiles not loaded); null if none. */
export function edgeAverage(data: Uint8ClampedArray, w: number, h: number, band: number): [number, number, number] | null {
  let r = 0, g = 0, b = 0, n = 0;
  for (let y = 0; y < h; y++) {
    const edgeRow = y < band || y >= h - band;
    for (let x = 0; x < w; x++) {
      if (!edgeRow && x >= band && x < w - band) { x = w - band - 1; continue; }
      const i = (y * w + x) * 4;
      if (data[i + 3] < 128) continue;
      r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
    }
  }
  return n ? [Math.round(r / n), Math.round(g / n), Math.round(b / n)] : null;
}

/** The track flattened onto the ground (every point's height set to `y`): its 2D ground projection. */
export function groundProjection(points: Float32Array, y: number): Float32Array {
  const out = Float32Array.from(points);
  for (let i = 1; i < out.length; i += 3) out[i] = y;
  return out;
}

/** An RGB colour scaled toward black by `k` (0 = unchanged, 1 = black), rounded. */
export function darken(rgb: [number, number, number], k: number): [number, number, number] {
  const f = 1 - Math.max(0, Math.min(1, k));
  return [Math.round(rgb[0] * f), Math.round(rgb[1] * f), Math.round(rgb[2] * f)];
}

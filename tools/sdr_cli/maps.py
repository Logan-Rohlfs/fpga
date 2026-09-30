"""Offline map tiles: site registry, coverage math and a polite resumable USGS prefetch.

Only USGS The National Map basemaps (public domain) are used. Nothing here
contacts the network except Fetcher.fetch.
"""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from . import __version__
from .core import ToolError

LAYERS = {
    'imagery': 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}',
    'topo': 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}',
}
OUTER_ZOOMS = range(5, 14)
INNER_ZOOMS = range(14, 18)
EST_BYTES = {'imagery': 20000, 'topo': 12000}
MAX_RATE = 8.0
MAX_ZOOM = 20
MAX_CONSECUTIVE_FAILURES = 20
BACKOFF_START = 2.0
BACKOFF_MAX = 60.0
KM_PER_DEG = 111.32
MAX_LAT = 85.0511287798
EXTENSIONS = {'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png'}
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')


def maps_dir(root):
    return Path(root) / '.sdr' / 'maps'


# ---------------------------------------------------------------- registry

def _latlon(value, field, site_id):
    try:
        lat, lon = value
    except (TypeError, ValueError):
        raise ToolError('sites: {} of {!r} must be [lat, lon]'.format(field, site_id))
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)) \
            or abs(lat) > 90 or abs(lon) > 180:
        raise ToolError('sites: {} of {!r} is not a valid latitude/longitude'.format(field, site_id))
    return [float(lat), float(lon)]


def _radius(site, field, site_id):
    value = site.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not 0 < value <= 500:
        raise ToolError('sites: {} of {!r} must be a number of km in (0, 500]'.format(field, site_id))
    return value


def _validate(site):
    if not isinstance(site, dict):
        raise ToolError('sites: each site must be an object')
    site_id = site.get('id')
    if not isinstance(site_id, str) or not ID_RE.match(site_id):
        raise ToolError('sites: bad id {!r} (lowercase letters, digits and dashes)'.format(site_id))
    name = site.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ToolError('sites: {!r} needs a name'.format(site_id))
    center = _latlon(site.get('center'), 'center', site_id)
    pad = _latlon(site['pad'], 'pad', site_id) if site.get('pad') is not None else list(center)
    outer = _radius(site, 'outer_radius_km', site_id)
    inner = _radius(site, 'inner_radius_km', site_id)
    if inner > outer:
        raise ToolError('sites: {!r} inner_radius_km exceeds outer_radius_km'.format(site_id))
    return {'id': site_id, 'name': name, 'center': center, 'pad': pad,
            'outer_radius_km': outer, 'inner_radius_km': inner}


def _read_sites(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ToolError('sites: cannot read {}: {}'.format(path, exc))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('sites'), list):
        raise ToolError('sites: {} must be {{"version": 1, "sites": [...]}}'.format(path))
    return [_validate(site) for site in data['sites']]


def load_sites(root):
    """Tracked sites, then the optional .sdr/gui/sites.json merged by id (local wins)."""
    merged = {}
    for site in _read_sites(Path(__file__).with_name('sites.json')):
        merged[site['id']] = site
    local = Path(root) / '.sdr' / 'gui' / 'sites.json'
    if local.is_file():
        for site in _read_sites(local):
            merged[site['id']] = site
    return list(merged.values())


# ---------------------------------------------------------------- tile math

def tile_xy(lat, lon, z):
    n = 2 ** z
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    rad = math.radians(lat)
    x = math.floor((lon + 180.0) / 360.0 * n)
    y = math.floor((1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def bbox(lat, lon, radius_km):
    """(north, west, south, east)."""
    dlat = radius_km / KM_PER_DEG
    dlon = radius_km / (KM_PER_DEG * math.cos(math.radians(lat)))
    return lat + dlat, lon - dlon, lat - dlat, lon + dlon


def tile_range(lat, lon, radius_km, z):
    """Inclusive (x0, x1, y0, y1) from the NW to the SE corner."""
    north, west, south, east = bbox(lat, lon, radius_km)
    x0, y0 = tile_xy(north, west, z)
    x1, y1 = tile_xy(south, east, z)
    return x0, x1, y0, y1


def plan(site):
    lat, lon = site['center']
    tiles = []
    for zooms, radius in ((OUTER_ZOOMS, site['outer_radius_km']), (INNER_ZOOMS, site['inner_radius_km'])):
        for z in zooms:
            x0, x1, y0, y1 = tile_range(lat, lon, radius, z)
            tiles.extend((z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
    return tiles


def estimate(site, layer):
    if layer not in LAYERS:
        raise ValueError('unknown layer {!r}'.format(layer))
    zooms = {}
    for z, _x, _y in plan(site):
        zooms[z] = zooms.get(z, 0) + 1
    total = sum(zooms.values())
    return {'zooms': zooms, 'tiles': total, 'bytes': total * EST_BYTES[layer]}


# ---------------------------------------------------------------- store

def _int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('{} must be a non-negative integer'.format(name))
    return value


def tile_path(root, layer, z, x, y):
    """Existing .jpg/.png tile path or None. Raises ValueError on bad input."""
    if not isinstance(layer, str) or layer not in LAYERS:
        raise ValueError('unknown layer {!r}'.format(layer))
    _int(z, 'z'), _int(x, 'x'), _int(y, 'y')
    if z > MAX_ZOOM:
        raise ValueError('z must be at most {}'.format(MAX_ZOOM))
    base = maps_dir(root) / layer / str(z) / str(x)
    for ext in ('jpg', 'png'):
        path = base / '{}.{}'.format(y, ext)
        if path.is_file():
            return path
    return None


def _read_json(path, default):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + '.part')
    part.write_text(json.dumps(data, indent=1, sort_keys=True), encoding='utf-8')
    os.replace(str(part), str(path))


def _missing_path(root, layer):
    return maps_dir(root) / layer / 'missing.json'


def write_coverage(root, layer):
    """Record, per site, the zooms actually present for one layer."""
    if layer not in LAYERS:
        raise ValueError('unknown layer {!r}'.format(layer))
    result = {}
    for site in load_sites(root):
        zooms = [z for z, x, y in plan(site) if tile_path(root, layer, z, x, y)]
        if zooms:
            outer = [z for z in zooms if z in OUTER_ZOOMS]
            result[site['id']] = {'min_z': min(zooms), 'max_z': max(zooms), 'tiles': len(zooms),
                                  'outer_max_z': max(outer) if outer else None}
    _write_json(maps_dir(root) / layer / 'coverage.json', result)
    return result


def coverage(root):
    """{site_id: {layer: {min_z, max_z, tiles}, 'outer_max_z': n}} from the per-layer coverage.json files.

    outer_max_z is the highest zoom of the outer ring (z5-13) actually present for the site in any layer.
    """
    out = {}
    for layer in LAYERS:
        for site_id, info in _read_json(maps_dir(root) / layer / 'coverage.json', {}).items():
            try:
                entry = out.setdefault(site_id, {'outer_max_z': None})
                entry[layer] = {'min_z': int(info['min_z']), 'max_z': int(info['max_z']),
                                'tiles': int(info['tiles'])}
                outer = info.get('outer_max_z')
                if isinstance(outer, int) and (entry['outer_max_z'] is None or outer > entry['outer_max_z']):
                    entry['outer_max_z'] = outer
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
    return out


# ---------------------------------------------------------------- fetch

class Fetcher:
    def __init__(self, root, opener=None, sleep=time.sleep, clock=time.monotonic, rate=4.0):
        if not rate > 0:
            raise ValueError('rate must be positive')
        self.root = Path(root)
        self.opener = opener
        self.sleep = sleep
        self.clock = clock
        self.interval = 1.0 / min(float(rate), MAX_RATE)
        self.user_agent = 'SpaceRaidersSDR/{} (tile prefetch; offline ground station)'.format(__version__)
        self._last = None

    def _pace(self):
        if self._last is not None:
            wait = self._last + self.interval - self.clock()
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    def _request(self, url):
        """Return (status, content_type, body); a network error raises OSError."""
        if self.opener is None:
            self.opener = urllib.request.build_opener()
        request = urllib.request.Request(url, headers={'User-Agent': self.user_agent})
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            with contextlib.suppress(Exception):
                exc.close()
            return exc.code, '', b''
        try:
            status = getattr(response, 'status', None) or response.getcode()
            content_type = response.headers.get('Content-Type', '') or ''
            body = response.read()
        finally:
            close = getattr(response, 'close', None)
            if close:
                close()
        return status, content_type.split(';')[0].strip().lower(), body

    def fetch(self, site, layer, retry_missing=False, progress=print):
        if layer not in LAYERS:
            raise ValueError('unknown layer {!r}'.format(layer))
        template = LAYERS[layer]
        missing_file = _missing_path(self.root, layer)
        missing = _read_json(missing_file, {})
        stats = {'fetched': 0, 'skipped': 0, 'missing': 0, 'failed': 0, 'bytes': 0}
        tiles = plan(site)
        consecutive = 0
        delay = BACKOFF_START
        dirty = False
        try:
            for index, (z, x, y) in enumerate(tiles, 1):
                if tile_path(self.root, layer, z, x, y):
                    stats['skipped'] += 1
                    continue
                key = '{}/{}/{}'.format(z, x, y)
                if key in missing and not retry_missing:
                    stats['missing'] += 1
                    continue
                url = template.format(z=z, y=y, x=x)
                while True:
                    self._pace()
                    try:
                        status, content_type, body = self._request(url)
                    except OSError:
                        status, content_type, body = 0, '', b''
                    if status == 200 and content_type in EXTENSIONS:
                        consecutive, delay = 0, BACKOFF_START
                        directory = maps_dir(self.root) / layer / str(z) / str(x)
                        directory.mkdir(parents=True, exist_ok=True)
                        ext = EXTENSIONS[content_type]
                        part = directory / '{}.{}.part'.format(y, ext)
                        try:
                            part.write_bytes(body)
                            os.replace(str(part), str(directory / '{}.{}'.format(y, ext)))
                        finally:
                            if part.exists():
                                part.unlink()
                        if missing.pop(key, None) is not None:
                            dirty = True
                        stats['fetched'] += 1
                        stats['bytes'] += len(body)
                        break
                    if status != 0 and status != 429 and not 500 <= status < 600:
                        # 404, other 4xx, or a 200 that is not an image: the tile is unavailable.
                        consecutive, delay = 0, BACKOFF_START
                        missing[key] = status
                        dirty = True
                        stats['missing'] += 1
                        break
                    consecutive += 1
                    if consecutive >= MAX_CONSECUTIVE_FAILURES:
                        stats['failed'] = consecutive
                        progress('{}: stopping after {} consecutive failures (last: {}) at z{}/{}/{}'.format(
                            layer, consecutive, status or 'network error', z, x, y))
                        return stats
                    self.sleep(delay)
                    delay = min(delay * 2, BACKOFF_MAX)
                if index % 200 == 0:
                    progress('{} {}: {}/{} tiles'.format(site['id'], layer, index, len(tiles)))
                if dirty and index % 50 == 0:
                    _write_json(missing_file, missing)
                    dirty = False
            return stats
        finally:
            if dirty:
                _write_json(missing_file, missing)


# ---------------------------------------------------------------- command line

def add_arguments(parser):
    sub = parser.add_subparsers(dest='maps_command', required=True)
    sub.add_parser('list', help='Show sites and downloaded tile counts')
    fetch = sub.add_parser('fetch', help='Download USGS tiles (polite, resumable)')
    target = fetch.add_mutually_exclusive_group(required=True)
    target.add_argument('--site', help='Site id')
    target.add_argument('--all', action='store_true', help='Every site')
    fetch.add_argument('--layer', choices=['imagery', 'topo', 'all'], default='all')
    fetch.add_argument('--dry-run', action='store_true', help='Print the estimate and stop')
    fetch.add_argument('--rate', type=float, default=4.0, help='Requests per second (capped at 8)')
    fetch.add_argument('--retry-missing', action='store_true', help='Ask again for tiles recorded as missing')


def _layer_stats(root, layer):
    base = maps_dir(root) / layer
    count = size = 0
    if base.is_dir():
        for path in base.rglob('*'):
            if path.suffix in ('.jpg', '.png') and path.is_file():
                count += 1
                size += path.stat().st_size
    return count, size, len(_read_json(_missing_path(root, layer), {}))


def _size(n):
    return '{:.1f} MB'.format(n / 1e6)


def run(args, root, opener=None, sleep=time.sleep, clock=time.monotonic, out=print):
    root = Path(root)
    sites = load_sites(root)
    if args.maps_command == 'list':
        for site in sites:
            out('{}  {}  center {:.5f},{:.5f}'.format(site['id'], site['name'], *site['center']))
            for layer in LAYERS:
                count, size, missing = _layer_stats(root, layer)
                out('  {:8} {} tiles ({} planned), {}, {} missing'.format(
                    layer, count, estimate(site, layer)['tiles'], _size(size), missing))
        return 0
    if not args.rate > 0:
        raise ToolError('--rate must be positive')
    rate = min(args.rate, MAX_RATE)
    if args.all:
        chosen = sites
    else:
        chosen = [s for s in sites if s['id'] == args.site]
        if not chosen:
            raise ToolError('Unknown site {!r}. Known: {}'.format(args.site, ', '.join(s['id'] for s in sites)))
    layers = list(LAYERS) if args.layer == 'all' else [args.layer]
    fetcher = None if args.dry_run else Fetcher(root, opener=opener, sleep=sleep, clock=clock, rate=rate)
    for site in chosen:
        for layer in layers:
            est = estimate(site, layer)
            out('{} {}: {} tiles, about {} (estimate)'.format(site['id'], layer, est['tiles'], _size(est['bytes'])))
            out('  per zoom: ' + ', '.join('z{}={}'.format(z, n) for z, n in sorted(est['zooms'].items())))
            if args.dry_run:
                continue
            stats = fetcher.fetch(site, layer, retry_missing=args.retry_missing, progress=out)
            out('  fetched {fetched}, skipped {skipped}, missing {missing}, failed {failed}, {size}'.format(
                size=_size(stats['bytes']), **stats))
            write_coverage(root, layer)
            if stats['failed']:
                return 1
    return 0


def main(argv, root, **kwargs):
    parser = argparse.ArgumentParser(prog='sdr maps')
    add_arguments(parser)
    try:
        return run(parser.parse_args(argv), root, **kwargs)
    except (ToolError, ValueError, OSError) as exc:
        print('sdr: ' + str(exc), file=sys.stderr)
        return 1

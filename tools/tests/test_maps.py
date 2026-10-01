import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from sdr_cli import maps


class FakeResponse:
    def __init__(self, body=b'img', content_type='image/jpeg', status=200):
        self.body, self.status = body, status
        self.headers = {'Content-Type': content_type}

    def read(self):
        return self.body

    def close(self):
        pass


class FakeOpener:
    """Scripted responses: each item is a status int, a FakeResponse, or a callable(url)."""

    def __init__(self, script=None, default=None):
        self.script = list(script or [])
        self.default = default
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        item = self.script.pop(0) if self.script else self.default
        if item is None:
            item = FakeResponse()
        if callable(item):
            item = item(request.full_url)
        if isinstance(item, int):
            raise urllib.error.HTTPError(request.full_url, item, 'err', {}, None)
        return item


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def tiny_site():
    return {'id': 'tiny', 'name': 'Tiny', 'center': [33.5, -99.3], 'pad': [33.5, -99.3],
            'outer_radius_km': 0.01, 'inner_radius_km': 0.01}


class MathAndRegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def sites(self):
        return {s['id']: s for s in maps.load_sites(self.root)}

    def test_tile_xy_and_range(self):
        self.assertEqual(maps.tile_xy(33.4986975, -99.3329862, 10), (229, 410))
        self.assertEqual(maps.tile_range(33.4986975, -99.3329862, 5, 17), (29350, 29389, 52559, 52598))
        north, west, south, east = maps.bbox(33.0, -99.0, 20)
        self.assertGreater(north, south)
        self.assertLess(west, east)

    def test_plan_counts(self):
        sites = self.sites()
        self.assertEqual(len(maps.plan(sites['seymour'])), 2358)
        self.assertEqual(len(maps.plan(sites['ttu'])), 2462)
        self.assertEqual(len(maps.plan(sites['irec-pecos'])), 2235)

    def test_estimate(self):
        est = maps.estimate(self.sites()['seymour'], 'topo')
        self.assertEqual(est['tiles'], 2358)
        self.assertEqual(est['bytes'], 2358 * 12000)
        self.assertEqual(est['zooms'][17], 1600)
        self.assertEqual(sum(est['zooms'].values()), 2358)

    def test_tracked_sites(self):
        sites = self.sites()
        self.assertEqual(list(sites), ['seymour', 'irec-pecos', 'ttu'])
        self.assertEqual(sites['seymour']['center'], [33.4986975, -99.3329862])
        self.assertEqual(sites['irec-pecos']['center'], [31.0427222, -103.5316389])
        self.assertEqual(sites['ttu']['center'], [33.584, -101.875])
        self.assertEqual(sites['ttu']['pad'], [33.584, -101.875])

    def test_local_sites_override_by_id(self):
        local = self.root / '.sdr' / 'gui'
        local.mkdir(parents=True)
        (local / 'sites.json').write_text(json.dumps({'version': 1, 'sites': [
            {'id': 'ttu', 'name': 'Override', 'center': [1.0, 2.0], 'outer_radius_km': 10, 'inner_radius_km': 2},
            {'id': 'extra', 'name': 'Extra', 'center': [10, 20], 'outer_radius_km': 3, 'inner_radius_km': 1}]}))
        sites = self.sites()
        self.assertEqual(sites['ttu']['name'], 'Override')
        self.assertEqual(sites['ttu']['pad'], [1.0, 2.0])
        self.assertIn('extra', sites)
        self.assertEqual(len(sites), 4)

    def test_invalid_site_rejected(self):
        local = self.root / '.sdr' / 'gui'
        local.mkdir(parents=True)
        for bad in ({'id': 'Bad Id', 'name': 'x', 'center': [1, 2], 'outer_radius_km': 3, 'inner_radius_km': 1},
                    {'id': 'a', 'name': 'x', 'center': [91, 2], 'outer_radius_km': 3, 'inner_radius_km': 1},
                    {'id': 'a', 'name': 'x', 'center': [1, 2], 'outer_radius_km': 1, 'inner_radius_km': 3}):
            (local / 'sites.json').write_text(json.dumps({'version': 1, 'sites': [bad]}))
            with self.assertRaises(maps.ToolError):
                maps.load_sites(self.root)


class FetcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.time = FakeTime()
        self.site = tiny_site()
        self.tiles = maps.plan(self.site)

    def fetcher(self, opener, rate=4.0):
        return maps.Fetcher(self.root, opener=opener, sleep=self.time.sleep, clock=self.time.clock, rate=rate)

    def test_writes_jpg_atomically_with_user_agent_and_zyx_url(self):
        opener = FakeOpener(default=FakeResponse(b'jpegdata'))
        stats = self.fetcher(opener).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertEqual(stats['fetched'], len(self.tiles))
        self.assertEqual(stats['bytes'], 8 * len(self.tiles))
        z, x, y = self.tiles[0]
        path = self.root / '.sdr' / 'maps' / 'imagery' / str(z) / str(x) / '{}.jpg'.format(y)
        self.assertEqual(path.read_bytes(), b'jpegdata')
        self.assertEqual(list((self.root / '.sdr' / 'maps').rglob('*.part')), [])
        first = opener.requests[0]
        self.assertTrue(first.get_header('User-agent').startswith('SpaceRaidersSDR/'))
        self.assertEqual(first.full_url, maps.LAYERS['imagery'].format(z=z, y=y, x=x))
        self.assertTrue(first.full_url.endswith('/{}/{}/{}'.format(z, y, x)))

    def test_png_extension_from_content_type(self):
        opener = FakeOpener(default=FakeResponse(b'png', 'image/png'))
        self.fetcher(opener).fetch(self.site, 'topo', progress=lambda *_: None)
        z, x, y = self.tiles[0]
        self.assertEqual(maps.tile_path(self.root, 'topo', z, x, y).suffix, '.png')

    def test_existing_tile_is_skipped_without_request(self):
        z, x, y = self.tiles[0]
        path = self.root / '.sdr' / 'maps' / 'imagery' / str(z) / str(x)
        path.mkdir(parents=True)
        (path / '{}.jpg'.format(y)).write_bytes(b'old')
        opener = FakeOpener()
        stats = self.fetcher(opener).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertEqual(stats['skipped'], 1)
        self.assertEqual(len(opener.requests), len(self.tiles) - 1)
        self.assertNotIn('/{}/{}/{}'.format(z, y, x), [r.full_url[-len('/{}/{}/{}'.format(z, y, x)):]
                                                    for r in opener.requests])

    def test_404_recorded_and_not_rerequested_unless_retry_missing(self):
        opener = FakeOpener(script=[404])
        stats = self.fetcher(opener).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertEqual(stats['missing'], 1)
        z, x, y = self.tiles[0]
        recorded = json.loads((self.root / '.sdr' / 'maps' / 'imagery' / 'missing.json').read_text())
        self.assertIn('{}/{}/{}'.format(z, x, y), recorded)
        again = FakeOpener()
        stats = self.fetcher(again).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertEqual((stats['missing'], stats['skipped']), (1, len(self.tiles) - 1))
        self.assertEqual(len(again.requests), 0)
        retry = FakeOpener()
        stats = self.fetcher(retry).fetch(self.site, 'imagery', retry_missing=True, progress=lambda *_: None)
        self.assertEqual(len(retry.requests), 1)
        self.assertEqual(stats['fetched'], 1)
        self.assertEqual(json.loads((self.root / '.sdr' / 'maps' / 'imagery' / 'missing.json').read_text()), {})

    def test_non_image_response_is_missing(self):
        opener = FakeOpener(script=[FakeResponse(b'<html>', 'text/html')])
        stats = self.fetcher(opener).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertEqual(stats['missing'], 1)
        self.assertEqual(stats['fetched'], len(self.tiles) - 1)

    def test_429_backs_off_2_then_4(self):
        opener = FakeOpener(script=[429, 429])
        stats = self.fetcher(opener).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertEqual(self.time.sleeps[:2], [2.0, 4.0])
        self.assertTrue(all(s == 0.25 for s in self.time.sleeps[2:]))  # only request pacing after
        self.assertEqual(stats['fetched'], len(self.tiles))
        self.assertEqual(stats['failed'], 0)

    def test_20_consecutive_500s_stop(self):
        opener = FakeOpener(default=500)
        stats = self.fetcher(opener).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertGreater(stats['failed'], 0)
        self.assertEqual(len(opener.requests), 20)
        self.assertEqual(self.time.sleeps[:6], [2.0, 4.0, 8.0, 16.0, 32.0, 60.0])
        self.assertEqual(max(self.time.sleeps), 60.0)
        self.assertEqual(stats['fetched'], 0)

    def test_rate_spaces_requests(self):
        stamps = []

        def stamp(_url):
            stamps.append(self.time.now)
            return FakeResponse()
        self.fetcher(FakeOpener(default=stamp), rate=4.0).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertGreater(len(stamps), 2)
        for a, b in zip(stamps, stamps[1:]):
            self.assertGreaterEqual(b - a, 0.25 - 1e-9)

    def test_rate_capped_at_eight(self):
        self.assertAlmostEqual(self.fetcher(FakeOpener(), rate=100).interval, 0.125)

    def test_incomplete_read_and_empty_body_are_retryable(self):
        import http.client

        class Truncated(FakeResponse):
            def read(self):
                raise http.client.IncompleteRead(b'ab')
        opener = FakeOpener(script=[Truncated(), FakeResponse(b'')])
        stats = self.fetcher(opener).fetch(self.site, 'imagery', progress=lambda *_: None)
        self.assertEqual(self.time.sleeps[:2], [2.0, 4.0])
        self.assertEqual((stats['fetched'], stats['failed']), (len(self.tiles), 0))

    def test_default_opener_built_lazily(self):
        self.assertIsNone(maps.Fetcher(self.root).opener)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_tile_path_validation(self):
        for args in (('../x', 5, 1, 1), ('imagery', 21, 1, 1), ('imagery', 5, -1, 1), ('imagery', 5, 1.5, 1),
                     ('imagery', True, 1, 1), ('imagery', 5, 1, '1')):
            with self.assertRaises(ValueError):
                maps.tile_path(self.root, *args)
        self.assertIsNone(maps.tile_path(self.root, 'imagery', 5, 1, 1))

    def test_coverage(self):
        self.assertEqual(maps.coverage(self.root), {})
        site = {s['id']: s for s in maps.load_sites(self.root)}['seymour']
        stored = [maps.plan(site)[0], [t for t in maps.plan(site) if t[0] == 17][0]]
        for z, x, y in stored:
            path = self.root / '.sdr' / 'maps' / 'topo' / str(z) / str(x)
            path.mkdir(parents=True, exist_ok=True)
            (path / '{}.png'.format(y)).write_bytes(b'x')
        maps.write_coverage(self.root, 'topo')
        cov = maps.coverage(self.root)
        self.assertEqual(cov['seymour']['topo'], {'min_z': 5, 'max_z': 17, 'tiles': 2})
        self.assertEqual(cov['seymour']['outer_max_z'], 5)
        self.assertNotIn('imagery', cov['seymour'])
        self.assertNotIn('ttu', cov)

    def test_sites_with_coverage(self):
        sites = {s['id']: s for s in maps.sites_with_coverage(self.root)}
        self.assertEqual(len(sites), 3)
        self.assertEqual((sites['seymour']['layers'], sites['seymour']['outer_max_z']), ({}, None))
        site = sites['seymour']
        z, x, y = maps.plan(site)[0]
        path = self.root / '.sdr' / 'maps' / 'topo' / str(z) / str(x)
        path.mkdir(parents=True)
        (path / '{}.png'.format(y)).write_bytes(b'x')
        maps.write_coverage(self.root, 'topo')
        seymour = {s['id']: s for s in maps.sites_with_coverage(self.root)}['seymour']
        self.assertEqual(seymour['layers'], {'topo': {'min_z': 5, 'max_z': 5}})
        self.assertEqual(seymour['outer_max_z'], 5)
        for key in ('name', 'center', 'pad', 'outer_radius_km', 'inner_radius_km'):
            self.assertIn(key, seymour)


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def call(self, argv, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = maps.main(argv, self.root, **kwargs)
        return code, out.getvalue()

    def test_dry_run_prints_counts_and_makes_no_requests(self):
        opener = FakeOpener()
        code, text = self.call(['fetch', '--site', 'seymour', '--dry-run'], opener=opener)
        self.assertEqual(code, 0)
        self.assertIn('2358 tiles', text)
        self.assertIn('z17=1600', text)
        self.assertEqual(opener.requests, [])
        self.assertFalse((self.root / '.sdr').exists())

    def test_list(self):
        code, text = self.call(['list'])
        self.assertEqual(code, 0)
        for site_id in ('seymour', 'irec-pecos', 'ttu'):
            self.assertIn(site_id, text)

    def test_unknown_site(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code, _ = self.call(['fetch', '--site', 'nope', '--dry-run'])
        self.assertEqual(code, 1)
        self.assertIn('Unknown site', err.getvalue())

    def test_repeated_failures_return_1(self):
        time = FakeTime()
        code, text = self.call(['fetch', '--site', 'ttu', '--layer', 'topo'], opener=FakeOpener(default=500),
                               sleep=time.sleep, clock=time.clock)
        self.assertEqual(code, 1)
        self.assertIn('failed 20', text)

    def test_fetch_success_writes_coverage(self):
        local = self.root / '.sdr' / 'gui'
        local.mkdir(parents=True)
        (local / 'sites.json').write_text(json.dumps({'version': 1, 'sites': [
            {'id': 'mini', 'name': 'Mini', 'center': [33.5, -99.3], 'outer_radius_km': 0.01,
             'inner_radius_km': 0.01}]}))
        time = FakeTime()
        code, _ = self.call(['fetch', '--site', 'mini', '--layer', 'imagery', '--rate', '50'],
                            opener=FakeOpener(), sleep=time.sleep, clock=time.clock)
        self.assertEqual(code, 0)
        cov = maps.coverage(self.root)
        self.assertEqual(cov['mini']['imagery']['max_z'], 17)
        self.assertEqual(cov['mini']['outer_max_z'], 13)


if __name__ == '__main__':
    unittest.main()

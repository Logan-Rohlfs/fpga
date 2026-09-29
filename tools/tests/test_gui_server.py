# tools/tests/test_gui_server.py
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from link_samples import sample_stream
from sdr_cli import freqplan, roles as r

try:
    from aiohttp.test_utils import TestClient, TestServer
    from sdr_cli.web.server import GuiServer
except ImportError:   # the gui extra is optional
    GuiServer = None


class SampleOnce:
    """Replays the sample stream once a viewer is connected, then stays idle."""
    kind, responds_to_tuning, detail = 'replay', False, 'sample'

    def __init__(self, clients):
        self.clients = clients

    async def chunks(self):
        while not self.clients():
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        yield sample_stream()
        await asyncio.sleep(3600)


@unittest.skipIf(GuiServer is None, 'aiohttp not installed: pip install -e ".[gui]"')
class GuiServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        static = Path(self.tmp.name) / 'static'
        static.mkdir()
        (static / 'index.html').write_text('<!doctype html><title>test</title>')
        roles = r.RoleManager(r.hash_password('pw', iterations=1000))
        self.state_path = Path(self.tmp.name) / 'gui_state.json'
        self.server = GuiServer(lambda get_tuning: SampleOnce(lambda: self.server.clients), roles,
                                self.state_path, static_dir=static)
        self.server.BAD_PASSWORD_DELAY_S = 0
        self.client = TestClient(TestServer(self.server.app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def recv(self, ws, predicate, limit=300):
        for _ in range(limit):
            msg = await asyncio.wait_for(ws.receive_json(), 3)
            if predicate(msg):
                return msg
        self.fail('expected message not received')

    def of(self, kind, **match):
        return lambda m: m['type'] == kind and all(m.get(k) == v for k, v in match.items())

    async def connect(self):
        ws = await self.client.ws_connect('/ws')
        hello = await self.recv(ws, self.of('hello'))
        return ws, hello

    async def test_index_and_hello(self):
        resp = await self.client.get('/')
        self.assertEqual(resp.status, 200)
        ws, hello = await self.connect()
        self.assertEqual(hello['role']['role'], 'viewer')
        self.assertTrue(hello['role']['can_admin'])
        self.assertAlmostEqual(hello['tuning']['derived']['lo_hz'], 441.38e6, places=0)
        await ws.close()

    async def test_records_and_spectrum_fan_out(self):
        ws, _ = await self.connect()
        spectrum = await self.recv(ws, self.of('spectrum'))
        self.assertEqual(len(spectrum['db10']), 256)
        record = await self.recv(ws, lambda m: m['type'] == 'record' and m['record']['type'] == 'IQ_SNAPSHOT')
        self.assertIn('IQ_SNAPSHOT', record['text'])
        await ws.close()

    async def test_late_viewer_gets_latest_status_at_once(self):
        first, _ = await self.connect()
        await self.recv(first, lambda m: m['type'] == 'record' and m['record']['type'] == 'LINK_STATS')
        late, _ = await self.connect()
        status = await self.recv(late, lambda m: m['type'] == 'record' and m['record']['type'] == 'STATUS', limit=5)
        self.assertEqual(status['record']['fields']['version'], 2)
        await first.close()
        await late.close()

    async def test_viewer_cannot_tune_and_admin_change_is_broadcast(self):
        admin, _ = await self.connect()
        viewer, _ = await self.connect()
        await viewer.send_json(dict(type='tune', changes=dict(nco_hz=101e3)))
        self.assertEqual((await self.recv(viewer, self.of('error')))['code'], 'not_admin')
        await admin.send_json(dict(type='login', password='nope', label='gs'))
        self.assertEqual((await self.recv(admin, self.of('error')))['code'], 'bad_password')
        await admin.send_json(dict(type='login', password='pw', label='gs'))
        role = await self.recv(admin, self.of('role', role='admin'))
        self.assertTrue(role['token'])
        await admin.send_json(dict(type='tune', changes=dict(lo_hz=441.39e6)))
        tuned = await self.recv(viewer, self.of('tuning'))
        self.assertAlmostEqual(tuned['derived']['lo_hz'], 441.39e6, places=0)
        await admin.send_json(dict(type='tune', changes=dict(frac=99999)))
        self.assertEqual((await self.recv(admin, self.of('error')))['code'], 'out_of_range')
        self.server.save_if_dirty()
        self.assertAlmostEqual(freqplan.lo_hz(freqplan.load_state(self.state_path)), 441.39e6, places=0)
        await admin.close()
        await viewer.close()

    async def test_takeover_is_confirmed_and_announced(self):
        a, _ = await self.connect()
        b, _ = await self.connect()
        await a.send_json(dict(type='login', password='pw', label='gs'))
        await self.recv(a, self.of('role', role='admin'))
        await b.send_json(dict(type='login', password='pw', label='phone'))
        need = await self.recv(b, self.of('takeover_required'))
        self.assertEqual(need['held_by'], 'gs')
        await b.send_json(dict(type='login', password='pw', label='phone', takeover=True))
        await self.recv(b, self.of('role', role='admin'))
        demoted = await self.recv(a, self.of('role', reason='taken_over'))
        self.assertEqual((demoted['role'], demoted['by']), ('viewer', 'phone'))
        await a.close()
        await b.close()

    async def test_bad_json_is_reported_not_fatal(self):
        ws, _ = await self.connect()
        await ws.send_str('not json')
        self.assertEqual((await self.recv(ws, self.of('error')))['code'], 'bad_json')
        await ws.send_json(dict(type='ping'))
        await self.recv(ws, self.of('pong'))
        await ws.close()

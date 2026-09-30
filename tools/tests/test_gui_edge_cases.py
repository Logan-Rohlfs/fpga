import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from sdr_cli import freqplan as fp
from sdr_cli.core import DEFAULTS, ToolError, save_config
from sdr_cli.fanout import Outgoing
from sdr_cli.hub import Hub
from sdr_cli.roles import RoleManager
from sdr_cli.sources import ReplaySource, SimSource

try:
    from sdr_cli.web.server import Client, GuiServer, QUEUE_MAX
except ImportError:
    Client = None

class ModelEdges(unittest.TestCase):
    def test_derived_overflow_is_rejected(self):
        for change in ({'carrier_hz':1e20}, {'ref_hz':1e308}, {'lo_hz':1e308}, {'ref_hz':5e-324}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                fp.update(fp.TuningState(),change)

    def test_simulator_reports_unrepresentable_settings(self):
        for change in ({'carrier_hz':3e9}, {'target_if_hz':3e9}):
            state=fp.update(fp.TuningState(),change)
            with self.subTest(change=change), self.assertRaises(ToolError):
                SimSource(lambda:state).step()

    def test_empty_looping_replay_is_rejected(self):
        with tempfile.NamedTemporaryFile() as f, self.assertRaises(ToolError):
            ReplaySource(f.name,loop=True)

    def test_config_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_config(Path(tmp),dict(DEFAULTS))
            self.assertEqual((Path(tmp)/'.sdr/config.json').stat().st_mode & 0o777,0o600)

    def test_reload_can_resume_before_old_socket_closes(self):
        roles=RoleManager();roles.connect('old',True);roles.connect('new',True)
        token=roles.login('old','','test')['token']
        self.assertTrue(roles.resume('new',token))
        roles.disconnect('old')
        self.assertEqual(roles.role('new'),'admin')
        self.assertEqual(roles.role('old'),'viewer')

class SourceErrors(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_source_error_is_reported(self):
        class Broken:
            kind='sim'; responds_to_tuning=True; detail='test'
            async def chunks(self):
                raise RuntimeError('broken source')
                yield b''
        hub=Hub()
        with self.assertLogs('sdr_cli.hub',level='ERROR'):
            await hub.run(Broken())
        self.assertEqual(hub.source['state'],'down')
        self.assertIn('broken source',hub.source['detail'])

    @unittest.skipIf(Client is None, 'aiohttp not installed')
    async def test_slot_flood_never_closes_and_control_is_delivered(self):
        class Socket:
            closed = False
            def __init__(self):
                self.sent = []
            async def close(self, **kwargs):
                self.closed = True
            async def send_str(self, data):
                self.sent.append(json.loads(data))
            async def send_bytes(self, data):
                self.sent.append(bytes(data))
        with tempfile.TemporaryDirectory() as tmp:
            server = GuiServer(lambda tuning: None, RoleManager(), Path(tmp) / 'state.json')
            ws = Socket(); client = Client(ws, True)
            client.outbox.subscribe(['spectrum.A'])
            client.put(dict(type='role', role='viewer'))
            for i in range(5000):
                client.outbox.offer(Outgoing('spectrum.A', 'slot', 'spectrum.A', bytes([1, 1, i % 256])))
            client.put(dict(type='pong'))
            sender = asyncio.ensure_future(server._send_loop(client))
            for _ in range(100):
                if len(ws.sent) >= 3:
                    break
                await asyncio.sleep(0.01)
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        self.assertFalse(ws.closed)
        self.assertEqual(ws.sent, [dict(type='role', role='viewer'), dict(type='pong'), bytes([1, 1, 4999 % 256])])

    @unittest.skipIf(Client is None, 'aiohttp not installed')
    async def test_control_flood_closes_with_1013(self):
        class Socket:
            closed = None
            async def close(self, **kwargs):
                self.closed = kwargs
        ws = Socket(); client = Client(ws, True)
        for _ in range(QUEUE_MAX):
            client.put(dict(type='role', role='viewer'))
        await asyncio.sleep(0)
        self.assertIsNone(ws.closed)
        client.put(dict(type='role', role='viewer'))
        await asyncio.sleep(0)
        self.assertEqual(ws.closed['code'], 1013)

    @unittest.skipIf(Client is None, 'aiohttp not installed')
    async def test_resync_snapshots_and_dropped_notice_at_most_1hz(self):
        from sdr_cli import fanout
        class Socket:
            async def close(self, **kwargs):
                pass
        now = [0.0]
        with tempfile.TemporaryDirectory() as tmp:
            hub = Hub(clock=lambda: now[0], wall=lambda: now[0])
            server = GuiServer(lambda tuning: None, RoleManager(), Path(tmp) / 'state.json', hub=hub,
                               clock=lambda: now[0])
        client = Client(Socket(), True)
        client.outbox = fanout.Outbox('viewer', clock=lambda: now[0])
        box = client.outbox
        box.subscribe(['frames', 'events'])
        for i in range(fanout.STREAM_MAX['viewer'] + 1):
            box.offer(Outgoing('events', 'stream', 'events', 'e%d' % i))
        box.offer(Outgoing('frames', 'stream', 'frames', 'f0'))
        for i in range(3):
            box.offer(Outgoing('frames', 'stream', 'frames', 'f%d' % (i + 1)))   # sampled out: 3 dropped
        server._service(client)
        items = []
        while True:
            item, _ = box.next()
            if item is None:
                break
            items.append(item)
        self.assertEqual(json.loads(items[0]), dict(type='dropped', channel='frames', count=3))
        self.assertEqual(items[1], 'f0')
        self.assertEqual(len(items), 3)
        self.assertIn('"reset":true', items[2])            # fresh events snapshot after the overflow resync
        now[0] = 0.5
        box.offer(Outgoing('frames', 'stream', 'frames', 'f4'))
        box.offer(Outgoing('frames', 'stream', 'frames', 'f5'))   # sampled out: 1 dropped
        self.assertAlmostEqual(server._service(client), 0.5)   # next notice waits for the 1 Hz period
        self.assertEqual(box.next(), ('f4', None))
        self.assertEqual(box.next(), (None, None))
        now[0] = 1.0
        self.assertIsNone(server._service(client))
        self.assertEqual(json.loads(box.next()[0])['count'], 1)

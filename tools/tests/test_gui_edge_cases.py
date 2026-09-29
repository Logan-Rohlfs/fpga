import asyncio
from pathlib import Path
import tempfile
import unittest
from sdr_cli import freqplan as fp
from sdr_cli.core import DEFAULTS, ToolError, save_config
from sdr_cli.hub import Hub
from sdr_cli.roles import RoleManager
from sdr_cli.sources import ReplaySource, SimSource

try:
    from sdr_cli.web.server import Client, QUEUE_MAX
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
    async def test_slow_client_reconnects_instead_of_losing_control_messages(self):
        class Socket:
            closed=False
            async def close(self, **kwargs):
                self.closed=True
        ws=Socket(); client=Client(ws,True)
        client.put(dict(type='role',role='viewer'))
        for _ in range(QUEUE_MAX): client.put(dict(type='spectrum'))
        await asyncio.sleep(0)
        self.assertTrue(ws.closed)

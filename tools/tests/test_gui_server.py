# tools/tests/test_gui_server.py
import asyncio
import errno
import json
import socket
from pathlib import Path
import tempfile
import unittest

from link_samples import rom_flight_frames, sample_stream
from sdr_cli import fanout, gui_wire, protocol as p, roles as r
from sdr_cli import freqplan, sources
from sdr_cli.core import ToolError
from sdr_cli.hub import Hub

try:
    from aiohttp import WSMsgType
    from aiohttp.test_utils import TestClient, TestServer
    from sdr_cli.web import server as web_server
    from sdr_cli.web.server import GuiServer
except ImportError:   # the gui extra is optional
    GuiServer = None


class Idle:
    """A source that never produces data; tests drive the hub directly."""
    kind, responds_to_tuning, detail = 'replay', False, 'idle'

    async def chunks(self):
        await asyncio.sleep(3600)
        yield b''


def best_telem(raw, n):
    return p.encode_message(p.BEST_TELEM, p.build_payload(p.BEST_TELEM, {'t_us': n, 'source': 0, 'raw': raw}),
                            seq=n)


def flight_rows(data):
    """(times) from one FLIGHT_ROWS binary message."""
    kind, _version, _origin, _rsvd, count, n = gui_wire.FLIGHT_HEADER.unpack_from(data)
    assert kind == gui_wire.KIND_FLIGHT and count == len(gui_wire.FIELD_KEYS)
    size = gui_wire.ROW.size
    return [gui_wire.ROW.unpack_from(data, gui_wire.FLIGHT_HEADER.size + i * size)[0] for i in range(n)]


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


class FakeSession:
    """Serial session whose opens follow a shared script; an empty script opens fine."""
    script = []            # shared: each connect() pops an action
    fail_read = False      # one-shot read failure

    def __init__(self, config):
        self.config, self.port = config, config['port']
        self.connected = False

    def connect(self):
        if self.connected:
            return
        action = FakeSession.script.pop(0) if FakeSession.script else 'ok'
        if isinstance(action, Exception):
            raise ToolError('Cannot open {}: {}'.format(self.port, action)) from action
        self.connected = True

    def read(self):
        if FakeSession.fail_read:
            FakeSession.fail_read = False
            self.connected = False
            raise ToolError('UART disconnected') from OSError(errno.EIO, 'I/O error')
        return b''

    def send(self, data):
        pass

    def close(self):
        self.connected = False


def serial_factory(get_tuning):
    return sources.SerialSource(dict(port='/dev/fake0', baud=1000000), session_factory=FakeSession,
                                get_tuning=get_tuning)


def distinct(states):
    out = []
    for s in states:
        if not out or out[-1] != s:
            out.append(s)
    return out


@unittest.skipIf(GuiServer is None, 'aiohttp not installed: pip install -e ".[gui]"')
class GuiServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        static = Path(self.tmp.name) / 'static'
        static.mkdir()
        (static / 'index.html').write_text('<!doctype html><title>test</title>')
        self.static = static
        self.state_path = Path(self.tmp.name) / 'gui_state.json'
        self.server = None
        self.server, self.client = await self.start(
            lambda get_tuning: SampleOnce(lambda: self.server is not None and self.server.clients))

    async def start(self, factory, hub=None, sleep=None):
        roles = r.RoleManager(r.hash_password('pw', iterations=1000))
        server = GuiServer(factory, roles, self.state_path, static_dir=self.static, hub=hub)
        server.BAD_PASSWORD_DELAY_S = 0
        if sleep is not None:
            server.sleep = sleep
        client = TestClient(TestServer(server.app()))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return server, client

    async def next_msg(self, ws):
        """A dict for a text frame, bytes for a binary frame."""
        msg = await ws.receive()
        if msg.type == WSMsgType.TEXT:
            return json.loads(msg.data)
        if msg.type == WSMsgType.BINARY:
            return msg.data
        self.fail('socket closed: {}'.format(msg))

    async def recv(self, ws, predicate, limit=300):
        async def receive():
            for _ in range(limit):
                msg = await self.next_msg(ws)
                if isinstance(msg, dict) and predicate(msg):
                    return msg
            self.fail('expected message not received')
        return await asyncio.wait_for(receive(), 3)

    async def recv_binary(self, ws, limit=300):
        async def receive():
            for _ in range(limit):
                msg = await self.next_msg(ws)
                if isinstance(msg, bytes):
                    return msg
            self.fail('expected binary message not received')
        return await asyncio.wait_for(receive(), 3)

    def of(self, kind, **match):
        return lambda m: m['type'] == kind and all(m.get(k) == v for k, v in match.items())

    async def connect(self, client=None):
        ws = await (client or self.client).ws_connect('/ws')
        hello = await self.recv(ws, self.of('hello'))
        return ws, hello

    async def test_admin_can_explicitly_repair_saved_unsupported_profile(self):
        from dataclasses import replace
        self.server.tuning = replace(self.server.tuning, fs_hz=2_000_000, filter_hz=20_000,
            target_if_hz=120_000, window_hz=20_000, injection='high', nco_hz=700_000)
        self.server.hub.source.update(kind='serial', responds_to_tuning=True)
        viewer, _ = await self.connect()
        await viewer.send_json(dict(type='use_compiled_profile'))
        self.assertEqual((await self.recv(viewer, self.of('error')))['code'], 'not_admin')
        self.assertEqual(self.server.tuning.fs_hz, 2_000_000)
        await viewer.send_json(dict(type='login', password='pw', label='gs'))
        await self.recv(viewer, self.of('role', role='admin'))
        await viewer.send_json(dict(type='use_compiled_profile'))
        fixed = (await self.recv(viewer, self.of('tuning')))['state']
        self.assertEqual([fixed[k] for k in ('fs_hz', 'filter_hz', 'target_if_hz', 'window_hz', 'injection', 'nco_hz')],
                         [1_000_000, 35_000, 100_000, 35_000, 'low', 100_000])
        self.assertEqual(fixed['carrier_hz'], 441_480_000)
        await viewer.close()

    async def test_index_and_hello(self):
        resp = await self.client.get('/')
        self.assertEqual(resp.status, 200)
        ws, hello = await self.connect()
        self.assertEqual(hello['role']['role'], 'viewer')
        self.assertTrue(hello['role']['can_admin'])
        self.assertAlmostEqual(hello['tuning']['derived']['lo_hz'], 441.38e6, places=0)
        self.assertEqual(len(hello['flight_schema']['fields']), 20)
        self.assertEqual(hello['channels'], list(fanout.CHANNELS))
        self.assertEqual((hello['budget'], hello['role']['budget'], hello['sites']), ('viewer', 'viewer', []))
        await ws.send_json(dict(type='login', password='pw', label='gs'))
        role = await self.recv(ws, self.of('role', role='admin'))
        self.assertEqual(role['budget'], 'operator')
        await ws.send_json(dict(type='logout'))
        role = await self.recv(ws, self.of('role', role='viewer'))
        self.assertEqual(role['budget'], 'viewer')
        await ws.close()

    async def test_records_and_spectrum_fan_out(self):
        ws, _ = await self.connect()
        await ws.send_json(dict(type='subscribe', channels=['spectrum.A', 'iq.A']))
        subscribed = await self.recv(ws, self.of('subscribed'))
        self.assertEqual(subscribed['channels'], ['spectrum.A', 'iq.A'])
        spectrum = await self.recv_binary(ws)
        self.assertEqual(spectrum[:3], b'\x01\x01\x00')
        self.assertEqual(len(spectrum), gui_wire.SPECTRUM_HEADER.size + 2 * 256)
        record = await self.recv(ws, lambda m: m['type'] == 'record' and m['record']['type'] == 'IQ_SNAPSHOT')
        self.assertIn('IQ_SNAPSHOT', record['text'])
        await ws.close()

    async def test_subscribe_gets_subscribed_then_binary_spectrum(self):
        ws, _ = await self.connect()
        await ws.send_json(dict(type='subscribe', channels=['spectrum.A', 'link']))
        seen = []
        async def until_binary():
            while not (seen and isinstance(seen[-1], bytes)):
                seen.append(await self.next_msg(ws))
        await asyncio.wait_for(until_binary(), 3)
        kinds = [m['type'] for m in seen if isinstance(m, dict)]
        self.assertIn('subscribed', kinds)
        self.assertNotIn('record', kinds[:kinds.index('subscribed')])
        self.assertEqual(seen[-1][:2], b'\x01\x01')
        await ws.close()

    async def test_unsubscribed_client_gets_only_control_and_stats(self):
        ws, _ = await self.connect()
        seen = []
        async def collect():
            while True:
                seen.append(await self.next_msg(ws))
        task = asyncio.ensure_future(collect())
        for _ in range(100):
            if self.server.hub.decoder.stats['messages']:
                break
            await asyncio.sleep(0.02)
        self.assertTrue(self.server.hub.decoder.stats['messages'])
        await asyncio.sleep(0.7)   # at least one more stats period
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertFalse([m for m in seen if isinstance(m, bytes)])
        self.assertTrue({m['type'] for m in seen} <= {'stats', 'role', 'tuning'}, {m['type'] for m in seen})
        self.assertIn('stats', {m['type'] for m in seen})
        await ws.close()

    async def test_unknown_channel_is_rejected(self):
        ws, _ = await self.connect()
        await ws.send_json(dict(type='subscribe', channels=['link', 'nope']))
        self.assertEqual((await self.recv(ws, self.of('error')))['code'], 'bad_channel')
        await ws.send_json(dict(type='subscribe', channels='link'))
        self.assertEqual((await self.recv(ws, self.of('error')))['code'], 'bad_channel')
        client = next(iter(self.server.clients.values()))
        self.assertEqual(client.outbox.subscribed, frozenset())
        await ws.close()

    async def test_late_viewer_gets_latest_status_at_once(self):
        first, _ = await self.connect()
        await first.send_json(dict(type='subscribe', channels=['link']))
        await self.recv(first, lambda m: m['type'] == 'record' and m['record']['type'] == 'LINK_STATS')
        late, _ = await self.connect()
        await late.send_json(dict(type='subscribe', channels=['link']))
        status = await self.recv(late, lambda m: m['type'] == 'record' and m['record']['type'] == 'STATUS', limit=5)
        self.assertEqual(status['record']['fields']['version'], 2)
        await first.close()
        await late.close()

    async def test_late_join_flight_history_then_live_rows(self):
        now = [1760000000.0]
        hub = Hub(wall=lambda: now[0])
        server, client = await self.start(lambda get_tuning: Idle(), hub=hub)
        frames = rom_flight_frames()
        early, _ = await self.connect(client)
        await early.send_json(dict(type='subscribe', channels=['flight']))
        await self.recv(early, self.of('history', channel='flight'))
        for n in range(40):
            now[0] += 0.05
            hub.feed(best_telem(frames[n], n))
        late, _ = await self.connect(client)
        await late.send_json(dict(type='subscribe', channels=['flight']))
        await self.recv(late, self.of('subscribed'))
        marker = await self.recv(late, self.of('history', channel='flight'))
        self.assertEqual(marker['count'], 40)
        times = []
        while len(times) < 40:
            times += flight_rows(await self.recv_binary(late))
        self.assertEqual(len(times), 40)
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))
        for n in range(40, 50):
            now[0] += 0.05
            hub.feed(best_telem(frames[n], n))
        live = []
        while len(live) < 10:
            live += flight_rows(await self.recv_binary(late))
        self.assertEqual(len(set(times + live)), 50)
        self.assertTrue(all(b > a for a, b in zip(times + live, (times + live)[1:])))
        early_rows = []
        while len(early_rows) < 50:
            early_rows += flight_rows(await self.recv_binary(early))
        self.assertEqual(early_rows, times + live)
        await early.close()
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

    async def test_handler_errors_do_not_drop_the_socket(self):
        ws, _ = await self.connect()
        with self.assertLogs('sdr_cli.web.server', level='ERROR'):
            self.server.roles.resume = lambda client, token: (_ for _ in ()).throw(RuntimeError('test'))
            await ws.send_json(dict(type='resume', token='test'))
            self.assertEqual((await self.recv(ws, self.of('error')))['code'], 'bad_request')
            await ws.send_json(dict(type='ping'))
            await self.recv(ws, self.of('pong'))
        await ws.close()

    async def test_reload_resume_and_logout(self):
        old, _ = await self.connect()
        await old.send_json(dict(type='login', password='pw', label='reload'))
        token = (await self.recv(old, self.of('role', role='admin')))['token']
        new, _ = await self.connect()
        await new.send_json(dict(type='resume', token=token))
        await self.recv(new, self.of('role', role='admin', reason='resumed'))
        await self.recv(old, self.of('role', role='viewer'))
        await old.close()
        await new.send_json(dict(type='tune', changes=dict(nco_hz=101000)))
        self.assertEqual((await self.recv(new,self.of('tuning')))['state']['nco_hz'],101000)
        await new.send_json(dict(type='logout'))
        await self.recv(new,self.of('role',role='viewer',reason='logout'))
        await new.send_json(dict(type='resume',token=token))
        await self.recv(new,self.of('role',role='viewer',reason='resume_failed'))
        await new.close()

    async def test_source_reconnect_waits_for_old_cleanup(self):
        events=[]
        class SlowClose:
            kind='sim'; responds_to_tuning=True; detail='test'
            async def chunks(self):
                events.append('start')
                try:
                    await asyncio.sleep(3600)
                    yield b''
                finally:
                    await asyncio.sleep(0.02)
                    events.append('closed')
        self.server.source_factory=lambda tuning: SlowClose()
        ws,_=await self.connect()
        await ws.send_json(dict(type='login',password='pw',label='test'))
        await self.recv(ws,self.of('role',role='admin'))
        for _ in range(2):
            await ws.send_json(dict(type='reconnect_source'))
            await self.recv(ws,lambda m:m['type']=='stats' and m['source']['kind']=='sim' and m['source']['state']=='running')
        self.assertEqual(events,['start','closed','start'])
        await ws.close()

    # ---- serial supervisor (spec 18)
    def recorder(self, hub):
        """Source dicts from every stats Outgoing, and source_state event texts, before any outbox."""
        stats, events = [], []

        def record(out):
            if out.channel == 'stats':
                stats.append(json.loads(out.data)['source'])
            elif out.channel == 'events':
                events.extend(e['text'] for e in json.loads(out.data)['items'] if e['kind'] == 'source_state')
        hub.subscribe(record)
        return stats, events

    async def until(self, predicate, timeout=3.0):
        async def poll():
            while not predicate():
                await asyncio.sleep(0.01)
        await asyncio.wait_for(poll(), timeout)

    def serial_setup(self, script):
        FakeSession.script, FakeSession.fail_read = list(script), False
        self.addCleanup(setattr, FakeSession, 'script', [])
        self.addCleanup(setattr, FakeSession, 'fail_read', False)

    async def test_serial_supervisor_reports_waiting_busy_running_and_reconnects(self):
        self.serial_setup([OSError(errno.ENOENT, 'No such file or directory'), OSError(errno.EBUSY, 'Resource busy'),
                           'ok'])
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)
        hub = Hub()
        stats, _ = self.recorder(hub)
        server, _ = await self.start(serial_factory, hub=hub, sleep=sleep)
        await self.until(lambda: stats and stats[-1]['state'] == 'running')
        self.assertEqual(distinct([s['state'] for s in stats]), ['waiting', 'busy', 'running'])
        busy = next(s for s in stats if s['state'] == 'busy')
        self.assertIn('/dev/fake0', busy['detail'])
        self.assertIn('another process', busy['detail'])
        self.assertEqual(busy['port'], '/dev/fake0')
        self.assertEqual(busy['retry_in_s'], 1.0)
        self.assertEqual(next(s for s in stats if s['state'] == 'waiting')['retry_in_s'], 0.5)
        mark = len(stats)
        FakeSession.fail_read = True
        await self.until(lambda: stats[-1]['state'] == 'running' and 'reconnecting' in [s['state'] for s in stats[mark:]])
        after = distinct([s['state'] for s in stats[mark:]])
        self.assertEqual(after[after.index('reconnecting'):], ['reconnecting', 'running'])
        reconnecting = next(s for s in stats[mark:] if s['state'] == 'reconnecting')
        self.assertEqual(reconnecting['retry_in_s'], 0.5)
        self.assertIn('UART disconnected', reconnecting['detail'])
        self.assertEqual(sleeps, [0.5, 1.0, 0.5])   # the back-off resets after running
        self.assertNotIn('retry_in_s', stats[-1])

    async def test_only_state_changes_emit_source_state_events(self):
        self.serial_setup([OSError(errno.EBUSY, 'Resource busy'), OSError(errno.EBUSY, 'Resource busy'), 'ok'])
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)
        hub = Hub()
        stats, events = self.recorder(hub)
        await self.start(serial_factory, hub=hub, sleep=sleep)
        await self.until(lambda: stats and stats[-1]['state'] == 'running')
        self.assertEqual(sleeps, [0.5, 1.0])
        self.assertEqual([t.split(' (')[0] for t in events], ['Source busy', 'Source running'])

    async def test_operator_reconnect_cuts_a_long_wait_short(self):
        self.serial_setup([OSError(errno.ENOENT, 'No such file or directory')])
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)
            await asyncio.sleep(3600)
        hub = Hub()
        stats, _ = self.recorder(hub)
        server, client = await self.start(serial_factory, hub=hub, sleep=sleep)
        await self.until(lambda: stats and stats[-1]['state'] == 'waiting')
        viewer, _ = await self.connect(client)
        await viewer.send_json(dict(type='reconnect_source'))
        self.assertEqual((await self.recv(viewer, self.of('error')))['code'], 'not_admin')
        self.assertEqual(stats[-1]['state'], 'waiting')
        operator, _ = await self.connect(client)
        await operator.send_json(dict(type='login', password='pw', label='gs'))
        await self.recv(operator, self.of('role', role='admin'))
        await operator.send_json(dict(type='reconnect_source'))
        await self.until(lambda: stats[-1]['state'] == 'running', timeout=1.0)
        self.assertEqual(sleeps, [0.5])
        await viewer.close()
        await operator.close()

    async def test_replay_does_not_reconnect_after_ended(self):
        made, sleeps = [], []

        class Short:
            kind, responds_to_tuning, detail = 'replay', False, 'short'

            async def chunks(self):
                yield b''

        def factory(get_tuning):
            made.append(1)
            return Short()

        async def sleep(delay):
            sleeps.append(delay)
        hub = Hub()
        stats, _ = self.recorder(hub)
        await self.start(factory, hub=hub, sleep=sleep)
        await self.until(lambda: stats and stats[-1]['state'] == 'ended')
        await asyncio.sleep(0.1)
        self.assertEqual((len(made), sleeps, stats[-1]['state']), (1, [], 'ended'))

    async def test_send_loop_failure_is_logged_and_closes_the_socket(self):
        ws, _ = await self.connect()
        client = next(iter(self.server.clients.values()))

        def broken():
            raise ValueError('encoder bug')
        client.outbox.next = broken
        with self.assertLogs('sdr_cli.web.server', 'ERROR'):
            client.ready.set()
            msg = await asyncio.wait_for(self._until_closed(ws), 3)
        self.assertEqual(msg.type, WSMsgType.CLOSE)
        self.assertEqual(ws.close_code, 1011)

    async def _until_closed(self, ws):
        while True:
            msg = await ws.receive()
            if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING):
                return msg


@unittest.skipIf(GuiServer is None, 'aiohttp not installed: pip install -e ".[gui]"')
class OutsideLoopTest(unittest.TestCase):
    """run_gui builds GuiServer outside any loop; web.run_app then runs it on a new loop."""

    def test_retry_wait_really_waits_on_a_fresh_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = GuiServer(lambda get_tuning: Idle(), r.RoleManager(''), Path(tmp) / 'state.json',
                               static_dir=Path(tmp))
            loop = asyncio.new_event_loop()
            try:
                start = loop.time()
                loop.run_until_complete(server._retry_wait(0.2))
                self.assertGreaterEqual(loop.time() - start, 0.18)

                async def locked():
                    async with server.lock():
                        return True
                self.assertTrue(loop.run_until_complete(locked()))
            finally:
                loop.close()

    def test_supervisor_failure_is_logged_and_reported_down(self):
        class Broken:
            kind, responds_to_tuning, detail, port = 'serial', False, 'broken', '/dev/broken'

            def open(self):
                pass

            def close(self):
                pass

        async def run():
            hub = Hub()

            async def boom(source):
                raise KeyError('bug')
            hub.run = boom
            with tempfile.TemporaryDirectory() as tmp:
                server = GuiServer(lambda get_tuning: Broken(), r.RoleManager(''), Path(tmp) / 's.json',
                                   static_dir=Path(tmp), hub=hub)
                with self.assertLogs('sdr_cli.web.server', 'ERROR'):
                    await server._supervise(Broken())
            return hub.source
        source = asyncio.run(run())
        self.assertEqual(source['state'], 'down')
        self.assertIn('bug', source['detail'])


@unittest.skipIf(GuiServer is None, 'aiohttp not installed: pip install -e ".[gui]"')
class PreflightBindTest(unittest.TestCase):
    def test_port_in_use_raises_and_free_port_passes(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(('127.0.0.1', 0))
            held.listen()
            port = held.getsockname()[1]
            with self.assertRaises(ToolError) as caught:
                web_server.preflight_bind('127.0.0.1', port)
            self.assertIn(str(port), str(caught.exception))
            self.assertIn('--http-port', str(caught.exception))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(('127.0.0.1', 0))
            free = probe.getsockname()[1]
        self.assertIsNone(web_server.preflight_bind('127.0.0.1', free))

    def test_time_wait_connections_do_not_block_a_restart(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # as aiohttp does
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        client = socket.create_connection(('127.0.0.1', port))
        accepted, _ = listener.accept()
        accepted.close()   # the server side closes first, so its port is left in TIME_WAIT
        client.close()
        listener.close()
        self.assertIsNone(web_server.preflight_bind('127.0.0.1', port))

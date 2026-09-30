"""Web GUI server: built static files plus one WebSocket per viewer.

See docs/superpowers/specs/2026-09-29-gui-design.md. All logic lives in the
toolkit-free modules (hub, roles, freqplan, sources); this file is glue.
"""
import asyncio
import json
import logging
from pathlib import Path
import socket
import time
import uuid
import webbrowser

from aiohttp import WSMsgType, web

from .. import __version__, apex, freqplan
from ..core import ToolError
from ..fanout import CHANNELS, Outbox
from ..hub import Hub, dumps
from ..protocol import PROTOCOL_VERSION
from ..roles import ADMIN, RoleManager
from ..sources import from_args

STATIC_DIR = Path(__file__).resolve().parent / 'static'
QUEUE_MAX = 400   # control messages; fanout.CONTROL_MAX enforces it
DROPPED_PERIOD_S = 1.0
LOCAL_ADDRESSES = ('127.0.0.1', '::1')
BUILD_HINT = 'GUI is not built. Run: cd tools/sdr_web && npm install && npm run build'


def error(code, text):
    return dict(type='error', code=code, text=text)


def budget(role):
    """Wire role -> rate budget name sent to clients ('admin' uses the operator budget)."""
    return 'operator' if role == ADMIN else 'viewer'


class Client:
    def __init__(self, ws, local):
        self.id = uuid.uuid4().hex
        self.ws = ws
        self.local = local
        self.outbox = Outbox('viewer')
        self.ready = asyncio.Event()
        self.outbox.on_ready = self.ready.set
        self.closing = False
        self.dropped = 0
        self.dropped_sent = None

    def put(self, msg):
        """Queue an ordered control message (a dict, or a str already encoded)."""
        self.put_encoded(msg if isinstance(msg, str) else dumps(msg))

    def put_encoded(self, text):
        if self.closing:
            return
        self.outbox.control(text)
        if self.outbox.overflowed:
            # A lost role/tuning message is unsafe. Reconnect for an authoritative snapshot.
            self.closing = True
            asyncio.ensure_future(self.ws.close(code=1013, message=b'Slow viewer: reconnect for current state'))

    def set_role(self, role):
        self.outbox.set_role(ADMIN if role == ADMIN else 'viewer')


class GuiServer:
    STATS_PERIOD_S = 0.5
    BAD_PASSWORD_DELAY_S = 1.0

    def __init__(self, source_factory, roles, state_path, static_dir=STATIC_DIR, hub=None, clock=time.monotonic):
        self.source_factory = source_factory
        self.roles = roles
        self.state_path = Path(state_path)
        self.static_dir = Path(static_dir)
        self.tuning = freqplan.load_state(self.state_path)
        self.dirty = False
        self.hub = hub or Hub()
        self.clock = clock
        self.clients = {}
        self.source_task = None
        self.tasks = []
        self.source_lock = asyncio.Lock()
        self.hub.client_counts = self.client_counts
        self.hub.subscribe(self.offer)

    # ---- lifecycle
    def app(self):
        app = web.Application()
        app.router.add_get('/ws', self.websocket)
        app.router.add_get('/', self.index)
        assets = self.static_dir / 'assets'
        if assets.is_dir():
            app.router.add_static('/assets', assets)
        app.on_startup.append(self._start)
        app.on_shutdown.append(self._shutdown)
        return app

    async def index(self, request):
        index = self.static_dir / 'index.html'
        if not index.is_file():
            raise web.HTTPServiceUnavailable(text=BUILD_HINT)
        return web.FileResponse(index)

    async def _start(self, app):
        await self.start_source()
        self.tasks.append(asyncio.ensure_future(self._housekeeping()))

    async def _shutdown(self, app):
        for client in list(self.clients.values()):
            await client.ws.close()
        pending = self.tasks + ([self.source_task] if self.source_task else [])
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.save_if_dirty()

    async def start_source(self):
        async with self.source_lock:
            if self.source_task and not self.source_task.done():
                self.source_task.cancel()
                await asyncio.gather(self.source_task, return_exceptions=True)
            try:
                source = self.source_factory(lambda: self.tuning)
            except ToolError as exc:
                self.hub.set_source(None, 'down', str(exc))
                return
            self.source_task = asyncio.ensure_future(self.hub.run(source))

    async def _housekeeping(self):
        while True:
            await asyncio.sleep(self.STATS_PERIOD_S)
            if self.roles.expire():
                self.broadcast_roles('released')
            self.save_if_dirty()
            self.hub.tick(self.hub.wall())
            self.hub.publish(self.hub.stats_outgoing())

    def save_if_dirty(self):
        """Tuning saves are batched so drags don't write the disk (a Pi SD card) 30 times a second."""
        if self.dirty:
            freqplan.save_state(self.state_path, self.tuning)
            self.dirty = False

    # ---- outgoing
    def offer(self, out):
        """Hub subscriber: the same encoded Outgoing goes to every client's outbox."""
        for client in self.clients.values():
            client.outbox.offer(out)

    def broadcast(self, msg):
        """Ordered control message to every client, encoded once."""
        text = dumps(msg)
        for client in list(self.clients.values()):
            client.put_encoded(text)

    def client_counts(self):
        operators = sum(1 for c in self.clients.values() if self.roles.role(c.id) == ADMIN)
        return dict(operators=operators, viewers=len(self.clients) - operators)

    def tuning_message(self):
        return dict(type='tuning', state=freqplan.to_dict(self.tuning), derived=freqplan.derive(self.tuning))

    def send_tuning(self, clients):
        """Tuning is a latest-wins control slot: a drag never floods the control queue."""
        text = dumps(self.tuning_message())
        for client in clients:
            if not client.closing:
                client.outbox.control_slot('tuning', text)

    def role_message(self, client, reason, **extra):
        """Every role message also moves the client's outbox to the matching rate budget."""
        role = self.roles.role(client.id)
        client.set_role(role)
        return dict(type='role', role=role, budget=budget(role), admin=self.roles.admin_info(),
                    can_admin=self.roles.can_login(client.id), reason=reason, **extra)

    def broadcast_roles(self, reason, skip=()):
        for client in list(self.clients.values()):
            if client.id not in skip:
                client.put(self.role_message(client, reason))

    def _service(self, client):
        """Resync snapshots and the 1 Hz dropped notice. Returns seconds until a notice is due."""
        box = client.outbox
        resync = box.take_resync()
        for channel in [c for c in CHANNELS if c in resync]:
            if channel in box.subscribed:
                box.put_snapshot(channel, self.hub.snapshot(channel))
        client.dropped += box.take_dropped().get('frames', 0)
        if not client.dropped:
            return None
        now = self.clock()
        if client.dropped_sent is not None and now < client.dropped_sent + DROPPED_PERIOD_S:
            return client.dropped_sent + DROPPED_PERIOD_S - now
        client.put(dict(type='dropped', channel='frames', count=client.dropped))
        client.dropped, client.dropped_sent = 0, now
        return None

    async def _send_loop(self, client):
        ws = client.ws
        try:
            while True:
                notice = self._service(client)
                data, wait = client.outbox.next()
                if data is None:
                    if notice is not None:
                        wait = notice if wait is None else min(wait, notice)
                    client.ready.clear()
                    try:
                        await asyncio.wait_for(client.ready.wait(), wait)
                    except asyncio.TimeoutError:
                        pass
                elif isinstance(data, bytes):
                    await ws.send_bytes(data)
                else:
                    await ws.send_str(data)
        except (ConnectionResetError, RuntimeError):
            return

    # ---- incoming
    async def websocket(self, request):
        ws = web.WebSocketResponse(heartbeat=20, compress=True)
        await ws.prepare(request)
        client = Client(ws, request.remote in LOCAL_ADDRESSES)
        self.clients[client.id] = client
        self.roles.connect(client.id, client.local)
        role = self.role_message(client, 'connect')
        client.put(dict(type='hello', server_version=__version__, protocol_version=PROTOCOL_VERSION,
                        source=dict(self.hub.source), role=role, budget=role['budget'],
                        tuning=self.tuning_message(), flight_schema=apex.flight_schema(),
                        channels=list(CHANNELS), sites=[]))
        client.outbox.offer(self.hub.stats_outgoing())
        sender = asyncio.ensure_future(self._send_loop(client))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    client.put(error('bad_json', 'Message is not JSON.'))
                    continue
                if not isinstance(data, dict):
                    client.put(error('bad_json', 'Message must be a JSON object.'))
                    continue
                try:
                    await self.handle(client, data)
                except Exception:
                    logging.getLogger(__name__).exception('GUI message handler failed')
                    client.put(error('bad_request', 'The server could not handle that message.'))
        finally:
            sender.cancel()
            self.clients.pop(client.id, None)
            self.roles.disconnect(client.id)
        return ws

    async def handle(self, client, data):
        kind = data.get('type')
        is_admin = self.roles.role(client.id) == ADMIN
        if kind == 'ping':
            client.put(dict(type='pong'))
        elif kind == 'subscribe':
            self._subscribe(client, data.get('channels'))
        elif kind == 'login':
            await self._login(client, data)
        elif kind == 'resume':
            if self.roles.resume(client.id, data.get('token')):
                client.put(self.role_message(client, 'resumed', token=data.get('token')))
                self.broadcast_roles('admin_changed', skip={client.id})
            else:
                client.put(self.role_message(client, 'resume_failed'))
        elif kind == 'logout':
            if self.roles.logout(client.id):
                self.broadcast_roles('logout')
        elif kind == 'use_compiled_profile':
            if not is_admin:
                client.put(error('not_admin', 'Only the Admin can change tuning.'))
                return
            if self.hub.source.get('kind') != 'serial' or not self.hub.source.get('responds_to_tuning'):
                client.put(error('unsupported', 'No compatible receiver profile has been detected.'))
                return
            # Explicit repair of a saved incompatible profile, never silent normalization.
            changes = dict(fs_hz=1_000_000, filter_hz=35_000, target_if_hz=100_000,
                           window_hz=35_000, injection='low')
            # A saved NCO valid at a higher sample rate also needs an explicit reset.
            if not 0 <= self.tuning.nco_hz < 500_000:
                changes['nco_hz'] = 100_000
            self.tuning = freqplan.update(self.tuning, changes)
            self.dirty = True
            self.send_tuning(self.clients.values())
        elif kind == 'tune':
            if not is_admin:
                client.put(error('not_admin', 'Only the Admin can change tuning.'))
                return
            try:
                new = freqplan.update(self.tuning, data.get('changes'))
                if self.hub.source.get('kind') == 'serial' and self.hub.source.get('responds_to_tuning'):
                    from ..receiver_control import tuning_words
                    tuning_words(new)
            except ValueError as exc:
                client.put(error('out_of_range', str(exc)))
                self.send_tuning([client])
                return
            if new != self.tuning:
                self.tuning, self.dirty = new, True
            self.send_tuning(self.clients.values())
        elif kind == 'reconnect_source':
            if not is_admin:
                client.put(error('not_admin', 'Only the Admin can reconnect the source.'))
                return
            await self.start_source()
        else:
            client.put(error('unknown_type', 'Unknown message type: {}'.format(kind)))

    def _subscribe(self, client, channels):
        if not isinstance(channels, list) or not all(isinstance(c, str) for c in channels):
            client.put(error('bad_channel', 'channels must be a list of channel names.'))
            return
        try:
            added = client.outbox.subscribe(channels)
        except ValueError as exc:
            client.put(error('bad_channel', str(exc)))
            return
        client.put(dict(type='subscribed', channels=[c for c in CHANNELS if c in client.outbox.subscribed]))
        # Same synchronous step as the subscription: no live row can land before its snapshot.
        for channel in [c for c in CHANNELS if c in added]:
            client.outbox.put_snapshot(channel, self.hub.snapshot(channel))

    async def _login(self, client, data):
        result = self.roles.login(client.id, str(data.get('password') or ''), data.get('label'),
                                  bool(data.get('takeover')))
        if result['ok']:
            client.put(self.role_message(client, 'login', token=result['token']))
            demoted = self.clients.get(result['demoted']) if result['demoted'] else None
            if demoted:
                demoted.put(self.role_message(demoted, 'taken_over', by=self.roles.admin_info()['label']))
            self.broadcast_roles('admin_changed', skip={client.id} | ({demoted.id} if demoted else set()))
        elif result['code'] == 'needs_takeover':
            client.put(dict(type='takeover_required', held_by=result['held_by'], since=result['since']))
        elif result['code'] == 'bad_password':
            await asyncio.sleep(self.BAD_PASSWORD_DELAY_S)
            client.put(error('bad_password', 'Wrong Admin password.'))
        else:
            client.put(error('no_password', 'No Admin password is set. Run ./sdr setup --gui-password on the '
                                            'server, or log in from the server machine itself.'))


def lan_addresses():
    """Best-effort IPv4 addresses other devices can use to reach this machine."""
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))   # TEST-NET address; UDP connect sends no packet
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith('127.'))
    except OSError:
        pass
    return sorted(found)


def run_gui(root, config, args):
    if not (STATIC_DIR / 'index.html').is_file():
        raise ToolError(BUILD_HINT)
    factory = from_args(config, args.source, file=args.file, speed=args.speed, loop=args.loop)
    roles = RoleManager(config.get('gui_admin_hash', ''))
    server = GuiServer(factory, roles, root / '.sdr/gui_state.json')
    host = '0.0.0.0' if args.lan else '127.0.0.1'
    url = 'http://127.0.0.1:{}/'.format(args.http_port)
    print('SDR GUI at {} (source: {})'.format(url, args.source))
    if args.lan:
        for address in lan_addresses():
            print('  LAN: http://{}:{}/'.format(address, args.http_port))
        if not roles.password_hash:
            print('  No Admin password is set: only this machine can become Admin (sdr setup --gui-password).')
    else:
        print('  Local only. Add --lan to let other devices on the network connect.')
    print('  Ctrl-C stops the server.')
    app = server.app()

    async def open_browser(app):
        if not args.no_browser:
            asyncio.get_running_loop().call_later(0.3, webbrowser.open, url)

    app.on_startup.append(open_browser)
    web.run_app(app, host=host, port=args.http_port, print=None, access_log=None)

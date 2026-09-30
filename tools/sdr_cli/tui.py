"""A btop-inspired, keyboard-driven terminal dashboard using the same operations as the CLI."""
from collections import deque
import curses
from datetime import datetime
from pathlib import Path
import queue
import shlex
import threading
import time

from .core import ToolError, bitstream, build, program, save_config, simulate
from .display import WaterfallScale
from .protocol import CHANNELS, PROTOCOL_VERSION, SPECTRUM, bin_frequency, describe, power_db
from .serial_io import Session, safe_text


HELP = [
    'c  connect / disconnect UART       r  record / stop raw capture',
    's  simulate RTL                    b  build current sources on Windows',
    'p  program volatile FPGA memory    F  persistent flash (confirmation)',
    'x  text / hex view                 SPACE  freeze / resume display',
    'v  cycle RAW / LINK / SPECTRUM views of pane 03',
    ':  command entry                   ?  help       q  quit',
    '',
    'Commands: connect, disconnect, sim, build, build demo, program, flash, record, stop,',
    '          port DEVICE, baud RATE, send TEXT, send-hex aa 01 ff, clear, quit',
    'Use quotes for text with spaces. Arrow up/down scroll the receive pane.',
    '',
    'Raw recordings: .sdr/captures/ with a companion metadata file.',
    'The FPGA sends COBS-framed link messages at 1 Mbaud. Every current message',
    'is SIMULATED by stand-in producers: no RF, XADC, or demodulation exists yet.',
    'The FPGA has no command receiver.',
    'A host write counts bytes sent; it does not confirm FPGA acceptance.',
    '',
    'Builds include uncommitted RTL. No Git push is needed. Close other serial',
    'monitors before connecting. Programming temporarily disconnects UART.',
    'Press any key to close help.',
]


class Dashboard:
    def __init__(self, screen, root, config):
        self.screen, self.root, self.config = screen, root, config
        self.session = Session(config)
        self.events = deque(maxlen=500)
        self.messages = queue.Queue(maxsize=4000)
        self.worker = None
        self.busy = ''
        self.reconnect = False
        self.hex = False
        self.view = 'raw'
        self.scales = {ch: WaterfallScale() for ch in CHANNELS}
        self.frozen = None
        self.scroll = 0
        self.rates = deque([0.0] * 90, maxlen=90)
        self.rate_at = time.monotonic()
        self.rate_bytes = 0
        self.input = None
        self.confirm = False
        self.help = False
        self.running = True
        self.operation_log = None
        self.log('Ready. Press c to connect, ? for help, or : for commands.')
        self.log('RF stages not implemented; decoded link data is SIMULATED. Press v for LINK view.')

    def log(self, message):
        self.events.append((time.strftime('%H:%M:%S'), safe_text(message)))

    def connect(self):
        if self.busy in ('program', 'flash'):
            raise ToolError('Wait for programming to finish before connecting.')
        self.session.connect()
        self.log('Connected: {} @ {} baud'.format(self.session.port, self.config['baud']))

    def record(self):
        if self.session.capture_file:
            self.session.stop_capture()
            self.log('Recording saved: ' + str(self.session.capture_path))
        else:
            if not self.session.connected:
                raise ToolError('Connect before starting a recording.')
            name = datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.bin'
            self.session.start_capture(self.root / '.sdr/captures' / name)
            self.log('Recording raw bytes to ' + str(self.session.capture_path))

    def start(self, operation):
        if self.busy:
            raise ToolError('Already running {}. Wait for it to finish.'.format(self.busy))
        self.reconnect = self.session.connected and operation in ('program', 'flash')
        if operation in ('program', 'flash'):
            if self.session.capture_file:
                self.record()
            self.session.disconnect()
        folder = self.root / '.sdr/logs'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (datetime.now().strftime('%Y%m%d-%H%M%S-%f-') + operation + '.log')
        self.busy = operation
        self.log('Starting {}. Full log: {}'.format(operation, path.relative_to(self.root)))
        def work():
            error = None
            try:
                with path.open('w') as output:
                    def log(line):
                        output.write(line + '\n')
                        output.flush()
                        # Keep UI memory bounded even when synthesis is very verbose.
                        try:
                            self.messages.put_nowait(('log', line))
                        except queue.Full:
                            pass
                    if operation == 'sim':
                        simulate(self.root, self.config['project'], log)
                    elif operation == 'build':
                        build(self.root, self.config.copy(), log)
                    elif operation == 'build-demo':
                        build(self.root, self.config.copy(), log, demo=True)
                    else:
                        program(self.root, self.config.copy(), persist=operation == 'flash', log=log)
            except Exception as exc:
                error = str(exc)
            self.messages.put(('done', error))
        self.worker = threading.Thread(target=work, name='sdr-' + operation)
        self.worker.start()

    def execute(self, command):
        words = shlex.split(command)
        if not words:
            return
        cmd, args = words[0], words[1:]
        if cmd in ('sim', 'build', 'program') and not args:
            self.start(cmd)
        elif cmd == 'build' and args == ['demo']:
            self.start('build-demo')
        elif cmd == 'flash' and not args:
            if self.busy:
                raise ToolError('Wait for the active operation to finish.')
            self.confirm = True
            self.input = ''
        elif cmd == 'connect' and not args:
            self.connect()
        elif cmd == 'disconnect' and not args:
            self.session.disconnect()
            self.log('UART disconnected.')
        elif cmd == 'record' and not args:
            self.record()
        elif cmd == 'stop' and not args:
            if self.session.capture_file:
                self.record()
        elif cmd in ('port', 'baud') and len(args) == 1:
            if self.busy or self.session.connected:
                raise ToolError('Disconnect UART and wait for operations before changing settings.')
            updated = self.config.copy()
            updated[cmd] = int(args[0]) if cmd == 'baud' else args[0]
            save_config(self.root, updated)
            self.config.update(updated)
            self.log('{} set to {}'.format(cmd, args[0]))
        elif cmd in ('send', 'send-hex') and args:
            data = bytes.fromhex(' '.join(args)) if cmd == 'send-hex' else ' '.join(args).encode()
            self.session.send(data)
            self.log('Sent {} bytes. FPGA command acknowledgement is not implemented.'.format(len(data)))
        elif cmd == 'clear' and not args:
            self.session.lines.clear()
            self.session.hex_lines.clear()
            self.events.clear()
            self.scroll = 0
        elif cmd in ('quit', 'q') and not args:
            if self.busy:
                raise ToolError('Waiting for {}. Quit after it finishes; operation is still running.'.format(self.busy))
            self.running = False
        elif cmd in ('help', '?'):
            self.help = True
        else:
            raise ToolError('Unknown command or arguments. Press ? for available commands.')

    def key(self, key):
        if self.help:
            self.help = False
            return
        if self.input is not None:
            if key == '\x1b':
                self.input = None
                self.confirm = False
            elif key in ('\n', '\r', curses.KEY_ENTER):
                command, confirm = self.input, self.confirm
                self.input = None
                self.confirm = False
                if confirm:
                    if command == 'FLASH':
                        self.start('flash')
                    else:
                        self.log('Persistent flash cancelled.')
                else:
                    self.execute(command)
            elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
                self.input = self.input[:-1]
            elif isinstance(key, str) and key.isprintable() and len(self.input) < 1024:
                self.input += key
            return
        if key == ':':
            self.input = ''
        elif key == '?':
            self.help = True
        elif key == 'x':
            self.hex = not self.hex
            self.frozen = None
            self.scroll = 0
        elif key == 'v':
            self.view = VIEWS[(VIEWS.index(self.view) + 1) % len(VIEWS)]
        elif key == ' ':
            self.frozen = None if self.frozen is not None else self.rx_lines()
        elif key == curses.KEY_UP:
            self.scroll = min(250, self.scroll + 1)
        elif key == curses.KEY_DOWN:
            self.scroll = max(0, self.scroll - 1)
        elif key in ('q', 'c', 's', 'b', 'p', 'r', 'F'):
            commands = dict(q='quit', c='disconnect' if self.session.connected else 'connect',
                            s='sim', b='build', p='program', r='record', F='flash')
            self.execute(commands[key])

    def put(self, y, x, text, color=0, bold=False, width=None):
        h, w = self.screen.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w - 1:
            return
        limit = w - x - 1 if width is None else min(width, w - x - 1)
        if limit <= 0:
            return
        attribute = curses.color_pair(color) | (curses.A_BOLD if bold else 0)
        try:
            self.screen.addnstr(y, x, text, limit, attribute)
        except curses.error:
            pass  # A terminal can resize between getmaxyx and drawing.

    def box(self, y, x, h, w, title, color=1):
        self.put(y, x, '╭' + '─' * (w - 2) + '╮', color)
        for row in range(y + 1, y + h - 1):
            self.put(row, x, '│', color)
            self.put(row, x + w - 1, '│', color)
        self.put(y + h - 1, x, '╰' + '─' * (w - 2) + '╯', color)
        self.put(y, x + 2, ' ' + title + ' ', color, True, w - 5)

    def rx_lines(self):
        if self.hex:
            return list(self.session.hex_lines)
        lines = list(self.session.lines)
        if self.session.pending:
            lines.append(safe_text(self.session.pending))
        return lines

    def draw(self):
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        if h < 26 or w < 86:
            self.put(0, 1, 'SDR // WORKBENCH', 1, True)
            self.put(2, 1, 'Enlarge terminal to at least 86 columns × 26 rows.', 3)
            self.put(4, 1, 'Current: {} × {}. q quits; operations keep running.'.format(w, h))
            self.screen.refresh()
            return
        left = int(w * .61)
        right = w - left - 1
        self.put(0, 1, 'SDR', 1, True)
        self.put(0, 5, '// WORKBENCH', 2, True)
        self.put(0, 23, 'BASYS 3  ·  ' + self.config['project'].upper(), 4)
        self.put(0, w - 22, time.strftime('%Y-%m-%d %H:%M:%S'), 4)
        self.box(2, 0, 7, left, '01 / DEVICE', 1)
        self.box(2, left, 7, right, '02 / WORKFLOW', 2)
        status = 'CONNECTED' if self.session.connected else 'DISCONNECTED'
        self.put(3, 2, '● ' + status, 1 if self.session.connected else 3, True)
        self.put(4, 2, self.session.port or self.config['port'], 0, width=left - 4)
        self.put(5, 2, '{} baud  ·  8N1  ·  USB UART'.format(self.config['baud']), 4)
        link = self.session.link
        if link.status:
            firmware = 'Link protocol v{} · build 0x{:08x} · up {:.0f}s'.format(
                link.status.fields['version'], link.status.fields['build_id'], link.status.fields['uptime_ms'] / 1000)
        else:
            firmware = 'Legacy diagnostic heartbeat observed' if self.session.heartbeats else 'Firmware identity not confirmed'
        self.put(6, 2, firmware, 4, width=left - 4)
        self.put(7, 2, 'Receiver / RF metrics: ' + ('SIMULATED stand-in data' if link.synthetic else 'not implemented'),
                 3, width=left - 4)
        spinner = '◐◓◑◒'[int(time.monotonic() * 5) % 4]
        self.put(3, left + 2, (spinner + ' ' + self.busy.upper()) if self.busy else '● IDLE', 3 if self.busy else 1, True)
        self.put(4, left + 2, 'Build: ' + (self.config['host'] or 'run sdr setup'), 0, width=right - 4)
        try:
            ready = bitstream(self.root, self.config['project']).is_file()
        except (OSError, ToolError):
            ready = False
        self.put(5, left + 2, 'Bitstream: ' + ('available' if ready else 'not built'), 4)
        self.put(6, left + 2, 's simulate   b build   p program', 2, width=right - 4)
        self.put(7, left + 2, 'F persistent flash', 4)
        log_height = 7 if h < 34 else 9
        body_h = h - log_height - 12
        simulated = ' · SIMULATED' if link.synthetic else ''
        if self.view == 'raw':
            self.box(9, 0, body_h, left, '03 / RECEIVE · ' + ('HEX' if self.hex else 'TEXT'), 1)
        else:
            self.box(9, 0, body_h, left, '03 / ' + self.view.upper() + simulated, 1)
        self.box(9, left, body_h, right, '04 / TRAFFIC', 2)
        visible = body_h - 3
        if self.view == 'raw':
            lines = self.frozen if self.frozen is not None else self.rx_lines()
            end = max(0, len(lines) - self.scroll)
            shown = lines[max(0, end - visible):end]
            if not lines:
                shown = ['Waiting for UART data…', '', 'c connect   x text/hex   v views   r record']
            for i, line in enumerate(shown[:visible]):
                self.put(10 + i, 2, line, 0 if lines else 4, width=left - 4)
            state = 'FROZEN (capture continues)' if self.frozen is not None else ('SCROLL -' + str(self.scroll) if self.scroll else 'LIVE')
        else:
            rows = self.link_rows(left - 4) if self.view == 'link' else self.spectrum_rows(left - 4, visible)
            for i, (line, color) in enumerate(rows[:visible]):
                self.put(10 + i, 2, line, color, width=left - 4)
            state = 'v next view'
        self.put(9 + body_h - 1, 3, ' ' + state + ' ', 3 if self.frozen is not None else 1)
        rate = self.rates[-1]
        self.put(10, left + 2, '{:,.0f} B/s RX'.format(rate), 1, True, right - 4)
        bars = '▁▂▃▄▅▆▇█'
        values = list(self.rates)[-(right - 5):]
        peak = max(1, max(values))
        graph = ''.join(bars[min(7, int(v / peak * 7))] if v else '▁' for v in values)
        self.put(11, left + 2, graph, 1, width=right - 4)
        self.put(12, left + 2, '1s/bin · peak {:,.0f} B/s'.format(peak if peak > 1 else max(values)), 4, width=right - 4)
        d = self.session.decoder.stats
        errors = d['crc_errors'] + d['cobs_errors'] + d['length_errors']
        stats = [('RX {:,} B    TX {:,} B'.format(self.session.rx_bytes, self.session.tx_bytes), 4),
                 ('Capture: ' + ('REC {:,} B'.format(self.session.capture_bytes) if self.session.capture_file else 'off'),
                  3 if self.session.capture_file else 4),
                 ('Link msgs {:,}  err {}  gaps {}'.format(d['messages'], errors, d['seq_gaps']),
                  3 if errors or d['seq_gaps'] else 1)]
        rates = sorted(link.rates().items())
        stats += [('  '.join('{} {:.1f}/s'.format(n.replace('_', ' ').title().replace(' ', ''), v)
                             for n, v in rates[i:i + 2]), 4) for i in range(0, len(rates), 2)]
        for i, (line, color) in enumerate(stats):
            if 14 + i < 9 + body_h - 1:
                self.put(14 + i, left + 2, line, color, width=right - 4)
        log_y = 9 + body_h
        self.box(log_y, 0, log_height, w - 1, '05 / EVENTS & BUILD OUTPUT', 2)
        for i, (stamp, message) in enumerate(list(self.events)[-(log_height - 2):]):
            self.put(log_y + 1 + i, 2, stamp, 4)
            self.put(log_y + 1 + i, 11, message, 3 if 'failed' in message.lower() or 'error' in message.lower() else 0, width=w - 15)
        self.put(h - 3, 1, 'c connect  s sim  b build  p program  r record  v view  x hex  SPACE freeze  : command  ? help  q quit', 2, width=w - 3)
        if self.input is not None:
            prompt = 'Write persistent flash? Type FLASH: ' if self.confirm else ': '
            value = prompt + self.input
            self.put(h - 2, 1, value[-(w - 4):], 3 if self.confirm else 1, True)
        else:
            self.put(h - 2, 1, '2-GFSK telemetry  ·  link protocol v{}  ·  RF pipeline pending (data SIMULATED)'.format(
                PROTOCOL_VERSION), 4)
        if self.help:
            width = min(w - 6, 82)
            height = len(HELP) + 2
            top, x = (h - height) // 2, (w - width) // 2
            for row in range(top, top + height):
                self.put(row, x, ' ' * width, width=width)
            self.box(top, x, height, width, 'KEYS & COMMANDS', 1)
            for i, line in enumerate(HELP):
                self.put(top + 1 + i, x + 2, line, 0, width=width - 4)
        self.screen.refresh()

    def link_rows(self, width):
        link = self.session.link
        if not self.session.decoder.stats['messages']:
            return [('No link messages decoded yet.', 4), ('', 0),
                    ('Expecting COBS frames at {} baud. An older bitstream sends SDR READY'.format(self.config['baud']), 4),
                    ('at 115200 instead: rebuild/program, or view RAW text.', 4)]
        col = max(10, (width - 14) // 2)
        latest = {}
        for frame in reversed(link.frames):
            latest.setdefault(frame.fields['channel'], frame)
        def cell(ch, fmt, key, source=None):
            record = (source or link.metrics).get(ch)
            if not record:
                return '—'
            value = fmt.format(record.fields[key])
            return value + record.fields.get('power_unit', 'dBm') if key in ('rssi_dbm', 'noise_dbm') else value
        rows = [('{:<14}{:>{c}}{:>{c}}'.format('', 'CHANNEL A', 'CHANNEL B', c=col), 1)]
        for label, fmt, key, source in [('Signal', '{:.1f}', 'rssi_dbm', None), ('Noise', '{:.1f}', 'noise_dbm', None),
                                        ('SNR dB', '{:.1f}', 'snr_db', None), ('Freq off Hz', '{:+d}', 'freq_offset_hz', None),
                                        ('Sync quality', '{:.2f}', 'quality', latest), ('CRC good', '{:,}', 'crc_good', None),
                                        ('CRC bad', '{:,}', 'crc_bad', None), ('Sync hits', '{:,}', 'sync_hits', None)]:
            rows.append(('{:<14}{:>{c}}{:>{c}}'.format(label, cell('A', fmt, key, source), cell('B', fmt, key, source), c=col), 0))
        rows.append(('', 0))
        if link.link_stats:
            f = link.link_stats.fields
            rows.append(('BEST STREAM  from A {:,} · from B {:,} · both ok {:,} · neither {:,}'.format(
                f['from_a'], f['from_b'], f['both_ok'], f['neither_ok']), 1))
        else:
            rows.append(('BEST STREAM', 1))
        rows += [(describe(r), 0) for r in list(link.best)[-3:]]
        rows.append(('RECENT CHANNEL FRAMES', 1))
        rows += [(describe(r), 3 if not r.fields['crc_ok'] else 4) for r in list(link.frames)[-6:]]
        return rows

    def spectrum_rows(self, width, height):
        link = self.session.link
        half = max(4, (width - 3) // 2)
        wf_height = max(1, (height - 2) // 2)
        history = {ch: list(link.spectrum.get(ch, []))[::-1] for ch in CHANNELS}
        def title(ch):
            if not history[ch]:
                return 'WATERFALL ' + ch
            f = history[ch][0].fields
            return 'WATERFALL {} {:.1f}–{:.1f} kHz ↑new'.format(
                ch, bin_frequency(f, 0) / 1e3, bin_frequency(f, f['bins'] - 1) / 1e3)
        rows = [('{:<{w}} │ {}'.format(title('A'), title('B'), w=half), 1)]
        for n in range(wf_height):
            a, b = [shade_row(power_db(history[ch][n].fields), half, self.scales[ch]) if n < len(history[ch]) else ''
                    for ch in CHANNELS]
            rows.append(('{:<{w}} │ {}'.format(a, b, w=half), 0))
        a, b = ['{} {:.0f}…{:.0f} dBFS'.format(self.scales[ch].mode, self.scales[ch].low, self.scales[ch].high)
                for ch in CHANNELS]
        rows.append(('{:<{w}} │ {}'.format(a, b, w=half), 4))
        iq_height = max(3, height - wf_height - 3)
        snaps = [link.iq.get(ch) for ch in CHANNELS]
        points = [p for s in snaps if s for p in s.fields['iq']]
        scale = max([1] + [max(abs(i), abs(q)) for i, q in points])
        rows.append(('{:<{w}} │ {}'.format('CONSTELLATION A', 'CONSTELLATION B', w=half), 1))
        # Terminal cells are about twice as tall as wide: keep the plot roughly square.
        plot_w = min(half, 2 * iq_height + 1)
        pad = ' ' * ((half - plot_w) // 2)
        grids = [constellation(s.fields['iq'] if s else [], plot_w, iq_height, scale) for s in snaps]
        rows += [('{:<{w}} │ {}'.format(pad + grids[0][n], pad + grids[1][n], w=half), 2) for n in range(iq_height)]
        return rows

    def loop(self):
        self.screen.nodelay(True)
        self.screen.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            palette = [(1, 80), (2, 111), (3, 221), (4, 245)] if curses.COLORS >= 256 else [
                (1, curses.COLOR_CYAN), (2, curses.COLOR_BLUE), (3, curses.COLOR_YELLOW), (4, curses.COLOR_WHITE)]
            for number, color in palette:
                curses.init_pair(number, color, background)
        try:
            self.connect()
        except ToolError as exc:
            self.log(str(exc))
        try:
            while self.running:
                try:
                    self.session.read()
                    for record in self.session.last_records:
                        if record.type == SPECTRUM and record.fields['channel'] in self.scales:
                            self.scales[record.fields['channel']].update(power_db(record.fields))
                    now = time.monotonic()
                    if now - self.rate_at >= 1:
                        self.rates.append((self.session.rx_bytes - self.rate_bytes) / (now - self.rate_at))
                        self.rate_bytes, self.rate_at = self.session.rx_bytes, now
                    for _ in range(200):
                        try:
                            kind, value = self.messages.get_nowait()
                        except queue.Empty:
                            break
                        if kind == 'log':
                            self.log(value)
                        else:
                            operation, self.busy = self.busy, ''
                            self.log(operation + (' failed: ' + value if value else ' completed.'))
                            if self.reconnect:
                                self.reconnect = False
                                self.connect()
                    for _ in range(128):
                        try:
                            key = self.screen.get_wch()
                        except curses.error:
                            break
                        self.key(key)
                except (ToolError, ValueError, OSError) as exc:
                    self.log('Error: ' + str(exc))
                except KeyboardInterrupt:
                    if self.busy:
                        self.log('Operation still running; quit after it finishes.')
                    else:
                        self.running = False
                self.draw()
                time.sleep(.05)
        finally:
            self.session.close()


VIEWS = ('raw', 'link', 'spectrum')
SHADES = ' .:-=+*#%@'


def shade_row(row_db, width, scale):
    """Downsample dB bins to width characters (segment peak), shaded by the waterfall scale."""
    if not row_db or width <= 0:
        return ''
    n = len(row_db)
    out = []
    for c in range(width):
        a = c * n // width
        b = max(a + 1, (c + 1) * n // width)
        level = scale.normalize(max(row_db[a:b]))
        out.append(SHADES[min(len(SHADES) - 1, int(level * len(SHADES)))])
    return ''.join(out)


def constellation(iq, width, height, scale):
    grid = [[' '] * width for _ in range(height)]
    cx, cy = (width - 1) / 2, (height - 1) / 2
    for x in range(width):
        grid[int(round(cy))][x] = '·'
    for y in range(height):
        grid[y][int(round(cx))] = '·'
    for i, q in iq:
        x = int(round(cx + i / scale * cx))
        y = int(round(cy - q / scale * cy))
        grid[min(height - 1, max(0, y))][min(width - 1, max(0, x))] = 'o'
    return [''.join(row) for row in grid]


def launch(root, config):
    curses.wrapper(lambda screen: Dashboard(screen, root, config).loop())

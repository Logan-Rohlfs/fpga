"""Raw UART transport shared by the CLI and dashboard."""
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .core import ToolError


def serial_module():
    try:
        import serial
        return serial
    except ImportError as exc:
        raise ToolError('pyserial is missing. Install with: python3 -m pip install -e .') from exc


def ports():
    serial_module()
    from serial.tools import list_ports
    return sorted(list_ports.comports(), key=lambda port: port.device)


def resolve_port(configured):
    if configured and configured != 'auto':
        return configured
    found = ports()
    # Basys 3 FT2232: channel A is JTAG, B is UART. Never guess among boards.
    candidates = [p.device for p in found if p.vid == 0x0403 and p.pid == 0x6010 and
                  (p.device.endswith('1') or ' B' in (p.interface or '') or
                   (p.location or '').endswith(':1.1'))]
    if len(candidates) == 1:
        return candidates[0]
    raise ToolError('Cannot select a unique Basys 3 UART. Run sdr ports, then sdr setup --port DEVICE.')


def safe_text(data):
    text = data.decode('utf-8', errors='replace') if isinstance(data, (bytes, bytearray)) else str(data)
    return ''.join(c if c.isprintable() else (' ' if c == '\t' else '.') for c in text)


class Session:
    def __init__(self, config):
        self.config = config
        self.serial = None
        self.port = ''
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.started = None
        self.last_rx = None
        self.capture_file = None
        self.capture_path = None
        self.capture_bytes = 0
        self.lines = deque(maxlen=300)
        self.hex_lines = deque(maxlen=300)
        self.pending = bytearray()
        self.heartbeats = 0

    @property
    def connected(self):
        return self.serial is not None

    def connect(self):
        if self.connected:
            return
        serial = serial_module()
        self.port = resolve_port(self.config['port'])
        try:
            options = dict(baudrate=self.config['baud'], timeout=0, write_timeout=1)
            import os
            if os.name != 'nt':
                options['exclusive'] = True
            self.serial = serial.Serial(self.port, **options)
        except (OSError, serial.SerialException) as exc:
            raise ToolError('Cannot open {}: {}'.format(self.port, exc)) from exc
        self.started = time.monotonic()
        self.heartbeats = 0
        self.pending.clear()

    def disconnect(self):
        if self.serial is not None:
            self.serial.close()
            self.serial = None
        self.pending.clear()

    def read(self):
        if not self.connected:
            return b''
        try:
            data = self.serial.read(min(65536, max(1, self.serial.in_waiting)))
        except (OSError, serial_module().SerialException) as exc:
            self.disconnect()
            raise ToolError('UART disconnected: {}'.format(exc)) from exc
        if data:
            self.rx_bytes += len(data)
            self.last_rx = time.monotonic()
            if self.capture_file:
                try:
                    self.capture_file.write(data)
                    self.capture_bytes += len(data)
                except OSError as exc:
                    self.stop_capture()
                    raise ToolError('Recording failed: {}'.format(exc)) from exc
            for offset in range(0, len(data), 16):
                chunk = data[offset:offset + 16]
                self.hex_lines.append('{}  {}'.format(chunk.hex(' '), safe_text(chunk)))
            self.pending.extend(data)
            while b'\n' in self.pending:
                line, _, rest = self.pending.partition(b'\n')
                self.pending = bytearray(rest)
                if line.rstrip(b'\r') == b'SDR READY':
                    self.heartbeats += 1
                line = line.rstrip(b'\r')
                self.lines.append(safe_text(line[:512]) + (' …' if len(line) > 512 else ''))
            while len(self.pending) > 256:
                self.lines.append(safe_text(self.pending[:256]))
                del self.pending[:256]
        return data

    def send(self, data):
        if not self.connected:
            raise ToolError('Connect to UART first.')
        try:
            count = self.serial.write(data)
            if count != len(data):
                raise ToolError('Only {} of {} bytes were sent.'.format(count, len(data)))
            self.tx_bytes += count
        except (OSError, serial_module().SerialException) as exc:
            raise ToolError('UART write failed: {}'.format(exc)) from exc

    def start_capture(self, path):
        if self.capture_file:
            raise ToolError('A recording is already active.')
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            capture = path.open('xb')
        except OSError as exc:
            raise ToolError('Cannot create recording: {}'.format(exc)) from exc
        self.capture_file = capture
        self.capture_path = path
        self.capture_bytes = 0
        metadata = dict(started_at=datetime.now(timezone.utc).isoformat(),
                        port=self.port or self.config['port'], baud=self.config['baud'], format='raw UART bytes')
        try:
            path.with_suffix(path.suffix + '.json').write_text(json.dumps(metadata, indent=2) + '\n')
        except OSError:
            self.stop_capture()
            raise

    def stop_capture(self):
        if self.capture_file:
            try:
                self.capture_file.close()
            finally:
                self.capture_file = None

    def close(self):
        try:
            self.stop_capture()
        finally:
            self.disconnect()

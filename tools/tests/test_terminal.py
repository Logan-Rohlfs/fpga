"""Exercise curses in a real terminal and serial link, without FPGA hardware."""
import json
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipIf(os.name == 'nt', 'Uses Unix pseudo terminals')
class TerminalTest(unittest.TestCase):
    def test_dashboard_uart_command_and_resize(self):
        import fcntl
        import pty
        import termios
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            (root / 'scripts/build.tcl').write_text('# test checkout')
            (root / '.sdr').mkdir()
            master, slave = pty.openpty()
            uart_master, uart_slave = pty.openpty()
            for fd in (master, slave, uart_master, uart_slave):
                self.addCleanup(os.close, fd)
            (root / '.sdr/config.json').write_text(json.dumps({'port': os.ttyname(uart_slave), 'baud': 115200}))
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 120, 0, 0))
            environment = dict(os.environ, TERM='xterm-256color', LANG='en_US.UTF-8',
                               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
            process = subprocess.Popen([sys.executable, '-m', 'sdr_cli.cli', '--repo', str(root)],
                                       stdin=slave, stdout=slave, stderr=slave, env=environment,
                                       start_new_session=True)
            output = bytearray()
            def collect(seconds):
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    if select.select([master], [], [], .025)[0]:
                        try:
                            output.extend(os.read(master, 65536))
                        except OSError:
                            break
            try:
                collect(.4)
                os.write(uart_master, b'SDR READY\r\n')
                collect(.2)
                os.write(master, b':send-hex aa 00 ff\n')
                collect(1.3)  # one key is consumed per UI frame
                self.assertTrue(select.select([uart_master], [], [], 1)[0], output[-3000:])
                self.assertEqual(os.read(uart_master, 3), b'\xaa\x00\xff')
                os.write(master, b'?')
                collect(.1)
                os.write(master, b'\x1b')
                collect(.1)
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 20, 70, 0, 0))
                os.kill(process.pid, signal.SIGWINCH)
                collect(.2)
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 120, 0, 0))
                os.kill(process.pid, signal.SIGWINCH)
                collect(.2)
                os.write(master, b'q')
                collect(.2)
                self.assertEqual(process.wait(timeout=5), 0, output[-3000:])
                text = output.decode(errors='replace')
                self.assertNotIn('Traceback', text)
                for expected in ('WORKBENCH', 'SDR READY', 'KEYS & COMMANDS', 'Enlarge terminal'):
                    self.assertIn(expected, text)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)


@unittest.skipIf(os.name == 'nt', 'Uses Unix pseudo terminals')
class LinkTerminalTest(unittest.TestCase):
    """Decoded link data through the real CLI entry point and dashboard."""

    def setUp(self):
        import pty
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/build.tcl').write_text('# test checkout')
        (self.root / '.sdr').mkdir()
        self.uart_master, uart_slave = pty.openpty()
        self.addCleanup(os.close, self.uart_master)
        self.addCleanup(os.close, uart_slave)
        (self.root / '.sdr/config.json').write_text(json.dumps({'port': os.ttyname(uart_slave), 'baud': 115200}))
        self.environment = dict(os.environ, TERM='xterm-256color', LANG='en_US.UTF-8',
                                PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parents[1]),
                                                            str(Path(__file__).resolve().parent)]))
        from link_samples import sample_stream
        self.stream = sample_stream()

    def test_receive_prints_decoded_records_and_summary(self):
        process = subprocess.Popen([sys.executable, '-m', 'sdr_cli.cli', '--repo', str(self.root), 'receive',
                                    '--seconds', '1.5'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=self.environment)
        time.sleep(.5)
        os.write(self.uart_master, self.stream)
        out, err = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, err)
        out, err = out.decode(), err.decode()
        for expected in ('STATUS', 'BEST_TELEM', 'CHAN_FRAME   B crc=BAD', 'CHAN_METRICS A', 'LINK_STATS',
                         'SPECTRUM', 'IQ_SNAPSHOT', 'APEX TEST seq=2', '[SIMULATED]'):
            self.assertIn(expected, out)
        self.assertIn('crc_err=0', err)
        self.assertIn('SIMULATED (stand-in FPGA producers', err)

    def test_dashboard_link_and_spectrum_views(self):
        import fcntl
        import pty
        import termios
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 120, 0, 0))
        process = subprocess.Popen([sys.executable, '-m', 'sdr_cli.cli', '--repo', str(self.root)],
                                   stdin=slave, stdout=slave, stderr=slave, env=self.environment,
                                   start_new_session=True)
        output = bytearray()
        def collect(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if select.select([master], [], [], .025)[0]:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError:
                        break
        try:
            collect(.4)
            os.write(self.uart_master, self.stream)
            collect(.3)
            os.write(master, b'v')
            collect(.3)
            link_view = len(output)
            os.write(master, b'v')
            collect(.3)
            os.write(master, b'q')
            collect(.3)
            self.assertEqual(process.wait(timeout=5), 0, output[-3000:])
            before = output[:link_view].decode(errors='replace')
            after = output[link_view:].decode(errors='replace')
            self.assertNotIn('Traceback', before + after)
            # curses repaints only changed cells, so check distinctive tokens per view.
            for expected in ('LINK · SIMULATED', 'CHANNEL A', 'CHANNEL B', 'BEST STREAM', 'Link protocol v1',
                             'SIMULATED stand-in data'):
                self.assertIn(expected, before)
            for expected in ('SPECTRUM', 'WATERFALL A', 'CONSTELLATION B'):
                self.assertIn(expected, after)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()

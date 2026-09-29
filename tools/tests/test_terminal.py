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
            (root / '.sdr/config.json').write_text(json.dumps({'port': os.ttyname(uart_slave)}))
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


if __name__ == '__main__':
    unittest.main()

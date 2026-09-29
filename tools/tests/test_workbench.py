import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from sdr_cli import core
from sdr_cli.serial_io import Session, resolve_port, safe_text


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, content in [('scripts/build.tcl', 'build'), ('projects/sdr/rtl/top.sv', 'module top; endmodule'),
                              ('projects/sdr/constraints/basys3.xdc', 'pins'), ('key.txt', 'DO NOT UPLOAD'),
                              ('command.txt', 'DO NOT UPLOAD')]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.config = dict(core.DEFAULTS, host='100.73.154.107', user='logan')

    def test_snapshot_excludes_personal_files_and_matches_digest(self):
        archive = self.root / 'snapshot.zip'
        digest = core.snapshot(self.root, 'sdr', archive)
        with zipfile.ZipFile(archive) as output:
            self.assertEqual(set(output.namelist()), {'scripts/build.tcl', 'projects/sdr/rtl/top.sv',
                                                      'projects/sdr/constraints/basys3.xdc'})
        self.assertEqual(digest, core.source_digest(self.root, 'sdr'))
        (self.root / 'projects/sdr/rtl/top.sv').write_text('changed')
        self.assertNotEqual(digest, core.source_digest(self.root, 'sdr'))

    def test_config_roundtrip_and_validation(self):
        core.save_config(self.root, self.config)
        self.assertEqual(core.load_config(self.root), self.config)
        for field, value in [('host', '-oProxyCommand=anything'), ('user', 'a; b'),
                              ('remote_root', 'C:/a/../b'), ('baud', 0)]:
            with self.subTest(field=field), self.assertRaises(core.ToolError):
                core.save_config(self.root, dict(self.config, **{field: value}))

    def test_powershell_quoting(self):
        import base64
        script = 'Write-Output ' + core.ps_literal("C:/Logan's folder/vivado.bat")
        command = core.ps_command(script)
        self.assertEqual(base64.b64decode(command.split()[-1]).decode('utf-16le'), script)
        self.assertIn("Logan''s", script)

    def fake_copy(self, args, **kwargs):
        if args[0] == 'scp' and args[-2].endswith('/drc.rpt'):
            destination = Path(args[-1])
            for name in ('sdr.bit', 'timing.rpt', 'utilization.rpt', 'drc.rpt'):
                (destination / name).write_bytes(b'new bitstream or report')

    def test_build_publishes_complete_bundle_and_detects_stale_source(self):
        with patch.object(core, 'remote'), patch.object(core, 'run', side_effect=self.fake_copy):
            bit = core.build(self.root, self.config, log=lambda _: None)
        self.assertEqual(core.bitstream(self.root, 'sdr'), bit)
        self.assertTrue(bit.with_name('manifest.json').exists())
        with patch.object(core, 'run') as run:
            core.program(self.root, self.config, log=lambda _: None)
            self.assertNotIn('-f', run.call_args.args[0])
        (self.root / 'projects/sdr/rtl/top.sv').write_text('changed')
        with patch.object(core, 'run') as run, self.assertRaisesRegex(core.ToolError, 'Sources have changed'):
            core.program(self.root, self.config, log=lambda _: None)
        run.assert_not_called()

    def test_failed_build_does_not_replace_previous_bitstream(self):
        old = self.root / 'build/sdr/sdr.bit'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'known good')
        with patch.object(core, 'remote', side_effect=core.ToolError('Vivado failed')):
            with self.assertRaises(core.ToolError):
                core.build(self.root, self.config, log=lambda _: None)
        self.assertEqual(core.bitstream(self.root, 'sdr').read_bytes(), b'known good')
        self.assertFalse((old.parent / 'latest').exists())

    def test_corrupt_selected_bitstream_is_never_programmed(self):
        with patch.object(core, 'remote'), patch.object(core, 'run', side_effect=self.fake_copy):
            bit = core.build(self.root, self.config, log=lambda _: None)
        bit.write_bytes(b'corrupted')
        with patch.object(core, 'run') as run, self.assertRaisesRegex(core.ToolError, 'checksum'):
            core.program(self.root, self.config, log=lambda _: None)
        run.assert_not_called()

    def test_download_failure_preserves_previous_bundle(self):
        with patch.object(core, 'remote'), patch.object(core, 'run', side_effect=self.fake_copy):
            original = core.build(self.root, self.config, log=lambda _: None)
        with patch.object(core, 'remote'), patch.object(core, 'run', side_effect=core.ToolError('copy failed')):
            with self.assertRaises(core.ToolError):
                core.build(self.root, self.config, log=lambda _: None)
        self.assertEqual(core.bitstream(self.root, 'sdr'), original)

    def test_process_failure_propagates(self):
        import sys
        with self.assertRaisesRegex(core.ToolError, 'exit 7'):
            core.run([sys.executable, '-c', 'raise SystemExit(7)'], log=lambda _: None)


@unittest.skipIf(os.name == 'nt', 'PTY integration uses Unix pseudo terminals')
class SerialTest(unittest.TestCase):
    def setUp(self):
        import pty
        self.master, self.slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        self.session = Session(dict(core.DEFAULTS, port=os.ttyname(self.slave)))
        self.session.connect()
        self.addCleanup(self.session.close)

    def read_until(self, count):
        end = time.monotonic() + 1
        data = b''
        while len(data) < count and time.monotonic() < end:
            data += self.session.read()
            time.sleep(.005)
        self.assertEqual(len(data), count)
        return data

    def test_fragmented_receive_capture_and_binary_transmit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'capture.bin'
            self.session.start_capture(path)
            os.write(self.master, b'SDR RE')
            self.read_until(6)
            self.assertEqual(self.session.heartbeats, 0)
            os.write(self.master, b'ADY\r\n\x00\xff\x1b[31m\n')
            self.read_until(len(b'ADY\r\n\x00\xff\x1b[31m\n'))
            self.assertEqual(self.session.heartbeats, 1)
            self.assertEqual(self.session.lines[0], 'SDR READY')
            self.assertNotIn('\x1b', ''.join(self.session.lines))
            self.session.stop_capture()
            self.assertEqual(path.read_bytes(), b'SDR READY\r\n\x00\xff\x1b[31m\n')
            self.assertTrue(path.with_suffix('.bin.json').is_file())
            with self.assertRaises(core.ToolError):
                self.session.start_capture(path)
        self.session.send(b'\xaa\x00\xff')
        self.assertEqual(os.read(self.master, 3), b'\xaa\x00\xff')
        self.assertEqual(self.session.tx_bytes, 3)

    def test_binary_stream_has_bounded_display_buffer(self):
        for _ in range(10):
            os.write(self.master, b'X' * 1000)
            self.read_until(1000)
        self.assertLessEqual(len(self.session.pending), 256)
        self.assertLessEqual(len(self.session.hex_lines), 300)


class PortTest(unittest.TestCase):
    def port(self, device):
        from types import SimpleNamespace
        return SimpleNamespace(device=device, vid=0x0403, pid=0x6010, interface=None, location=None)

    def test_auto_selects_uart_not_jtag_and_rejects_ambiguity(self):
        with patch('sdr_cli.serial_io.ports', return_value=[self.port('/dev/cu.A0'), self.port('/dev/cu.A1')]):
            self.assertEqual(resolve_port('auto'), '/dev/cu.A1')
        with patch('sdr_cli.serial_io.ports', return_value=[self.port('/dev/cu.A1'), self.port('/dev/cu.B1')]):
            with self.assertRaises(core.ToolError):
                resolve_port('auto')

    def test_terminal_controls_suppressed(self):
        self.assertNotIn('\x1b', safe_text(b'\x1b[2J'))


class DashboardTest(unittest.TestCase):
    def setUp(self):
        from sdr_cli.tui import Dashboard
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ui = Dashboard(None, Path(self.temp.name), core.DEFAULTS.copy())

    def test_flash_needs_exact_confirmation(self):
        with patch.object(self.ui, 'start') as start:
            self.ui.execute('flash')
            self.assertTrue(self.ui.confirm)
            start.assert_not_called()
            for key in 'yes\n':
                self.ui.key(key)
            start.assert_not_called()
            self.ui.execute('flash')
            for key in 'FLASH\n':
                self.ui.key(key)
            start.assert_called_once_with('flash')

    def test_busy_quit_rejected_and_freeze_is_snapshot(self):
        self.ui.busy = 'build'
        with self.assertRaises(core.ToolError):
            self.ui.execute('quit')
        self.assertTrue(self.ui.running)
        self.ui.session.lines.append('first')
        self.ui.key(' ')
        self.ui.session.lines.append('second')
        self.assertEqual(self.ui.frozen, ['first'])
        self.ui.key(' ')
        self.assertIsNone(self.ui.frozen)

    def test_port_edit_is_saved_and_does_not_run_shell(self):
        self.ui.execute('port /dev/example')
        self.assertEqual(core.load_config(self.ui.root)['port'], '/dev/example')
        with self.assertRaises(core.ToolError):
            self.ui.execute('rm -rf anything')


if __name__ == '__main__':
    unittest.main()

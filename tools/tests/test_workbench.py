import json
import os
from pathlib import Path
import re
import tempfile
import threading
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

    def test_snapshot_includes_rom_images_like_build_tcl(self):
        rom = self.root / 'projects/sdr/rom'
        rom.mkdir()
        (rom / 'flight.mem').write_text('02\n')
        (rom / 'notes.txt').write_text('not a build input')
        names = [p.relative_to(self.root).as_posix() for p in core.source_files(self.root, 'sdr')]
        self.assertIn('projects/sdr/rom/flight.mem', names)
        self.assertNotIn('projects/sdr/rom/notes.txt', names)
        repo = Path(__file__).resolve().parents[2]
        tcl = (repo / 'scripts/build.tcl').read_text()
        self.assertIn('rom] *.mem', tcl)
        self.assertIn('read_mem', tcl)

    def test_demo_build_passes_variant_and_records_it(self):
        scripts, lines = [], []
        with patch.object(core, 'remote', side_effect=lambda config, script, log: scripts.append(script)), \
                patch.object(core, 'run', side_effect=self.fake_copy):
            bit = core.build(self.root, self.config, log=lambda _: None, demo=True)
        self.assertRegex(scripts[-1], r'-tclargs sdr demo \d+;')
        self.assertEqual(json.loads(bit.with_name('manifest.json').read_text())['variant'], 'demo')
        self.assertEqual(core.bitstream(self.root, 'sdr', demo=True), bit)
        with patch.object(core, 'run'):
            core.program(self.root, self.config, log=lines.append, demo=True)
        self.assertFalse(any('demo variant' in line for line in lines))  # the demo was asked for
        with patch.object(core, 'remote', side_effect=lambda config, script, log: scripts.append(script)), \
                patch.object(core, 'run', side_effect=self.fake_copy):
            bit = core.build(self.root, self.config, log=lambda _: None)
        self.assertRegex(scripts[-1], r'-tclargs sdr default \d+;')
        self.assertEqual(json.loads(bit.with_name('manifest.json').read_text())['variant'], 'default')

    def test_demo_build_is_sdr_only(self):
        with patch.object(core, 'remote') as remote, self.assertRaisesRegex(core.ToolError, 'sdr project'):
            core.build(self.root, dict(self.config, project='blink'), log=lambda _: None, demo=True)
        remote.assert_not_called()

    def test_cli_build_demo_flag(self):
        from sdr_cli import cli
        self.assertTrue(cli.parser().parse_args(['build', '--demo']).demo)
        self.assertFalse(cli.parser().parse_args(['build']).demo)

    def test_cli_parallel_build_flags(self):
        from sdr_cli import cli
        args = cli.parser().parse_args(['build', '--all', '--cores', '8'])
        self.assertTrue(args.all)
        self.assertEqual(args.cores, 8)
        self.assertFalse(cli.parser().parse_args(['build']).all)
        self.assertTrue(cli.parser().parse_args(['program', '--demo']).demo)
        with self.assertRaises(SystemExit), patch('sys.stderr'):
            cli.parser().parse_args(['build', '--all', '--demo'])

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
        # macOS pseudo-terminals reject nonstandard rates such as the 1 Mbaud default.
        self.session = Session(dict(core.DEFAULTS, port=os.ttyname(self.slave), baud=115200))
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

    def test_session_decodes_link_messages(self):
        from link_samples import sample_stream
        data = sample_stream()
        for offset in range(0, len(data), 97):   # arbitrary fragmentation
            os.write(self.master, data[offset:offset + 97])
            self.read_until(len(data[offset:offset + 97]))
        stats = self.session.decoder.stats
        self.assertEqual(stats['messages'], len(self.session.records))
        self.assertEqual(stats['crc_errors'] + stats['cobs_errors'] + stats['seq_gaps'], 0)
        self.assertEqual(set(stats['by_type']), {'STATUS', 'BEST_TELEM', 'CHAN_FRAME', 'CHAN_METRICS',
                                                 'LINK_STATS', 'SPECTRUM', 'IQ_SNAPSHOT'})
        link = self.session.link
        self.assertTrue(link.synthetic)
        self.assertEqual(link.status.fields['build_id'], 0x1234)
        self.assertEqual(len(link.spectrum['B']), 4)
        self.assertEqual(sorted(link.metrics), ['A', 'B'])

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

    def test_build_demo_command_uses_shared_build(self):
        with patch.object(self.ui, 'start') as start:
            self.ui.execute('build demo')
            start.assert_called_once_with('build-demo')
        with patch('sdr_cli.tui.build') as build:
            self.ui.start('build-demo')
            self.ui.worker.join(5)
        self.assertTrue(build.call_args.kwargs['demo'])

    def test_port_edit_is_saved_and_does_not_run_shell(self):
        self.ui.execute('port /dev/example')
        self.assertEqual(core.load_config(self.ui.root)['port'], '/dev/example')
        with self.assertRaises(core.ToolError):
            self.ui.execute('rm -rf anything')


class ParallelBuildTest(RepositoryTest):
    def test_thread_count_clamps(self):
        self.assertEqual(core.thread_count(12, 1), 8)
        self.assertEqual(core.thread_count(12, 2), 6)
        self.assertEqual(core.thread_count(12, 3), 4)
        self.assertEqual(core.thread_count(4, 2), 2)
        self.assertEqual(core.thread_count(1, 2), 1)
        self.assertEqual(core.thread_count(64, 2), 8)

    def test_host_cores_from_remote_override_and_fallback(self):
        def reply(text):
            return lambda config, script, log: log(text)
        with patch.object(core, 'remote', side_effect=reply('CORES=12')) as remote:
            self.assertEqual(core.host_cores(self.config), 12)
            self.assertIn('NUMBER_OF_PROCESSORS', remote.call_args.args[1])
        with patch.object(core, 'remote', side_effect=reply('CORES=16')):
            self.assertEqual(core.host_cores(self.config), 16)
        with patch.object(core, 'remote') as remote:
            self.assertEqual(core.host_cores(dict(self.config, host_cores=6)), 6)
            remote.assert_not_called()
        for side in (core.ToolError('ssh down'), None):
            lines = []
            with patch.object(core, 'remote', side_effect=side or reply('garbage')):
                self.assertEqual(core.host_cores(self.config, lines.append), 12)
            self.assertTrue(any('assuming 12' in line for line in lines))

    def test_host_cores_config_validation(self):
        for bad in (-1, 'x', 2000, True):
            with self.subTest(bad=bad), self.assertRaises(core.ToolError):
                core.validate_config(dict(self.config, host_cores=bad))
        core.validate_config(dict(self.config, host_cores=0))

    def test_build_tcl_takes_thread_argument(self):
        repo = Path(__file__).resolve().parents[2]
        tcl = (repo / 'scripts/build.tcl').read_text()
        self.assertIn('set_param general.maxThreads $threads', tcl)
        self.assertNotRegex(tcl, r'maxThreads\s+\d')

    def test_single_build_uses_one_build_share(self):
        scripts = []
        with patch.object(core, 'remote', side_effect=lambda c, s, log: scripts.append(s)), \
                patch.object(core, 'run', side_effect=self.fake_copy), \
                patch.object(core, 'host_cores', return_value=12):
            bit = core.build(self.root, self.config, log=lambda _: None)
        self.assertIn('-tclargs sdr default 8;', scripts[-1])
        self.assertEqual(json.loads(bit.with_name('manifest.json').read_text())['threads'], 8)

    def test_invalid_thread_count_is_rejected_before_remote_work(self):
        with patch.object(core, 'remote') as remote, self.assertRaisesRegex(core.ToolError, 'threads'):
            core.build(self.root, self.config, log=lambda _: None, threads=9)
        remote.assert_not_called()

    def run_parallel(self, cores=12, fail_variant=None):
        scripts, lines, uploads = {}, [], []
        lock = threading.Lock()
        both_in_vivado = threading.Barrier(2, timeout=10)

        def fake_remote(config, script, log):
            match = re.search(r'-tclargs sdr (\w+) (\d+);', script)
            if match:
                with lock:
                    scripts[match.group(1)] = (script, int(match.group(2)))
                log('vivado output')
                both_in_vivado.wait()  # proves the builds overlap
                if match.group(1) == fail_variant:
                    raise core.ToolError('Vivado failed')
            elif 'Directory' in script:
                with lock:
                    uploads.append(re.findall(r"'([^']+)'", script)[-1])

        def fake_run(args, **kwargs):
            self.fake_copy(args, **kwargs)

        with patch.object(core, 'remote', side_effect=fake_remote), \
                patch.object(core, 'run', side_effect=fake_run), \
                patch.object(core, 'host_cores', return_value=cores) as detect:
            try:
                result = core.build_variants(self.root, self.config, log=lines.append)
            except core.ToolError as exc:
                result = exc
        return result, scripts, lines, uploads, detect

    def test_parallel_build_isolates_paths_threads_and_pointers(self):
        result, scripts, lines, uploads, detect = self.run_parallel()
        self.assertEqual(set(result), {'default', 'demo'})
        detect.assert_called_once()  # cores read once per invocation
        self.assertEqual({v: s[1] for v, s in scripts.items()}, {'default': 6, 'demo': 6})
        self.assertEqual(len(set(uploads)), 2)  # distinct remote directories
        self.assertNotEqual(result['default'].parent, result['demo'].parent)
        self.assertEqual(core.bitstream(self.root, 'sdr'), result['default'])
        self.assertEqual(core.bitstream(self.root, 'sdr', demo=True), result['demo'])
        for variant, bit in result.items():
            manifest = json.loads(bit.with_name('manifest.json').read_text())
            self.assertEqual((manifest['variant'], manifest['threads']), (variant, 6))
        self.assertEqual(sorted(p.name for p in (self.root / 'build/sdr').glob('*.tmp')), [])
        for variant in ('default', 'demo'):
            self.assertTrue(any(line.startswith('[{}] '.format(variant)) for line in lines))
        self.assertTrue(all(line.startswith('[') or not line.startswith(' ') for line in lines))
        # both programs stay unambiguous and pass their own freshness check
        for demo in (False, True):
            with patch.object(core, 'run') as run:
                core.program(self.root, self.config, log=lambda _: None, demo=demo)
            self.assertEqual(Path(run.call_args.args[0][-1]), result['demo' if demo else 'default'])

    def test_parallel_threads_follow_core_count(self):
        _, scripts, *_ = self.run_parallel(cores=4)
        self.assertEqual({s[1] for s in scripts.values()}, {2})
        _, scripts, *_ = self.run_parallel(cores=1)
        self.assertEqual({s[1] for s in scripts.values()}, {1})

    def test_parallel_failure_keeps_other_build_and_reports(self):
        result, _, lines, *_ = self.run_parallel(fail_variant='demo')
        self.assertIsInstance(result, core.ToolError)
        self.assertIn('demo', str(result))
        self.assertTrue(any(line.startswith('[demo] FAILED') for line in lines))
        self.assertTrue(core.bitstream(self.root, 'sdr').is_file())  # default completed
        with self.assertRaisesRegex(core.ToolError, 'No demo build'):
            core.bitstream(self.root, 'sdr', demo=True)

    def test_source_change_check_is_per_build(self):
        lines = []

        def fake_remote(config, script, log):
            if '-tclargs' in script and 'demo' in script:
                (self.root / 'projects/sdr/rtl/top.sv').write_text('changed mid-build')

        with patch.object(core, 'remote', side_effect=fake_remote), \
                patch.object(core, 'run', side_effect=self.fake_copy), \
                patch.object(core, 'host_cores', return_value=12):
            core.build(self.root, self.config, log=lines.append, demo=True, threads=6)
        self.assertTrue(any('Sources changed during this build' in line for line in lines))

    def test_parallel_demo_needs_sdr_project(self):
        with patch.object(core, 'remote') as remote, self.assertRaisesRegex(core.ToolError, 'sdr project'):
            core.build_variants(self.root, dict(self.config, project='blink'), log=lambda _: None)
        remote.assert_not_called()

    def test_baseexception_in_worker_is_reported_not_keyerror(self):
        def fake_remote(config, script, log):
            if 'demo' in script and '-tclargs' in script:
                raise KeyboardInterrupt()

        with patch.object(core, 'remote', side_effect=fake_remote), \
                patch.object(core, 'run', side_effect=self.fake_copy), \
                patch.object(core, 'host_cores', return_value=12):
            with self.assertRaisesRegex(core.ToolError, 'demo'):
                core.build_variants(self.root, self.config, log=lambda _: None)

    def test_interrupt_terminates_children_and_reports_cancelled(self):
        import sys
        started = threading.Event()
        lines = []
        real_join = threading.Thread.join
        calls = []

        def fake_remote(config, script, log):
            if '-tclargs' in script:
                # a real child process, like the ssh that runs Vivado
                started.set()
                core.run([sys.executable, '-c', 'import time; time.sleep(60)'], log=log)

        def interrupting_join(self, timeout=None):
            if timeout is None and not calls:
                calls.append(1)
                started.wait(10)
                time.sleep(0.3)
                raise KeyboardInterrupt()
            return real_join(self, timeout)

        with patch.object(core, 'remote', side_effect=fake_remote), \
                patch.object(core, 'run', side_effect=core.run), \
                patch.object(core, 'host_cores', return_value=12), \
                patch.object(threading.Thread, 'join', interrupting_join):
            begin = time.time()
            with self.assertRaises(KeyboardInterrupt):
                core.build_variants(self.root, self.config, log=lines.append)
        self.assertLess(time.time() - begin, 20)
        self.assertTrue(any(l.startswith('Cancelled:') and 'may keep running' in l for l in lines))
        self.assertFalse(any(t.name.startswith('sdr-build-') and t.is_alive() for t in threading.enumerate()))
        self.assertFalse(core._cancelled)

    def test_program_notice_only_when_default_selected_but_demo(self):
        with patch.object(core, 'remote'), patch.object(core, 'run', side_effect=self.fake_copy), \
                patch.object(core, 'host_cores', return_value=12):
            bit = core.build(self.root, self.config, log=lambda _: None, demo=True, threads=8)
        (bit.parent.parent.parent / 'latest').write_text(bit.parent.name + '\n')  # legacy shared pointer
        notices = []
        with patch.object(core, 'run'):
            core.program(self.root, self.config, log=notices.append)
        self.assertTrue(any('no --demo' in n for n in notices))
        notices.clear()
        with patch.object(core, 'run'):
            core.program(self.root, self.config, log=notices.append, demo=True)
        self.assertFalse(any('Selected build' in n for n in notices))

    def test_tui_commands_start_the_same_operations(self):
        from sdr_cli import tui
        dash = tui.Dashboard.__new__(tui.Dashboard)
        started = []
        dash.start = started.append
        for command in ('build all', 'program demo', 'build demo'):
            tui.Dashboard.execute(dash, command)
        self.assertEqual(started, ['build-all', 'program-demo', 'build-demo'])


if __name__ == '__main__':
    unittest.main()

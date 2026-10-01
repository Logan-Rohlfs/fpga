# tools/tests/test_sources.py
import errno
from pathlib import Path
import tempfile
import unittest

import re

from link_samples import rom_flight_frames, sample_stream
from sdr_cli import apex, freqplan, protocol as p, sources
from sdr_cli.core import ToolError


def decode(data):
    decoder = p.StreamDecoder()
    return decoder, decoder.feed(data)


class ApexFrameTest(unittest.TestCase):
    def test_build_test_frame(self):
        self.assertTrue(apex.parse_frame(apex.build_test_frame(5))['crc_ok'])
        self.assertFalse(apex.parse_frame(apex.build_test_frame(5, good=False))['crc_ok'])
        self.assertEqual(apex.parse_frame(apex.build_test_frame(5))['fields']['text'], 'APEX RADIO TEST')


class SimSourceTest(unittest.TestCase):
    def setUp(self):
        self.state = freqplan.TuningState()
        self.sim = sources.SimSource(lambda: self.state, seed=1)

    def run_ticks(self, n):
        return b''.join(self.sim.step() for _ in range(n))

    def peak_hz(self, records, channel='A'):
        row = [r for r in records if r.type == p.SPECTRUM and r.fields['channel'] == channel][-1].fields
        k = max(range(row['bins']), key=row['power'].__getitem__)
        return p.bin_frequency(row, k)

    def test_all_types_decode_cleanly_and_are_synthetic(self):
        decoder, records = decode(self.run_ticks(40))
        s = decoder.stats
        self.assertEqual((s['crc_errors'], s['cobs_errors'], s['length_errors'], s['seq_gaps']), (0, 0, 0, 0))
        self.assertEqual({r.name for r in records}, set(p.TYPE_NAMES.values()) - {'CONFIG'})
        self.assertTrue(all(r.synthetic for r in records))
        frames = [r for r in records if r.type == p.CHAN_FRAME]
        self.assertTrue(frames and all(r.fields['apex']['kind'] == 'TEST' for r in frames))

    def test_spectrum_follows_the_lo(self):
        _, records = decode(self.run_ticks(2))   # carrier + 10.4 kHz bench offset → IF 110.4 kHz, lobes ±25 kHz
        self.assertLess(min(abs(self.peak_hz(records) - f) for f in (85.4e3, 135.4e3)), 1.5e3)
        self.state = freqplan.with_lo(self.state, freqplan.lo_hz(self.state) + 10e3)
        _, records = decode(self.run_ticks(2))
        self.assertLess(min(abs(self.peak_hz(records) - f) for f in (75.4e3, 125.4e3)), 1.5e3)

    def test_losing_the_signal_stops_frames(self):
        self.state = freqplan.with_lo(self.state, freqplan.lo_hz(self.state) - 100e3)   # IF 210 kHz
        _, records = decode(self.run_ticks(4))
        self.assertFalse([r for r in records if r.type in (p.CHAN_FRAME, p.BEST_TELEM)])
        metrics = [r for r in records if r.type == p.CHAN_METRICS][-1].fields
        self.assertLess(metrics['rssi_dbm'], -105)


class ReplaySourceTest(unittest.IsolatedAsyncioTestCase):
    async def collect(self, source, limit=10 ** 6):
        out = b''
        async for chunk in source.chunks():
            out += chunk
            if len(out) >= limit:
                break
        return out

    async def test_replays_exact_bytes_and_loops(self):
        data = sample_stream()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'capture.bin'
            path.write_bytes(data)
            self.assertEqual(await self.collect(sources.ReplaySource(path, speed=0)), data)
            looped = await self.collect(sources.ReplaySource(path, speed=0, loop=True), limit=2 * len(data))
            self.assertEqual(looped[:2 * len(data)], data * 2)

    def test_rejects_missing_file_and_negative_speed(self):
        with self.assertRaises(ToolError):
            sources.ReplaySource('/nonexistent/capture.bin')
        with tempfile.NamedTemporaryFile() as f, self.assertRaises(ToolError):
            sources.ReplaySource(f.name, speed=-1)


class FakeSession:
    def __init__(self, config):
        self.config = config
        self.port = 'fake0'
        self.pending = [b'ab', b'', b'cd']
        self.closed = False

    def connect(self):
        pass

    def read(self):
        if not self.pending:
            raise ToolError('UART disconnected: unplugged')
        return self.pending.pop(0)

    def close(self):
        self.closed = True


class SerialSourceTest(unittest.IsolatedAsyncioTestCase):
    async def test_yields_reads_until_error_and_closes(self):
        source = sources.SerialSource(dict(port='auto', baud=1000000), session_factory=FakeSession)
        out = b''
        with self.assertRaises(ToolError):
            async for chunk in source.chunks():
                out += chunk
        self.assertEqual(out, b'abcd')
        self.assertTrue(source.session.closed)
        self.assertEqual(source.detail, 'fake0 @ 1000000 baud')


class BackoffTest(unittest.TestCase):
    def test_sequence_and_reset(self):
        backoff = sources.Backoff()
        self.assertEqual([backoff.next() for _ in range(6)], [0.5, 1, 2, 4, 8, 8])
        backoff.reset()
        self.assertEqual([backoff.next() for _ in range(2)], [0.5, 1])


class ClassifyOpenErrorTest(unittest.TestCase):
    def chained(self, cause):
        try:
            raise ToolError('Cannot open /dev/x') from cause
        except ToolError as exc:
            return exc

    def test_errno_of_the_cause(self):
        self.assertEqual(sources.classify_open_error(
            self.chained(OSError(errno.ENOENT, 'No such file or directory'))), 'missing')
        self.assertEqual(sources.classify_open_error(self.chained(OSError(errno.ENXIO, 'Device not configured'))),
                         'missing')
        self.assertEqual(sources.classify_open_error(self.chained(OSError(errno.EBUSY, 'Resource busy'))), 'busy')
        self.assertEqual(sources.classify_open_error(self.chained(OSError(errno.EACCES, 'Permission denied'))),
                         'denied')
        self.assertEqual(sources.classify_open_error(self.chained(OSError(errno.EPERM, 'Operation not permitted'))),
                         'denied')

    def test_message_text(self):
        self.assertEqual(sources.classify_open_error(ToolError(
            "could not open port COM4: PermissionError(13, 'Access is denied.')")), 'busy')
        self.assertEqual(sources.classify_open_error(ToolError(
            'Cannot open /dev/x: could not open port /dev/x: No such file or directory')), 'missing')
        self.assertEqual(sources.classify_open_error(ValueError('x')), 'other')
        # port 'auto' with no board attached
        self.assertEqual(sources.classify_open_error(ToolError(
            'Cannot select a unique Basys 3 UART. Run sdr ports, then sdr setup --port DEVICE.')), 'missing')

    def test_exclusive_lock_conflict_is_busy(self):
        # pyserial's posix exclusive=True flock fails with EAGAIN when another process holds the port.
        self.assertEqual(sources.classify_open_error(self.chained(OSError(
            errno.EAGAIN, 'Could not exclusively lock port /dev/x: [Errno 35] Resource temporarily unavailable'))),
            'busy')


class FactoryTest(unittest.TestCase):
    def test_from_args(self):
        config = dict(port='auto', baud=1000000)
        self.assertIsInstance(sources.from_args(config, 'sim')(freqplan.TuningState), sources.SimSource)
        self.assertIsInstance(sources.from_args(config, 'serial')(None), sources.SerialSource)
        self.assertIsInstance(sources.from_args(config, 'demo')(freqplan.TuningState), sources.DemoSource)
        with self.assertRaises(ToolError):
            sources.from_args(config, 'replay')
        with self.assertRaises(ToolError):
            sources.from_args(config, 'radio')


SDR_TOP = Path(__file__).resolve().parents[2] / 'projects/sdr/rtl/sdr_top.sv'
RTL = Path(__file__).resolve().parents[2] / 'projects/sdr/rtl/receiver_link_sources.sv'


def rtl_constant(name, rtl=None):
    return int(re.search(r'\b' + name + r'=(\d+)', (rtl or RTL).read_text()).group(1))


class DemoSourceTest(unittest.TestCase):
    """Host stand-in for the demo bitstream (DEMO_FLIGHT=1): the ROM frames, loss windows and loop."""

    def setUp(self):
        self.demo = sources.DemoSource(lambda: freqplan.TuningState(), seed=1)

    def slots(self, first, count):
        self.demo.tick = first
        _, records = decode(b''.join(self.demo.step() for _ in range(count)))
        return records

    def test_profile_constants_match_the_rtl(self):
        self.assertEqual(len(self.demo.rom), rtl_constant('FLIGHT_ROM_FRAMES'))
        self.assertEqual(sources.DEMO_GAP_SLOTS, rtl_constant('FLIGHT_GAP_SLOTS'))
        self.assertEqual(sources.DEMO_LOSS['A'], (rtl_constant('FLIGHT_LOSS_A_FIRST'), rtl_constant('FLIGHT_LOSS_A_LAST')))
        self.assertEqual(sources.DEMO_LOSS['B'], (rtl_constant('FLIGHT_LOSS_B_FIRST'), rtl_constant('FLIGHT_LOSS_B_LAST')))

    def test_spectrum_uses_the_demo_bitstream_dft_length(self):
        bins = rtl_constant('SPECTRUM_BINS', SDR_TOP)   # sdr_top sets the bitstream's DFT length
        self.assertEqual(sources.DEMO_SPEC_BINS, bins)
        rows = [r for r in self.slots(0, 4) if r.type == p.SPECTRUM]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(len(r.fields['power']), bins)
            self.assertEqual(r.fields['bin_hz'], 100000 / bins)
        # The plain simulator keeps its own 256-bin model.
        sim = sources.SimSource(lambda: freqplan.TuningState(), seed=1)
        _, recs = decode(b''.join(sim.step() for _ in range(4)))
        self.assertEqual({len(r.fields['power']) for r in recs if r.type == p.SPECTRUM}, {256})

    def test_rom_frames_in_order_synthetic_with_the_demo_build_id(self):
        records = self.slots(0, 40)
        self.assertTrue(all(r.synthetic for r in records))
        status = [r for r in records if r.type == p.STATUS]
        self.assertTrue(status and all(r.fields['build_id'] == 0x53445246 for r in status))
        best = [r for r in records if r.type == p.BEST_TELEM]
        self.assertEqual([r.fields['raw'] for r in best], rom_flight_frames()[:40])
        self.assertTrue(all(r.fields['apex']['kind'] == 'FLIGHT' for r in best))
        metrics = [r for r in records if r.type == p.CHAN_METRICS]
        self.assertTrue(metrics and all(r.fields['power_unit'] == 'dBFS' for r in metrics))
        self.assertEqual({r.name for r in records}, set(p.TYPE_NAMES.values()) - {'CONFIG'})

    def test_loss_windows_drop_one_antenna_and_best_covers(self):
        first, last = sources.DEMO_LOSS['A']
        records = self.slots(first, last - first + 1)
        frames = [r for r in records if r.type == p.CHAN_FRAME]
        self.assertEqual({r.fields['channel'] for r in frames}, {'B'})
        best = [r for r in records if r.type == p.BEST_TELEM]
        self.assertEqual(len(best), last - first + 1)
        self.assertTrue(all(r.fields['source'] == 'B' for r in best))

    def test_gap_then_loop_back_to_frame_zero(self):
        n = len(self.demo.rom)
        records = self.slots(n - 1, sources.DEMO_GAP_SLOTS + 2)
        best = [r.fields['raw'] for r in records if r.type == p.BEST_TELEM]
        self.assertEqual(best, [rom_flight_frames()[n - 1], rom_flight_frames()[0]])

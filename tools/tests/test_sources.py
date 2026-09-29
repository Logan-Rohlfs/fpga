# tools/tests/test_sources.py
from pathlib import Path
import tempfile
import unittest

from link_samples import sample_stream
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
        self.assertEqual({r.name for r in records}, set(p.TYPE_NAMES.values()))
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


class FactoryTest(unittest.TestCase):
    def test_from_args(self):
        config = dict(port='auto', baud=1000000)
        self.assertIsInstance(sources.from_args(config, 'sim')(freqplan.TuningState), sources.SimSource)
        self.assertIsInstance(sources.from_args(config, 'serial')(None), sources.SerialSource)
        with self.assertRaises(ToolError):
            sources.from_args(config, 'replay')
        with self.assertRaises(ToolError):
            sources.from_args(config, 'radio')

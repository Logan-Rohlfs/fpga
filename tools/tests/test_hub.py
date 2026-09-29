# tools/tests/test_hub.py
import json
import unittest

from link_samples import sample_messages, sample_stream
from sdr_cli.core import ToolError
from sdr_cli.hub import Hub


class HubTest(unittest.TestCase):
    def test_feed_turns_records_into_client_messages(self):
        hub = Hub()
        seen = []
        hub.subscribe(seen.append)
        messages = hub.feed(sample_stream())
        self.assertEqual(len(messages), len(sample_messages()))
        self.assertEqual(seen, messages)
        spectrum = [m for m in messages if m['type'] == 'spectrum']
        self.assertEqual(len(spectrum), 8)
        first = spectrum[0]
        self.assertEqual((first['channel'], first['bins'], len(first['db10'])), ('A', 256, 256))
        self.assertAlmostEqual(first['f0_hz'], 50000.0)
        self.assertEqual(first['db10'][90], -500)      # power 140 → −120 + 70 = −50 dBFS
        self.assertLess(first['low'], first['high'])
        records = [m for m in messages if m['type'] == 'record']
        self.assertEqual(records[0]['record']['type'], 'STATUS')
        self.assertIn('STATUS', records[0]['text'])
        json.dumps(messages)

    def test_snapshot_replays_latest_slow_records(self):
        hub = Hub()
        self.assertEqual(hub.snapshot(), [])
        hub.feed(sample_stream())
        kinds = [m['record']['type'] for m in hub.snapshot()]
        self.assertEqual(kinds, ['STATUS', 'LINK_STATS', 'CHAN_METRICS', 'CHAN_METRICS', 'IQ_SNAPSHOT', 'IQ_SNAPSHOT',
                                 'BEST_TELEM'])

    def test_unsubscribe(self):
        hub = Hub()
        seen = []
        stop = hub.subscribe(seen.append)
        stop()
        hub.feed(sample_stream())
        self.assertEqual(seen, [])

    def test_stats_and_byte_rate(self):
        now = [100.0]
        hub = Hub(clock=lambda: now[0])
        hub.feed(b'\x00' * 1000)
        self.assertAlmostEqual(hub.byte_rate(), 200.0)
        stats = hub.stats_message()
        json.dumps(stats)
        self.assertEqual(stats['decoder']['bytes'], 1000)
        now[0] += 6
        self.assertEqual(hub.byte_rate(), 0.0)

    def test_isolates_subscribers_from_failures(self):
        hub = Hub()
        seen = []
        hub.subscribe(lambda msg: (_ for _ in ()).throw(OSError('subscriber failure')))
        hub.subscribe(seen.append)
        with self.assertLogs('sdr_cli.hub', level='ERROR'):
            messages = hub.feed(sample_stream())
        self.assertEqual(len(seen), len(messages))


class Once:
    kind, responds_to_tuning, detail = 'replay', False, 'sample.bin'

    async def chunks(self):
        yield sample_stream()


class Broken(Once):
    async def chunks(self):
        raise ToolError('Cannot open /dev/cu.usbserial: busy')
        yield b''


class HubRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_reports_source_states(self):
        hub = Hub()
        states = []
        hub.subscribe(lambda m: m['type'] == 'stats' and states.append(m['source']['state']))
        await hub.run(Once())
        self.assertEqual(states, ['running', 'ended'])
        self.assertEqual(hub.link.status.name, 'STATUS')
        await hub.run(Broken())
        self.assertEqual(hub.source['state'], 'down')
        self.assertIn('busy', hub.source['detail'])

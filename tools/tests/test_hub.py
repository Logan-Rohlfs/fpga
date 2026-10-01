# tools/tests/test_hub.py
import json
import struct
import unittest

from link_samples import rom_flight_frames, rom_frames, sample_stream, with_crc
from sdr_cli import gui_wire, protocol as p
from sdr_cli.core import ToolError
from sdr_cli.fanout import Outgoing
from sdr_cli.hub import Hub


def best_telem(raw, n=0, source=0):
    return p.encode_message(p.BEST_TELEM, p.build_payload(p.BEST_TELEM, {'t_us': n, 'source': source, 'raw': raw}),
                            seq=n)


def chan_frame(raw, channel=0, crc_ok=1, n=0):
    return p.encode_message(p.CHAN_FRAME, p.build_payload(p.CHAN_FRAME, dict(
        channel=channel, crc_ok=crc_ok, t_us=n, rssi_dbm_x10=-700, quality=200, freq_offset_hz=0, raw=raw)), seq=n)


def fake_hub(start=1760000000.0):
    now = [start]
    return Hub(clock=lambda: now[0], wall=lambda: now[0]), now


class HubTest(unittest.TestCase):
    def test_status_build_id_sets_source_profile(self):
        hub = Hub()
        self.assertNotIn('profile', hub.stats_message()['source'])
        hub.feed(p.encode_message(p.STATUS, p.build_payload(p.STATUS, dict(
            version=p.PROTOCOL_VERSION, channels=3, uptime_ms=1, build_id=0x53445246, dropped=0)), seq=0))
        self.assertEqual(hub.stats_message()['source']['profile']['id'], 'apex_demo')

    def test_feed_turns_records_into_client_messages(self):
        hub = Hub()
        seen = []
        hub.subscribe(seen.append)
        outs = hub.feed(sample_stream())
        self.assertEqual(seen, outs)
        self.assertTrue(all(isinstance(o, Outgoing) for o in outs))
        self.assertTrue({'link', 'frames', 'spectrum.A', 'iq.A'} <= {o.channel for o in outs})
        spectrum = [o for o in outs if o.channel.startswith('spectrum.')]
        self.assertEqual(len(spectrum), 8)
        first = spectrum[0]
        self.assertEqual((first.mode, first.key), ('slot', 'spectrum.A'))
        self.assertIsInstance(first.data, bytes)
        self.assertEqual(first.data[:2], b'\x01\x01')
        head = gui_wire.SPECTRUM_HEADER.unpack_from(first.data)
        self.assertEqual((head[2], head[5]), (0, 256))              # channel A, 256 bins
        self.assertAlmostEqual(head[8], 50000.0)                     # f0_hz
        self.assertLess(head[10], head[11])                          # low < high
        db10 = struct.unpack_from('<256h', first.data, gui_wire.SPECTRUM_HEADER.size)
        self.assertEqual(db10[90], -500)      # power 140 → −120 + 70 = −50 dBFS
        link = [o for o in outs if o.channel == 'link']
        self.assertEqual(link[0].key, 'link.STATUS')
        status = json.loads(link[0].data)
        self.assertEqual(status['record']['type'], 'STATUS')
        self.assertIn('STATUS', status['text'])
        self.assertEqual({o.key for o in link}, {'link.STATUS', 'link.LINK_STATS', 'link.CHAN_METRICS.A',
                                                 'link.CHAN_METRICS.B'})
        for o in outs:
            if isinstance(o.data, str):
                json.loads(o.data)
        # TEST frames are not flight rows.
        self.assertFalse([o for o in outs if o.channel.startswith('flight')])

    def test_flight_rows_events_and_encode_once(self):
        hub, now = fake_hub()
        a, b = [], []
        hub.subscribe(a.append)
        hub.subscribe(b.append)
        outs = []
        for n, raw in enumerate(rom_flight_frames()[:80]):
            now[0] += 0.05
            outs += hub.feed(best_telem(raw, n))
        self.assertEqual(len(a), len(outs))
        self.assertTrue(all(x is y for x, y in zip(a, b)))           # encode once, shared object
        flight = [o for o in outs if o.channel == 'flight']
        self.assertEqual(len(flight), 80)
        self.assertEqual(flight[0].mode, 'stream')
        self.assertEqual(flight[0].data[:1], b'\x02')
        self.assertEqual(flight[0].data[2], gui_wire.ORIGINS['best'])
        row = flight[0].data[gui_wire.FLIGHT_HEADER.size:]
        t, flags = struct.unpack_from('<dB', row)
        self.assertEqual(t, 1760000000.05)
        self.assertEqual(flags, gui_wire.FLAG_SYNTHETIC | (0 << 1))  # best_from A
        self.assertEqual(len([o for o in outs if o.channel == 'frames']), 80)
        events = [json.loads(o.data) for o in outs if o.channel == 'events']
        self.assertTrue(events)
        self.assertEqual(events[0]['type'], 'events')
        self.assertFalse(events[0]['reset'])
        self.assertIn('launch', [e['kind'] for m in events for e in m['items']])
        snap = hub.snapshot('flight')
        self.assertEqual(json.loads(snap[0]), dict(type='history', channel='flight', count=80))

    def test_best_from_follows_the_source(self):
        hub, now = fake_hub()
        raw = rom_flight_frames()[0]
        for source, code in ((1, 1), (2, 2)):
            flight = [o for o in hub.feed(best_telem(raw, source=source)) if o.channel == 'flight']
            flags = flight[0].data[gui_wire.FLIGHT_HEADER.size + 8]
            self.assertEqual(flags >> 1 & 3, code)

    def test_channel_flight_rows(self):
        hub, now = fake_hub()
        raw = rom_flight_frames()[0]
        outs = hub.feed(chan_frame(raw, channel=1))
        flight = [o for o in outs if o.channel.startswith('flight')]
        self.assertEqual([o.channel for o in flight], ['flight.B'])
        self.assertEqual(flight[0].data[2], gui_wire.ORIGINS['B'])
        flags = flight[0].data[gui_wire.FLIGHT_HEADER.size + 8]
        self.assertEqual(flags >> 1 & 3, 3)                           # best_from n/a
        # A receiver CRC failure keeps the frame out of flight.B even when the APEX CRC passes.
        outs = hub.feed(chan_frame(raw, channel=1, crc_ok=0))
        self.assertEqual([o.channel for o in outs if o.channel != 'events'], ['frames'])

    def test_crc_bad_frame_reaches_frames_only(self):
        hub, now = fake_hub()
        bad = bytearray(rom_flight_frames()[0])
        bad[10] ^= 0xFF
        for msg in (best_telem(bytes(bad)), chan_frame(bytes(bad))):
            outs = hub.feed(msg)
            self.assertEqual([o.channel for o in outs if o.channel != 'events'], ['frames'])

    def test_crc_good_wrong_length_flight_frame_is_rejected(self):
        hub, now = fake_hub()
        short = with_crc(rom_frames()[0][:-1])                        # valid CRC, body one byte short
        for msg in (best_telem(short), chan_frame(short)):
            record = p.StreamDecoder().feed(msg)[0]
            self.assertTrue(record.fields['apex']['crc_ok'])
            self.assertEqual(record.fields['apex']['kind'], 'FLIGHT')
            outs = hub.feed(msg)
            self.assertEqual([o.channel for o in outs if o.channel != 'events'], ['frames'])
        self.assertEqual(json.loads(hub.snapshot('flight')[0])['count'], 0)
        self.assertEqual(json.loads(hub.snapshot('flight.A')[0])['count'], 0)

    def test_crc_burst_event_from_decoded_channel_letters(self):
        hub, now = fake_hub()
        bad = bytearray(rom_flight_frames()[0])
        bad[10] ^= 0xFF
        kinds = []
        for n in range(3):
            now[0] += 0.1
            for o in hub.feed(chan_frame(bytes(bad), channel=1, crc_ok=0, n=n)):
                if o.channel == 'events':
                    kinds += [(e['kind'], e['channel']) for e in json.loads(o.data)['items']]
        self.assertEqual(kinds, [('crc_burst', 'B')])

    def test_tick_emits_signal_loss(self):
        hub, now = fake_hub()
        hub.feed(chan_frame(rom_flight_frames()[0], channel=0))
        outs = hub.tick(now[0] + 1.0)
        self.assertEqual([e['kind'] for e in json.loads(outs[0].data)['items']], ['signal_loss'])
        self.assertEqual(json.loads(hub.snapshot('events')[0])['items'][-1]['kind'], 'signal_loss')

    def test_snapshot_replays_latest_slow_records(self):
        hub = Hub()
        self.assertEqual(hub.snapshot('link'), [])
        self.assertEqual(hub.snapshot('iq.A'), [])
        hub.feed(sample_stream())
        link = [json.loads(m) for m in hub.snapshot('link')]
        self.assertEqual([m['record']['type'] for m in link if m['type'] == 'record'],
                         ['STATUS', 'LINK_STATS', 'CHAN_METRICS', 'CHAN_METRICS'])
        history = [m for m in link if m['type'] == 'metrics_history']
        self.assertEqual([m['channel'] for m in history], ['A', 'B'])
        self.assertEqual(history[0]['power_unit'], 'dBm')
        iq = [json.loads(m) for m in hub.snapshot('iq.A')]
        self.assertEqual([m['record']['type'] for m in iq], ['IQ_SNAPSHOT'])
        frames = hub.snapshot('frames')
        self.assertEqual(json.loads(frames[0]), dict(type='history', channel='frames', count=9))
        spectrum = hub.snapshot('spectrum.B')
        self.assertEqual(json.loads(spectrum[0])['count'], 4)
        self.assertEqual(spectrum[1][:3], b'\x01\x01\x01')

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
        self.assertNotIn('clients', stats)
        self.assertEqual(hub.stats_message(clients=dict(operators=1, viewers=2))['clients'],
                         dict(operators=1, viewers=2))
        out = hub.stats_outgoing()
        self.assertEqual((out.channel, out.mode, out.key), ('stats', 'slot', 'stats'))
        now[0] += 6
        self.assertEqual(hub.byte_rate(), 0.0)

    def test_set_source_keeps_profile_and_emits_source_state(self):
        hub, now = fake_hub()
        seen = []
        hub.subscribe(seen.append)
        hub.source['profile'] = 'apex_demo'
        hub.set_source(Once(), 'running')
        self.assertEqual(hub.source['profile'], 'apex_demo')
        self.assertEqual([o.channel for o in seen], ['stats', 'events'])
        self.assertEqual(json.loads(seen[1].data)['items'][0]['kind'], 'source_state')
        hub.set_source(None, 'down', 'no port')
        self.assertEqual((hub.source['kind'], hub.source['profile']), ('none', 'apex_demo'))

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
        hub.subscribe(lambda o: o.channel == 'stats' and states.append(json.loads(o.data)['source']['state']))
        await hub.run(Once())
        self.assertEqual(states, ['running', 'ended'])
        self.assertEqual(hub.link.status.name, 'STATUS')
        await hub.run(Broken())
        self.assertEqual(hub.source['state'], 'down')
        self.assertIn('busy', hub.source['detail'])

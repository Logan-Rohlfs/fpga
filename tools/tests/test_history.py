import json
import math
import unittest

from sdr_cli import gui_wire
from sdr_cli.history import BATCH, DECIMATE, FULL_RES_S, History


def row(t):
    return gui_wire.encode_flight_row(t, {'alt_agl_m': t}, False)


def parse(msgs):
    return [json.loads(m) if isinstance(m, str) else m for m in msgs]


def rows_in(msg):
    n = int.from_bytes(msg[6:8], 'little')
    size = gui_wire.ROW.size
    return [gui_wire.ROW.unpack(msg[8 + i * size:8 + (i + 1) * size])[0] for i in range(n)]


class HistoryTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((FULL_RES_S, DECIMATE, BATCH), (120.0, 20, 4096))

    def test_flight_cap_drops_oldest(self):
        h = History()
        for i in range(36005):
            h.add_flight('best', float(i), row(float(i)))
        snap = h.snapshot('flight', 36004.0)
        ts = [t for m in snap[1:] for t in rows_in(m)]
        self.assertEqual(len(h._flight['best']), 36000)
        self.assertNotIn(0.0, ts)
        self.assertEqual(ts[-1], 36004.0)

    def test_decimation(self):
        h = History()
        n = 300 * 20
        for i in range(n):
            t = i / 20
            h.add_flight('A', t, row(t))
        now = (n - 1) / 20
        snap = h.snapshot('flight.A', now)
        ts = [t for m in snap[1:] for t in rows_in(m)]
        recent = sum(1 for i in range(n) if i / 20 >= now - 120.0)
        older = n - recent
        self.assertEqual(len(ts), recent + math.ceil(older / 20))
        self.assertEqual(json.loads(snap[0])['count'], len(ts))
        self.assertTrue(all(a < b for a, b in zip(ts, ts[1:])))
        self.assertEqual(len(set(ts)), len(ts))

    def test_batching(self):
        h = History()
        for i in range(5000):
            h.add_flight('best', 1000.0 + i / 100, row(1000.0 + i / 100))
        snap = h.snapshot('flight', 1050.0)
        self.assertEqual(json.loads(snap[0]), {'type': 'history', 'channel': 'flight', 'count': 5000})
        self.assertEqual([len(rows_in(m)) for m in snap[1:]], [4096, 904])
        self.assertEqual(snap[1][:2], bytes([gui_wire.KIND_FLIGHT, 1]))
        self.assertEqual(snap[1][2], gui_wire.ORIGINS['best'])

    def test_events_snapshot(self):
        h = History()
        for i in range(2005):
            h.add_event({'id': i, 't': float(i), 'kind': 'x', 'category': 'flight'})
        snap = h.snapshot('events', 0.0)
        self.assertEqual(len(snap), 1)
        msg = json.loads(snap[0])
        self.assertEqual(msg['type'], 'events')
        self.assertTrue(msg['reset'])
        self.assertEqual(len(msg['items']), 2000)
        self.assertEqual(msg['items'][0]['id'], 5)

    def test_spectrum_snapshot(self):
        h = History()
        for i in range(130):
            h.add_spectrum('A', bytes([i]))
        snap = h.snapshot('spectrum.A', 0.0)
        self.assertEqual(json.loads(snap[0]), {'type': 'history', 'channel': 'spectrum.A', 'count': 120})
        self.assertEqual(len(snap), 121)
        self.assertEqual(snap[1], bytes([10]))
        self.assertEqual(h.snapshot('spectrum.B', 0.0)[0], '{"type":"history","channel":"spectrum.B","count":0}')

    def test_iq(self):
        h = History()
        self.assertEqual(h.snapshot('iq.A', 0.0), [])
        h.set_latest('iq.A', 'one')
        h.set_latest('iq.A', 'two')
        self.assertEqual(h.snapshot('iq.A', 0.0), ['two'])

    def test_link_snapshot(self):
        h = History()
        h.set_latest('link.CHAN_METRICS.B', 'cb')
        h.set_latest('link.CONFIG', 'cfg')
        h.set_latest('link.STATUS', 'st')
        h.set_latest('link.LINK_STATS', 'ls')
        h.set_latest('link.CHAN_METRICS.A', 'ca')
        for i in range(650):
            h.add_metrics('A', float(i), -50.0, -90.0, 40.0, 1.0, i, 0, 'dBm')
        h.add_metrics('B', 1.0, -60.0, -90.0, 30.0, 2.0, 1, 2, 'dB')
        snap = h.snapshot('link', 0.0)
        self.assertEqual(snap[:5], ['st', 'ls', 'cfg', 'ca', 'cb'])
        hist = parse(snap[5:])
        self.assertEqual([m['channel'] for m in hist], ['A', 'B'])
        for m in hist:
            self.assertEqual(m['type'], 'metrics_history')
            lens = {len(m[k]) for k in ('t', 'rssi', 'noise', 'snr', 'df', 'crc_good', 'crc_bad')}
            self.assertEqual(len(lens), 1)
        self.assertEqual(len(hist[0]['t']), 600)
        self.assertEqual(hist[0]['t'][0], 50.0)
        self.assertEqual(hist[0]['power_unit'], 'dBm')
        self.assertEqual(hist[1]['crc_bad'], [2])

    def test_non_finite_becomes_null(self):
        h = History()
        h.add_metrics('A', 1.0, math.nan, -90.0, math.inf, -math.inf, 1, 0, 'dBm')
        h.add_event({'id': 1, 't': 1.0, 'kind': 'x', 'category': 'link', 'value': math.nan})
        metrics = json.loads(h.snapshot('link', 0.0)[0], parse_constant=self.fail)
        self.assertEqual((metrics['rssi'], metrics['snr'], metrics['df']), ([None], [None], [None]))
        events = json.loads(h.snapshot('events', 0.0)[0], parse_constant=self.fail)
        self.assertIsNone(events['items'][0]['value'])

    def test_flight_origins_isolated(self):
        h = History()
        h.add_flight('A', 1.0, row(1.0))
        h.add_flight('B', 2.0, row(2.0))
        h.add_flight('B', 3.0, row(3.0))
        for ch, origin, ts in (('flight.A', 0, [1.0]), ('flight.B', 1, [2.0, 3.0]), ('flight', 2, [])):
            snap = h.snapshot(ch, 3.0)
            self.assertEqual([t for m in snap[1:] for t in rows_in(m)], ts)
            if ts:
                self.assertEqual(snap[1][2], origin)

    def test_empty_flight_snapshot(self):
        self.assertEqual(History().snapshot('flight', 10.0),
                         ['{"type":"history","channel":"flight","count":0}'])

    def test_frames(self):
        h = History()
        for i in range(205):
            h.add_frame(str(i))
        snap = h.snapshot('frames', 0.0)
        self.assertEqual(json.loads(snap[0])['count'], 200)
        self.assertEqual(snap[1:], [str(i) for i in range(5, 205)])

    def test_unknown_channel(self):
        for name in ('nope', 'flight.C', 'spectrum.C', 'iq.Z'):
            with self.assertRaises(KeyError):
                History().snapshot(name, 0.0)


if __name__ == '__main__':
    unittest.main()

import unittest

from sdr_cli.fanout import CONTROL_MAX, Outbox, Outgoing


def make(role='viewer'):
    now = [0.0]
    return Outbox(role, clock=lambda: now[0]), now


def drain(box):
    out = []
    while True:
        d, _ = box.next()
        if d is None:
            return out
        out.append(d)


def slot(ch, data, key=None):
    return Outgoing(ch, 'slot', key or ch, data)


def stream(ch, data):
    return Outgoing(ch, 'stream', ch, data)


class OutboxTest(unittest.TestCase):
    def run_spectrum(self, role):
        box, now = make(role)
        box.subscribe(['spectrum.A'])
        got = []
        for i in range(50):
            now[0] = i * 0.02
            box.offer(slot('spectrum.A', i))
            d, _ = box.next()
            if d is not None:
                got.append(d)
                self.assertEqual(d, i)
        return got

    def test_viewer_spectrum_limited(self):
        self.assertIn(len(self.run_spectrum('viewer')), (5, 6))

    def test_admin_spectrum_unlimited(self):
        self.assertEqual(len(self.run_spectrum('admin')), 50)

    def test_slot_replacement(self):
        box, _ = make()
        box.subscribe(['iq.A'])
        for i in range(3):
            box.offer(slot('iq.A', i))
        self.assertEqual(drain(box), [2])

    def test_unsubscribed_dropped_control_and_stats_pass(self):
        box, _ = make()
        box.offer(stream('flight', 'f'))
        box.control('c')
        box.offer(slot('stats', 's'))
        self.assertEqual(drain(box), ['c', 's'])

    def test_order(self):
        box, _ = make()
        box.subscribe(['flight', 'iq.A'])
        box.offer(slot('iq.A', 'slot'))
        box.offer(stream('flight', 'stream'))
        box.control('control')
        self.assertEqual(drain(box), ['control', 'stream', 'slot'])

    def test_stream_overflow_resync(self):
        box, _ = make()
        box.subscribe(['flight'])
        for i in range(601):
            box.offer(stream('flight', i))
        self.assertEqual(box.take_resync(), {'flight'})
        self.assertFalse(box.overflowed)
        box.control('c')
        self.assertEqual(drain(box), ['c'])
        self.assertEqual(box.take_resync(), set())

    def test_control_overflow(self):
        box, _ = make()
        for i in range(CONTROL_MAX + 1):
            box.control(i)
        self.assertTrue(box.overflowed)

    def test_frames_sampling(self):
        box, now = make()
        box.subscribe(['frames'])
        got = 0
        for i in range(100):
            now[0] = i * 0.01
            box.offer(stream('frames', i))
            got += len(drain(box))
        self.assertLessEqual(got, 10)
        self.assertGreaterEqual(box.take_dropped().get('frames', 0), 90)
        self.assertEqual(box.take_dropped(), {})

    def test_set_role_lifts_limit(self):
        box, now = make('viewer')
        box.subscribe(['spectrum.A'])
        box.offer(slot('spectrum.A', 0))
        self.assertEqual(drain(box), [0])
        now[0] = 0.02
        box.offer(slot('spectrum.A', 1))
        self.assertEqual(drain(box), [])
        box.set_role('admin')
        now[0] = 0.04
        box.offer(slot('spectrum.A', 2))
        self.assertEqual(drain(box), [2])

    def test_subscribe(self):
        box, _ = make()
        with self.assertRaises(ValueError) as cm:
            box.subscribe(['flight', 'nope'])
        self.assertIn('nope', str(cm.exception))
        self.assertEqual(box.subscribed, frozenset())
        self.assertEqual(box.subscribe(['flight', 'events']), {'flight', 'events'})
        self.assertEqual(box.subscribe(['flight', 'events']), set())

    def test_snapshot_before_live(self):
        box, _ = make()
        box.subscribe(['flight'])
        box.put_snapshot('flight', ['h1', 'h2', 'h3'])
        box.offer(stream('flight', 'live'))
        self.assertEqual(drain(box), ['h1', 'h2', 'h3', 'live'])

    def test_large_snapshot_not_overflow(self):
        box, _ = make()
        box.subscribe(['flight'])
        box.put_snapshot('flight', list(range(2000)))
        box.offer(stream('flight', 'live'))
        self.assertEqual(box.take_resync(), set())
        self.assertEqual(len(drain(box)), 2001)

    def test_snapshot_survives_after_live_drained(self):
        box, _ = make()
        box.subscribe(['flight'])
        for i in range(590):
            box.offer(stream('flight', i))
        box.subscribe(['flight', 'flight.A'])
        box.put_snapshot('flight.A', list(range(4000)))
        for _ in range(590):
            box.next()
        for i in range(11):
            box.offer(stream('flight', i))
        self.assertEqual(box.take_resync(), set())
        self.assertEqual(len(drain(box)), 4011)

    def test_cap_holds_after_snapshot_purge(self):
        box, _ = make()
        box.subscribe(['flight', 'events'])
        for i in range(500):
            box.offer(stream('flight', i))
        box.put_snapshot('events', list(range(1000)))
        box.subscribe(['flight'])
        for i in range(101):
            box.offer(stream('flight', i))
        self.assertEqual(box.take_resync(), {'flight'})

    def test_bad_inputs(self):
        box, _ = make()
        with self.assertRaises(TypeError):
            box.subscribe('flight')
        with self.assertRaises(ValueError):
            box.offer(Outgoing('flight', 'bogus', 'flight', 'x'))

    def test_control_slot(self):
        box, _ = make()
        box.subscribe(['flight'])
        box.offer(stream('flight', 'stream'))
        box.control('a')
        box.control_slot('tuning', 't1')
        box.control('b')
        box.control_slot('tuning', 't2')
        box.control_slot('tuning', 't3')
        self.assertEqual(drain(box), ['a', 't3', 'b', 'stream'])
        box.control_slot('tuning', 't4')
        box.control_slot('tuning', 't5')
        self.assertEqual(drain(box), ['t5'])

    def test_subscribe_purges_removed(self):
        box, _ = make()
        box.subscribe(['flight', 'events', 'iq.A', 'iq.B'])
        box.offer(stream('flight', 'f'))
        box.offer(stream('events', 'e'))
        box.offer(slot('iq.A', 'a'))
        box.offer(slot('iq.B', 'b'))
        box.subscribe(['events', 'iq.B'])
        self.assertEqual(drain(box), ['e', 'b'])

    def test_wait_reported(self):
        box, now = make()
        box.subscribe(['iq.A'])
        box.offer(slot('iq.A', 0))
        self.assertEqual(drain(box), [0])
        now[0] = 0.1
        box.offer(slot('iq.A', 1))
        d, wait = box.next()
        self.assertIsNone(d)
        self.assertAlmostEqual(wait, 0.4)


if __name__ == '__main__':
    unittest.main()


VIEWER_BYTES_10S = 100000   # spec 2.4: <= 10 kB/s per viewer before compression


def viewer_load_bytes(seconds=10):
    """Bytes a viewer on the Flight preset channels receives from a replay at source rates.

    BEST FLIGHT 20 Hz, CHAN_METRICS 2 x 10 Hz, SPECTRUM (128 bins, the RTL default) 2 x 10 Hz, LINK_STATS
    and STATUS 1 Hz, drained every 10 ms. Snapshots and stats are not counted.
    """
    from link_samples import rom_flight_frames
    from sdr_cli import protocol as p
    from sdr_cli.hub import Hub

    def enc(kind, fields, seq):
        return p.encode_message(kind, p.build_payload(kind, fields), seq=seq)

    now = [1760000000.0]
    hub = Hub(clock=lambda: now[0], wall=lambda: now[0])
    box = Outbox('viewer', clock=lambda: now[0])
    box.subscribe(['flight', 'events', 'link', 'spectrum.A', 'spectrum.B'])
    hub.subscribe(box.offer)
    frames = rom_flight_frames()
    total, seq = 0, 0
    for step in range(seconds * 100):
        now[0] = 1760000000.0 + step * 0.01
        data = b''
        if step % 5 == 0:
            data += enc(p.BEST_TELEM, dict(t_us=step * 10000, source=0, raw=frames[(step // 5) % len(frames)]), seq)
        if step % 10 == 0:
            for ch in (0, 1):
                data += enc(p.CHAN_METRICS, dict(channel=ch, rssi_dbm_x10=-716, noise_dbm_x10=-1000,
                                                 snr_db_x10=284, freq_offset_hz=10300, sync_hits=step,
                                                 crc_good=step, crc_bad=0), seq)
                data += enc(p.SPECTRUM, dict(channel=ch, averages=1, row=step // 10, t_us=step * 10000,
                                             center_hz=100000, bin_mhz=781250, db_ref_x10=-1200,
                                             db_step_x100=50, power=[(k * 7 + step) % 40 for k in range(128)]), seq)
        if step % 100 == 0:
            data += enc(p.LINK_STATS, dict(from_a=step, from_b=step, both_ok=step, neither_ok=0, best_sent=step), seq)
            data += enc(p.STATUS, dict(version=2, channels=3, uptime_ms=step * 10, build_id=0x1234, dropped=0), seq)
        seq += 1
        if data:
            hub.feed(data)
        while True:
            item, _ = box.next()
            if item is None:
                break
            total += len(item) if isinstance(item, bytes) else len(item.encode('utf-8'))
    return total


class ViewerBudgetTest(unittest.TestCase):
    def test_flight_preset_viewer_load_within_budget(self):
        total = viewer_load_bytes()
        self.assertLessEqual(total, VIEWER_BYTES_10S, 'viewer load {} B in 10 s'.format(total))

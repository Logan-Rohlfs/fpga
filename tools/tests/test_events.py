import unittest

from link_samples import rom_flight_frames, with_crc
from sdr_cli import apex, events, protocol as p

KEYS = {'id', 't', 'kind', 'category', 'text', 'channel', 'value', 'quantity', 'segment', 'synthetic'}


def best(raw, n=0, t=None, src=0, flags=p.FLAG_SYNTHETIC):
    return p.Record(p.BEST_TELEM, 'BEST_TELEM', flags, n & 0xFF,
                    dict(t_us=0, source=src, frame_len=len(raw), raw=raw, apex=apex.parse_frame(raw)),
                    t=0.05 * n if t is None else t)


def chan(channel, ok, t, flags=p.FLAG_SYNTHETIC):
    raw = apex.build_test_frame(0, ok)
    return p.Record(p.CHAN_FRAME, 'CHAN_FRAME', flags, 0,
                    dict(channel=channel, crc_ok=int(ok), t_us=0, raw=raw, apex=apex.parse_frame(raw)), t=t)


def flight_raw(phase):
    body = bytearray(apex.FLIGHT_STRUCT.size)
    body[8] = apex.PHASES.index(phase)
    return with_crc(bytes([apex.FLIGHT]) + bytes(body))


def kinds(evs):
    return [e['kind'] for e in evs]


class FlightEventsTest(unittest.TestCase):
    def test_rom_pass_and_wrap(self):
        d = events.EventDeriver()
        frames = rom_flight_frames()
        self.assertEqual(len(frames), 1381)   # launch to landing (rtl FLIGHT_ROM_FRAMES)
        parsed = [apex.parse_frame(f)['fields'] for f in frames]
        out = []
        for n, raw in enumerate(frames):
            out += d.feed(best(raw, n))
        out += d.feed(best(frames[0], len(frames)))
        ks = kinds(out)
        # Tail after the wrap, then the ordered flight milestones.
        self.assertEqual(ks[-2:], ['phase', 'flight_reset'])
        self.assertEqual([k for k in ks if k != 'phase'],
                         ['launch', 'burnout', 'apogee', 'max_velocity', 'landing', 'flight_reset'])
        self.assertEqual(out[0]['kind'], 'phase')
        self.assertEqual(out[0]['text'], 'ARMED → BOOST')
        self.assertEqual(out[1]['kind'], 'launch')
        self.assertEqual(out[-2]['text'], 'LANDED → ARMED')
        self.assertEqual(out[-1]['text'], 'New flight segment (replay loop or flight-computer restart)')
        # Apogee value/time are the segment maximum.
        # The simulated flight reaches its peak before the flight computer reports DESCENT, so the
        # segment maximum up to the first COAST exit is the ROM-wide peak.
        exit_i = next(i for i, f in enumerate(parsed) if f['phase'] == 'DESCENT')
        top = max(range(exit_i + 1), key=lambda i: parsed[i]['alt_agl_m'])
        self.assertEqual(max(f['alt_agl_m'] for f in parsed), parsed[top]['alt_agl_m'])
        apogee = next(e for e in out if e['kind'] == 'apogee')
        self.assertEqual(apogee['value'], parsed[top]['alt_agl_m'])
        self.assertEqual(apogee['t'], 0.05 * top)
        self.assertEqual(apogee['quantity'], 'length')
        vmax = next(e for e in out if e['kind'] == 'max_velocity')
        self.assertEqual(vmax['value'], max(f['velocity_mps'] for f in parsed[:exit_i + 1]))
        self.assertEqual(vmax['quantity'], 'speed')
        # Segments: 0 before the reset, 1 from it on; ids monotonic from 1.
        self.assertEqual([e['segment'] for e in out if e['kind'] != 'flight_reset'][:-1], [0] * (len(out) - 2))
        self.assertEqual(out[-1]['segment'], 1)
        self.assertEqual([e['id'] for e in out], list(range(1, len(out) + 1)))
        for e in out:
            self.assertEqual(set(e), KEYS)
            self.assertTrue(e['synthetic'])

    def test_simultaneous_order(self):
        d = events.EventDeriver()
        d.feed(best(flight_raw('IDLE'), 0))
        d.feed(best(flight_raw('BOOST'), 1))
        d.feed(best(flight_raw('COAST'), 2))
        out = d.feed(best(flight_raw('DESCENT'), 3))
        self.assertEqual(kinds(out), ['phase', 'apogee', 'max_velocity'])

    def test_landing(self):
        d = events.EventDeriver()
        out = []
        for n, ph in enumerate(['COAST', 'DESCENT', 'DESCENT', 'LANDED']):
            out += d.feed(best(flight_raw(ph), n))
        self.assertEqual(kinds(out), ['phase', 'apogee', 'max_velocity', 'phase', 'landing'])
        self.assertEqual(kinds(out)[-2:], ['phase', 'landing'])
        self.assertEqual(out[-1]['text'][:7], 'Landing')

    def test_bad_crc_and_non_flight_ignored(self):
        d = events.EventDeriver()
        d.feed(best(flight_raw('ARMED'), 0))
        bad = bytearray(flight_raw('BOOST'))
        bad[-1] ^= 0xFF
        self.assertEqual(d.feed(best(bytes(bad), 1)), [])
        self.assertEqual(d.feed(best(apex.build_test_frame(1), 2)), [])
        self.assertEqual(kinds(d.feed(best(flight_raw('BOOST'), 3))), ['phase', 'launch'])

    def test_real_flag(self):
        d = events.EventDeriver()
        d.feed(best(flight_raw('ARMED'), 0, flags=0))
        out = d.feed(best(flight_raw('BOOST'), 1, flags=0))
        self.assertTrue(out and not any(e['synthetic'] for e in out))


class LinkEventsTest(unittest.TestCase):
    def test_loss_and_reacquire(self):
        d = events.EventDeriver()
        for n in range(21):
            self.assertEqual(d.feed(chan(0, True, n * 0.05)), [])
        self.assertEqual(d.tick(1.2), [])
        out = d.tick(1.26)
        self.assertEqual(kinds(out), ['signal_loss'])
        self.assertEqual(out[0]['channel'], 'A')
        self.assertEqual(out[0]['t'], 1.26)
        self.assertEqual(d.tick(1.4), [])
        out = d.feed(chan(0, True, 1.5))
        self.assertEqual(kinds(out), ['reacquire'])
        self.assertAlmostEqual(out[0]['value'], 0.5)
        self.assertEqual(d.tick(1.6), [])

    def test_loss_detected_on_feed(self):
        d = events.EventDeriver()
        d.feed(chan(1, True, 0.0))
        out = d.feed(chan(1, True, 0.6))
        self.assertEqual(kinds(out), ['signal_loss', 'reacquire'])
        self.assertEqual(out[0]['channel'], 'B')

    def test_crc_burst(self):
        d = events.EventDeriver()
        self.assertEqual(d.feed(chan(0, False, 0.0)), [])
        self.assertEqual(d.feed(chan(0, False, 0.1)), [])
        out = d.feed(chan(0, False, 0.2))
        self.assertEqual(kinds(out), ['crc_burst'])
        self.assertEqual(out[0]['channel'], 'A')
        self.assertEqual(d.feed(chan(0, False, 0.3)), [])
        self.assertEqual(d.feed(chan(0, False, 1.5)), [])
        self.assertEqual(d.feed(chan(0, False, 1.6)), [])
        self.assertEqual(kinds(d.feed(chan(0, False, 1.7))), ['crc_burst'])

    def test_source_switch(self):
        d = events.EventDeriver()
        out = []
        for n, src in enumerate([0] * 5 + [1] * 4 + [0]):
            out += d.feed(best(apex.build_test_frame(n), n, src=src))
        self.assertEqual(out, [])
        for n in range(10, 14):
            self.assertEqual(d.feed(best(apex.build_test_frame(n), n, src=1)), [])
        out = d.feed(best(apex.build_test_frame(14), 14, src=1))
        self.assertEqual(kinds(out), ['source_switch'])
        self.assertEqual(out[0]['channel'], 'B')
        self.assertEqual(d.feed(best(apex.build_test_frame(15), 15, src=1)), [])

    def test_source_state_dedups(self):
        d = events.EventDeriver()
        out = d.source_state('down', 'unplugged', 3.0)
        self.assertEqual(kinds(out), ['source_state'])
        self.assertIn('down', out[0]['text'])
        self.assertEqual(out[0]['t'], 3.0)
        self.assertEqual(d.source_state('down', 'still unplugged', 4.0), [])
        self.assertEqual(kinds(d.source_state('running', '', 5.0)), ['source_state'])

    def test_category_matches_kind(self):
        d = events.EventDeriver()
        out = []
        for n, raw in enumerate(rom_flight_frames()):
            out += d.feed(best(raw, n, src=n // 10 % 2))
        out += d.feed(best(rom_flight_frames()[0], 400))
        for n in range(3):
            out += d.feed(chan(0, False, 500 + n * 0.1))
        out += d.feed(chan(1, True, 500.0)) + d.feed(chan(1, True, 501.0)) + d.tick(510)
        out += d.source_state('down', 'x', 511.0)
        seen = set(e['kind'] for e in out)
        self.assertEqual(seen, set(events.ALL_KINDS))
        for e in out:
            self.assertEqual(e['category'], 'link' if e['kind'] in events.LINK_KINDS else 'flight')
        self.assertTrue(set(events.FLIGHT_KINDS) <= set(events.FLIGHT_CATEGORY_KINDS))
        self.assertEqual(events.ALL_KINDS, events.FLIGHT_CATEGORY_KINDS + events.LINK_KINDS)

    def test_constants(self):
        self.assertEqual(events.FLIGHT_KINDS, ('launch', 'burnout', 'apogee', 'landing'))
        self.assertEqual(set(events.ALL_KINDS), {
            'phase', 'launch', 'burnout', 'apogee', 'max_velocity', 'landing', 'flight_reset',
            'signal_loss', 'reacquire', 'crc_burst', 'source_switch', 'source_state'})


if __name__ == '__main__':
    unittest.main()

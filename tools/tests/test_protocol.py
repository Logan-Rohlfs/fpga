import random
import unittest

from sdr_cli import apex, protocol as p


def test_frame(seq=7, good=True):
    body = bytes([0x01, seq]) + b'APEX RADIO TEST'
    crc = p.crc16_ccitt(body)
    if not good:
        crc ^= 0x0001
    return body + bytes([crc >> 8, crc & 0xFF])


class CodingTest(unittest.TestCase):
    def test_crc_check_value(self):
        self.assertEqual(p.crc16_ccitt(b'123456789'), 0x29B1)

    def test_cobs_vectors(self):
        vectors = [
            (b'', b'\x01'),
            (b'\x00', b'\x01\x01'),
            (b'\x00\x00', b'\x01\x01\x01'),
            (b'\x11\x22\x00\x33', b'\x03\x11\x22\x02\x33'),
            (b'\x01' * 254, b'\xff' + b'\x01' * 254 + b'\x01'),
            (b'\x01' * 255, b'\xff' + b'\x01' * 254 + b'\x02\x01'),
            (b'\x01' * 253 + b'\x00', b'\xfe' + b'\x01' * 253 + b'\x01'),
        ]
        for raw, encoded in vectors:
            with self.subTest(raw=raw[:4], n=len(raw)):
                self.assertEqual(p.cobs_encode(raw), encoded)
                self.assertEqual(p.cobs_decode(encoded), raw)
                self.assertNotIn(0, encoded)

    def test_cobs_roundtrip_random(self):
        rng = random.Random(4)
        for _ in range(300):
            raw = bytes(rng.choice([0, 1, 255, rng.randrange(256)]) for _ in range(rng.randrange(700)))
            self.assertEqual(p.cobs_decode(p.cobs_encode(raw)), raw)

    def test_cobs_rejects_invalid(self):
        for bad in (b'', b'\x05\x01', b'\x02\x00'):
            with self.assertRaises(ValueError):
                p.cobs_decode(bad)


class MessageTest(unittest.TestCase):
    def roundtrip(self, mtype, fields):
        wire = p.encode_message(mtype, p.build_payload(mtype, fields), seq=3)
        self.assertEqual(wire[-1], 0)
        records = p.StreamDecoder().feed(wire)
        self.assertEqual(len(records), 1)
        return records[0]

    def test_every_type_roundtrips(self):
        r = self.roundtrip(p.STATUS, dict(version=2, channels=3, uptime_ms=1234, build_id=0xABCD, dropped=2))
        self.assertEqual((r.name, r.fields['uptime_ms'], r.fields['dropped']), ('STATUS', 1234, 2))
        self.assertTrue(r.synthetic)
        r = self.roundtrip(p.BEST_TELEM, dict(t_us=99, source=1, raw=test_frame()))
        self.assertEqual((r.fields['source'], r.fields['apex']['kind']), ('B', 'TEST'))
        r = self.roundtrip(p.CHAN_FRAME, dict(channel=0, crc_ok=1, t_us=5, rssi_dbm_x10=-715, quality=204,
                                              freq_offset_hz=10400, raw=test_frame(good=False)))
        self.assertEqual(r.fields['channel'], 'A')
        self.assertAlmostEqual(r.fields['rssi_dbm'], -71.5)
        self.assertFalse(r.fields['apex']['crc_ok'])
        r = self.roundtrip(p.CHAN_METRICS, dict(channel=1, rssi_dbm_x10=-700, noise_dbm_x10=-1000, snr_db_x10=300,
                                                freq_offset_hz=-5, sync_hits=10, crc_good=9, crc_bad=1))
        self.assertEqual((r.fields['channel'], r.fields['snr_db'], r.fields['crc_bad']), ('B', 30.0, 1))
        r = self.roundtrip(p.LINK_STATS, dict(from_a=1, from_b=2, both_ok=3, neither_ok=4, best_sent=5))
        self.assertEqual(r.fields['neither_ok'], 4)
        r = self.roundtrip(p.SPECTRUM, dict(channel=0, averages=4, row=65535, t_us=123, center_hz=100000,
                                            bin_mhz=390625, db_ref_x10=-1200, db_step_x100=50, power=list(range(256))))
        f = r.fields
        self.assertEqual((f['row'], len(f['power']), f['power'][255], f['averages'], f['t_us']), (65535, 256, 255, 4, 123))
        self.assertEqual((f['center_hz'], f['bin_hz'], f['db_ref'], f['db_step']), (100000, 390.625, -120.0, 0.5))
        self.assertEqual(p.bin_frequency(f, 128), 100000.0)
        self.assertEqual(p.bin_frequency(f, 0), 100000 - 128 * 390.625)
        self.assertEqual(p.power_db(f)[:3], [-120.0, -119.5, -119.0])
        r = self.roundtrip(p.IQ_SNAPSHOT, dict(channel=1, t_us=9, sample_rate_hz=100000, iq=[(1, -1), (-32768, 32767)]))
        self.assertEqual((r.fields['iq'], r.fields['sample_rate_hz'], r.fields['t_us']), ([(1, -1), (-32768, 32767)], 100000, 9))

    def test_unknown_type_is_reported_not_fatal(self):
        r = self.roundtrip(0x7E, {'payload': b'\x00\x01'})
        self.assertEqual(r.name, 'UNKNOWN(0x7E)')

    def test_format_marks_simulated(self):
        r = self.roundtrip(p.CHAN_FRAME, dict(channel=1, crc_ok=1, t_us=5, rssi_dbm_x10=-715, quality=204,
                                              freq_offset_hz=10400, raw=test_frame(seq=212)))
        line = p.format_record(r)
        for text in ('CHAN_FRAME', 'B', 'crc=ok', '-71.5', 'TEST', 'seq=212', 'SIMULATED'):
            self.assertIn(text, line)


class StreamTest(unittest.TestCase):
    def wire(self, seq, dropped=0):
        return p.encode_message(p.STATUS, p.build_payload(
            p.STATUS, dict(version=1, channels=3, uptime_ms=seq, build_id=0, dropped=dropped)), seq=seq)

    def test_fragmented_feed(self):
        data = b''.join(self.wire(s) for s in range(5))
        d = p.StreamDecoder()
        out = []
        for i in range(0, len(data), 3):
            out += d.feed(data[i:i + 3])
        self.assertEqual([r.seq for r in out], list(range(5)))
        self.assertEqual(d.stats['seq_gaps'], 0)
        self.assertEqual(d.stats['by_type']['STATUS'], 5)

    def test_resync_after_garbage_bad_crc_and_truncation(self):
        good = self.wire(1)
        corrupt = bytearray(self.wire(2))
        corrupt[4] ^= 0x40
        truncated = self.wire(3)[:6] + b'\x00'
        d = p.StreamDecoder()
        out = d.feed(b'SDR READY\r\n\x00' + good + bytes(corrupt) + truncated + self.wire(4))
        self.assertEqual([r.seq for r in out], [1, 4])
        self.assertGreaterEqual(d.stats['crc_errors'] + d.stats['cobs_errors'] + d.stats['length_errors'], 2)
        self.assertGreater(d.stats['resync_bytes'], 0)

    def test_leading_partial_message_is_discarded(self):
        d = p.StreamDecoder()
        out = d.feed(self.wire(1)[5:] + self.wire(2))
        self.assertEqual([r.seq for r in out], [2])

    def test_seq_gaps_count_wrap(self):
        d = p.StreamDecoder()
        d.feed(self.wire(254) + self.wire(255) + self.wire(0) + self.wire(3))
        self.assertEqual(d.stats['seq_gaps'], 2)

    def test_link_state_aggregates(self):
        s = p.LinkState()
        d = p.StreamDecoder()
        msgs = [
            (p.STATUS, dict(version=1, channels=3, uptime_ms=10, build_id=0, dropped=0)),
            (p.CHAN_METRICS, dict(channel=1, rssi_dbm_x10=-700, noise_dbm_x10=-1000, snr_db_x10=300,
                                  freq_offset_hz=-5, sync_hits=10, crc_good=9, crc_bad=1)),
            (p.SPECTRUM, dict(channel=0, row=1, power=[1] * 256)),
            (p.SPECTRUM, dict(channel=0, row=2, power=[2] * 256)),
            (p.IQ_SNAPSHOT, dict(channel=0, iq=[(1, 2)])),
            (p.BEST_TELEM, dict(t_us=1, source=0, raw=test_frame())),
        ]
        s.update(d.feed(b''.join(p.encode_message(t, p.build_payload(t, f), seq=i) for i, (t, f) in enumerate(msgs))))
        self.assertEqual(s.status.fields['uptime_ms'], 10)
        self.assertEqual(s.metrics['B'].fields['crc_good'], 9)
        self.assertEqual([row.fields['row'] for row in s.spectrum['A']], [1, 2])
        self.assertEqual(s.iq['A'].fields['iq'], [(1, 2)])
        self.assertEqual(len(s.best), 1)
        self.assertTrue(s.synthetic)


class ApexTest(unittest.TestCase):
    def test_test_frame(self):
        f = apex.parse_frame(test_frame(seq=9))
        self.assertEqual((f['kind'], f['crc_ok'], f['fields']['seq'], f['fields']['text']), ('TEST', True, 9, 'APEX RADIO TEST'))
        self.assertFalse(apex.parse_frame(test_frame(good=False))['crc_ok'])

    def test_flight_and_short_frames(self):
        body = bytes([0x02]) + b'KG5LDI' + bytes(35)
        crc = p.crc16_ccitt(body)
        f = apex.parse_frame(body + bytes([crc >> 8, crc & 0xFF]))
        self.assertEqual((f['kind'], f['crc_ok'], f['fields']['callsign']), ('FLIGHT', True, 'KG5LDI'))
        self.assertEqual(apex.parse_frame(b'\x02\x00')['kind'], 'FLIGHT')
        self.assertFalse(apex.parse_frame(b'\x02\x00')['crc_ok'])


if __name__ == '__main__':
    unittest.main()

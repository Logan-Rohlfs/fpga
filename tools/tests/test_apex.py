import json
import unittest
from link_samples import rom_flight_frames
from sdr_cli import apex


class ApexSchemaTest(unittest.TestCase):
    def test_schema_order_and_length(self):
        keys = [f['key'] for f in apex.FLIGHT_SCHEMA]
        self.assertEqual(len(keys), 20)
        self.assertEqual(keys[:3], ['seq', 'phase', 'phase_status'])
        self.assertEqual(keys[-1], 'azimuth_deg')
        schema = apex.flight_schema()
        self.assertEqual(schema['version'], 1)
        self.assertEqual(len(json.loads(json.dumps(schema))['fields']), 20)

    def test_bits_decode(self):
        body = bytearray(apex.FLIGHT_STRUCT.size)
        body[8] = 0x02 | 0x08 | 0x80      # phase BOOST, airbrakes_authorized, gps_time_valid
        body[9] = 0x01 | 0x90             # imu, gps, sd
        f = apex._flight(bytes(body))
        self.assertEqual(f['phase'], 'BOOST')
        self.assertEqual(f['phase_status'], 0x8A)
        self.assertTrue(f['interlocks']['airbrakes_authorized'] and f['interlocks']['gps_time_valid'])
        self.assertFalse(f['interlocks']['servo_powered'])
        self.assertEqual([k for k, v in f['health_bits'].items() if v], ['imu', 'gps', 'sd'])

    def test_demo_rom_first_frame(self):
        frame = apex.parse_frame(rom_flight_frames()[0])
        self.assertTrue(frame['crc_ok'])
        self.assertEqual(frame['fields']['gps_fix'], 0)
        self.assertEqual(frame['fields']['health'], 0x90)
        self.assertEqual(len(rom_flight_frames()), 293)


if __name__ == '__main__':
    unittest.main()

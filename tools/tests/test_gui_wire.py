import json
import math
import struct
import unittest
from pathlib import Path

from link_samples import rom_frames
from sdr_cli import apex, gui_wire

# SPECTRUM_HEADER field indexes (struct order) and byte offsets
H_KIND, H_VERSION, H_CHANNEL, H_FLAGS, H_ROW, H_BINS, H_RF_LO, H_INJECTION = 0, 1, 2, 3, 4, 5, 12, 13
SPECTRUM_FLAGS_OFFSET = 3
ROW_FLAGS_OFFSET = 8      # after the f64 t
GOLDEN = Path(__file__).resolve().parents[1] / 'sdr_web/src/lib/wire.golden.json'


class GuiWireTest(unittest.TestCase):
    def test_spectrum_without_reference(self):
        data = gui_wire.encode_spectrum('B', 7, 1.5, 50000.0, 15625.0, -90.0, -10.0, [-900, -100, 0], True)
        self.assertEqual(gui_wire.SPECTRUM_HEADER.size, 52)
        self.assertEqual(len(data), 52 + 6)
        h = gui_wire.SPECTRUM_HEADER.unpack(data[:52])
        self.assertEqual((h[H_KIND], h[H_VERSION], h[H_CHANNEL], h[H_FLAGS], h[H_ROW], h[H_BINS]), (1, 1, 1, 0b001, 7, 3))
        self.assertTrue(math.isnan(h[H_RF_LO]))
        self.assertEqual(h[H_INJECTION], 255)
        self.assertEqual(struct.unpack('<3h', data[52:]), (-900, -100, 0))

    def test_spectrum_with_reference(self):
        data = gui_wire.encode_spectrum('A', 1, 0.0, 0.0, 1.0, 0.0, 1.0, [0], False,
                                        {'lo_hz': 441.38e6, 'injection': 'low', 'inferred': True})
        h = gui_wire.SPECTRUM_HEADER.unpack(data[:52])
        self.assertEqual(h[H_FLAGS], 0b110)
        self.assertEqual(h[H_RF_LO], 441.38e6)
        self.assertEqual(h[H_INJECTION], 0)
        data = gui_wire.encode_spectrum('B', 1, 0.0, 0.0, 1.0, 0.0, 1.0, [], True,
                                        {'lo_hz': 1e6, 'injection': 'low', 'inferred': True})
        self.assertEqual(data[SPECTRUM_FLAGS_OFFSET], 0b111)

    def _row(self, **kw):
        body = rom_frames()[0][1:]
        return gui_wire.encode_flight_row(1.0, apex._flight(body), True, **kw)

    def test_flight_row(self):
        row = self._row()
        self.assertEqual(len(row), 90)
        t, flags, _res, *values = gui_wire.ROW.unpack(row)
        self.assertEqual(flags, 0b111)   # synthetic, best_from n/a (3)
        self.assertEqual(values[gui_wire.FIELD_KEYS.index("phase")], apex.PHASE_ENUM.index('ARMED'))
        self.assertEqual(self._row(best_from=2)[ROW_FLAGS_OFFSET], 0b101)

    def test_pack_flight(self):
        row = self._row()
        data = gui_wire.pack_flight('best', [row, row])
        self.assertEqual(gui_wire.FLIGHT_HEADER.unpack(data[:8]), (2, 1, 2, 0, 20, 2))
        self.assertEqual(len(data), 8 + 180)
        with self.assertRaises(ValueError):
            gui_wire.pack_flight('A', [row] * 65536)

    def test_unknown_phase(self):
        self.assertEqual(gui_wire.flight_values({'phase': '???'})[gui_wire.FIELD_KEYS.index('phase')], 6)

    def test_none_field_becomes_nan(self):
        values = gui_wire.flight_values({'lat_deg': None})
        self.assertTrue(math.isnan(values[gui_wire.FIELD_KEYS.index('lat_deg')]))

    def test_unknown_channel_raises(self):
        with self.assertRaises(ValueError):
            gui_wire.encode_spectrum('C', 0, 0.0, 0.0, 1.0, 0.0, 1.0, [], False)

    def test_golden_spectrum_expect_shape(self):
        vectors = {v['name']: v for v in json.loads(GOLDEN.read_text())}
        e = vectors['spectrum_rf_reference']['expect']
        # t_us is the integer round(t * 1e6); no kind or seconds t in the SpectrumMsg shape
        self.assertEqual(e['t_us'], round(1760000000.25 * 1e6))
        self.assertNotIn('t', e)
        self.assertNotIn('kind', e)
        self.assertEqual(e['type'], 'spectrum')
        self.assertIsNone(vectors['spectrum_rf_injection_unknown']['expect']['rf_reference'])
        nulls = vectors['flight_missing_nan_fields']['expect']['rows'][0]['values']
        self.assertEqual(nulls.count(None), 3)

    def test_golden_not_stale(self):
        self.assertEqual(json.loads(GOLDEN.read_text()), json.loads(json.dumps(gui_wire.golden_vectors())))
        self.assertNotIn('NaN', GOLDEN.read_text())


if __name__ == '__main__':
    unittest.main()

import json
import math
import struct
import unittest
from pathlib import Path

from link_samples import rom_frames
from sdr_cli import apex, gui_wire

GOLDEN = Path(__file__).resolve().parents[1] / 'sdr_web/src/lib/wire.golden.json'


class GuiWireTest(unittest.TestCase):
    def test_spectrum_without_reference(self):
        data = gui_wire.encode_spectrum('B', 7, 1.5, 50000.0, 15625.0, -90.0, -10.0, [-900, -100, 0], True)
        self.assertEqual(gui_wire.SPECTRUM_HEADER.size, 52)
        self.assertEqual(len(data), 52 + 6)
        h = gui_wire.SPECTRUM_HEADER.unpack(data[:52])
        self.assertEqual((h[0], h[1], h[2], h[3], h[4], h[5]), (1, 1, 1, 0b001, 7, 3))
        self.assertTrue(math.isnan(h[12]))
        self.assertEqual(h[13], 255)
        self.assertEqual(struct.unpack('<3h', data[52:]), (-900, -100, 0))

    def test_spectrum_with_reference(self):
        data = gui_wire.encode_spectrum('A', 1, 0.0, 0.0, 1.0, 0.0, 1.0, [0], False,
                                        {'lo_hz': 441.38e6, 'injection': 'low', 'inferred': True})
        h = gui_wire.SPECTRUM_HEADER.unpack(data[:52])
        self.assertEqual(h[3], 0b110)
        self.assertEqual(h[12], 441.38e6)
        self.assertEqual(h[13], 0)
        data = gui_wire.encode_spectrum('B', 1, 0.0, 0.0, 1.0, 0.0, 1.0, [], True,
                                        {'lo_hz': 1e6, 'injection': 'low', 'inferred': True})
        self.assertEqual(data[3], 0b111)

    def _row(self, **kw):
        body = rom_frames()[0][1:]
        return gui_wire.encode_flight_row(1.0, apex._flight(body), True, **kw)

    def test_flight_row(self):
        row = self._row()
        self.assertEqual(len(row), 90)
        t, flags, _res, *values = gui_wire.ROW.unpack(row)
        self.assertEqual(flags, 0b111)   # synthetic, best_from n/a (3)
        self.assertEqual(values[1], apex.PHASE_ENUM.index('ARMED'))
        self.assertEqual(self._row(best_from=2)[8], 0b101)

    def test_pack_flight(self):
        row = self._row()
        data = gui_wire.pack_flight('best', [row, row])
        self.assertEqual(gui_wire.FLIGHT_HEADER.unpack(data[:8]), (2, 1, 2, 0, 20, 2))
        self.assertEqual(len(data), 8 + 180)
        with self.assertRaises(ValueError):
            gui_wire.pack_flight('A', [row] * 65536)

    def test_unknown_phase(self):
        self.assertEqual(gui_wire.flight_values({'phase': '???'})[1], 6)

    def test_golden_not_stale(self):
        self.assertEqual(json.loads(GOLDEN.read_text()), json.loads(json.dumps(gui_wire.golden_vectors())))
        self.assertNotIn('NaN', GOLDEN.read_text())


if __name__ == '__main__':
    unittest.main()

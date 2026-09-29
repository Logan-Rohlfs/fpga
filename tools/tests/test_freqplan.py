import json
from pathlib import Path
import tempfile
import unittest

from sdr_cli import freqplan as fp


class SynthesizerTest(unittest.TestCase):
    def test_default_plan_matches_mockup(self):
        s = fp.TuningState()
        self.assertAlmostEqual(fp.pfd_hz(s), 10e6)
        self.assertAlmostEqual(fp.vco_hz(s), 3531.04e6, places=1)
        self.assertAlmostEqual(fp.lo_hz(s), 441.38e6, places=1)
        self.assertAlmostEqual(fp.lo_step_hz(s), 125.0)
        self.assertAlmostEqual(fp.if_hz(s, s.carrier_hz), 100e3, places=1)
        self.assertAlmostEqual(fp.image_hz(s), 441.28e6, places=1)

    def test_with_lo_round_trips_and_quantizes_to_step(self):
        s = fp.TuningState()
        up = fp.with_lo(s, 441.381e6)
        self.assertEqual((up.n_int, up.frac), (353, 1048))
        self.assertAlmostEqual(fp.lo_hz(up), 441.381e6, places=1)
        self.assertEqual(fp.with_lo(s, 441380060).frac, 1040)   # +60 Hz rounds down (step 125 Hz)
        self.assertEqual(fp.with_lo(s, 441380070).frac, 1041)   # +70 Hz rounds up

    def test_with_lo_carries_into_n(self):
        edge = fp.with_lo(fp.TuningState(), 10e6 * 354 / 8 - 10)   # 10 Hz below an integer-N boundary
        self.assertEqual((edge.n_int, edge.frac), (354, 0))

    def test_with_lo_rejects_below_range(self):
        with self.assertRaises(ValueError):
            fp.with_lo(fp.TuningState(), 1e6)

    def test_high_side_injection(self):
        s = fp.with_lo(fp.update(fp.TuningState(), {'injection': 'high'}), 441.58e6)
        self.assertAlmostEqual(fp.if_hz(s, s.carrier_hz), 100e3, places=1)
        self.assertAlmostEqual(fp.image_hz(s), 441.68e6, places=1)
        self.assertAlmostEqual(fp.rf_hz(s, 100e3), 441.48e6, places=1)

    def test_nco_tuning_word(self):
        s = fp.TuningState()
        self.assertEqual(fp.nco_ftw(s), 0x1999999A)
        self.assertAlmostEqual(fp.nco_resolution_hz(s), 1e6 / 2 ** 32)


class UpdateTest(unittest.TestCase):
    def test_partial_update_applies_lo_last(self):
        s = fp.update(fp.TuningState(), {'out_div': 4, 'lo_hz': 441.38e6})
        self.assertEqual(s.out_div, 4)
        self.assertAlmostEqual(fp.lo_hz(s), 441.38e6, places=0)

    def test_rejects_bad_values(self):
        bad = [{'frac': 10000}, {'mod': 1}, {'out_div': 3}, {'injection': 'side'}, {'r_div': 0},
               {'n_int': 2.5}, {'nco_hz': 600e3}, {'fs_hz': 0}, {'ref_hz': float('nan')},
               {'bogus': 1}, {'n_int': True}, {'lo_hz': 'x'}, {'window_hz': -1}]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                fp.update(fp.TuningState(), change)

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            fp.update(fp.TuningState(), [1])

    def test_warnings(self):
        self.assertEqual(fp.warnings(fp.TuningState()), [])
        off = fp.with_lo(fp.TuningState(), 441.2e6)
        self.assertIn('outside the 100 ± 35 kHz window', ' '.join(fp.warnings(off)))
        vco = fp.update(fp.TuningState(), {'out_div': 16, 'lo_hz': 441.38e6})
        self.assertIn('VCO', ' '.join(fp.warnings(vco)))

    def test_derive_is_json_ready(self):
        d = fp.derive(fp.TuningState())
        json.dumps(d)
        self.assertEqual(d['nco_ftw'], 0x1999999A)
        self.assertEqual(d['warnings'], [])
        self.assertAlmostEqual(d['lo_hz'], 441.38e6, places=1)


class PersistenceTest(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'gui_state.json'
            self.assertEqual(fp.load_state(path), fp.TuningState())
            s = fp.with_lo(fp.TuningState(), 441.39e6)
            fp.save_state(path, s)
            self.assertEqual(fp.load_state(path), s)
            path.write_text('{"frac": 99999}')
            self.assertEqual(fp.load_state(path), fp.TuningState())
            path.write_text('not json')
            self.assertEqual(fp.load_state(path), fp.TuningState())

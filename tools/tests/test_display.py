import random
import unittest

from sdr_cli.display import WaterfallScale


def noisy_row(floor=-105.0, signal_db=None, bins=256, seed=1):
    rng = random.Random(seed)
    row = [floor + rng.uniform(-3, 3) for _ in range(bins)]
    if signal_db is not None:
        for k in (90, 91, 218, 219):
            row[k] = signal_db
    return row


class WaterfallScaleTest(unittest.TestCase):
    def test_auto_is_default_and_converges_around_noise_and_signal(self):
        scale = WaterfallScale()
        self.assertEqual(scale.mode, 'auto')
        for n in range(60):
            scale.update(noisy_row(signal_db=-50.0, seed=n))
        self.assertLess(scale.low, -105.0)
        self.assertGreater(scale.low, -115.0)
        self.assertGreaterEqual(scale.high, -50.0)
        self.assertLess(scale.high, -40.0)
        self.assertLess(scale.normalize(-105.0), 0.3)       # noise: dim but visible
        self.assertGreater(scale.normalize(-105.0), 0.0)
        self.assertGreater(scale.normalize(-50.0), 0.9)     # signal: hot

    def test_noise_only_keeps_minimum_span(self):
        scale = WaterfallScale(min_span_db=30.0)
        for n in range(60):
            scale.update(noisy_row(seed=n))
        self.assertGreaterEqual(scale.high - scale.low, 30.0 - 1e-9)
        self.assertLess(scale.normalize(-105.0), 0.4)

    def test_new_strong_signal_expands_quickly_and_decays_slowly(self):
        scale = WaterfallScale()
        for n in range(60):
            scale.update(noisy_row(seed=n))
        quiet_high = scale.high
        for n in range(3):
            scale.update(noisy_row(signal_db=-30.0, seed=n))
        self.assertGreater(scale.high, -35.0)               # fast attack
        loud_high = scale.high
        scale.update(noisy_row(seed=99))
        self.assertGreater(scale.high, loud_high - 3.0)      # slow release, no flicker
        self.assertGreater(loud_high, quiet_high)

    def test_manual_limits_ignore_updates_and_clip(self):
        scale = WaterfallScale()
        scale.set_manual(-110.0, -60.0)
        scale.update(noisy_row(signal_db=-20.0))
        self.assertEqual((scale.mode, scale.low, scale.high), ('manual', -110.0, -60.0))
        self.assertEqual(scale.normalize(-120.0), 0.0)
        self.assertEqual(scale.normalize(-20.0), 1.0)
        self.assertAlmostEqual(scale.normalize(-85.0), 0.5)
        with self.assertRaises(ValueError):
            scale.set_manual(-60.0, -60.0)
        scale.set_auto()
        self.assertEqual(scale.mode, 'auto')

    def test_first_row_initializes_and_empty_row_is_ignored(self):
        scale = WaterfallScale()
        scale.update([])
        scale.update(noisy_row(signal_db=-50.0))
        self.assertLess(scale.low, -105.0)
        self.assertGreater(scale.high, -55.0)


if __name__ == '__main__':
    unittest.main()

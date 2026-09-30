import json
from pathlib import Path
import unittest

from sdr_cli import units

JSON_PATH = Path(__file__).resolve().parents[1] / 'sdr_web/src/lib/units.catalogue.json'


class UnitsTest(unittest.TestCase):
    def test_catalogue_matches_json_file(self):
        self.assertEqual(json.loads(JSON_PATH.read_text(encoding='utf-8')), units.CATALOGUE)
        self.assertEqual(JSON_PATH.read_text(encoding='utf-8'), units.catalogue_json())

    def test_conversions(self):
        self.assertEqual(units.convert(100, 'temperature', '°F'), 212)
        self.assertAlmostEqual(units.convert(1000, 'length', 'ft'), 3280.84, places=2)
        self.assertAlmostEqual(units.convert(101325, 'pressure', 'inHg'), 29.92, places=2)
        self.assertEqual(units.convert(9.80665, 'acceleration', 'g'), 1)

    def test_systems_cover_every_dimensional_quantity(self):
        for name, system in units.CATALOGUE['systems'].items():
            for quantity, spec in units.CATALOGUE['quantities'].items():
                if not spec['units']:
                    self.assertNotIn(quantity, system)
                    continue
                with self.subTest(system=name, quantity=quantity):
                    self.assertTrue(units.is_unit(quantity, system[quantity]))

    def test_is_unit(self):
        self.assertTrue(units.is_unit('length', 'ft'))
        self.assertFalse(units.is_unit('length', 'furlong'))
        self.assertFalse(units.is_unit('nonsense', 'm'))


if __name__ == '__main__':
    unittest.main()

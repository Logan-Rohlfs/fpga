"""Independent checks of the checked-in APEX flight replay ROM.

Frames are decoded with the host's APEX parser (sdr_cli.apex), not with the
generator's packer, and compared with the CSV rows they came from. The row
selection here is a separate implementation of the documented window rule.
CSV-based tests skip when the apex checkout is not next to this repository.
"""
import csv
import importlib.util
import os
from pathlib import Path
import re
import struct
import unittest

from sdr_cli import apex
from link_samples import ROM_MEM, rom_frames, with_crc

REPO = Path(__file__).resolve().parents[2]
RTL = REPO / 'projects/sdr/rtl/receiver_link_sources.sv'
# The flight log lives in the sibling apex checkout; APEX_FLIGHT_CSV overrides the path (for a worktree).
CSV = Path(os.environ.get('APEX_FLIGHT_CSV') or (REPO.parent / 'apex/sim/output/log_exports/'
                                                 'Flight_02_2026-06-17T21-28-54-800/IREC-2026-SRAD-TELEMETRY.csv'))
EMULATED = {'gps_fix', 'gps_sats', 'lat_deg', 'lon_deg', 'gps_alt_m', 'tilt_deg', 'azimuth_deg'}


def decode(frame):
    return apex.parse_frame(with_crc(frame))


def rtl_constant(name):
    return int(re.search(r'\b' + name + r'=(\d+)', RTL.read_text()).group(1))


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


class RomStructureTest(unittest.TestCase):
    def setUp(self):
        self.frames = rom_frames()
        self.decoded = [decode(frame) for frame in self.frames]

    def test_frames_are_apex_flight_with_radio_seq_from_zero(self):
        self.assertEqual(len(self.frames), rtl_constant('FLIGHT_ROM_FRAMES'))
        for index, frame in enumerate(self.decoded):
            self.assertEqual(frame['kind'], 'FLIGHT')
            self.assertTrue(frame['crc_ok'])
            self.assertEqual(frame['fields']['callsign'], 'KG5LDI')
            self.assertEqual(frame['fields']['seq'], index)

    def test_phases_follow_the_flight_and_loss_windows_fall_where_documented(self):
        order = ['ARMED', 'BOOST', 'COAST', 'DESCENT', 'LANDED']
        phases = [frame['fields']['phase'] for frame in self.decoded]
        ranks = [order.index(phase) for phase in phases]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(set(phases), set(order))
        a = range(rtl_constant('FLIGHT_LOSS_A_FIRST'), rtl_constant('FLIGHT_LOSS_A_LAST') + 1)
        b = range(rtl_constant('FLIGHT_LOSS_B_FIRST'), rtl_constant('FLIGHT_LOSS_B_LAST') + 1)
        self.assertTrue(set(phases[i] for i in a) <= {'BOOST', 'COAST'})
        self.assertEqual({phases[i] for i in b}, {'COAST', 'DESCENT'})
        for window in (a, b):
            self.assertTrue(6 <= len(window) <= 20)   # 0.3 to 1 s at 20 Hz


@unittest.skipUnless(CSV.is_file(), 'apex flight CSV not available')
class RomMatchesCsvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CSV.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        events = [r for r in rows if r['record_type'] == 'EVENT']
        samples = [r for r in rows if r['record_type'] == 'SAMPLE']
        launch = [int(r['time_ms']) for r in events if r['event'] == 'LAUNCH_DETECTED'][0]
        apogee = [int(r['time_ms']) for r in events
                  if r['event'] == 'PHASE' and r['phase'] == 'DESCENT' and int(r['time_ms']) > launch][0]
        landing = [int(r['time_ms']) for r in events
                   if r['event'] == 'PHASE' and r['phase'] == 'LANDED' and int(r['time_ms']) > apogee][0]
        times = [int(r['time_ms']) for r in samples]
        start = min(t for t in times if t >= launch - 2000)
        # Real time (50 ms per frame) to apogee + 3 s, then 200 ms of flight per frame to landing + 3 s.
        cls.expected = []
        tick = start
        while tick <= landing + 3000:
            cls.expected.append(max((r for r in samples if int(r['time_ms']) <= tick),
                                    key=lambda r: int(r['time_ms'])))
            tick += 50 if tick < apogee + 3000 else 200
        cls.frames = [decode(frame)['fields'] for frame in rom_frames()]

    def test_one_frame_per_20hz_tick(self):
        self.assertEqual(len(self.frames), len(self.expected))

    def test_fields_match_csv_within_firmware_scaling(self):
        def value(row, column):
            return float(row[column]) if row[column] else 0.0

        # (decoded field, CSV column, LSB, int16 scale) for tlm_s16 fields
        scaled = [('gps_alt_m', 'gps_alt_msl_m', 0.5, 2), ('alt_agl_m', 'alt_m', 0.1, 10),
                  ('velocity_mps', 'vel_mps', 0.02, 50), ('pred_apogee_m', 'pred_apogee_m', 0.1, 10),
                  ('vert_accel_mps2', 'vert_accel_mps2', 0.01, 100), ('accel_z_mps2', 'az_mss', 0.01, 100),
                  ('roll_rate_rads', 'gz_rads', 0.002, 500)]
        for index, (fields, row) in enumerate(zip(self.frames, self.expected)):
            with self.subTest(frame=index):
                self.assertEqual(fields['phase'], row['phase'])
                # This log never has a fix, so the generator emulates the GPS group (checked in
                # test_apex_flight_generator); every other field must be the logged value.
                self.assertLessEqual(int(value(row, 'gps_fix')), 0)
                self.assertEqual(fields['gps_fix'], 3)
                for name, column, lsb, scale in scaled:
                    if name in EMULATED:
                        continue
                    target = min(max(value(row, column), -32768 / scale), 32767 / scale)   # int16 clamp
                    self.assertLessEqual(abs(fields[name] - target), lsb / 2 + 1e-6, name)
                deploy = value(row, 'deploy')
                self.assertTrue(deploy - 1 / 255 - 1e-6 <= fields['deployment'] <= deploy + 1e-6)
                pressure = value(row, 'baro_pa')
                self.assertTrue(pressure - 2 < fields['baro_pa'] <= pressure + 1e-3)
                self.assertEqual(fields['baro_temp_c'], int(value(row, 'baro_temp_c')))

    def test_checked_in_rom_is_current(self):
        spec = importlib.util.spec_from_file_location('apex_flight_rom',
                                                      REPO / 'projects/sdr/host/apex_flight_rom.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        self.assertEqual(generator.render_mem(generator.load_rows(CSV), CSV), ROM_MEM.read_text())


if __name__ == '__main__':
    unittest.main()

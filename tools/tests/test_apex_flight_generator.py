"""The demo ROM generator on a small synthetic flight log (no apex checkout needed).

Frames are decoded with the host's APEX parser (sdr_cli.apex), not with the
generator's packer. The fixture is a made-up flight with the CSV columns the
generator reads; it does not stand in for the IREC log.
"""
import importlib.util
import math
from pathlib import Path
import unittest

from sdr_cli import apex, receiver_control
from link_samples import with_crc

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('apex_flight_rom', REPO / 'projects/sdr/host/apex_flight_rom.py')
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

PAD = (31.0427222, -103.5316389)
LAUNCH, COAST, DESCENT, LANDED, LAST = 10_000, 10_500, 18_000, 40_000, 50_000


def event(t, phase, kind):
    return dict(record_type='EVENT', time_ms=str(t), phase=phase, event=kind)


def sample(t, phase, alt, fix=0, lat='65.69', lon='123.22'):
    return dict(record_type='SAMPLE', time_ms=str(t), phase=phase, event='', gps_fix=str(fix), gps_sats='0',
                storage_health='2', gps_lat_deg=lat, gps_lon_deg=lon, gps_alt_msl_m='18223.8', alt_m=str(alt),
                vel_mps='0', pred_apogee_m='0', vert_accel_mps2='0', az_mss='-9.8', gz_rads='0', deploy='0',
                baro_pa='90268', baro_temp_c='30')


def fixture(**overrides):
    rows = [event(LAUNCH, 'BOOST', 'LAUNCH_DETECTED'), event(COAST, 'COAST', 'PHASE'),
            event(DESCENT, 'DESCENT', 'PHASE'), event(LANDED, 'LANDED', 'PHASE')]
    for t in range(0, LAST + 1, 20):
        if t < LAUNCH:
            phase, alt = 'ARMED', 0.0
        elif t < COAST:
            phase, alt = 'BOOST', (t - LAUNCH) * 0.1
        elif t < DESCENT:
            phase, alt = 'COAST', 50 + (t - COAST) * 0.2
        elif t < LANDED:
            phase, alt = 'DESCENT', max(0.0, 1550 - (t - DESCENT) * 0.07)
        else:
            phase, alt = 'LANDED', 0.0
        rows.append(sample(t, phase, alt, **overrides))
    return rows


def decoded(rows):
    return [apex.parse_frame(with_crc(f))['fields'] for f in gen.build_frames(rows, pad=PAD)]


def offset_m(fields):
    north = (fields['lat_deg'] - PAD[0]) * gen.M_PER_DEG_LAT
    east = (fields['lon_deg'] - PAD[1]) * gen.M_PER_DEG_LAT * math.cos(math.radians(PAD[0]))
    return math.hypot(north, east)


class ScheduleTest(unittest.TestCase):
    def test_real_time_to_apogee_then_four_times_faster_to_landing(self):
        ticks = gen.replay_ticks(fixture())
        self.assertEqual(ticks[0], LAUNCH - gen.PRE_LAUNCH_MS)
        steps = [b - a for a, b in zip(ticks, ticks[1:])]
        cut = ticks.index(DESCENT + gen.POST_APOGEE_MS)
        self.assertEqual(set(steps[:cut]), {gen.TICK_MS})
        self.assertEqual(set(steps[cut:]), {gen.DESCENT_STEP_MS})
        self.assertLessEqual(ticks[-1], LANDED + gen.POST_LANDING_MS)
        self.assertGreater(ticks[-1] + gen.DESCENT_STEP_MS, LANDED + gen.POST_LANDING_MS)

    def test_frames_cover_the_whole_flight_in_phase_order(self):
        phases = [f['phase'] for f in decoded(fixture())]
        order = ['ARMED', 'BOOST', 'COAST', 'DESCENT', 'LANDED']
        ranks = [order.index(p) for p in phases]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(set(phases), set(order))

    def test_without_a_landing_event_the_log_end_closes_the_window(self):
        rows = [r for r in fixture() if not (r['record_type'] == 'EVENT' and r['phase'] == 'LANDED')]
        self.assertEqual(gen.flight_window(rows)[1], LAST)

    def test_rom_budget_is_enforced(self):
        rows = fixture()
        budget = gen.ROM_BUDGET_BYTES
        gen.ROM_BUDGET_BYTES = gen.FRAME_BYTES * 10
        try:
            with self.assertRaises(ValueError):
                gen.build_frames(rows, pad=PAD)
        finally:
            gen.ROM_BUDGET_BYTES = budget


class EmulationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = decoded(fixture())

    def test_deterministic(self):
        self.assertEqual(gen.build_frames(fixture(), pad=PAD), gen.build_frames(fixture(), pad=PAD))

    def test_gps_starts_at_the_pad_drifts_and_holds_after_landing(self):
        f = self.frames
        self.assertTrue(all(x['gps_fix'] == 3 for x in f))
        self.assertTrue(all(9 <= x['gps_sats'] + (x['phase'] == 'BOOST') <= 12 for x in f))
        self.assertLess(offset_m(f[0]), 8)            # on the pad, within the GPS noise
        peak = max(x['alt_agl_m'] for x in f)
        landed = [x for x in f if x['phase'] == 'LANDED']
        expected = gen.ASCENT_DRIFT * peak + gen.WIND_MPS * (LANDED - DESCENT) / 1000.0
        for x in landed:
            self.assertAlmostEqual(offset_m(x), expected, delta=10)
        bearing = math.degrees(math.atan2((landed[-1]['lon_deg'] - PAD[1]) * math.cos(math.radians(PAD[0])),
                                          landed[-1]['lat_deg'] - PAD[0]))
        self.assertAlmostEqual(bearing, gen.DRIFT_BEARING_DEG, delta=1)

    def test_gps_altitude_is_pad_elevation_plus_agl(self):
        elev = gen.pressure_altitude(90268)
        for x in self.frames:
            self.assertAlmostEqual(x['gps_alt_m'], elev + x['alt_agl_m'], delta=10)

    def test_a_logged_fix_is_kept(self):
        f = decoded(fixture(fix=3, lat='31.5', lon='-103.0'))
        self.assertTrue(all(x['lat_deg'] == gen.f32(31.5) and x['lon_deg'] == gen.f32(-103.0) for x in f))
        self.assertTrue(all(x['gps_alt_m'] == 32767 * 0.5 for x in f))   # the logged value, int16-clamped

    def test_interlocks_and_health_follow_the_phase(self):
        for x in self.frames:
            on = x['interlocks']
            phase = x['phase']
            self.assertEqual(on['airbrakes_authorized'], phase == 'COAST', phase)
            self.assertEqual(on['servo_powered'], phase in ('ARMED', 'BOOST', 'COAST', 'DESCENT'), phase)
            self.assertTrue(on['arm_switches_closed'] and on['logging_ready'] and on['gps_time_valid'])
            h = x['health_bits']
            self.assertTrue(h['imu'] and h['highg'] and h['baro'] and h['mag'] and h['radio'] and h['gps'])
            self.assertTrue(h['sd'] and not h['qspi'])      # storage_health 2 = STORAGE_OK_SD only

    def test_tilt_and_azimuth_are_plausible(self):
        for x in self.frames:
            self.assertTrue(0 <= x['azimuth_deg'] < 360)
            if x['phase'] == 'ARMED':
                self.assertEqual(x['tilt_deg'], 2)
            elif x['phase'] in ('BOOST', 'COAST'):
                self.assertTrue(2 <= x['tilt_deg'] <= 27)
            elif x['phase'] == 'DESCENT':
                self.assertTrue(92 <= x['tilt_deg'] <= 108)
            else:
                self.assertEqual(x['tilt_deg'], 88)

    def test_logged_fields_are_not_touched(self):
        for x in self.frames:
            self.assertEqual(x['baro_pa'], 90268)
            self.assertEqual(x['baro_temp_c'], 30)


class EmulatedListTest(unittest.TestCase):
    def test_keys_are_schema_keys_and_match_the_demo_profile(self):
        keys = [k for k, _ in gen.EMULATED]
        schema = [f['key'] for f in apex.FLIGHT_SCHEMA]
        self.assertTrue(set(keys) <= set(schema))
        profile = receiver_control.profile_for(receiver_control.APEX_DEMO_BUILD_ID)
        self.assertEqual(profile['emulated_fields'], keys)
        self.assertIn('emulated', profile['emulated_note'])


if __name__ == '__main__':
    unittest.main()

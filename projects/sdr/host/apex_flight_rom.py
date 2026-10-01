#!/usr/bin/env python3
"""Generate the APEX flight replay ROM for the opt-in demo bitstream.

Reads the IREC 2026 flight log exported by the apex repository and writes
``projects/sdr/rom/apex_flight.mem``: one hex byte per line for ``$readmemh``.
The build never reads the CSV; the generated ``.mem`` is checked in.

Regenerate (from the repository root, with the apex checkout next to this one):

    python3 projects/sdr/host/apex_flight_rom.py
    python3 projects/sdr/host/apex_flight_rom.py --check   # verify it is current

Each ROM frame is the bytes the APEX firmware places after the 0x2DD4 sync:
the type byte 0x02 and the 41-byte little-endian FLIGHT body (42 bytes). The
RTL transmitter (adc_signal_source) sends preamble and sync, streams these
bytes MSB first, and appends CRC-16-CCITT (0x1021, init 0xFFFF, big-endian)
over type+body, as apex fsw/src/radio.cpp radio_build_frame() does.

Replay choices (documented assumptions, not firmware facts):
- Window: the whole flight, from 2 s before LAUNCH_DETECTED to 3 s after the
  PHASE event that enters LANDED (or the last SAMPLE row if there is none).
- Cadence: one frame per 20 Hz radio slot. Up to 3 s after apogee (the PHASE
  event that leaves COAST) each frame advances 50 ms of flight time, which is
  real time. After that each frame advances DESCENT_STEP_MS (200 ms), so the
  descent and landing replay at 4x speed and the ROM fits ROM_BUDGET_BYTES.
  Each frame uses the latest SAMPLE row at or before its flight time (a
  zero-order hold). Values are never interpolated.
- seq: a radio counter from 0 (the CSV seq is a log counter, not radio seq).
- Only FLIGHT frames. The firmware's once-per-second HOUSEKEEPING beat is not
  replayed, so no seq numbers are skipped.
- health bits 4, 6 and 7 are derived as the firmware derives them, from the
  gps_fix sent (>= 0) and storage_health (STORAGE_OK_FLASH=1, STORAGE_OK_SD=2;
  INFERRED to be the logged storage_health() value).
- Fields the log does not have are EMULATED (table EMULATED below), so the demo
  shows a complete ground-station view. Emulation is deterministic (seeded) and
  follows the logged altitude and phase. The GUI labels these fields as
  emulated; they are not flight data. The host decoder never invents values.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import sys

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CSV = (REPO.parent / 'apex/sim/output/log_exports/Flight_02_2026-06-17T21-28-54-800'
               / 'IREC-2026-SRAD-TELEMETRY.csv')
DEFAULT_MEM = REPO / 'projects/sdr/rom/apex_flight.mem'
SITES = REPO / 'tools/sdr_cli/sites.json'
SITE_ID = 'irec-pecos'

FRAME_TYPE_FLIGHT = 0x02
CALLSIGN = b'KG5LDI'
TICK_MS = 50                # 20 Hz, RADIO_TELEM_FLIGHT_HZ
PRE_LAUNCH_MS = 2000
POST_APOGEE_MS = 3000
DESCENT_STEP_MS = 200       # flight time per frame after apogee + POST_APOGEE_MS (4x speed)
POST_LANDING_MS = 3000
ROM_BUDGET_BYTES = 64 * 1024   # demo ROM budget: at most 16 of the 50 RAMB36 tiles
PHASES = ('IDLE', 'ARMED', 'BOOST', 'COAST', 'DESCENT', 'LANDED')   # flight_state.h
STORAGE_OK_FLASH, STORAGE_OK_SD = 0x01, 0x02                       # storage.h
HEALTH_GPS, HEALTH_QSPI, HEALTH_SD = 0x10, 0x40, 0x80                # radio.cpp
HEALTH_SENSORS_AND_RADIO = 0x01 | 0x02 | 0x04 | 0x08 | 0x20          # imu, highg, baro, mag, radio
FLAG_AIRBRAKES_AUTH, FLAG_SERVO_POWER, FLAG_ARM_SWITCHES = 0x08, 0x10, 0x20
FLAG_LOG_READY, FLAG_GPS_TIME = 0x40, 0x80

# Emulation constants: demo choices, not flight data.
SEED = 2026
ASCENT_DRIFT = 0.12         # metres downrange per metre of climb (weathercocking)
WIND_MPS = 4.0              # drift under canopy, from the altitude peak until landing
DRIFT_BEARING_DEG = 62.0    # direction of the drift, degrees true
GPS_SIGMA_M = 1.5           # horizontal noise per axis, 1 sigma
GPS_ALT_SIGMA_M = 2.0
M_PER_DEG_LAT = 111320.0

# Every emulated FLIGHT field: (GUI schema key, rule). The demo receiver profile
# (tools/sdr_cli/receiver_control.py) lists the same keys so the GUI can label
# them as emulated; tools/tests/test_apex_flight_rom.py keeps the two in step.
EMULATED = (
    ('gps_fix', 'only when the logged fix is OFFLINE or SEARCHING: a 3D fix'),
    ('gps_sats', 'with an emulated fix: 9 to 12 satellites (a slow seeded random walk), one fewer in BOOST'),
    ('lat_deg', 'with an emulated fix: the irec-pecos pad (sites.json), moving {} m downrange per metre of '
                'climb, then {} m/s from the altitude peak until landing, toward {} deg true, plus {} m '
                'noise'.format(ASCENT_DRIFT, WIND_MPS, DRIFT_BEARING_DEG, GPS_SIGMA_M)),
    ('lon_deg', 'as lat_deg'),
    ('gps_alt_m', 'with an emulated fix: pad elevation (standard-atmosphere altitude of the mean logged ARMED '
                  'pressure) plus the logged altitude AGL, plus {} m noise'.format(GPS_ALT_SIGMA_M)),
    ('phase_status', 'interlock bits 3-7: airbrakes authorized in COAST, servo powered from ARMED to DESCENT, '
                     'arm switches closed from ARMED, logging ready always, GPS time valid with a 2D or 3D fix. '
                     'The phase bits 0-2 are logged.'),
    ('health', 'sensor bits 0-3 (IMU, high-g, baro, mag) and radio bit 5 on; bits 4, 6 and 7 derived as the '
               'firmware does'),
    ('tilt_deg', '2 deg on the rail, growing to 27 deg at the highest logged altitude, about 100 deg swinging '
                 'under canopy, 88 deg landed'),
    ('azimuth_deg', 'the drift bearing with a 3 deg wobble in BOOST and COAST, turning 20 deg/s under canopy, '
                    'held after landing'),
)

# APEX TelemFlight (fsw/src/radio.cpp:61-83, static_assert 41 bytes), packed
# little-endian. This table is the single place the layout is written down here.
# (offset, name, struct code, encoding, CSV column or None)
# Encodings follow radio.cpp:631-663:
#   s16:<scale>  tlm_s16(v, scale): float32 v*scale, clamp to int16, lroundf
#   trunc:<scale>:<lo>:<hi>  C cast of constrain(v*scale, lo, hi) (truncates)
#   f32 / i8 / u8 / u16 / text  copied; derived fields are built in pack_flight
#   emulated  absent from the log; the Emulator supplies it (table EMULATED)
FLIGHT_FIELDS = (
    (0, 'callsign', '6s', 'text', None),
    (6, 'seq', 'H', 'u16', None),
    (8, 'phase_status', 'B', 'derived', 'phase'),
    (9, 'health', 'B', 'derived', 'gps_fix, storage_health'),
    (10, 'gps_fix', 'b', 'i8', 'gps_fix'),
    (11, 'gps_sats', 'B', 'u8', 'gps_sats'),
    (12, 'gps_lat_deg', 'f', 'f32', 'gps_lat_deg'),
    (16, 'gps_lon_deg', 'f', 'f32', 'gps_lon_deg'),
    (20, 'gps_alt_msl', 'h', 's16:2', 'gps_alt_msl_m'),
    (22, 'alt_agl', 'h', 's16:10', 'alt_m'),
    (24, 'velocity', 'h', 's16:50', 'vel_mps'),
    (26, 'pred_apogee', 'h', 's16:10', 'pred_apogee_m'),
    (28, 'vert_accel', 'h', 's16:100', 'vert_accel_mps2'),
    (30, 'accel_z', 'h', 's16:100', 'az_mss'),
    (32, 'roll_rate', 'h', 's16:500', 'gz_rads'),
    (34, 'deployment', 'B', 'trunc:255:0:255', 'deploy'),
    (35, 'baro_pa', 'H', 'trunc:0.5:0:65535', 'baro_pa'),
    (37, 'baro_temp', 'b', 'trunc:1:-128:127', 'baro_temp_c'),
    (38, 'tilt_deg', 'b', 'emulated', None),
    (39, 'azimuth', 'H', 'emulated', None),
)
FLIGHT_STRUCT = struct.Struct('<' + ''.join(code for _, _, code, _, _ in FLIGHT_FIELDS))
FRAME_BYTES = 1 + FLIGHT_STRUCT.size        # type + body in the ROM; CRC is added by RTL
assert FLIGHT_STRUCT.size == 41
assert all(offset == struct.calcsize('<' + ''.join(f[2] for f in FLIGHT_FIELDS[:i]))
           for i, (offset, *_rest) in enumerate(FLIGHT_FIELDS))


def crc16_ccitt(data, crc=0xFFFF):
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        crc &= 0xFFFF
    return crc


def f32(value):
    """Round a Python float to IEEE float32, as the firmware stores it."""
    return struct.unpack('<f', struct.pack('<f', value))[0]


def lround(value):
    """C lroundf: nearest, halves away from zero."""
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def tlm_s16(value, scale):
    scaled = f32(f32(value) * f32(scale))
    if scaled >= 32767.0:
        return 32767
    if scaled <= -32768.0:
        return -32768
    return lround(scaled)


def trunc_clamped(value, scale, low, high):
    return int(min(max(f32(f32(value) * f32(scale)), low), high))


def number(row, column):
    text = row.get(column, '')
    return float(text) if text not in ('', None) else 0.0


def encode(row, encoding, column):
    kind, *args = encoding.split(':')
    if kind == 's16':
        return tlm_s16(number(row, column), float(args[0]))
    if kind == 'trunc':
        return trunc_clamped(number(row, column), *(float(a) for a in args))
    if kind == 'f32':
        return f32(number(row, column))
    if kind in ('i8', 'u8'):
        return int(number(row, column))
    if kind == 'emulated':
        return 0
    raise ValueError(encoding)


def pack_flight(row, seq, emulated=None):
    """TelemFlight body (41 bytes) for one CSV SAMPLE row.

    ``emulated`` maps FLIGHT_FIELDS names to wire values from the Emulator, plus
    'flag_bits' and 'health_bits' to OR into phase_status and health.
    """
    emulated = emulated or {}
    phase = PHASES.index(row['phase'])
    gps_fix = emulated.get('gps_fix', int(number(row, 'gps_fix')))
    storage = int(number(row, 'storage_health'))
    health = ((HEALTH_GPS if gps_fix >= 0 else 0) | (HEALTH_QSPI if storage & STORAGE_OK_FLASH else 0) |
              (HEALTH_SD if storage & STORAGE_OK_SD else 0) | emulated.get('health_bits', 0))
    values = []
    for _, name, _, encoding, column in FLIGHT_FIELDS:
        if name == 'callsign':
            values.append(CALLSIGN)
        elif name == 'seq':
            values.append(seq & 0xFFFF)
        elif name == 'phase_status':
            values.append((phase & 0x07) | emulated.get('flag_bits', 0))
        elif name == 'health':
            values.append(health)
        elif name in emulated:
            values.append(emulated[name])
        else:
            values.append(encode(row, encoding, column))
    return FLIGHT_STRUCT.pack(*values)


def site_pad(site_id=SITE_ID, path=SITES):
    """(lat, lon) of a site's pad in the tracked site registry."""
    sites = json.loads(Path(path).read_text())['sites']
    return tuple(next(s['pad'] for s in sites if s['id'] == site_id))


def pressure_altitude(pa):
    """Standard-atmosphere altitude (m) of a static pressure (Pa)."""
    return 44330.77 * (1.0 - (pa / 101325.0) ** 0.190263)


class Emulator:
    """Plausible wire values for the fields the flight log lacks (table EMULATED).

    Deterministic: seeded, and fed the selected rows in replay order.
    """

    def __init__(self, samples, pad, launch_ms, landing_ms):
        self.rng = random.Random(SEED)
        self.pad = pad
        armed = [number(r, 'baro_pa') for r in samples if r['phase'] == 'ARMED' and number(r, 'baro_pa') > 0]
        self.pad_elev = pressure_altitude(sum(armed) / len(armed)) if armed else 0.0
        self.top_alt = max([number(r, 'alt_m') for r in samples] + [1.0])
        self.launch_ms = launch_ms
        self.landing_ms = landing_ms
        self.sats = 10
        self.peak_alt = 0.0
        self.peak_ms = launch_ms
        self.azimuth = DRIFT_BEARING_DEG

    def values(self, tick_ms, row):
        """Wire values to override for one frame (see pack_flight)."""
        phase = row['phase']
        alt = number(row, 'alt_m')
        t = min(tick_ms, self.landing_ms)
        if tick_ms >= self.launch_ms and phase != 'LANDED' and alt > self.peak_alt:
            self.peak_alt, self.peak_ms = alt, t
        if self.rng.random() < 0.05:
            self.sats = min(12, max(9, self.sats + self.rng.choice((-1, 1))))
        out = {'health_bits': HEALTH_SENSORS_AND_RADIO}
        fix = int(number(row, 'gps_fix'))
        if fix <= 0:
            fix = 3
            dist = ASCENT_DRIFT * self.peak_alt + WIND_MPS * max(0.0, (t - self.peak_ms) / 1000.0)
            bearing = math.radians(DRIFT_BEARING_DEG)
            north = dist * math.cos(bearing) + self.rng.gauss(0.0, GPS_SIGMA_M)
            east = dist * math.sin(bearing) + self.rng.gauss(0.0, GPS_SIGMA_M)
            out.update(
                gps_fix=fix, gps_sats=self.sats - (1 if phase == 'BOOST' else 0),
                gps_lat_deg=f32(self.pad[0] + north / M_PER_DEG_LAT),
                gps_lon_deg=f32(self.pad[1] + east / (M_PER_DEG_LAT * math.cos(math.radians(self.pad[0])))),
                gps_alt_msl=tlm_s16(self.pad_elev + alt + self.rng.gauss(0.0, GPS_ALT_SIGMA_M), 2))
        flags = FLAG_LOG_READY
        if phase == 'COAST':
            flags |= FLAG_AIRBRAKES_AUTH
        if phase in ('ARMED', 'BOOST', 'COAST', 'DESCENT'):
            flags |= FLAG_SERVO_POWER
        if phase != 'IDLE':
            flags |= FLAG_ARM_SWITCHES
        if fix >= 2:
            flags |= FLAG_GPS_TIME
        out['flag_bits'] = flags
        seconds = tick_ms / 1000.0
        if phase in ('IDLE', 'ARMED'):
            tilt = 2.0
            self.azimuth = DRIFT_BEARING_DEG
        elif phase in ('BOOST', 'COAST'):
            tilt = 2.0 + 25.0 * min(1.0, max(0.0, alt) / self.top_alt) ** 2
            self.azimuth = DRIFT_BEARING_DEG + 3.0 * math.sin(2 * math.pi * seconds / 2.5)
        elif phase == 'DESCENT':
            tilt = 100.0 + 8.0 * math.sin(2 * math.pi * seconds / 7.0)
            self.azimuth = (DRIFT_BEARING_DEG + 20.0 * (tick_ms - self.peak_ms) / 1000.0) % 360.0
        else:
            tilt = 88.0
        out['tilt_deg'] = max(-128, min(127, int(round(tilt))))
        out['azimuth'] = int(round(self.azimuth * 10)) % 3600
        return out


def load_rows(csv_path):
    with open(csv_path, newline='') as stream:
        return list(csv.DictReader(stream))


def flight_window(rows):
    """Return (start_ms, end_ms, launch_ms, apogee_ms, landing_ms) per the replay window rule."""
    events = [r for r in rows if r['record_type'] == 'EVENT']
    samples = [r for r in rows if r['record_type'] == 'SAMPLE']
    launch = next(int(r['time_ms']) for r in events if r['event'] == 'LAUNCH_DETECTED')
    apogee = next(int(r['time_ms']) for r in events
                  if r['event'] == 'PHASE' and int(r['time_ms']) > launch and r['phase'] not in ('BOOST', 'COAST'))
    last = max(int(r['time_ms']) for r in samples)
    landing = next((int(r['time_ms']) for r in events
                    if r['event'] == 'PHASE' and r['phase'] == 'LANDED' and int(r['time_ms']) > apogee), last)
    begin = launch - PRE_LAUNCH_MS
    start = min(int(r['time_ms']) for r in samples if int(r['time_ms']) >= begin)
    return start, min(landing + POST_LANDING_MS, last), launch, apogee, landing


def replay_ticks(rows):
    """Flight times (ms) of the ROM frames: 50 ms steps to apogee + 3 s, then DESCENT_STEP_MS steps."""
    start, end, _, apogee, _ = flight_window(rows)
    ticks, tick = [], start
    while tick <= end:
        ticks.append(tick)
        tick += TICK_MS if tick < apogee + POST_APOGEE_MS else DESCENT_STEP_MS
    return ticks


def select_rows(rows):
    """Zero-order hold over the replay ticks: [(tick_ms, row), ...]."""
    samples = sorted((r for r in rows if r['record_type'] == 'SAMPLE'), key=lambda r: int(r['time_ms']))
    chosen, index = [], 0
    for tick in replay_ticks(rows):
        while index + 1 < len(samples) and int(samples[index + 1]['time_ms']) <= tick:
            index += 1
        chosen.append((tick, samples[index]))
    return chosen


def build_frames(rows, pad=None):
    """ROM frames (type + body) of the replay, with the emulated fields filled in."""
    _, _, launch, _, landing = flight_window(rows)
    samples = [r for r in rows if r['record_type'] == 'SAMPLE']
    emulator = Emulator(samples, pad or site_pad(), launch, landing)
    frames = [bytes([FRAME_TYPE_FLIGHT]) + pack_flight(row, seq, emulator.values(tick, row))
              for seq, (tick, row) in enumerate(select_rows(rows))]
    if len(frames) * FRAME_BYTES > ROM_BUDGET_BYTES:
        raise ValueError('{} frames exceed the {}-byte ROM budget'.format(len(frames), ROM_BUDGET_BYTES))
    return frames


def render_mem(rows, csv_path):
    start, _, launch, apogee, landing = flight_window(rows)
    digest = hashlib.sha256(Path(csv_path).read_bytes()).hexdigest()
    selected = select_rows(rows)
    frames = build_frames(rows)
    lines = [
        '// APEX IREC 2026 flight replay ROM. GENERATED, do not edit.',
        '// Regenerate: python3 projects/sdr/host/apex_flight_rom.py --csv <IREC-2026-SRAD-TELEMETRY.csv>',
        '// Source: apex sim/output/log_exports/Flight_02_2026-06-17T21-28-54-800/'
        'IREC-2026-SRAD-TELEMETRY.csv',
        '// Source sha256: ' + digest,
        '// Window: LAUNCH_DETECTED {} ms - {} ms to LANDED {} ms + {} ms; ticks {}..{} ms'.format(
            launch, PRE_LAUNCH_MS, landing, POST_LANDING_MS, start, selected[-1][0]),
        '// Cadence: 50 ms of flight per frame to apogee {} ms + {} ms, then {} ms per frame'.format(
            apogee, POST_APOGEE_MS, DESCENT_STEP_MS),
        '// EMULATED (absent from the log, see EMULATED in the generator): '
        + ', '.join(key for key, _ in EMULATED),
        '// {} frames x {} bytes: type 0x02 + 41-byte FLIGHT body. The RTL appends the CRC.'.format(
            len(selected), FRAME_BYTES),
    ]
    for seq, ((tick, row), frame) in enumerate(zip(selected, frames)):
        lines.append('// frame {} tick {} ms row {} {}'.format(seq, tick, row['time_ms'], row['phase']))
        lines += ['{:02x}'.format(b) for b in frame]
    return '\n'.join(lines) + '\n'


def read_mem(path):
    """Parse a generated .mem file back into a list of ROM frames."""
    data = bytearray()
    for line in Path(path).read_text().splitlines():
        text = line.split('//', 1)[0].strip()
        if text:
            data.append(int(text, 16))
    if len(data) % FRAME_BYTES:
        raise ValueError('ROM size is not a whole number of frames')
    return [bytes(data[i:i + FRAME_BYTES]) for i in range(0, len(data), FRAME_BYTES)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--csv', type=Path, default=DEFAULT_CSV, help='APEX IREC-2026-SRAD-TELEMETRY.csv')
    parser.add_argument('--output', type=Path, default=DEFAULT_MEM)
    parser.add_argument('--check', action='store_true', help='Fail if the output differs from a fresh generation')
    args = parser.parse_args(argv)
    if not args.csv.is_file():
        print('CSV not found: {} (pass --csv)'.format(args.csv), file=sys.stderr)
        return 2
    text = render_mem(load_rows(args.csv), args.csv)
    if args.check:
        current = args.output.read_text() if args.output.exists() else ''
        if current != text:
            print('{} is stale; regenerate it'.format(args.output), file=sys.stderr)
            return 1
        print('{} is current'.format(args.output))
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    frames = read_mem(args.output)
    print('Wrote {}: {} frames, {} ROM bytes'.format(args.output, len(frames), len(frames) * FRAME_BYTES))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

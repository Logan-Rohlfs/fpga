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
- Window: SAMPLE rows from 2 s before LAUNCH_DETECTED through 3 s after
  apogee, where apogee is the PHASE event that leaves COAST.
- Cadence: 20 Hz ticks starting at the first SAMPLE row in the window. Each
  tick uses the latest SAMPLE row at or before it (a zero-order hold).
- seq: a radio counter from 0 (the CSV seq is a log counter, not radio seq).
- Only FLIGHT frames. The firmware's once-per-second HOUSEKEEPING beat is not
  replayed, so no seq numbers are skipped.
- Fields absent from the CSV are zero: phase_status flag bits 3-7, health
  sensor bits 0-3 and radio bit 5, tilt_deg and azimuth. health bits 4, 6
  and 7 are derived as the firmware derives them, from the CSV gps_fix
  (>= 0) and storage_health (STORAGE_OK_FLASH=1, STORAGE_OK_SD=2; INFERRED
  to be the logged storage_health() value).
- gps_lat/lon are copied as logged (they look like placeholders in this log).
"""
import argparse
import csv
import hashlib
import math
from pathlib import Path
import struct
import sys

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CSV = (REPO.parent / 'apex/sim/output/log_exports/Flight_02_2026-06-17T21-28-54-800'
               / 'IREC-2026-SRAD-TELEMETRY.csv')
DEFAULT_MEM = REPO / 'projects/sdr/rom/apex_flight.mem'

FRAME_TYPE_FLIGHT = 0x02
CALLSIGN = b'KG5LDI'
TICK_MS = 50                # 20 Hz, RADIO_TELEM_FLIGHT_HZ
PRE_LAUNCH_MS = 2000
POST_APOGEE_MS = 3000
PHASES = ('IDLE', 'ARMED', 'BOOST', 'COAST', 'DESCENT', 'LANDED')   # flight_state.h
STORAGE_OK_FLASH, STORAGE_OK_SD = 0x01, 0x02                       # storage.h
HEALTH_GPS, HEALTH_QSPI, HEALTH_SD = 0x10, 0x40, 0x80                # radio.cpp

# APEX TelemFlight (fsw/src/radio.cpp:61-83, static_assert 41 bytes), packed
# little-endian. This table is the single place the layout is written down here.
# (offset, name, struct code, encoding, CSV column or None)
# Encodings follow radio.cpp:631-663:
#   s16:<scale>  tlm_s16(v, scale): float32 v*scale, clamp to int16, lroundf
#   trunc:<scale>:<lo>:<hi>  C cast of constrain(v*scale, lo, hi) (truncates)
#   f32 / i8 / u8 / u16 / text  copied; derived fields are built in pack_flight
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
    (38, 'tilt_deg', 'b', 'zero', None),
    (39, 'azimuth', 'H', 'zero', None),
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
    if kind == 'zero':
        return 0
    raise ValueError(encoding)


def pack_flight(row, seq):
    """TelemFlight body (41 bytes) for one CSV SAMPLE row."""
    phase = PHASES.index(row['phase'])
    gps_fix = int(number(row, 'gps_fix'))
    storage = int(number(row, 'storage_health'))
    health = ((HEALTH_GPS if gps_fix >= 0 else 0) | (HEALTH_QSPI if storage & STORAGE_OK_FLASH else 0) |
              (HEALTH_SD if storage & STORAGE_OK_SD else 0))
    values = []
    for _, name, _, encoding, column in FLIGHT_FIELDS:
        if name == 'callsign':
            values.append(CALLSIGN)
        elif name == 'seq':
            values.append(seq & 0xFFFF)
        elif name == 'phase_status':
            values.append(phase & 0x07)
        elif name == 'health':
            values.append(health)
        else:
            values.append(encode(row, encoding, column))
    return FLIGHT_STRUCT.pack(*values)


def load_rows(csv_path):
    with open(csv_path, newline='') as stream:
        return list(csv.DictReader(stream))


def flight_window(rows):
    """Return (start_ms, end_ms, launch_ms, apogee_ms) per the replay window rule."""
    launch = next(int(r['time_ms']) for r in rows
                  if r['record_type'] == 'EVENT' and r['event'] == 'LAUNCH_DETECTED')
    apogee = next(int(r['time_ms']) for r in rows
                  if r['record_type'] == 'EVENT' and r['event'] == 'PHASE' and int(r['time_ms']) > launch
                  and r['phase'] not in ('BOOST', 'COAST'))
    samples = [r for r in rows if r['record_type'] == 'SAMPLE']
    begin = launch - PRE_LAUNCH_MS
    start = min(int(r['time_ms']) for r in samples if int(r['time_ms']) >= begin)
    return start, apogee + POST_APOGEE_MS, launch, apogee


def select_rows(rows):
    """20 Hz zero-order hold over the replay window: [(tick_ms, row), ...]."""
    start, end, _, _ = flight_window(rows)
    samples = sorted((r for r in rows if r['record_type'] == 'SAMPLE'), key=lambda r: int(r['time_ms']))
    chosen, index = [], 0
    tick = start
    while tick <= end:
        while index + 1 < len(samples) and int(samples[index + 1]['time_ms']) <= tick:
            index += 1
        chosen.append((tick, samples[index]))
        tick += TICK_MS
    return chosen


def build_frames(rows):
    return [bytes([FRAME_TYPE_FLIGHT]) + pack_flight(row, seq) for seq, (_, row) in enumerate(select_rows(rows))]


def render_mem(rows, csv_path):
    start, end, launch, apogee = flight_window(rows)
    digest = hashlib.sha256(Path(csv_path).read_bytes()).hexdigest()
    selected = select_rows(rows)
    lines = [
        '// APEX IREC 2026 flight replay ROM. GENERATED, do not edit.',
        '// Regenerate: python3 projects/sdr/host/apex_flight_rom.py --csv <IREC-2026-SRAD-TELEMETRY.csv>',
        '// Source: apex sim/output/log_exports/Flight_02_2026-06-17T21-28-54-800/'
        'IREC-2026-SRAD-TELEMETRY.csv',
        '// Source sha256: ' + digest,
        '// Window: LAUNCH_DETECTED {} ms - {} ms to apogee {} ms + {} ms; ticks {}..{} ms at 20 Hz'.format(
            launch, PRE_LAUNCH_MS, apogee, POST_APOGEE_MS, start, selected[-1][0]),
        '// {} frames x {} bytes: type 0x02 + 41-byte FLIGHT body. The RTL appends the CRC.'.format(
            len(selected), FRAME_BYTES),
    ]
    for seq, (tick, row) in enumerate(selected):
        frame = bytes([FRAME_TYPE_FLIGHT]) + pack_flight(row, seq)
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

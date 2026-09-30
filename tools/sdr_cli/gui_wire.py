"""Binary GUI wire formats (spec 3.4): SPECTRUM_ROW and FLIGHT_ROWS, plus golden vectors.

The frontend decodes the same bytes; ``golden_vectors()`` pins the encoding for both sides.
"""
import argparse
import json
import math
import struct
from pathlib import Path

from . import apex
from .protocol import crc16_ccitt

KIND_SPECTRUM = 0x01
KIND_FLIGHT = 0x02
VERSION = 1
ORIGINS = {'A': 0, 'B': 1, 'best': 2}
BEST_FROM = {'A': 0, 'B': 1, 'combined': 2}   # 3 = n/a
INJECTIONS = {'low': 0, 'high': 1}
INJECTION_UNKNOWN = 255

FLAG_SYNTHETIC = 0x01
FLAG_RF_REFERENCE = 0x02
FLAG_RF_INFERRED = 0x04

SPECTRUM_HEADER = struct.Struct('<BBBBIHHddfffdB3x')
FIELD_KEYS = tuple(f['key'] for f in apex.FLIGHT_SCHEMA)
FLIGHT_HEADER = struct.Struct('<BBBBHH')
ROW = struct.Struct('<dBB' + 'f' * len(FIELD_KEYS))
MAX_ROWS = 65535

_ROM = Path(__file__).resolve().parents[2] / 'projects/sdr/rom/apex_flight.mem'


def encode_spectrum(channel, row, t, f0_hz, bin_hz, low, high, db10, synthetic, rf_reference=None):
    flags = FLAG_SYNTHETIC if synthetic else 0
    rf_lo, injection = math.nan, INJECTION_UNKNOWN
    if rf_reference is not None:
        flags |= FLAG_RF_REFERENCE
        if rf_reference.get('inferred'):
            flags |= FLAG_RF_INFERRED
        rf_lo = float(rf_reference['lo_hz'])
        injection = INJECTIONS.get(rf_reference.get('injection'), INJECTION_UNKNOWN)
    db10 = list(db10)
    header = SPECTRUM_HEADER.pack(KIND_SPECTRUM, VERSION, 1 if channel == 'B' else 0, flags, row, len(db10), 0,
                                  t, f0_hz, bin_hz, low, high, rf_lo, injection)
    return header + struct.pack('<{}h'.format(len(db10)), *db10)


def flight_values(fields):
    """The 20 schema-ordered values. phase is its PHASE_ENUM index (UNKNOWN = 6)."""
    values = []
    for key in FIELD_KEYS:
        if key == 'phase':
            phase = fields.get('phase')
            values.append(float(apex.PHASE_ENUM.index(phase) if phase in apex.PHASE_ENUM
                                else apex.PHASE_ENUM.index('UNKNOWN')))
        else:
            values.append(float(fields.get(key, math.nan)))
    return tuple(values)


def encode_flight_row(t, fields, synthetic, best_from=None):
    """One 90-byte row. best_from is the BEST_TELEM source code (0 A, 1 B, 2 combined) or None (3)."""
    code = 3 if best_from is None else int(best_from)
    if not 0 <= code <= 3:
        raise ValueError('best_from must be 0..3 or None')
    flags = (FLAG_SYNTHETIC if synthetic else 0) | (code << 1)
    return ROW.pack(t, flags, 0, *flight_values(fields))


def pack_flight(origin, rows):
    rows = list(rows)
    if len(rows) > MAX_ROWS:
        raise ValueError('too many flight rows: {}'.format(len(rows)))
    return FLIGHT_HEADER.pack(KIND_FLIGHT, VERSION, ORIGINS[origin], 0, len(FIELD_KEYS), len(rows)) + b''.join(rows)


def _f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def _json_num(x):
    return None if isinstance(x, float) and not math.isfinite(x) else x


def _spectrum_vector(name, args, rf_reference):
    channel, row, t, f0, bin_hz, low, high, db10, synthetic = args
    data = encode_spectrum(channel, row, t, f0, bin_hz, low, high, db10, synthetic, rf_reference)
    expect = dict(kind=KIND_SPECTRUM, channel=channel, row=row, t=t, f0_hz=f0, bin_hz=_f32(bin_hz),
                  bins=len(db10), low=_f32(low), high=_f32(high), synthetic=synthetic, db10=list(db10),
                  rf_reference=None)
    if rf_reference is not None:
        expect['rf_reference'] = dict(lo_hz=float(rf_reference['lo_hz']), injection=rf_reference['injection'],
                                      inferred=bool(rf_reference.get('inferred')))
    return dict(name=name, hex=data.hex(), expect=expect)


def _flight_vector(name, origin, rows):
    """rows: [(t, fields, synthetic, best_from)]."""
    data = pack_flight(origin, [encode_flight_row(*r) for r in rows])
    expect_rows = []
    for t, fields, synthetic, best_from in rows:
        expect_rows.append(dict(
            t=t, synthetic=synthetic, best_from=3 if best_from is None else best_from,
            values=[_json_num(_f32(v)) for v in flight_values(fields)]))
    expect = dict(kind=KIND_FLIGHT, origin=origin, field_count=len(FIELD_KEYS), keys=list(FIELD_KEYS),
                  rows=expect_rows)
    return dict(name=name, hex=data.hex(), expect=expect)


def _rom_frame0_fields():
    data = bytearray()
    for line in _ROM.read_text().splitlines():
        text = line.split('//', 1)[0].strip()
        if text:
            data.append(int(text, 16))
    frame = bytes(data[:42])
    frame += bytes([crc16_ccitt(frame) >> 8, crc16_ccitt(frame) & 0xFF])
    return apex.parse_frame(frame)['fields']


def golden_vectors():
    f0 = _rom_frame0_fields()
    f1 = dict(f0, seq=f0['seq'] + 1, phase='BOOST', alt_agl_m=123.4, gps_fix=-1)
    f2 = dict(f0, phase='???', lat_deg=33.5)
    return [
        _spectrum_vector('spectrum_no_rf', ('B', 7, 1.5, 50000.0, 15625.0, -90.0, -10.0, [-900, -100, 0, 32767, -32768],
                                            True), None),
        _spectrum_vector('spectrum_rf_reference', ('A', 123456, 1760000000.25, -1e6, 1953.125, -95.5, -12.25,
                                                   [-950, -800, -125], False),
                         dict(lo_hz=441.38e6, injection='low', inferred=True)),
        _spectrum_vector('spectrum_rf_high', ('A', 1, 2.0, 0.0, 100.0, -80.0, -20.0, [-500], False),
                         dict(lo_hz=500e6, injection='high')),
        _flight_vector('flight_single_best', 'best', [(1760000000.5, f0, True, 0)]),
        _flight_vector('flight_batch_a', 'A', [(1760000001.0, f1, False, None), (1760000001.05, f2, True, None)]),
    ]


def write_golden(path):
    Path(path).write_text(json.dumps(golden_vectors(), indent=2) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description='GUI wire format tools')
    parser.add_argument('--golden', metavar='PATH', required=True, help='write golden vectors JSON')
    write_golden(parser.parse_args(argv).golden)


if __name__ == '__main__':
    main()

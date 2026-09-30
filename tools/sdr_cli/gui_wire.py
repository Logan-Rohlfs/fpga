"""Binary GUI wire formats (spec 3.4): SPECTRUM_ROW and FLIGHT_ROWS, plus golden vectors.

The frontend decodes the same bytes; ``golden_vectors()`` pins the encoding for both sides.
"""
import argparse
import json
import math
import struct
from pathlib import Path

from . import apex

KIND_SPECTRUM = 0x01
KIND_FLIGHT = 0x02
VERSION = 1
ORIGINS = {'A': 0, 'B': 1, 'best': 2}
BEST_FROM = {'A': 0, 'B': 1, 'combined': 2}   # 3 = n/a
CHANNELS = {'A': 0, 'B': 1}
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
    if channel not in ('A', 'B'):
        raise ValueError('channel must be A or B: {!r}'.format(channel))
    flags = FLAG_SYNTHETIC if synthetic else 0
    rf_lo, injection = math.nan, INJECTION_UNKNOWN
    if rf_reference is not None:
        flags |= FLAG_RF_REFERENCE
        if rf_reference.get('inferred'):
            flags |= FLAG_RF_INFERRED
        rf_lo = float(rf_reference['lo_hz'])
        injection = INJECTIONS.get(rf_reference.get('injection'), INJECTION_UNKNOWN)
    db10 = list(db10)
    header = SPECTRUM_HEADER.pack(KIND_SPECTRUM, VERSION, CHANNELS[channel], flags, row, len(db10), 0,
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
            value = fields.get(key)
            values.append(math.nan if value is None else float(value))
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
    """expect is the decoded SpectrumMsg (types.ts). t_us = round(t * 1e6), an integer.

    A present reference whose injection is neither 'low' nor 'high' travels as 255 and
    decodes to rf_reference null, because the TS Injection type has no unknown value.
    """
    channel, row, t, f0, bin_hz, low, high, db10, synthetic = args
    data = encode_spectrum(channel, row, t, f0, bin_hz, low, high, db10, synthetic, rf_reference)
    expect = dict(type='spectrum', channel=channel, row=row, t_us=int(round(t * 1e6)), f0_hz=f0,
                  bin_hz=_f32(bin_hz), bins=len(db10), db10=list(db10), low=_f32(low), high=_f32(high),
                  synthetic=synthetic, rf_reference=None)
    if rf_reference is not None and rf_reference.get('injection') in INJECTIONS:
        expect['rf_reference'] = dict(lo_hz=float(rf_reference['lo_hz']), injection=rf_reference['injection'],
                                      inferred=bool(rf_reference.get('inferred')))
    return dict(name=name, hex=data.hex(), expect=expect)


def _flight_vector(name, origin, rows):
    """rows: [(t, fields, synthetic, best_from)]. expect: {kind, origin, fieldCount, n, rows[{t, flags, values}]}."""
    encoded = [encode_flight_row(*r) for r in rows]
    data = pack_flight(origin, encoded)
    expect_rows = []
    for raw in encoded:
        t, flags, _reserved, *values = ROW.unpack(raw)
        expect_rows.append(dict(t=t, flags=flags, values=[_json_num(v) for v in values]))
    expect = dict(kind='flight', origin=origin, fieldCount=len(FIELD_KEYS), n=len(rows), rows=expect_rows)
    return dict(name=name, hex=data.hex(), expect=expect)


def _rom_frame0_fields():
    return apex.parse_frame(apex.with_crc(apex.read_rom_frames(_ROM)[0]))['fields']


def golden_vectors():
    f0 = _rom_frame0_fields()
    f1 = dict(f0, seq=f0['seq'] + 1, phase='BOOST', alt_agl_m=123.4, gps_fix=-1)
    f2 = dict(f0, phase='???', lat_deg=33.5)
    f3 = dict(f0, lat_deg=None, lon_deg=math.nan)
    del f3['tilt_deg']
    return [
        _spectrum_vector('spectrum_no_rf', ('B', 7, 1.5, 50000.0, 15625.0, -90.0, -10.0,
                                            [-900, -100, 0, 32767, -32768], True), None),
        _spectrum_vector('spectrum_rf_reference', ('A', 123456, 1760000000.25, -1e6, 1953.125, -95.5, -12.25,
                                                   [-950, -800, -125], False),
                         dict(lo_hz=441.38e6, injection='low', inferred=True)),
        _spectrum_vector('spectrum_rf_high', ('A', 1, 2.0, 0.0, 100.0, -80.0, -20.0, [-500], False),
                         dict(lo_hz=500e6, injection='high')),
        _spectrum_vector('spectrum_rf_injection_unknown', ('B', 2, 3.000001, 0.0, 100.0, -80.0, -20.0, [-1, 1], True),
                         dict(lo_hz=500e6, injection='unknown')),
        _flight_vector('flight_single_best', 'best', [(1760000000.5, f0, True, 0)]),
        _flight_vector('flight_batch_a', 'A', [(1760000001.0, f1, False, None), (1760000001.05, f2, True, None)]),
        _flight_vector('flight_origin_b_best_from_b', 'B', [(1760000002.0, f1, False, 1)]),
        _flight_vector('flight_best_from_combined', 'best', [(1760000003.0, f0, True, 2)]),
        _flight_vector('flight_missing_nan_fields', 'best', [(1760000004.0, f3, False, None)]),
    ]


def write_golden(path):
    Path(path).write_text(json.dumps(golden_vectors(), indent=2) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description='GUI wire format tools')
    parser.add_argument('--golden', metavar='PATH', required=True, help='write golden vectors JSON')
    write_golden(parser.parse_args(argv).golden)


if __name__ == '__main__':
    main()

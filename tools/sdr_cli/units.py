"""Units catalogue for the GUI (SI internally; display = si * factor + offset).

The JSON twin lives at tools/sdr_web/src/lib/units.catalogue.json and is generated with
`python -m sdr_cli.units --write PATH`; a test keeps the two identical.
"""
import json
import sys


def _u(uid, factor=1, offset=0, label=None):
    return dict(id=uid, label=label or uid, factor=factor, offset=offset)


def _q(si, *units):
    return dict(si=si, units=list(units))


CATALOGUE = dict(
    quantities=dict(
        length=_q('m', _u('m'), _u('km', 0.001), _u('ft', 3.280839895)),
        speed=_q('m/s', _u('m/s'), _u('km/h', 3.6), _u('mph', 2.2369362920544), _u('ft/s', 3.280839895)),
        acceleration=_q('m/s²', _u('m/s²'), _u('ft/s²', 3.280839895), _u('g', 1 / 9.80665)),
        pressure=_q('Pa', _u('Pa'), _u('hPa', 0.01), _u('inHg', 0.000295299830714)),
        temperature=_q('°C', _u('°C'), _u('°F', 1.8, 32)),
        angle=_q('deg', _u('deg')),
        angular_rate=_q('rad/s', _u('rad/s'), _u('deg/s', 57.29577951308232)),
        ratio=_q('1', _u('fraction'), _u('%', 100)),
        coordinate=_q('deg', _u('deg')),
        power_dbfs=_q('dBFS', _u('dBFS')),
        power_db=_q('dB', _u('dB')),
        frequency=_q('Hz', _u('Hz'), _u('kHz', 0.001), _u('MHz', 1e-6)),
        count=_q(None), enum=_q(None), enum_signed=_q(None), bits=_q(None),
    ),
    systems=dict(
        metric=dict(length='m', speed='m/s', acceleration='m/s²', pressure='hPa', temperature='°C',
                    angle='deg', angular_rate='deg/s', ratio='%', coordinate='deg',
                    power_dbfs='dBFS', power_db='dB', frequency='kHz'),
        imperial=dict(length='ft', speed='ft/s', acceleration='ft/s²', pressure='inHg', temperature='°F',
                      angle='deg', angular_rate='deg/s', ratio='%', coordinate='deg',
                      power_dbfs='dBFS', power_db='dB', frequency='kHz'),
    ),
)


def _unit(quantity, unit_id):
    for unit in CATALOGUE['quantities'][quantity]['units']:
        if unit['id'] == unit_id:
            return unit
    raise KeyError('unknown unit {!r} for {}'.format(unit_id, quantity))


def is_unit(quantity, unit_id):
    return quantity in CATALOGUE['quantities'] and any(
        u['id'] == unit_id for u in CATALOGUE['quantities'][quantity]['units'])


def convert(value, quantity, unit_id):
    """SI value to display units."""
    unit = _unit(quantity, unit_id)
    return value * unit['factor'] + unit['offset']


def catalogue_json():
    return json.dumps(CATALOGUE, indent=2, sort_keys=True) + '\n'


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == '--write':
        with open(argv[1], 'w', encoding='utf-8') as stream:
            stream.write(catalogue_json())
        return 0
    sys.stderr.write('usage: python -m sdr_cli.units --write PATH\n')
    return 2


if __name__ == '__main__':
    sys.exit(main())

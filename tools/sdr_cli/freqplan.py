"""Receiver frequency plan: synthesizer LO, mixer IF and image, NCO tuning word.

Shared by the GUI server and the host simulator; no UI imports. The synthesizer
part is not chosen yet, so this is a generic fractional-N model:
    LO = ref / R * (N + FRAC / MOD) / output divider
Defaults are placeholders (see docs/superpowers/specs/2026-09-29-gui-design.md).
"""
from dataclasses import asdict, dataclass, fields, replace
import json
import math
from pathlib import Path

OUT_DIVS = (1, 2, 4, 8, 16, 32, 64)
INJECTIONS = ('low', 'high')
_INTEGERS = ('r_div', 'n_int', 'frac', 'mod', 'out_div')


@dataclass(frozen=True)
class TuningState:
    carrier_hz: float = 441.48e6     # nominal TX carrier (user-reported)
    injection: str = 'low'           # 'low': IF = RF - LO; 'high': IF = LO - RF
    target_if_hz: float = 100e3
    window_hz: float = 35e3          # XADC IF window half-width
    ref_hz: float = 10e6
    r_div: int = 1
    n_int: int = 353
    frac: int = 1040
    mod: int = 10000
    out_div: int = 8
    vco_min_hz: float = 2.2e9        # placeholder VCO range
    vco_max_hz: float = 4.4e9
    nco_hz: float = 100e3
    fs_hz: float = 1e6               # placeholder XADC rate
    filter_hz: float = 35e3          # channel filter half-width


FIELDS = tuple(f.name for f in fields(TuningState))


def pfd_hz(s):
    return s.ref_hz / s.r_div


def vco_hz(s):
    return pfd_hz(s) * (s.n_int + s.frac / s.mod)


def lo_hz(s):
    return vco_hz(s) / s.out_div


def lo_step_hz(s):
    return pfd_hz(s) / s.mod / s.out_div


def if_hz(s, rf):
    """IF produced by an RF input for the current LO and injection side."""
    return rf - lo_hz(s) if s.injection == 'low' else lo_hz(s) - rf


def rf_hz(s, if_value):
    """RF frequency that lands on if_value."""
    return lo_hz(s) + if_value if s.injection == 'low' else lo_hz(s) - if_value


def image_hz(s):
    """The other RF frequency that also lands on the target IF."""
    return lo_hz(s) - s.target_if_hz if s.injection == 'low' else lo_hz(s) + s.target_if_hz


def nco_ftw(s):
    return int(round(s.nco_hz / s.fs_hz * 2 ** 32)) % 2 ** 32


def nco_resolution_hz(s):
    return s.fs_hz / 2 ** 32


def with_lo(s, target_lo_hz):
    """Nearest synthesizer setting to target_lo_hz; only N and FRAC change."""
    ratio = target_lo_hz * s.out_div / pfd_hz(s)
    n = int(math.floor(ratio))
    frac = int(round((ratio - n) * s.mod))
    if frac >= s.mod:
        n, frac = n + 1, frac - s.mod
    if n < 1:
        raise ValueError('LO {:.0f} Hz is below the synthesizer range'.format(target_lo_hz))
    return replace(s, n_int=n, frac=frac)


def validate(s):
    problems = []
    if s.injection not in INJECTIONS:
        problems.append('injection must be low or high')
    for name in ('carrier_hz', 'target_if_hz', 'window_hz', 'ref_hz', 'fs_hz', 'filter_hz', 'vco_min_hz'):
        if not getattr(s, name) > 0:
            problems.append('{} must be positive'.format(name))
    if s.r_div < 1 or s.n_int < 1:
        problems.append('R and N must be at least 1')
    if s.mod < 2 or not 0 <= s.frac < s.mod:
        problems.append('need MOD >= 2 and 0 <= FRAC < MOD')
    if s.out_div not in OUT_DIVS:
        problems.append('output divider must be one of {}'.format(', '.join(map(str, OUT_DIVS))))
    if not s.vco_min_hz < s.vco_max_hz:
        problems.append('VCO range must have min < max')
    if s.fs_hz > 0 and not 0 <= s.nco_hz < s.fs_hz / 2:
        problems.append('NCO must be between 0 and half the sample rate')
    if problems:
        raise ValueError('; '.join(problems))
    return s


def warnings(s):
    """Legal but probably wrong settings, for display."""
    out = []
    vco = vco_hz(s)
    if not s.vco_min_hz <= vco <= s.vco_max_hz:
        out.append('VCO {:.1f} MHz is outside {:.0f}–{:.0f} MHz'.format(
            vco / 1e6, s.vco_min_hz / 1e6, s.vco_max_hz / 1e6))
    expected = if_hz(s, s.carrier_hz)
    if abs(expected - s.target_if_hz) > s.window_hz:
        out.append('Carrier lands at {:.1f} kHz IF, outside the {:.0f} ± {:.0f} kHz window'.format(
            expected / 1e3, s.target_if_hz / 1e3, s.window_hz / 1e3))
    if abs(s.nco_hz - expected) > s.filter_hz:
        out.append('NCO is {:+.1f} kHz from the carrier IF, outside the ±{:.0f} kHz channel filter'.format(
            (s.nco_hz - expected) / 1e3, s.filter_hz / 1e3))
    return out


def derive(s):
    return dict(pfd_hz=pfd_hz(s), vco_hz=vco_hz(s), lo_hz=lo_hz(s), lo_step_hz=lo_step_hz(s),
                expected_if_hz=if_hz(s, s.carrier_hz), image_hz=image_hz(s), nco_ftw=nco_ftw(s),
                nco_resolution_hz=nco_resolution_hz(s), warnings=warnings(s))


def _number(key, value, integer):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('{} must be a number'.format(key))
    try:
        if not math.isfinite(value):
            raise ValueError('{} must be a number'.format(key))
    except OverflowError:
        raise ValueError('{} must be a number'.format(key))
    if integer:
        if value != int(value):
            raise ValueError('{} must be an integer'.format(key))
        return int(value)
    return float(value)


def update(s, changes):
    """Apply a partial change from a client. 'lo_hz' retunes N/FRAC after the other fields apply."""
    if not isinstance(changes, dict):
        raise ValueError('changes must be an object')
    unknown = set(changes) - set(FIELDS) - {'lo_hz'}
    if unknown:
        raise ValueError('unknown tuning field(s): ' + ', '.join(sorted(unknown)))
    values = {}
    for key, value in changes.items():
        if key == 'lo_hz':
            continue
        values[key] = str(value) if key == 'injection' else _number(key, value, key in _INTEGERS)
    new = validate(replace(s, **values))
    if 'lo_hz' in changes:
        new = validate(with_lo(new, _number('lo_hz', changes['lo_hz'], False)))
    return new


def to_dict(s):
    return asdict(s)


def load_state(path):
    """Saved state, or the defaults when the file is missing or unusable."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return TuningState()
    if not isinstance(data, dict):
        return TuningState()
    try:
        return update(TuningState(), {k: v for k, v in data.items() if k in FIELDS})
    except ValueError:
        return TuningState()


def save_state(path, s):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(to_dict(s), indent=2) + '\n')
    temporary.replace(path)

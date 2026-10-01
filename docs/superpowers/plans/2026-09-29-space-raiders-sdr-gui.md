# Space Raiders SDR web GUI — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `./sdr gui` serves a Space Raiders–branded web app (Tune and Telemetry
pages) from a Python server that decodes the FPGA link once and streams it to any
browser. Tuning state is shared, and a single password-protected Admin can change it.

**Architecture:** Toolkit-free Python modules (`freqplan`, `roles`, `sources`,
`hub`) hold all the logic and are unit-tested. A thin aiohttp layer
(`sdr_cli/web/server.py`) adds static files and one WebSocket per viewer. A
Svelte 5 + TypeScript app in `tools/sdr_web/` builds into
`tools/sdr_cli/web/static/`, renders with plain canvas, and sends only intent.
The server validates every change and broadcasts the result.

**Tech stack:** Python 3.9+ (stdlib + pyserial; aiohttp only in the `gui` extra),
Svelte 5.57, Vite 8.3, TypeScript 5.9, Vitest 5, svelte-check 4.7, and
@fontsource Jost / JetBrains Mono 5.3.

**Spec:** `docs/superpowers/specs/2026-09-29-gui-design.md`. Read it first. The
approved visual reference is the mockup
(https://claude.ai/artifact/Lu4E31moDobhsgF157Ujxy); its layout, colors, and
interactions are ported below.

**Dry run (2026-09-29, before execution).** Every code block here was extracted
into a scratch copy of the repo and run:

- 81 Python tests pass (Python 3.9.6, aiohttp 3.13.5), including the GUI server tests.
- 14 Vitest tests pass.
- svelte-check reports 0 errors and 0 warnings, and the build succeeds.
- The Tune and Telemetry pages render live against `--source sim` in headless Chrome.

Not run in the dry run: the manual, LAN, and hardware checks in Task 15. An
executor must still run every step; the dry run only means the code is known to
work as written.

## Global constraints

- **Python:** must run on Python 3.9 (the repo `.venv` is 3.9.6). No `match`,
  no `X | Y` type unions, no `list[int]` annotations at runtime, and no
  dataclass `slots=`/`kw_only=`.
- **Dependencies:** the base install stays `pyserial` only. `aiohttp>=3.9,<4` goes
  in the `gui` extra. The frontend has no runtime CDN, so everything is bundled
  (it must work on a LAN with no internet).
- **One decoder, one scale, one frequency model.** Reuse
  `protocol.StreamDecoder`/`LinkState`, `display.WaterfallScale`, and the new
  `freqplan`. TypeScript does not re-implement tuning math. Its one exception is
  the display mapping `rf = lo ± if` in `lib/axis.ts`.
- **Honesty rules (AGENTS.md):**
  - Anything flagged `SYNTHETIC` shows **SIMULATED**.
  - "Send to FPGA" stays disabled with the reason. Nothing claims a setting
    reached the FPGA.
  - With the serial or replay source, the UI states that the FPGA ignores tuning.
- **Security:** never print, log, or commit the Admin password or its hash
  (`./sdr config` masks it). Local state lives in ignored `.sdr/`
  (`config.json`, `gui_state.json`).
- **Git:**
  - The branch `gui-prep` already holds uncommitted work from the previous
    session (link layer v2 RTL/tests/docs, the untracked
    `tools/sdr_cli/display.py` and `tools/tests/test_display.py`). This plan
    builds on it: `hub.py` imports `display.WaterfallScale`, and Task 3 edits
    `link_samples.py`.
  - **Before Task 1, ask the user to commit that existing work** (or to confirm
    how to handle it), so each GUI commit contains only GUI changes.
  - **Never `git add -A`/`git add .`.** Stage only the files the task lists.
  - Never stage `key.txt` or `command.txt`.
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Branding:** Space Raiders only. Brand red `#FB0000` (light theme `#D10000`)
  is used for chrome, never for data or status. "Bad" status is coral
  `#FF7A6B` / `#C23A2B` and always carries a text label.
- **Commands:**
  - Python tests: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v`
  - Frontend: `cd tools/sdr_web && npm test && npm run check && npm run build`

## File map

```text
pyproject.toml                         gui extra, package data
.gitignore                             node_modules, built static
tools/sdr_cli/
  freqplan.py        NEW  TuningState, synthesizer/IF/image/NCO math, update+validate, persistence
  roles.py           NEW  password hashing, RoleManager (Viewer/Admin, takeover, grace, resume)
  sources.py         NEW  SerialSource, ReplaySource, SimSource, from_args factory
  hub.py             NEW  decode once → client messages, per-channel WaterfallScale, stats, run(source)
  apex.py            MOD  build_test_frame() shared by the simulator and tests
  core.py            MOD  DEFAULTS gains gui_admin_hash
  cli.py             MOD  `gui` subcommand, `setup --gui-password`, masked `config`
  web/__init__.py    NEW
  web/server.py      NEW  GuiServer (aiohttp), run_gui, lan_addresses
  web/static/        GENERATED by `npm run build` (ignored)
tools/tests/
  link_samples.py    MOD  import apex.build_test_frame
  test_freqplan.py, test_roles.py, test_sources.py, test_hub.py, test_gui_server.py, test_gui_cli.py   NEW
tools/sdr_web/                          NEW frontend
  package.json, vite.config.ts, svelte.config.js, tsconfig.json, index.html
  src/main.ts, src/app.css, src/App.svelte
  src/assets/space-raiders-logo.png, space-raiders-logo-on-dark.png   (already in the repo, untracked)
  src/lib/  types.ts format.ts ring.ts axis.ts colormap.ts waterfall.ts layout.ts throttle.ts
            theme.ts view.ts link.ts draw.ts cards.ts (+ *.test.ts)
  src/components/  Panel NumberField SelectField Segmented StatusBar RoleMenu Notices
                   Waterfall FreqPlan TuningDigits ReceiverPanel SynthPanel NcoPanel
                   ScalePanel SendPanel ChannelQuality LinkStatsBar CardGrid (.svelte)
  src/pages/Tune.svelte, src/pages/Telemetry.svelte
  src/pages/telemetry/  LatestFrameCard DeviceCard LinkCard ChannelsCard FlightCard FrameLogCard (.svelte)
docs: tools/README.md, README.md, docs/HANDOFF.md, AGENTS.md (Task 15)
```

## Phases

| Phase | Tasks | Deliverable you can check |
| --- | --- | --- |
| 1. Python core | 1–4 | frequency plan, roles, sources, and hub, all unit-tested with no web dependency |
| 2. Server + CLI | 5–6 | `./sdr gui --source sim` serves a placeholder page and live WebSocket JSON |
| 3. Frontend foundation | 7–10 | branded shell with tabs, status bar, role menu, and theme toggle, fed by the server |
| 4. Tune page | 11–13 | frequency plan, IF waterfall, controls, and channel quality working against the simulator |
| 5. Telemetry page | 14 | draggable/resizable cards with the dashboard's content |
| 6. Verification + docs | 15 | end-to-end checks and updated README/HANDOFF |

---

# Phase 1 — Python core

### Task 1: Frequency plan (`freqplan.py`)

**Files:**
- Create: `tools/sdr_cli/freqplan.py`
- Test: `tools/tests/test_freqplan.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Constant `OUT_DIVS`.
  - `TuningState`, a frozen dataclass whose fields are listed in Step 3.
  - Math functions:
    - `pfd_hz(s)`, `vco_hz(s)`, `lo_hz(s)`, `lo_step_hz(s)`
    - `if_hz(s, rf_hz)`, `rf_hz(s, if_value_hz)`, `image_hz(s)`
    - `nco_ftw(s) -> int`, `nco_resolution_hz(s)`
    - `with_lo(s, lo_hz) -> TuningState`
  - Checks and derived values:
    - `validate(s)` returns `s` or raises `ValueError`.
    - `warnings(s) -> list of str`.
    - `derive(s) -> dict`, with keys `pfd_hz vco_hz lo_hz lo_step_hz expected_if_hz image_hz nco_ftw nco_resolution_hz warnings`.
  - `update(s, changes: dict) -> TuningState`. It accepts any field plus `lo_hz`
    and raises `ValueError`.
  - Persistence: `to_dict(s)`, `load_state(path) -> TuningState`, `save_state(path, s)`.

- [ ] **Step 1: Write the failing tests**

```python
# tools/tests/test_freqplan.py
import json
from pathlib import Path
import tempfile
import unittest

from sdr_cli import freqplan as fp


class SynthesizerTest(unittest.TestCase):
    def test_default_plan_matches_mockup(self):
        s = fp.TuningState()
        self.assertAlmostEqual(fp.pfd_hz(s), 10e6)
        self.assertAlmostEqual(fp.vco_hz(s), 3531.04e6, places=1)
        self.assertAlmostEqual(fp.lo_hz(s), 441.38e6, places=1)
        self.assertAlmostEqual(fp.lo_step_hz(s), 125.0)
        self.assertAlmostEqual(fp.if_hz(s, s.carrier_hz), 100e3, places=1)
        self.assertAlmostEqual(fp.image_hz(s), 441.28e6, places=1)

    def test_with_lo_round_trips_and_quantizes_to_step(self):
        s = fp.TuningState()
        up = fp.with_lo(s, 441.381e6)
        self.assertEqual((up.n_int, up.frac), (353, 1048))
        self.assertAlmostEqual(fp.lo_hz(up), 441.381e6, places=1)
        self.assertEqual(fp.with_lo(s, 441380060).frac, 1040)   # +60 Hz rounds down (step 125 Hz)
        self.assertEqual(fp.with_lo(s, 441380070).frac, 1041)   # +70 Hz rounds up

    def test_with_lo_carries_into_n(self):
        edge = fp.with_lo(fp.TuningState(), 10e6 * 354 / 8 - 10)   # 10 Hz below an integer-N boundary
        self.assertEqual((edge.n_int, edge.frac), (354, 0))

    def test_with_lo_rejects_below_range(self):
        with self.assertRaises(ValueError):
            fp.with_lo(fp.TuningState(), 1e6)

    def test_high_side_injection(self):
        s = fp.with_lo(fp.update(fp.TuningState(), {'injection': 'high'}), 441.58e6)
        self.assertAlmostEqual(fp.if_hz(s, s.carrier_hz), 100e3, places=1)
        self.assertAlmostEqual(fp.image_hz(s), 441.68e6, places=1)
        self.assertAlmostEqual(fp.rf_hz(s, 100e3), 441.48e6, places=1)

    def test_nco_tuning_word(self):
        s = fp.TuningState()
        self.assertEqual(fp.nco_ftw(s), 0x1999999A)
        self.assertAlmostEqual(fp.nco_resolution_hz(s), 1e6 / 2 ** 32)


class UpdateTest(unittest.TestCase):
    def test_partial_update_applies_lo_last(self):
        s = fp.update(fp.TuningState(), {'out_div': 4, 'lo_hz': 441.38e6})
        self.assertEqual(s.out_div, 4)
        self.assertAlmostEqual(fp.lo_hz(s), 441.38e6, places=0)

    def test_rejects_bad_values(self):
        bad = [{'frac': 10000}, {'mod': 1}, {'out_div': 3}, {'injection': 'side'}, {'r_div': 0},
               {'n_int': 2.5}, {'nco_hz': 600e3}, {'fs_hz': 0}, {'ref_hz': float('nan')},
               {'bogus': 1}, {'n_int': True}, {'lo_hz': 'x'}, {'window_hz': -1}]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                fp.update(fp.TuningState(), change)

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            fp.update(fp.TuningState(), [1])

    def test_warnings(self):
        self.assertEqual(fp.warnings(fp.TuningState()), [])
        off = fp.with_lo(fp.TuningState(), 441.2e6)
        self.assertIn('outside the 100 ± 35 kHz window', ' '.join(fp.warnings(off)))
        vco = fp.update(fp.TuningState(), {'out_div': 16, 'lo_hz': 441.38e6})
        self.assertIn('VCO', ' '.join(fp.warnings(vco)))

    def test_derive_is_json_ready(self):
        d = fp.derive(fp.TuningState())
        json.dumps(d)
        self.assertEqual(d['nco_ftw'], 0x1999999A)
        self.assertEqual(d['warnings'], [])
        self.assertAlmostEqual(d['lo_hz'], 441.38e6, places=1)


class PersistenceTest(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'gui_state.json'
            self.assertEqual(fp.load_state(path), fp.TuningState())
            s = fp.with_lo(fp.TuningState(), 441.39e6)
            fp.save_state(path, s)
            self.assertEqual(fp.load_state(path), s)
            path.write_text('{"frac": 99999}')
            self.assertEqual(fp.load_state(path), fp.TuningState())
            path.write_text('not json')
            self.assertEqual(fp.load_state(path), fp.TuningState())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_freqplan.py' -v`
Expected: ERROR `ModuleNotFoundError: No module named 'sdr_cli.freqplan'`.

- [ ] **Step 3: Implement**

```python
# tools/sdr_cli/freqplan.py
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
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_freqplan.py' -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/sdr_cli/freqplan.py tools/tests/test_freqplan.py
git commit -m "Add frequency plan model for GUI tuning" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Roles (`roles.py`)

**Files:**
- Create: `tools/sdr_cli/roles.py`
- Test: `tools/tests/test_roles.py`

**Interfaces:**
- Produces:
  - Constants `VIEWER = 'viewer'`, `ADMIN = 'admin'`.
  - Password helpers: `hash_password(password, salt=None, iterations=200000) -> str`,
    `verify_password(password, stored) -> bool`, `clean_label(label) -> str`.
  - `RoleManager(password_hash='', clock=time.monotonic, wall=time.time)`, with
    attributes `password_hash` and `GRACE_S = 15.0`. Its methods:
    - Connections: `connect(client, local)`, `disconnect(client)`.
    - Queries: `role(client)`, `admin_info() -> {'label', 'since'} or None`,
      `can_login(client) -> bool`.
    - `login(client, password, label, takeover=False) -> dict`. It returns one of:
      - `{'ok': True, 'token', 'demoted'}`
      - `{'ok': False, 'code': 'bad_password'|'no_password'}`
      - `{'ok': False, 'code': 'needs_takeover', 'held_by', 'since'}`
    - `resume(client, token) -> bool`, `logout(client) -> bool`, `expire() -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tools/tests/test_roles.py
import unittest

from sdr_cli import roles as r


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class PasswordTest(unittest.TestCase):
    def test_hash_and_verify(self):
        stored = r.hash_password('rocket', iterations=1000)
        self.assertTrue(stored.startswith('pbkdf2_sha256$1000$'))
        self.assertTrue(r.verify_password('rocket', stored))
        self.assertFalse(r.verify_password('Rocket', stored))
        self.assertNotEqual(stored, r.hash_password('rocket', iterations=1000))   # salted
        for junk in ('', 'x$y', 'md5$1$00$00', None, 'pbkdf2_sha256$1$zz$00'):
            self.assertFalse(r.verify_password('rocket', junk))

    def test_label_is_cleaned(self):
        self.assertEqual(r.clean_label('  \x07gs\n '), 'gs')
        self.assertEqual(r.clean_label(''), 'admin')
        self.assertEqual(len(r.clean_label('x' * 50)), 32)


class RoleTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.roles = r.RoleManager(r.hash_password('pw', iterations=1000), clock=self.clock,
                                   wall=lambda: 1700000000.0)
        for client in ('a', 'b'):
            self.roles.connect(client, local=False)

    def test_everyone_starts_as_viewer(self):
        self.assertEqual((self.roles.role('a'), self.roles.role('b')), (r.VIEWER, r.VIEWER))
        self.assertIsNone(self.roles.admin_info())
        self.assertTrue(self.roles.can_login('a'))

    def test_bad_password(self):
        self.assertEqual(self.roles.login('a', 'nope', 'gs'), dict(ok=False, code='bad_password'))
        self.assertEqual(self.roles.role('a'), r.VIEWER)

    def test_single_admin_needs_confirmed_takeover(self):
        first = self.roles.login('a', 'pw', 'groundstation')
        self.assertTrue(first['ok'])
        self.assertIsNone(first['demoted'])
        held = self.roles.login('b', 'pw', 'phone')
        self.assertEqual(held, dict(ok=False, code='needs_takeover', held_by='groundstation', since=1700000000.0))
        self.assertEqual(self.roles.role('a'), r.ADMIN)
        taken = self.roles.login('b', 'pw', 'phone', takeover=True)
        self.assertTrue(taken['ok'])
        self.assertEqual(taken['demoted'], 'a')
        self.assertEqual((self.roles.role('a'), self.roles.role('b')), (r.VIEWER, r.ADMIN))
        self.assertEqual(self.roles.admin_info(), dict(label='phone', since=1700000000.0))

    def test_drop_keeps_admin_through_grace_and_resume(self):
        token = self.roles.login('a', 'pw', 'gs')['token']
        self.roles.disconnect('a')
        self.clock.t += 10
        self.assertFalse(self.roles.expire())
        self.roles.connect('a2', local=False)
        self.assertFalse(self.roles.resume('a2', 'wrong'))
        self.assertTrue(self.roles.resume('a2', token))
        self.assertEqual(self.roles.role('a2'), r.ADMIN)

    def test_drop_releases_after_grace(self):
        self.roles.login('a', 'pw', 'gs')
        self.roles.disconnect('a')
        self.clock.t += 16
        self.assertTrue(self.roles.expire())
        self.assertIsNone(self.roles.admin_info())
        self.assertTrue(self.roles.login('b', 'pw', 'x')['ok'])

    def test_logout(self):
        self.roles.login('a', 'pw', 'gs')
        self.assertFalse(self.roles.logout('b'))
        self.assertTrue(self.roles.logout('a'))
        self.assertEqual(self.roles.role('a'), r.VIEWER)

    def test_no_password_allows_only_localhost(self):
        roles = r.RoleManager('', clock=self.clock)
        roles.connect('lan', local=False)
        roles.connect('here', local=True)
        self.assertFalse(roles.can_login('lan'))
        self.assertTrue(roles.can_login('here'))
        self.assertEqual(roles.login('lan', '', 'x')['code'], 'no_password')
        self.assertTrue(roles.login('here', '', 'x')['ok'])
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_roles.py' -v`
Expected: ERROR `No module named 'sdr_cli.roles'`.

- [ ] **Step 3: Implement**

```python
# tools/sdr_cli/roles.py
"""GUI roles: every connection is a Viewer; one Admin at a time, unlocked by password.

Over plain HTTP on a LAN this prevents casual or accidental changes; it does not
resist someone sniffing the network. No web framework imports.
"""
import hashlib
import hmac
import os
import secrets
import time

VIEWER, ADMIN = 'viewer', 'admin'
ITERATIONS = 200000


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return 'pbkdf2_sha256${}${}${}'.format(iterations, salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        scheme, iterations, salt, digest = stored.split('$')
        if scheme != 'pbkdf2_sha256':
            return False
        candidate = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(iterations))
    except (AttributeError, ValueError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def clean_label(label):
    text = ''.join(c for c in str(label or '') if c.isprintable()).strip()[:32]
    return text or 'admin'


class RoleManager:
    GRACE_S = 15.0   # a dropped Admin keeps the role this long, so a page reload can resume it

    def __init__(self, password_hash='', clock=time.monotonic, wall=time.time):
        self.password_hash = password_hash
        self.clock = clock
        self.wall = wall
        self.local = {}
        self.admin = None   # dict(client, label, since, token, dropped_at)

    def connect(self, client, local):
        self.local[client] = bool(local)

    def disconnect(self, client):
        self.local.pop(client, None)
        if self.admin and self.admin['client'] == client:
            self.admin['client'] = None
            self.admin['dropped_at'] = self.clock()

    def role(self, client):
        return ADMIN if self.admin and self.admin['client'] == client else VIEWER

    def admin_info(self):
        return None if not self.admin else dict(label=self.admin['label'], since=self.admin['since'])

    def can_login(self, client):
        return bool(self.password_hash) or self.local.get(client, False)

    def login(self, client, password, label, takeover=False):
        if not self.can_login(client):
            return dict(ok=False, code='no_password')
        if self.password_hash and not verify_password(password or '', self.password_hash):
            return dict(ok=False, code='bad_password')
        self.expire()
        if self.admin and self.admin['client'] == client:
            self.admin['label'] = clean_label(label)
            return dict(ok=True, token=self.admin['token'], demoted=None)
        demoted = None
        if self.admin:
            if not takeover:
                return dict(ok=False, code='needs_takeover', held_by=self.admin['label'], since=self.admin['since'])
            demoted = self.admin['client']
        self.admin = dict(client=client, label=clean_label(label), since=self.wall(),
                          token=secrets.token_hex(16), dropped_at=None)
        return dict(ok=True, token=self.admin['token'], demoted=demoted)

    def resume(self, client, token):
        """Rebind a dropped Admin to a new connection that presents its token."""
        self.expire()
        if (self.admin and self.admin['client'] is None and token
                and hmac.compare_digest(self.admin['token'], str(token))):
            self.admin['client'] = client
            self.admin['dropped_at'] = None
            return True
        return False

    def logout(self, client):
        if self.admin and self.admin['client'] == client:
            self.admin = None
            return True
        return False

    def expire(self):
        """Release an Admin whose connection dropped more than GRACE_S ago."""
        if (self.admin and self.admin['client'] is None
                and self.clock() - self.admin['dropped_at'] > self.GRACE_S):
            self.admin = None
            return True
        return False
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_roles.py' -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/sdr_cli/roles.py tools/tests/test_roles.py
git commit -m "Add GUI Viewer/Admin role manager" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Byte sources (`sources.py`) and a shared APEX test-frame builder

**Files:**
- Modify: `tools/sdr_cli/apex.py` (append `build_test_frame`)
- Modify: `tools/tests/link_samples.py:5-8` (use the shared builder)
- Create: `tools/sdr_cli/sources.py`
- Test: `tools/tests/test_sources.py`

**Interfaces:**
- Consumes: `freqplan.TuningState`, `freqplan.if_hz`, `freqplan.with_lo`,
  `freqplan.lo_hz` (Task 1), and `protocol.encode_message`/`build_payload`.
- Produces:
  - `apex.build_test_frame(seq, good=True) -> bytes`.
  - Every source has attributes `kind`, `responds_to_tuning`, and `detail`, plus
    `async chunks()`, an async generator of `bytes`:
    - `SerialSource(config, session_factory=None)`
    - `ReplaySource(path, speed=1.0, loop=False, chunk=512)`
    - `SimSource(get_tuning, seed=None)`, which also has `step() -> bytes` (one 50 ms tick).
  - `from_args(config, kind, file=None, speed=1.0, loop=False)` returns a
    factory `(get_tuning) -> source`. It raises `ToolError`.

- [ ] **Step 1: Write the failing tests**

```python
# tools/tests/test_sources.py
from pathlib import Path
import tempfile
import unittest

from link_samples import sample_stream
from sdr_cli import apex, freqplan, protocol as p, sources
from sdr_cli.core import ToolError


def decode(data):
    decoder = p.StreamDecoder()
    return decoder, decoder.feed(data)


class ApexFrameTest(unittest.TestCase):
    def test_build_test_frame(self):
        self.assertTrue(apex.parse_frame(apex.build_test_frame(5))['crc_ok'])
        self.assertFalse(apex.parse_frame(apex.build_test_frame(5, good=False))['crc_ok'])
        self.assertEqual(apex.parse_frame(apex.build_test_frame(5))['fields']['text'], 'APEX RADIO TEST')


class SimSourceTest(unittest.TestCase):
    def setUp(self):
        self.state = freqplan.TuningState()
        self.sim = sources.SimSource(lambda: self.state, seed=1)

    def run_ticks(self, n):
        return b''.join(self.sim.step() for _ in range(n))

    def peak_hz(self, records, channel='A'):
        row = [r for r in records if r.type == p.SPECTRUM and r.fields['channel'] == channel][-1].fields
        k = max(range(row['bins']), key=row['power'].__getitem__)
        return p.bin_frequency(row, k)

    def test_all_types_decode_cleanly_and_are_synthetic(self):
        decoder, records = decode(self.run_ticks(40))
        s = decoder.stats
        self.assertEqual((s['crc_errors'], s['cobs_errors'], s['length_errors'], s['seq_gaps']), (0, 0, 0, 0))
        self.assertEqual({r.name for r in records}, set(p.TYPE_NAMES.values()))
        self.assertTrue(all(r.synthetic for r in records))
        frames = [r for r in records if r.type == p.CHAN_FRAME]
        self.assertTrue(frames and all(r.fields['apex']['kind'] == 'TEST' for r in frames))

    def test_spectrum_follows_the_lo(self):
        _, records = decode(self.run_ticks(2))   # carrier + 10.4 kHz bench offset → IF 110.4 kHz, lobes ±25 kHz
        self.assertLess(min(abs(self.peak_hz(records) - f) for f in (85.4e3, 135.4e3)), 1.5e3)
        self.state = freqplan.with_lo(self.state, freqplan.lo_hz(self.state) + 10e3)
        _, records = decode(self.run_ticks(2))
        self.assertLess(min(abs(self.peak_hz(records) - f) for f in (75.4e3, 125.4e3)), 1.5e3)

    def test_losing_the_signal_stops_frames(self):
        self.state = freqplan.with_lo(self.state, freqplan.lo_hz(self.state) - 100e3)   # IF 210 kHz
        _, records = decode(self.run_ticks(4))
        self.assertFalse([r for r in records if r.type in (p.CHAN_FRAME, p.BEST_TELEM)])
        metrics = [r for r in records if r.type == p.CHAN_METRICS][-1].fields
        self.assertLess(metrics['rssi_dbm'], -105)


class ReplaySourceTest(unittest.IsolatedAsyncioTestCase):
    async def collect(self, source, limit=10 ** 6):
        out = b''
        async for chunk in source.chunks():
            out += chunk
            if len(out) >= limit:
                break
        return out

    async def test_replays_exact_bytes_and_loops(self):
        data = sample_stream()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'capture.bin'
            path.write_bytes(data)
            self.assertEqual(await self.collect(sources.ReplaySource(path, speed=0)), data)
            looped = await self.collect(sources.ReplaySource(path, speed=0, loop=True), limit=2 * len(data))
            self.assertEqual(looped[:2 * len(data)], data * 2)

    def test_rejects_missing_file_and_negative_speed(self):
        with self.assertRaises(ToolError):
            sources.ReplaySource('/nonexistent/capture.bin')
        with tempfile.NamedTemporaryFile() as f, self.assertRaises(ToolError):
            sources.ReplaySource(f.name, speed=-1)


class FakeSession:
    def __init__(self, config):
        self.config = config
        self.port = 'fake0'
        self.pending = [b'ab', b'', b'cd']
        self.closed = False

    def connect(self):
        pass

    def read(self):
        if not self.pending:
            raise ToolError('UART disconnected: unplugged')
        return self.pending.pop(0)

    def close(self):
        self.closed = True


class SerialSourceTest(unittest.IsolatedAsyncioTestCase):
    async def test_yields_reads_until_error_and_closes(self):
        source = sources.SerialSource(dict(port='auto', baud=1000000), session_factory=FakeSession)
        out = b''
        with self.assertRaises(ToolError):
            async for chunk in source.chunks():
                out += chunk
        self.assertEqual(out, b'abcd')
        self.assertTrue(source.session.closed)
        self.assertEqual(source.detail, 'fake0 @ 1000000 baud')


class FactoryTest(unittest.TestCase):
    def test_from_args(self):
        config = dict(port='auto', baud=1000000)
        self.assertIsInstance(sources.from_args(config, 'sim')(freqplan.TuningState), sources.SimSource)
        self.assertIsInstance(sources.from_args(config, 'serial')(None), sources.SerialSource)
        with self.assertRaises(ToolError):
            sources.from_args(config, 'replay')
        with self.assertRaises(ToolError):
            sources.from_args(config, 'radio')
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_sources.py' -v`
Expected: ERROR, because `sdr_cli.sources` does not exist and `apex.build_test_frame` is missing.

- [ ] **Step 3: Add the APEX builder and reuse it in the test samples**

Append to `tools/sdr_cli/apex.py`:

```python


def build_test_frame(seq, good=True):
    """APEX TEST frame as the FPGA stand-in sends it; good=False flips the CRC's last bit."""
    data = bytes([TEST, seq & 0xFF]) + b'APEX RADIO TEST'
    crc = crc16_ccitt(data) ^ (0 if good else 1)
    return data + bytes([crc >> 8, crc & 0xFF])
```

In `tools/tests/link_samples.py`, replace the local `apex_test_frame`
definition (lines 5–8) with the shared builder:

```python
"""A small synthetic link stream containing every message type (mirrors rtl/link_test_sources.sv)."""
from sdr_cli import protocol as p
from sdr_cli.apex import build_test_frame as apex_test_frame
```

(Remove the old `def apex_test_frame` block. Its callers are unchanged.)

- [ ] **Step 4: Implement `sources.py`**

```python
# tools/sdr_cli/sources.py
"""Byte sources for the GUI hub: live UART, a recorded capture, or a host-side simulator.

Every source yields raw link bytes, so all of them go through the one StreamDecoder
in hub.py. Only SimSource reacts to tuning; the FPGA has no command receiver yet.
"""
import asyncio
import math
from pathlib import Path
import random

from . import apex, freqplan, protocol as p
from .core import ToolError

LINK_BYTES_PER_S = 100000   # 1 Mbaud, 8N1


class SerialSource:
    kind = 'serial'
    responds_to_tuning = False

    def __init__(self, config, session_factory=None):
        if session_factory is None:
            from .serial_io import Session as session_factory
        self.session = session_factory(config)

    @property
    def detail(self):
        return '{} @ {} baud'.format(self.session.port or self.session.config['port'], self.session.config['baud'])

    async def chunks(self):
        self.session.connect()
        try:
            while True:
                data = self.session.read()   # non-blocking: the port opens with timeout=0
                if data:
                    yield data
                else:
                    await asyncio.sleep(0.01)
        finally:
            self.session.close()


class ReplaySource:
    kind = 'replay'
    responds_to_tuning = False

    def __init__(self, path, speed=1.0, loop=False, chunk=512):
        self.path = Path(path).expanduser()
        if not self.path.is_file():
            raise ToolError('Replay file not found: {}'.format(path))
        if speed < 0:
            raise ToolError('Replay speed must be 0 (as fast as possible) or positive.')
        self.speed, self.loop, self.chunk = speed, loop, chunk
        self.detail = self.path.name + (' (looping)' if loop else '')

    async def chunks(self):
        data = self.path.read_bytes()
        while True:
            for offset in range(0, len(data), self.chunk):
                part = data[offset:offset + self.chunk]
                yield part
                await asyncio.sleep(len(part) / (LINK_BYTES_PER_S * self.speed) if self.speed else 0)
            if not self.loop:
                return


BENCH_OFFSET_HZ = 10.4e3          # TX crystal offset seen on the bench (module map)
TICK_S = 0.05
SPEC_BINS, SPEC_BIN_HZ = 256, 390.625
DB_REF, DB_STEP = -120.0, 0.5
FSK_DEVIATION_HZ = 25e3
CHANNEL_MODEL = {
    0: dict(peak_db=-50.0, noise_db=-105.0, rssi_offset=0.0, fail_every=11, radius=26000),
    1: dict(peak_db=-56.0, noise_db=-104.0, rssi_offset=-6.0, fail_every=7, radius=13000),
}


def _i16(v):
    return max(-32767, min(32767, int(round(v))))


class SimSource:
    """Host-side stand-in producer whose spectrum and metrics follow the tuning state.

    A toy model for developing the Tune page without hardware: 2-GFSK lobes at
    ±25 kHz around the carrier IF; "lock" needs the signal inside the XADC window
    and the lobes mostly inside the channel filter. Rates match rtl/link_test_sources.sv.
    Everything is flagged SYNTHETIC.
    """
    kind = 'sim'
    responds_to_tuning = True
    detail = 'host simulator'

    def __init__(self, get_tuning, seed=None):
        self.get_tuning = get_tuning
        self.rng = random.Random(seed)
        self.tick = 0
        self.seq = 0
        self.apex_seq = 0
        self.frames = {0: 0, 1: 0}
        self.good = {0: 0, 1: 0}
        self.bad = {0: 0, 1: 0}
        self.rows = {0: 0, 1: 0}
        self.link = dict(from_a=0, from_b=0, both_ok=0, neither_ok=0, best_sent=0)

    def _msg(self, mtype, fields):
        data = p.encode_message(mtype, p.build_payload(mtype, fields), seq=self.seq)
        self.seq = (self.seq + 1) & 0xFF
        return data

    def channel(self):
        """(state, signal IF, offset from NCO, locked) for the current tuning."""
        s = self.get_tuning()
        sig = freqplan.if_hz(s, s.carrier_hz + BENCH_OFFSET_HZ)
        df = sig - s.nco_hz
        locked = abs(sig - s.target_if_hz) <= s.window_hz and abs(df) <= max(0.0, s.filter_hz - 17e3)
        return s, sig, df, locked

    def step(self):
        """Bytes for one 50 ms tick."""
        t_us = int(round(self.tick * TICK_S * 1e6)) & 0xFFFFFFFF
        s, sig, df, locked = self.channel()
        out, ok = [], {0: False, 1: False}
        self.apex_seq = (self.apex_seq + 1) & 0xFF
        if locked:
            for ch in (0, 1):
                model = CHANNEL_MODEL[ch]
                self.frames[ch] += 1
                ok[ch] = self.frames[ch] % model['fail_every'] != 0
                if ok[ch]:
                    self.good[ch] += 1
                else:
                    self.bad[ch] += 1
                rssi = -78.0 + model['rssi_offset'] + self.rng.gauss(0, 0.8)
                out.append(self._msg(p.CHAN_FRAME, dict(
                    channel=ch, crc_ok=int(ok[ch]), t_us=t_us, rssi_dbm_x10=int(round(rssi * 10)),
                    quality=200 if ok[ch] else 90, freq_offset_hz=int(round(df)),
                    raw=apex.build_test_frame(self.apex_seq, ok[ch]))))
        if ok[0] or ok[1]:
            out.append(self._msg(p.BEST_TELEM, dict(t_us=t_us, source=0 if ok[0] else 1,
                                                    raw=apex.build_test_frame(self.apex_seq))))
            self.link['best_sent'] += 1
        if ok[0]:
            self.link['from_a'] += 1
        elif ok[1]:
            self.link['from_b'] += 1
        else:
            self.link['neither_ok'] += 1
        if ok[0] and ok[1]:
            self.link['both_ok'] += 1
        if self.tick % 2 == 0:
            for ch in (0, 1):
                out.append(self._metrics(ch, df, locked))
                out.append(self._spectrum(ch, t_us, s, sig))
        if self.tick % 4 == 0:
            for ch in (0, 1):
                out.append(self._iq(ch, t_us, locked))
        if self.tick % 20 == 0:
            out.append(self._msg(p.STATUS, dict(version=p.PROTOCOL_VERSION, channels=3,
                                                uptime_ms=int(self.tick * TICK_S * 1000), build_id=0, dropped=0)))
            out.append(self._msg(p.LINK_STATS, dict(self.link)))
        self.tick += 1
        return b''.join(out)

    def _metrics(self, ch, df, locked):
        model = CHANNEL_MODEL[ch]
        noise = -112.0 + self.rng.gauss(0, 0.4)
        rssi = (-78.0 + model['rssi_offset'] if locked else -112.0) + self.rng.gauss(0, 0.6)
        return self._msg(p.CHAN_METRICS, dict(
            channel=ch, rssi_dbm_x10=int(round(rssi * 10)), noise_dbm_x10=int(round(noise * 10)),
            snr_db_x10=int(round((rssi - noise) * 10)), freq_offset_hz=int(round(df)),
            sync_hits=self.frames[ch], crc_good=self.good[ch], crc_bad=self.bad[ch]))

    def _spectrum(self, ch, t_us, s, sig):
        model = CHANNEL_MODEL[ch]
        center = int(round(s.target_if_hz))
        peak = 10 ** (model['peak_db'] / 10)
        power = []
        for k in range(SPEC_BINS):
            f = center + (k - SPEC_BINS // 2) * SPEC_BIN_HZ
            linear = 10 ** ((model['noise_db'] + self.rng.gauss(0, 2.2)) / 10)
            for deviation in (-FSK_DEVIATION_HZ, FSK_DEVIATION_HZ):
                linear += peak * math.exp(-0.5 * ((f - sig - deviation) / 1.6e3) ** 2)
            db = 10 * math.log10(linear)
            power.append(max(0, min(255, int(round((db - DB_REF) / DB_STEP)))))
        row = self.rows[ch]
        self.rows[ch] = (row + 1) & 0xFFFF
        return self._msg(p.SPECTRUM, dict(
            channel=ch, averages=1, row=row, t_us=t_us, center_hz=center, bin_mhz=int(SPEC_BIN_HZ * 1000),
            db_ref_x10=int(DB_REF * 10), db_step_x100=int(DB_STEP * 100), power=power))

    def _iq(self, ch, t_us, locked):
        radius = CHANNEL_MODEL[ch]['radius'] if locked else 2000
        pairs = []
        for _ in range(64):
            angle = self.rng.uniform(0, 2 * math.pi)
            pairs.append((_i16(radius * math.cos(angle) + self.rng.gauss(0, 2200)),
                          _i16(radius * math.sin(angle) + self.rng.gauss(0, 2200))))
        return self._msg(p.IQ_SNAPSHOT, dict(channel=ch, t_us=t_us, sample_rate_hz=100000, iq=pairs))

    async def chunks(self):
        loop = asyncio.get_running_loop()
        start = loop.time()
        while True:
            yield self.step()
            await asyncio.sleep(max(0.0, start + self.tick * TICK_S - loop.time()))


def from_args(config, kind, file=None, speed=1.0, loop=False):
    """Validate the choice now; return a factory taking get_tuning() and building a fresh source."""
    if kind == 'sim':
        return lambda get_tuning: SimSource(get_tuning)
    if kind == 'replay':
        if not file:
            raise ToolError('--source replay needs --file CAPTURE.bin')
        ReplaySource(file, speed=speed, loop=loop)   # raises ToolError early for a bad path/speed
        return lambda get_tuning: ReplaySource(file, speed=speed, loop=loop)
    if kind == 'serial':
        return lambda get_tuning: SerialSource(config)
    raise ToolError('Unknown source {!r}: use serial, replay or sim.'.format(kind))
```

- [ ] **Step 5: Run the new tests and the existing suite**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v`
Expected: all PASS. This includes `test_protocol` and `test_workbench`, which
use `link_samples`.

- [ ] **Step 6: Commit**

```bash
git add tools/sdr_cli/sources.py tools/sdr_cli/apex.py tools/tests/link_samples.py tools/tests/test_sources.py
git commit -m "Add serial, replay and simulated byte sources for the GUI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Hub (`hub.py`)

**Files:**
- Create: `tools/sdr_cli/hub.py`
- Test: `tools/tests/test_hub.py`

**Interfaces:**
- Consumes: `protocol.StreamDecoder`, `LinkState`, `bin_frequency`, `power_db`,
  and `format_record`; `display.WaterfallScale`; and any Task 3 source.
- Produces: `Hub(clock=time.monotonic)`, with:
  - Attributes `decoder`, `link`, `scales`, and `source` (a dict with
    `kind state detail responds_to_tuning`).
  - Methods:
    - `subscribe(fn) -> unsubscribe()`, `publish(msg)`
    - `feed(data) -> [msg]`
    - `byte_rate() -> float`, `stats_message() -> dict`
    - `snapshot() -> [msg]`: the latest STATUS, LINK_STATS, per-channel metrics and I/Q, and last BEST_TELEM, for a newly connected viewer
    - `set_source(source, state, detail='')`
    - `async run(source)`
- The message shapes the server and client rely on:
  - `{'type': 'record', 'record': Record.as_json(), 'text': format_record(r)}`
  - `{'type': 'spectrum', 'channel', 'row', 't_us', 'f0_hz', 'bin_hz', 'bins', 'db10': [int], 'low', 'high', 'synthetic'}`.
    Here `db10` is dBFS×10, `f0_hz` is the center of bin 0, and `low`/`high` are
    the server auto-scale in dBFS.
  - `{'type': 'stats', 'decoder': {...}, 'rates': {name: per_s}, 'byte_rate', 'source': {...}}`

- [ ] **Step 1: Write the failing tests**

```python
# tools/tests/test_hub.py
import json
import unittest

from link_samples import sample_messages, sample_stream
from sdr_cli.core import ToolError
from sdr_cli.hub import Hub


class HubTest(unittest.TestCase):
    def test_feed_turns_records_into_client_messages(self):
        hub = Hub()
        seen = []
        hub.subscribe(seen.append)
        messages = hub.feed(sample_stream())
        self.assertEqual(len(messages), len(sample_messages()))
        self.assertEqual(seen, messages)
        spectrum = [m for m in messages if m['type'] == 'spectrum']
        self.assertEqual(len(spectrum), 8)
        first = spectrum[0]
        self.assertEqual((first['channel'], first['bins'], len(first['db10'])), ('A', 256, 256))
        self.assertAlmostEqual(first['f0_hz'], 50000.0)
        self.assertEqual(first['db10'][90], -500)      # power 140 → −120 + 70 = −50 dBFS
        self.assertLess(first['low'], first['high'])
        records = [m for m in messages if m['type'] == 'record']
        self.assertEqual(records[0]['record']['type'], 'STATUS')
        self.assertIn('STATUS', records[0]['text'])
        json.dumps(messages)

    def test_snapshot_replays_latest_slow_records(self):
        hub = Hub()
        self.assertEqual(hub.snapshot(), [])
        hub.feed(sample_stream())
        kinds = [m['record']['type'] for m in hub.snapshot()]
        self.assertEqual(kinds, ['STATUS', 'LINK_STATS', 'CHAN_METRICS', 'CHAN_METRICS', 'IQ_SNAPSHOT', 'IQ_SNAPSHOT',
                                 'BEST_TELEM'])

    def test_unsubscribe(self):
        hub = Hub()
        seen = []
        stop = hub.subscribe(seen.append)
        stop()
        hub.feed(sample_stream())
        self.assertEqual(seen, [])

    def test_stats_and_byte_rate(self):
        now = [100.0]
        hub = Hub(clock=lambda: now[0])
        hub.feed(b'\x00' * 1000)
        self.assertAlmostEqual(hub.byte_rate(), 200.0)
        stats = hub.stats_message()
        json.dumps(stats)
        self.assertEqual(stats['decoder']['bytes'], 1000)
        now[0] += 6
        self.assertEqual(hub.byte_rate(), 0.0)


class Once:
    kind, responds_to_tuning, detail = 'replay', False, 'sample.bin'

    async def chunks(self):
        yield sample_stream()


class Broken(Once):
    async def chunks(self):
        raise ToolError('Cannot open /dev/cu.usbserial: busy')
        yield b''


class HubRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_reports_source_states(self):
        hub = Hub()
        states = []
        hub.subscribe(lambda m: m['type'] == 'stats' and states.append(m['source']['state']))
        await hub.run(Once())
        self.assertEqual(states, ['running', 'ended'])
        self.assertEqual(hub.link.status.name, 'STATUS')
        await hub.run(Broken())
        self.assertEqual(hub.source['state'], 'down')
        self.assertIn('busy', hub.source['detail'])
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_hub.py' -v`
Expected: ERROR `No module named 'sdr_cli.hub'`.

- [ ] **Step 3: Implement**

```python
# tools/sdr_cli/hub.py
"""Decode one byte source and fan the results out to GUI clients (no web imports)."""
import asyncio
from collections import deque
import time

from .core import ToolError
from .display import WaterfallScale
from .protocol import CHANNELS, SPECTRUM, LinkState, StreamDecoder, bin_frequency, format_record, power_db


class Hub:
    RATE_WINDOW_S = 5.0

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.decoder = StreamDecoder()
        self.link = LinkState()
        self.scales = {ch: WaterfallScale() for ch in CHANNELS}
        self.subscribers = []
        self.arrivals = deque()
        self.source = dict(kind='none', state='starting', detail='', responds_to_tuning=False)

    def subscribe(self, fn):
        self.subscribers.append(fn)
        return lambda: self.subscribers.remove(fn)

    def publish(self, msg):
        for fn in list(self.subscribers):
            fn(msg)

    def feed(self, data):
        self.arrivals.append((self.clock(), len(data)))
        records = self.decoder.feed(data)
        self.link.update(records)
        messages = [self.message(r) for r in records]
        for msg in messages:
            self.publish(msg)
        return messages

    def message(self, r):
        if r.type == SPECTRUM:
            f = r.fields
            db = power_db(f)
            scale = self.scales.setdefault(f['channel'], WaterfallScale())
            scale.update(db)
            return dict(type='spectrum', channel=f['channel'], row=f['row'], t_us=f['t_us'],
                        f0_hz=bin_frequency(f, 0), bin_hz=f['bin_hz'], bins=f['bins'],
                        db10=[int(round(v * 10)) for v in db], low=scale.low, high=scale.high,
                        synthetic=r.synthetic)
        return dict(type='record', record=r.as_json(), text=format_record(r))

    def snapshot(self):
        """Latest slow-changing records, so a new viewer is not blank until the next 1 Hz message."""
        records = [self.link.status, self.link.link_stats, *self.link.metrics.values(), *self.link.iq.values()]
        if self.link.best:
            records.append(self.link.best[-1])
        return [self.message(r) for r in records if r is not None]

    def byte_rate(self):
        now = self.clock()
        while self.arrivals and self.arrivals[0][0] < now - self.RATE_WINDOW_S:
            self.arrivals.popleft()
        return sum(n for _, n in self.arrivals) / self.RATE_WINDOW_S

    def stats_message(self):
        decoder = dict(self.decoder.stats)
        decoder['by_type'] = dict(decoder['by_type'])
        return dict(type='stats', decoder=decoder, rates=self.link.rates(), byte_rate=self.byte_rate(),
                    source=dict(self.source))

    def set_source(self, source, state, detail=''):
        self.source = dict(kind=source.kind, state=state, detail=detail or source.detail,
                           responds_to_tuning=source.responds_to_tuning)
        self.publish(self.stats_message())

    async def run(self, source):
        """Consume a source until it ends or fails. Link state survives; the decoder restarts."""
        self.decoder = StreamDecoder()
        self.set_source(source, 'running')
        try:
            async for data in source.chunks():
                self.feed(data)
        except asyncio.CancelledError:
            self.set_source(source, 'stopped')
            raise
        except (ToolError, OSError) as exc:
            self.set_source(source, 'down', str(exc))
            return
        self.set_source(source, 'ended')
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_hub.py' -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/sdr_cli/hub.py tools/tests/test_hub.py
git commit -m "Add GUI hub: single decode path fanned out to clients" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Phase 2 — Server and CLI

### Task 5: aiohttp server (`web/server.py`)

**Files:**
- Modify: `pyproject.toml` (the `gui` extra and package data)
- Modify: `.gitignore`
- Create: `tools/sdr_cli/web/__init__.py`, `tools/sdr_cli/web/server.py`
- Test: `tools/tests/test_gui_server.py`

**Interfaces:**
- Consumes: `Hub` (Task 4), `RoleManager`/`ADMIN` (Task 2), `freqplan.load_state/save_state/update/derive/to_dict` (Task 1), `sources.from_args` (Task 3).
- Produces:
  - `GuiServer(source_factory, roles, state_path, static_dir=STATIC_DIR, hub=None)`, with:
    - Methods `.app() -> aiohttp.web.Application`, `.start_source()`, and `.save_if_dirty()`.
    - Class attributes `STATS_PERIOD_S` and `BAD_PASSWORD_DELAY_S`.
    - Attributes `clients` and `tuning`.
  - `run_gui(root, config, args)` and `lan_addresses()`.
- The WebSocket message schema is listed in the spec. The server-only additions are:
  - the `hello` payload `{server_version, protocol_version, source, role: <role msg>, tuning: <tuning msg>}`;
  - the `role` msg `{role, admin, can_admin, reason, token?, by?}`;
  - the `tuning` msg `{state, derived}`.

- [ ] **Step 1: Add the extra, package data and ignores**

In `pyproject.toml`, add the following below `dependencies = [...]` in `[project]`:

```toml
[project.optional-dependencies]
gui = ["aiohttp>=3.9,<4"]
```

and at the end of the file:

```toml
[tool.setuptools.package-data]
sdr_cli = ["web/static/**/*"]
```

Append to `.gitignore`:

```gitignore

# GUI: frontend dependencies and the built bundle (produced by `npm run build`)
tools/sdr_web/node_modules/
tools/sdr_cli/web/static/
```

Install: `.venv/bin/python -m pip install -e '.[gui]'`
Expected: `Successfully installed aiohttp-3.x ...` (plus its dependencies).

- [ ] **Step 2: Write the failing tests**

```python
# tools/tests/test_gui_server.py
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from link_samples import sample_stream
from sdr_cli import freqplan, roles as r

try:
    from aiohttp.test_utils import TestClient, TestServer
    from sdr_cli.web.server import GuiServer
except ImportError:   # the gui extra is optional
    GuiServer = None


class SampleOnce:
    """Replays the sample stream once a viewer is connected, then stays idle."""
    kind, responds_to_tuning, detail = 'replay', False, 'sample'

    def __init__(self, clients):
        self.clients = clients

    async def chunks(self):
        while not self.clients():
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        yield sample_stream()
        await asyncio.sleep(3600)


@unittest.skipIf(GuiServer is None, 'aiohttp not installed: pip install -e ".[gui]"')
class GuiServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        static = Path(self.tmp.name) / 'static'
        static.mkdir()
        (static / 'index.html').write_text('<!doctype html><title>test</title>')
        roles = r.RoleManager(r.hash_password('pw', iterations=1000))
        self.state_path = Path(self.tmp.name) / 'gui_state.json'
        self.server = GuiServer(lambda get_tuning: SampleOnce(lambda: self.server.clients), roles,
                                self.state_path, static_dir=static)
        self.server.BAD_PASSWORD_DELAY_S = 0
        self.client = TestClient(TestServer(self.server.app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def recv(self, ws, predicate, limit=300):
        for _ in range(limit):
            msg = await asyncio.wait_for(ws.receive_json(), 3)
            if predicate(msg):
                return msg
        self.fail('expected message not received')

    def of(self, kind, **match):
        return lambda m: m['type'] == kind and all(m.get(k) == v for k, v in match.items())

    async def connect(self):
        ws = await self.client.ws_connect('/ws')
        hello = await self.recv(ws, self.of('hello'))
        return ws, hello

    async def test_index_and_hello(self):
        resp = await self.client.get('/')
        self.assertEqual(resp.status, 200)
        ws, hello = await self.connect()
        self.assertEqual(hello['role']['role'], 'viewer')
        self.assertTrue(hello['role']['can_admin'])
        self.assertAlmostEqual(hello['tuning']['derived']['lo_hz'], 441.38e6, places=0)
        await ws.close()

    async def test_records_and_spectrum_fan_out(self):
        ws, _ = await self.connect()
        spectrum = await self.recv(ws, self.of('spectrum'))
        self.assertEqual(len(spectrum['db10']), 256)
        record = await self.recv(ws, lambda m: m['type'] == 'record' and m['record']['type'] == 'IQ_SNAPSHOT')
        self.assertIn('IQ_SNAPSHOT', record['text'])
        await ws.close()

    async def test_late_viewer_gets_latest_status_at_once(self):
        first, _ = await self.connect()
        await self.recv(first, lambda m: m['type'] == 'record' and m['record']['type'] == 'LINK_STATS')
        late, _ = await self.connect()
        status = await self.recv(late, lambda m: m['type'] == 'record' and m['record']['type'] == 'STATUS', limit=5)
        self.assertEqual(status['record']['fields']['version'], 2)
        await first.close()
        await late.close()

    async def test_viewer_cannot_tune_and_admin_change_is_broadcast(self):
        admin, _ = await self.connect()
        viewer, _ = await self.connect()
        await viewer.send_json(dict(type='tune', changes=dict(nco_hz=101e3)))
        self.assertEqual((await self.recv(viewer, self.of('error')))['code'], 'not_admin')
        await admin.send_json(dict(type='login', password='nope', label='gs'))
        self.assertEqual((await self.recv(admin, self.of('error')))['code'], 'bad_password')
        await admin.send_json(dict(type='login', password='pw', label='gs'))
        role = await self.recv(admin, self.of('role', role='admin'))
        self.assertTrue(role['token'])
        await admin.send_json(dict(type='tune', changes=dict(lo_hz=441.39e6)))
        tuned = await self.recv(viewer, self.of('tuning'))
        self.assertAlmostEqual(tuned['derived']['lo_hz'], 441.39e6, places=0)
        await admin.send_json(dict(type='tune', changes=dict(frac=99999)))
        self.assertEqual((await self.recv(admin, self.of('error')))['code'], 'out_of_range')
        self.server.save_if_dirty()
        self.assertAlmostEqual(freqplan.lo_hz(freqplan.load_state(self.state_path)), 441.39e6, places=0)
        await admin.close()
        await viewer.close()

    async def test_takeover_is_confirmed_and_announced(self):
        a, _ = await self.connect()
        b, _ = await self.connect()
        await a.send_json(dict(type='login', password='pw', label='gs'))
        await self.recv(a, self.of('role', role='admin'))
        await b.send_json(dict(type='login', password='pw', label='phone'))
        need = await self.recv(b, self.of('takeover_required'))
        self.assertEqual(need['held_by'], 'gs')
        await b.send_json(dict(type='login', password='pw', label='phone', takeover=True))
        await self.recv(b, self.of('role', role='admin'))
        demoted = await self.recv(a, self.of('role', reason='taken_over'))
        self.assertEqual((demoted['role'], demoted['by']), ('viewer', 'phone'))
        await a.close()
        await b.close()

    async def test_bad_json_is_reported_not_fatal(self):
        ws, _ = await self.connect()
        await ws.send_str('not json')
        self.assertEqual((await self.recv(ws, self.of('error')))['code'], 'bad_json')
        await ws.send_json(dict(type='ping'))
        await self.recv(ws, self.of('pong'))
        await ws.close()
```

- [ ] **Step 3: Run to verify failure**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_gui_server.py' -v`
Expected: the tests are **skipped** with "aiohttp not installed" if Step 1's
install was skipped. Otherwise they ERROR with `No module named 'sdr_cli.web'`.
Both confirm that nothing exists yet.

- [ ] **Step 4: Implement**

`tools/sdr_cli/web/__init__.py`:

```python
"""Web GUI server (optional `gui` extra)."""
```

`tools/sdr_cli/web/server.py`:

```python
"""Web GUI server: built static files plus one WebSocket per viewer.

See docs/superpowers/specs/2026-09-29-gui-design.md. All logic lives in the
toolkit-free modules (hub, roles, freqplan, sources); this file is glue.
"""
import asyncio
import json
from pathlib import Path
import socket
import uuid
import webbrowser

from aiohttp import WSMsgType, web

from .. import __version__, freqplan
from ..core import ToolError
from ..hub import Hub
from ..protocol import PROTOCOL_VERSION
from ..roles import ADMIN, RoleManager
from ..sources import from_args

STATIC_DIR = Path(__file__).resolve().parent / 'static'
QUEUE_MAX = 400
LOCAL_ADDRESSES = ('127.0.0.1', '::1')
BUILD_HINT = 'GUI is not built. Run: cd tools/sdr_web && npm install && npm run build'


def error(code, text):
    return dict(type='error', code=code, text=text)


class Client:
    def __init__(self, ws, local):
        self.id = uuid.uuid4().hex
        self.ws = ws
        self.local = local
        self.queue = asyncio.Queue(maxsize=QUEUE_MAX)

    def put(self, msg):
        if self.queue.full():   # a slow viewer drops its oldest message; live views prefer fresh data
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(msg)


class GuiServer:
    STATS_PERIOD_S = 0.5
    BAD_PASSWORD_DELAY_S = 1.0

    def __init__(self, source_factory, roles, state_path, static_dir=STATIC_DIR, hub=None):
        self.source_factory = source_factory
        self.roles = roles
        self.state_path = Path(state_path)
        self.static_dir = Path(static_dir)
        self.tuning = freqplan.load_state(self.state_path)
        self.dirty = False
        self.hub = hub or Hub()
        self.clients = {}
        self.source_task = None
        self.tasks = []
        self.hub.subscribe(self.broadcast)

    # ---- lifecycle
    def app(self):
        app = web.Application()
        app.router.add_get('/ws', self.websocket)
        app.router.add_get('/', self.index)
        assets = self.static_dir / 'assets'
        if assets.is_dir():
            app.router.add_static('/assets', assets)
        app.on_startup.append(self._start)
        app.on_shutdown.append(self._shutdown)
        return app

    async def index(self, request):
        index = self.static_dir / 'index.html'
        if not index.is_file():
            raise web.HTTPServiceUnavailable(text=BUILD_HINT)
        return web.FileResponse(index)

    async def _start(self, app):
        self.start_source()
        self.tasks.append(asyncio.ensure_future(self._housekeeping()))

    async def _shutdown(self, app):
        for client in list(self.clients.values()):
            await client.ws.close()
        pending = self.tasks + ([self.source_task] if self.source_task else [])
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.save_if_dirty()

    def start_source(self):
        if self.source_task and not self.source_task.done():
            self.source_task.cancel()
        try:
            source = self.source_factory(lambda: self.tuning)
        except ToolError as exc:
            self.hub.source = dict(kind='none', state='down', detail=str(exc), responds_to_tuning=False)
            self.broadcast(self.hub.stats_message())
            return
        self.source_task = asyncio.ensure_future(self.hub.run(source))

    async def _housekeeping(self):
        while True:
            await asyncio.sleep(self.STATS_PERIOD_S)
            if self.roles.expire():
                self.broadcast_roles('released')
            self.save_if_dirty()
            self.broadcast(self.hub.stats_message())

    def save_if_dirty(self):
        """Tuning saves are batched so drags don't write the disk (a Pi SD card) 30 times a second."""
        if self.dirty:
            freqplan.save_state(self.state_path, self.tuning)
            self.dirty = False

    # ---- outgoing
    def broadcast(self, msg):
        for client in self.clients.values():
            client.put(msg)

    def tuning_message(self):
        return dict(type='tuning', state=freqplan.to_dict(self.tuning), derived=freqplan.derive(self.tuning))

    def role_message(self, client, reason, **extra):
        return dict(type='role', role=self.roles.role(client.id), admin=self.roles.admin_info(),
                    can_admin=self.roles.can_login(client.id), reason=reason, **extra)

    def broadcast_roles(self, reason, skip=()):
        for client in self.clients.values():
            if client.id not in skip:
                client.put(self.role_message(client, reason))

    async def _send_loop(self, client):
        try:
            while True:
                msg = await client.queue.get()
                await client.ws.send_str(json.dumps(msg, separators=(',', ':')))
        except (ConnectionResetError, RuntimeError):
            return

    # ---- incoming
    async def websocket(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        client = Client(ws, request.remote in LOCAL_ADDRESSES)
        self.clients[client.id] = client
        self.roles.connect(client.id, client.local)
        client.put(dict(type='hello', server_version=__version__, protocol_version=PROTOCOL_VERSION,
                        source=dict(self.hub.source), role=self.role_message(client, 'connect'),
                        tuning=self.tuning_message()))
        client.put(self.hub.stats_message())
        for msg in self.hub.snapshot():
            client.put(msg)
        sender = asyncio.ensure_future(self._send_loop(client))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    client.put(error('bad_json', 'Message is not JSON.'))
                    continue
                if not isinstance(data, dict):
                    client.put(error('bad_json', 'Message must be a JSON object.'))
                    continue
                await self.handle(client, data)
        finally:
            sender.cancel()
            self.clients.pop(client.id, None)
            self.roles.disconnect(client.id)
        return ws

    async def handle(self, client, data):
        kind = data.get('type')
        is_admin = self.roles.role(client.id) == ADMIN
        if kind == 'ping':
            client.put(dict(type='pong'))
        elif kind == 'login':
            await self._login(client, data)
        elif kind == 'resume':
            if self.roles.resume(client.id, data.get('token')):
                client.put(self.role_message(client, 'resumed', token=data.get('token')))
                self.broadcast_roles('admin_changed', skip={client.id})
        elif kind == 'logout':
            if self.roles.logout(client.id):
                self.broadcast_roles('logout')
        elif kind == 'tune':
            if not is_admin:
                client.put(error('not_admin', 'Only the Admin can change tuning.'))
                return
            try:
                new = freqplan.update(self.tuning, data.get('changes'))
            except ValueError as exc:
                client.put(error('out_of_range', str(exc)))
                client.put(self.tuning_message())
                return
            if new != self.tuning:
                self.tuning, self.dirty = new, True
            self.broadcast(self.tuning_message())
        elif kind == 'reconnect_source':
            if not is_admin:
                client.put(error('not_admin', 'Only the Admin can reconnect the source.'))
                return
            self.start_source()
        else:
            client.put(error('unknown_type', 'Unknown message type: {}'.format(kind)))

    async def _login(self, client, data):
        result = self.roles.login(client.id, str(data.get('password') or ''), data.get('label'),
                                  bool(data.get('takeover')))
        if result['ok']:
            client.put(self.role_message(client, 'login', token=result['token']))
            demoted = self.clients.get(result['demoted']) if result['demoted'] else None
            if demoted:
                demoted.put(self.role_message(demoted, 'taken_over', by=self.roles.admin_info()['label']))
            self.broadcast_roles('admin_changed', skip={client.id} | ({demoted.id} if demoted else set()))
        elif result['code'] == 'needs_takeover':
            client.put(dict(type='takeover_required', held_by=result['held_by'], since=result['since']))
        elif result['code'] == 'bad_password':
            await asyncio.sleep(self.BAD_PASSWORD_DELAY_S)
            client.put(error('bad_password', 'Wrong Admin password.'))
        else:
            client.put(error('no_password', 'No Admin password is set. Run ./sdr setup --gui-password on the '
                                            'server, or log in from the server machine itself.'))


def lan_addresses():
    """Best-effort IPv4 addresses other devices can use to reach this machine."""
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))   # TEST-NET address; UDP connect sends no packet
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith('127.'))
    except OSError:
        pass
    return sorted(found)


def run_gui(root, config, args):
    if not (STATIC_DIR / 'index.html').is_file():
        raise ToolError(BUILD_HINT)
    factory = from_args(config, args.source, file=args.file, speed=args.speed, loop=args.loop)
    roles = RoleManager(config.get('gui_admin_hash', ''))
    server = GuiServer(factory, roles, root / '.sdr/gui_state.json')
    host = '0.0.0.0' if args.lan else '127.0.0.1'
    url = 'http://127.0.0.1:{}/'.format(args.http_port)
    print('SDR GUI at {} (source: {})'.format(url, args.source))
    if args.lan:
        for address in lan_addresses():
            print('  LAN: http://{}:{}/'.format(address, args.http_port))
        if not roles.password_hash:
            print('  No Admin password is set: only this machine can become Admin (sdr setup --gui-password).')
    else:
        print('  Local only. Add --lan to let other devices on the network connect.')
    print('  Ctrl-C stops the server.')
    app = server.app()

    async def open_browser(app):
        if not args.no_browser:
            asyncio.get_running_loop().call_later(0.3, webbrowser.open, url)

    app.on_startup.append(open_browser)
    web.run_app(app, host=host, port=args.http_port, print=None, access_log=None)
```

- [ ] **Step 5: Run to verify pass**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_gui_server.py' -v`
Expected: 6 tests PASS, none skipped.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore tools/sdr_cli/web/__init__.py tools/sdr_cli/web/server.py tools/tests/test_gui_server.py
git commit -m "Add aiohttp GUI server with shared tuning and Admin takeover" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: CLI — `sdr gui`, `setup --gui-password`, masked `config`

**Files:**
- Modify: `tools/sdr_cli/core.py:20-22` (DEFAULTS)
- Modify: `tools/sdr_cli/cli.py` (parser, `configure`, new `prompt_gui_password`, `config` masking, `gui` dispatch)
- Test: `tools/tests/test_gui_cli.py`

**Interfaces:**
- Consumes: `roles.hash_password`/`verify_password` (Task 2) and `web.server.run_gui` (Task 5).
- Produces:
  - `cli.prompt_gui_password(read=getpass.getpass, interactive=None) -> str`, which returns the hash.
  - `cli.public_config(config) -> dict`, with the hash masked.
  - Config key `gui_admin_hash`.
  - `gui` CLI flags: `--source {serial,replay,sim}`, `--file`, `--speed`, `--loop`,
    `--lan`, `--http-port`, `--no-browser`, `--port`, `--baud`.

- [ ] **Step 1: Write the failing tests**

```python
# tools/tests/test_gui_cli.py
from pathlib import Path
import tempfile
import unittest

from sdr_cli import cli, core, roles


class GuiCliTest(unittest.TestCase):
    def test_gui_arguments(self):
        args = cli.parser().parse_args(['gui', '--source', 'sim', '--lan', '--http-port', '9000', '--no-browser'])
        self.assertEqual((args.command, args.source, args.lan, args.http_port, args.no_browser),
                         ('gui', 'sim', True, 9000, True))
        defaults = cli.parser().parse_args(['gui'])
        self.assertEqual((defaults.source, defaults.lan, defaults.http_port, defaults.speed), ('serial', False, 8080, 1.0))

    def test_password_prompt(self):
        answers = iter(['correct horse', 'correct horse'])
        stored = cli.prompt_gui_password(read=lambda prompt: next(answers), interactive=True)
        self.assertTrue(roles.verify_password('correct horse', stored))
        mismatch = iter(['correct horse', 'wrong horse'])
        with self.assertRaises(core.ToolError):
            cli.prompt_gui_password(read=lambda prompt: next(mismatch), interactive=True)
        with self.assertRaises(core.ToolError):
            cli.prompt_gui_password(read=lambda prompt: 'short', interactive=True)
        with self.assertRaises(core.ToolError):
            cli.prompt_gui_password(read=lambda prompt: 'x', interactive=False)

    def test_hash_is_saved_and_masked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = dict(core.DEFAULTS, gui_admin_hash=roles.hash_password('pw', iterations=1000))
            core.save_config(root, config)
            loaded = core.load_config(root)
            self.assertEqual(loaded['gui_admin_hash'], config['gui_admin_hash'])
            self.assertEqual(cli.public_config(loaded)['gui_admin_hash'], '(set)')
            self.assertEqual(cli.public_config(core.DEFAULTS)['gui_admin_hash'], '')
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_gui_cli.py' -v`
Expected: FAIL. Argparse exits on `gui` as an invalid choice (`SystemExit: 2`),
and `prompt_gui_password` is missing.

- [ ] **Step 3: Implement**

`tools/sdr_cli/core.py`: add the key to `DEFAULTS`. It must stay a string, because
`validate_config` requires string fields.

```python
DEFAULTS = dict(project="sdr", port="auto", baud=1000000, host="", user="",
                identity="", remote_root="C:/sdr-builds",
                vivado="C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat",
                gui_admin_hash="")
```

`tools/sdr_cli/cli.py`:

1. Add `import getpass` to the imports (keep them alphabetical: after `argparse`).
2. In `parser()`, after the `setup.add_argument('--interactive', ...)` line, add:

```python
    setup.add_argument('--gui-password', action='store_true',
                       help='Prompt for the GUI Admin password (stored hashed in .sdr/config.json)')
```

3. In `parser()`, before `return p`, add:

```python
    gui = sub.add_parser('gui', help='Serve the web GUI (local only unless --lan)')
    gui.add_argument('--source', choices=['serial', 'replay', 'sim'], default='serial',
                     help='serial: the board (default); replay: a capture file; sim: host simulator')
    gui.add_argument('--file', type=Path, help='Capture to replay (with --source replay)')
    gui.add_argument('--speed', type=float, default=1.0, help='Replay speed; 0 is as fast as possible')
    gui.add_argument('--loop', action='store_true', help='Replay the capture forever')
    gui.add_argument('--lan', action='store_true', help='Listen on all interfaces so other devices can connect')
    gui.add_argument('--http-port', type=int, default=8080)
    gui.add_argument('--no-browser', action='store_true', help='Do not open a browser window')
    gui.add_argument('--port', help='UART device override')
    gui.add_argument('--baud', type=int)
```

4. Add these functions above `def configure`:

```python
def prompt_gui_password(read=getpass.getpass, interactive=None):
    """Ask twice; return the salted hash. The password itself is never stored or printed."""
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise ToolError('Setting the GUI password needs a terminal.')
    first = read('New GUI Admin password: ')
    if len(first) < 8:
        raise ToolError('Use at least 8 characters.')
    if read('Repeat the password: ') != first:
        raise ToolError('The passwords do not match.')
    from .roles import hash_password
    return hash_password(first)


def public_config(config):
    """Settings safe to print: the Admin password hash is masked."""
    return dict(config, gui_admin_hash='(set)' if config.get('gui_admin_hash') else '')
```

5. In `configure()`, immediately before `save_config(root, config)`:

```python
    if getattr(args, 'gui_password', False):
        config['gui_admin_hash'] = prompt_gui_password()
```

6. In `main()`, change the `config` branch to print the masked settings:

```python
        elif args.command == 'config':
            print(json.dumps(public_config(config), indent=2))
```

7. In `main()`, add a `gui` branch before `return 0` (after the `send` branch):

```python
        elif args.command == 'gui':
            try:
                from .web.server import run_gui
            except ImportError as exc:
                raise ToolError('The GUI needs aiohttp. Install with: .venv/bin/python -m pip install -e ".[gui]"') from exc
            run_gui(root, config, args)
```

- [ ] **Step 4: Run the new tests and the full suite**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v`
Expected: all PASS.

- [ ] **Step 5: Smoke-test the command without a frontend**

Run: `./sdr gui --source sim --no-browser`
Expected: it exits with `sdr: GUI is not built. Run: cd tools/sdr_web && npm install && npm run build`.
The frontend arrives in Phase 3.

- [ ] **Step 6: Commit**

```bash
git add tools/sdr_cli/core.py tools/sdr_cli/cli.py tools/tests/test_gui_cli.py
git commit -m "Add sdr gui command and hashed GUI Admin password setup" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Phase 3 — Frontend foundation

All paths in this phase are relative to `tools/sdr_web/` unless they start with `tools/`.

### Task 7: Scaffold, theme, and branded shell

**Files:**
- Create: `package.json`, `vite.config.ts`, `svelte.config.js`, `tsconfig.json`, `index.html`
- Create: `src/main.ts`, `src/app.css`, `src/lib/theme.ts`, `src/lib/theme.test.ts`, `src/App.svelte` (temporary shell, finished in Task 10)
- Existing assets: `src/assets/space-raiders-logo.png` and `src/assets/space-raiders-logo-on-dark.png`
  were placed by the planner and are untracked. Stage them in this task.

**Interfaces:**
- Produces:
  - Theme helpers: `type ThemeChoice = 'system' | 'dark' | 'light'`, `loadTheme()`,
    `applyTheme(choice)`, `nextTheme(choice)`.
  - CSS tokens used by every later task:
    - Surfaces and text: `--bg --panel --panel-2 --line --line-2 --fg --muted --faint --wf-bg`.
    - Brand: `--brand --brand-soft`.
    - Data colors: `--if --lo --ch-a --ch-b`.
    - Status: `--good --warn --bad --synth`.
    - Logo switches: `--logo-dark --logo-light`.
    - Fonts: `--f-ui --f-mono`.
  - Shared classes:
    - Layout: `.panel .ph .pb .sub .right .stack .row`.
    - Controls: `.btn .btn.primary .seg .field`.
    - Labels: `.pill .pill.synth .chip.good|warn|bad .tag`.
    - Text and readouts: `.mono .muted .note .derived .empty .big`.

- [ ] **Step 1: Create the project files**

`package.json`:

```json
{
  "name": "space-raiders-sdr-gui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "check": "svelte-check --tsconfig ./tsconfig.json",
    "test": "vitest run"
  },
  "dependencies": {
    "@fontsource/jetbrains-mono": "^5.3.0",
    "@fontsource/jost": "^5.3.0"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^7.3.1",
    "@tsconfig/svelte": "^5.0.8",
    "svelte": "^5.57.1",
    "svelte-check": "^4.7.6",
    "typescript": "~5.9.3",
    "vite": "^8.3.1",
    "vitest": "^5.0.2"
  }
}
```

`vite.config.ts`:

```ts
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

// The bundle is written into the Python package so `./sdr gui` serves it.
// `npm run dev` proxies the WebSocket to a running `./sdr gui --no-browser`.
export default defineConfig({
  plugins: [svelte()],
  build: { outDir: '../sdr_cli/web/static', emptyOutDir: true },
  server: { proxy: { '/ws': { target: 'ws://127.0.0.1:8080', ws: true } } },
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
});
```

`svelte.config.js`:

```js
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default { preprocess: vitePreprocess() };
```

`tsconfig.json`:

```json
{
  "extends": "@tsconfig/svelte/tsconfig.json",
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noEmit": true,
    "isolatedModules": true,
    "verbatimModuleSyntax": true,
    "skipLibCheck": true,
    "types": ["vite/client"]
  },
  "include": ["src/**/*.ts", "src/**/*.svelte", "vite.config.ts"]
}
```

`index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <title>Space Raiders SDR</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 2: Install**

Run: `cd tools/sdr_web && npm install`
Expected: `added N packages` with no errors. `package-lock.json` is created and
gets committed.

- [ ] **Step 3: Write the failing theme test**

`src/lib/theme.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { nextTheme } from './theme';

describe('theme', () => {
  it('cycles system → dark → light → system', () => {
    expect(nextTheme('system')).toBe('dark');
    expect(nextTheme('dark')).toBe('light');
    expect(nextTheme('light')).toBe('system');
  });
});
```

Run: `npm test`
Expected: FAIL, `Cannot find module './theme'` (or a failure to resolve the import).

- [ ] **Step 4: Implement theme, tokens, entry and a temporary shell**

`src/lib/theme.ts`:

```ts
export type ThemeChoice = 'system' | 'dark' | 'light';

const KEY = 'sdr.theme';

export function loadTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'dark' || v === 'light' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    /* per-device convenience only */
  }
}

export const nextTheme = (c: ThemeChoice): ThemeChoice => (c === 'system' ? 'dark' : c === 'dark' ? 'light' : 'system');
```

`src/app.css`. Light and dark are both designed; brand red is used for chrome only:

```css
/* Space Raiders SDR. Dark bench instrument by default, light for outdoor tablets.
   Brand red (#FB0000, sampled from the logo) marks identity and chrome, never data or status. */
:root {
  color-scheme: dark;
  --bg: #0b0b0c;
  --panel: #141416;
  --panel-2: #1c1c1f;
  --line: #2a2a2e;
  --line-2: #3a3a40;
  --fg: #f2f2f2;
  --muted: #a0a0a8;
  --faint: #66666e;
  --brand: #fb0000;
  --brand-soft: #fb000029;
  --if: #4fc3e0;
  --lo: #f2b544;
  --ch-a: #6aa8f5;
  --ch-b: #e285b8;
  --good: #52c486;
  --warn: #e8a33c;
  --bad: #ff7a6b;
  --synth: #b594f2;
  --wf-bg: #04060f;
  --logo-dark: inline-block;
  --logo-light: none;
  --f-ui: 'Jost', 'Futura', 'Century Gothic', system-ui, sans-serif;
  --f-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme='dark']) {
    color-scheme: light;
    --bg: #ffffff; --panel: #f6f6f7; --panel-2: #ececef; --line: #dcdce0; --line-2: #c6c6cc;
    --fg: #0b0b0c; --muted: #55555c; --faint: #8a8a92; --brand: #d10000; --brand-soft: #d100001f;
    --if: #0f7fa0; --lo: #a86a00; --ch-a: #1f6fd1; --ch-b: #b83b80;
    --good: #1e8a4f; --warn: #a86400; --bad: #c23a2b; --synth: #7a4fd0;
    --logo-dark: none; --logo-light: inline-block;
  }
}
:root[data-theme='light'] {
  color-scheme: light;
  --bg: #ffffff; --panel: #f6f6f7; --panel-2: #ececef; --line: #dcdce0; --line-2: #c6c6cc;
  --fg: #0b0b0c; --muted: #55555c; --faint: #8a8a92; --brand: #d10000; --brand-soft: #d100001f;
  --if: #0f7fa0; --lo: #a86a00; --ch-a: #1f6fd1; --ch-b: #b83b80;
  --good: #1e8a4f; --warn: #a86400; --bad: #c23a2b; --synth: #7a4fd0;
  --logo-dark: none; --logo-light: inline-block;
}

* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body { background: var(--bg); color: var(--fg); font: 15px/1.45 var(--f-ui); }
button, input, select { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
code { font-family: var(--f-mono); font-size: 0.9em; }

.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; min-width: 0; }
.ph { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 12px; padding: 9px 12px 7px; border-bottom: 1px solid var(--line); }
.ph h2 { margin: 0; font: 600 13px var(--f-ui); letter-spacing: 0.12em; text-transform: uppercase; }
.sub { color: var(--muted); font-size: 12.5px; }
.right { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.pb { padding: 10px 12px; }
.stack { display: grid; gap: 9px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.mono { font-family: var(--f-mono); font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.note { font-size: 13px; color: var(--muted); line-height: 1.4; margin: 0; }
.big { font: 500 22px var(--f-mono); }

.btn { border: 1px solid var(--line-2); background: var(--panel-2); border-radius: 5px; padding: 4px 11px; cursor: pointer; font-size: 14px; }
.btn:hover:not(:disabled) { border-color: var(--muted); }
.btn.primary { background: var(--brand); border-color: var(--brand); color: #fff; }
.btn[aria-pressed='true'] { border-color: var(--brand); box-shadow: inset 0 -2px 0 var(--brand); }
.btn:disabled { cursor: not-allowed; opacity: 0.55; }

.seg { display: inline-flex; border: 1px solid var(--line-2); border-radius: 5px; overflow: hidden; }
.seg button { border: 0; background: var(--bg); padding: 3px 10px; cursor: pointer; font-size: 13px; color: var(--muted); }
.seg button[aria-pressed='true'] { background: var(--panel-2); color: var(--fg); box-shadow: inset 0 -2px 0 var(--brand); }
.seg button + button { border-left: 1px solid var(--line-2); }
.seg button:disabled { cursor: not-allowed; }

.field { display: grid; grid-template-columns: 1fr 120px; align-items: center; gap: 8px; }
.field label { color: var(--muted); font-size: 13.5px; }
.field input, .field select { width: 100%; background: var(--bg); border: 1px solid var(--line-2); border-radius: 4px; padding: 3px 7px; font: 13px var(--f-mono); text-align: right; }
.field input:disabled, .field select:disabled { color: var(--muted); border-style: dashed; }

.derived { display: grid; grid-template-columns: 1fr auto; gap: 3px 10px; margin: 0; padding-top: 8px; border-top: 1px dashed var(--line-2); font: 12.5px var(--f-mono); }
.derived dt { color: var(--muted); font: 13.5px var(--f-ui); }
.derived dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }

.pill { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--line-2); font: 500 12px var(--f-mono); color: var(--muted); white-space: nowrap; }
.pill .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--faint); }
.pill .dot.good { background: var(--good); }
.pill .dot.warn { background: var(--warn); }
.pill .dot.bad { background: var(--bad); }
.pill.synth { color: var(--synth); border-color: var(--synth);
  background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--synth) 14%, transparent) 0 4px, transparent 4px 8px); }
.chip { display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border-radius: 4px; font: 600 11.5px var(--f-ui); letter-spacing: 0.08em; text-transform: uppercase; }
.chip::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.chip.good { color: var(--good); background: color-mix(in srgb, var(--good) 14%, transparent); }
.chip.warn { color: var(--warn); background: color-mix(in srgb, var(--warn) 14%, transparent); }
.chip.bad { color: var(--bad); background: color-mix(in srgb, var(--bad) 14%, transparent); }
.tag { font: 600 10.5px var(--f-ui); letter-spacing: 0.08em; text-transform: uppercase; color: var(--warn); border: 1px solid color-mix(in srgb, var(--warn) 45%, transparent); padding: 0 5px; border-radius: 3px; }
.empty { height: 100%; display: grid; place-content: center; text-align: center; gap: 4px; color: var(--muted); font-size: 13.5px; border: 1px dashed var(--line-2); border-radius: 6px; padding: 10px; }
.empty strong { color: var(--fg); font-weight: 500; }

@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
```

`src/main.ts`:

```ts
import '@fontsource/jost/400.css';
import '@fontsource/jost/500.css';
import '@fontsource/jost/600.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import './app.css';
import { mount } from 'svelte';
import App from './App.svelte';
import { applyTheme, loadTheme } from './lib/theme';

applyTheme(loadTheme());
mount(App, { target: document.getElementById('app')! });
```

`src/App.svelte`. This temporary shell proves the build and the branding; Task 10
replaces it:

```svelte
<script lang="ts">
  import logoLight from './assets/space-raiders-logo.png';
  import logoDark from './assets/space-raiders-logo-on-dark.png';
</script>

<header class="top">
  <span class="brand">
    <img class="logo light" src={logoLight} alt="Space Raiders" />
    <img class="logo dark" src={logoDark} alt="Space Raiders" />
    <span class="product">SDR</span>
  </span>
</header>
<main class="pb"><p class="note">Connecting…</p></main>

<style>
  .top { display: flex; align-items: center; padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }
  .brand { display: flex; align-items: center; gap: 10px; }
  .logo { height: 22px; width: auto; }
  .logo.dark { display: var(--logo-dark); }
  .logo.light { display: var(--logo-light); }
  .product { font: 600 13px var(--f-ui); letter-spacing: 0.2em; color: var(--brand); border-left: 1px solid var(--line-2); padding-left: 10px; }
</style>
```

- [ ] **Step 5: Verify tests, types and build**

Run: `npm test && npm run check && npm run build`
Expected:
- The theme tests PASS.
- svelte-check reports `0 errors`.
- The build writes `tools/sdr_cli/web/static/index.html` and `assets/`.

- [ ] **Step 6: Verify the server serves it**

Run it from the repo root: `./sdr gui --source sim --no-browser`. In a second
terminal, run `curl -s http://127.0.0.1:8080/ | head -5`.
Expected: the built `index.html`, with `<title>Space Raiders SDR</title>`. Stop
the server with Ctrl-C.

- [ ] **Step 7: Commit**

```bash
git add tools/sdr_web/package.json tools/sdr_web/package-lock.json tools/sdr_web/vite.config.ts \
  tools/sdr_web/svelte.config.js tools/sdr_web/tsconfig.json tools/sdr_web/index.html \
  tools/sdr_web/src/main.ts tools/sdr_web/src/app.css tools/sdr_web/src/App.svelte \
  tools/sdr_web/src/lib/theme.ts tools/sdr_web/src/lib/theme.test.ts \
  tools/sdr_web/src/assets/space-raiders-logo.png tools/sdr_web/src/assets/space-raiders-logo-on-dark.png
git commit -m "Scaffold Space Raiders SDR web frontend with theme tokens" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Pure view helpers (tested)

**Files:**
- Create: `src/lib/format.ts`, `src/lib/ring.ts`, `src/lib/axis.ts`, `src/lib/colormap.ts`, `src/lib/waterfall.ts`, `src/lib/layout.ts`, `src/lib/throttle.ts`
- Test: `src/lib/helpers.test.ts`

**Interfaces:**
- Produces:
  - `format.ts`: `mhz(hz, digits=6)`, `khz(hz, digits=1)`, `signedKhz(hz, digits=1)`,
    `hzText(hz)`, `hex32(v)`, `clockTime(epochS)`.
  - `ring.ts`: `class Ring { constructor(size); push(v); values(): readonly number[]; last; clear() }`.
  - `axis.ts`:
    - `interface Axis { f0; f1; left; right; width }` and `PAD = { left: 44, right: 10 }`.
    - `makeAxis(f0, f1, width)`, `xOf(a, f)`, `fOf(a, x)`, `ticks(f0, f1, step)`.
    - `ifToRf(loHz, injection, ifHz)`.
  - `colormap.ts`: `LUT` (256×RGB `Uint8ClampedArray`).
  - `waterfall.ts`: `paintRow(out, db10, low, high)` and
    `class WaterfallImage { bins; rows; canvas; push(db10, low, high) }`.
  - `layout.ts`:
    - `interface CardLayout { id; w; h }`, `MAX_W = 4`, `MAX_H = 4`.
    - `sanitize(saved, defaults)`, `move(layout, id, targetId, after)`, `resize(layout, id, w, h, cols)`.
    - `loadLayout(key, defaults)`, `saveLayout(key, layout)`.
  - `throttle.ts`: `createCoalescer<T>(send, intervalMs=33) -> { push(update), flush() }`.

- [ ] **Step 1: Write the failing tests**

`src/lib/helpers.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PAD, fOf, ifToRf, makeAxis, ticks, xOf } from './axis';
import { LUT } from './colormap';
import { hex32, khz, mhz, signedKhz } from './format';
import { move, resize, sanitize } from './layout';
import { Ring } from './ring';
import { createCoalescer } from './throttle';
import { paintRow } from './waterfall';

describe('format', () => {
  it('formats radio units', () => {
    expect(mhz(441.38e6, 3)).toBe('441.380');
    expect(khz(110400)).toBe('110.4 kHz');
    expect(signedKhz(-10400)).toBe('−10.4 kHz');
    expect(signedKhz(10400)).toBe('+10.4 kHz');
    expect(hex32(0x1999999a)).toBe('0x1999999A');
  });
});

describe('Ring', () => {
  it('keeps the newest values up to its size', () => {
    const r = new Ring(3);
    [1, 2, 3, 4].forEach((v) => r.push(v));
    expect(r.values()).toEqual([2, 3, 4]);
    expect(r.last).toBe(4);
  });
});

describe('axis', () => {
  it('maps frequency to pixels and back', () => {
    const a = makeAxis(50e3, 150e3, 454);
    expect(xOf(a, 50e3)).toBe(PAD.left);
    expect(xOf(a, 150e3)).toBe(454 - PAD.right);
    expect(fOf(a, xOf(a, 123e3))).toBeCloseTo(123e3, 6);
    expect(ticks(50e3, 150e3, 25e3)).toEqual([50e3, 75e3, 100e3, 125e3, 150e3]);
  });
  it('maps IF to RF for either injection side', () => {
    expect(ifToRf(441.38e6, 'low', 100e3)).toBe(441.48e6);
    expect(ifToRf(441.58e6, 'high', 100e3)).toBe(441.48e6);
  });
});

describe('colormap and waterfall rows', () => {
  it('runs dark to bright', () => {
    const lum = (i: number) => LUT[i * 3] * 0.2126 + LUT[i * 3 + 1] * 0.7152 + LUT[i * 3 + 2] * 0.0722;
    expect(LUT.length).toBe(768);
    expect(lum(0)).toBeLessThan(lum(128));
    expect(lum(128)).toBeLessThan(lum(255));
  });
  it('paints clamped RGBA pixels', () => {
    const out = new Uint8ClampedArray(3 * 4);
    paintRow(out, [-1300, -900, -400], -120, -50);   // below, middle, above the scale
    expect([out[0], out[1], out[2], out[3]]).toEqual([LUT[0], LUT[1], LUT[2], 255]);
    expect([out[8], out[9], out[10]]).toEqual([LUT[765], LUT[766], LUT[767]]);
    expect(out[4]).toBe(LUT[Math.round((30 / 70) * 255) * 3]);
  });
});

describe('card layout', () => {
  const defaults = [{ id: 'a', w: 2, h: 1 }, { id: 'b', w: 1, h: 1 }, { id: 'c', w: 4, h: 2 }];
  it('sanitizes saved layouts', () => {
    expect(sanitize(null, defaults)).toEqual(defaults);
    expect(sanitize([{ id: 'c', w: 9, h: 0 }, { id: 'zzz', w: 1, h: 1 }, { id: 'c', w: 1, h: 1 }], defaults)).toEqual([
      { id: 'c', w: 4, h: 1 }, { id: 'a', w: 2, h: 1 }, { id: 'b', w: 1, h: 1 },
    ]);
  });
  it('moves and resizes', () => {
    expect(move(defaults, 'c', 'a', false).map((c) => c.id)).toEqual(['c', 'a', 'b']);
    expect(move(defaults, 'a', 'b', true).map((c) => c.id)).toEqual(['b', 'a', 'c']);
    expect(resize(defaults, 'b', 3, 9, 2)).toEqual([defaults[0], { id: 'b', w: 2, h: 4 }, defaults[2]]);
  });
});

describe('coalescer', () => {
  afterEach(() => vi.useRealTimers());
  it('sends the first update now and merges the rest per interval', () => {
    vi.useFakeTimers();
    const sent: object[] = [];
    const c = createCoalescer<Record<string, number>>((m) => sent.push(m), 33);
    c.push({ lo_hz: 1 });
    c.push({ lo_hz: 2 });
    c.push({ nco_hz: 3 });
    expect(sent).toEqual([{ lo_hz: 1 }]);
    vi.advanceTimersByTime(33);
    expect(sent).toEqual([{ lo_hz: 1 }, { lo_hz: 2, nco_hz: 3 }]);
  });
});
```

Run: `npm test`
Expected: FAIL, because the imported modules don't exist yet.

- [ ] **Step 2: Implement the helpers**

`src/lib/format.ts`:

```ts
export const mhz = (hz: number, digits = 6) => (hz / 1e6).toFixed(digits);
export const khz = (hz: number, digits = 1) => `${(hz / 1e3).toFixed(digits)} kHz`;
export const signedKhz = (hz: number, digits = 1) => `${hz >= 0 ? '+' : '−'}${Math.abs(hz / 1e3).toFixed(digits)} kHz`;
export const hzText = (hz: number) => (Math.abs(hz) >= 1e3 ? khz(hz, 3) : `${hz.toFixed(1)} Hz`);
export const hex32 = (v: number) => '0x' + (v >>> 0).toString(16).toUpperCase().padStart(8, '0');
export const clockTime = (epochS: number) =>
  new Date(epochS * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
```

`src/lib/ring.ts`:

```ts
/** Fixed-size history (sparklines). */
export class Ring {
  private buf: number[] = [];
  constructor(readonly size: number) {}
  push(v: number): void {
    this.buf.push(v);
    if (this.buf.length > this.size) this.buf.shift();
  }
  values(): readonly number[] {
    return this.buf;
  }
  get last(): number | undefined {
    return this.buf[this.buf.length - 1];
  }
  clear(): void {
    this.buf = [];
  }
}
```

`src/lib/axis.ts`:

```ts
/** Frequency ↔ pixel mapping shared by every spectrum drawing. */
export interface Axis { f0: number; f1: number; left: number; right: number; width: number }

export const PAD = { left: 44, right: 10 };

export const makeAxis = (f0: number, f1: number, width: number): Axis => ({ f0, f1, left: PAD.left, right: PAD.right, width });
export const xOf = (a: Axis, f: number) => a.left + ((f - a.f0) / (a.f1 - a.f0)) * (a.width - a.left - a.right);
export const fOf = (a: Axis, x: number) => a.f0 + ((x - a.left) / (a.width - a.left - a.right)) * (a.f1 - a.f0);

export function ticks(f0: number, f1: number, step: number): number[] {
  const out: number[] = [];
  for (let k = Math.ceil(f0 / step - 1e-9); k * step <= f1 + 1e-6; k++) out.push(k * step);
  return out;
}

/** Display-only mapping; authoritative LO/IF values come from the server's `derived`. */
export const ifToRf = (loHz: number, injection: 'low' | 'high', ifHz: number) =>
  injection === 'low' ? loHz + ifHz : loHz - ifHz;
```

`src/lib/colormap.ts`:

```ts
/** Waterfall colormap: perceptual, monotonic lightness (same in both themes). */
const STOPS: [number, [number, number, number]][] = [
  [0, [4, 6, 18]], [0.22, [40, 18, 84]], [0.45, [122, 30, 108]],
  [0.65, [206, 64, 70]], [0.82, [248, 142, 30]], [1, [252, 250, 170]],
];

export const LUT: Uint8ClampedArray = (() => {
  const out = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let k = 0;
    while (STOPS[k + 1][0] < t) k++;
    const [t0, a] = STOPS[k];
    const [t1, b] = STOPS[k + 1];
    const u = (t - t0) / (t1 - t0);
    for (let c = 0; c < 3; c++) out[i * 3 + c] = a[c] + (b[c] - a[c]) * u;
  }
  return out;
})();
```

`src/lib/waterfall.ts`:

```ts
import { LUT } from './colormap';

/** Write one spectrum row (dBFS×10) into RGBA pixels using the low..high dBFS scale. */
export function paintRow(out: Uint8ClampedArray, db10: ArrayLike<number>, low: number, high: number): void {
  const span = high - low || 1;
  for (let k = 0; k < db10.length; k++) {
    const n = Math.min(1, Math.max(0, (db10[k] / 10 - low) / span));
    const i = Math.round(n * 255) * 3;
    out[k * 4] = LUT[i];
    out[k * 4 + 1] = LUT[i + 1];
    out[k * 4 + 2] = LUT[i + 2];
    out[k * 4 + 3] = 255;
  }
}

/** Scrolling offscreen image: one pixel column per bin, newest row on top. */
export class WaterfallImage {
  readonly canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private row: ImageData;

  constructor(readonly bins: number, readonly rows: number) {
    this.canvas = document.createElement('canvas');
    this.canvas.width = bins;
    this.canvas.height = rows;
    this.ctx = this.canvas.getContext('2d')!;
    this.ctx.fillStyle = '#04060f';
    this.ctx.fillRect(0, 0, bins, rows);
    this.row = this.ctx.createImageData(bins, 1);
  }

  push(db10: ArrayLike<number>, low: number, high: number): void {
    this.ctx.drawImage(this.canvas, 0, 0, this.bins, this.rows - 1, 0, 1, this.bins, this.rows - 1);
    paintRow(this.row.data, db10, low, high);
    this.ctx.putImageData(this.row, 0, 0);
  }
}
```

`src/lib/layout.ts`:

```ts
/** Telemetry card layout: order + span per card, saved per device. */
export interface CardLayout { id: string; w: number; h: number }

export const MAX_W = 4;
export const MAX_H = 4;

const clampInt = (v: unknown, lo: number, hi: number, fallback: number) =>
  typeof v === 'number' && Number.isFinite(v) ? Math.min(hi, Math.max(lo, Math.round(v))) : fallback;

export function sanitize(saved: unknown, defaults: CardLayout[]): CardLayout[] {
  const byId = new Map(defaults.map((d) => [d.id, d]));
  const seen = new Set<string>();
  const out: CardLayout[] = [];
  if (Array.isArray(saved)) {
    for (const item of saved as Partial<CardLayout>[]) {
      const d = item && typeof item.id === 'string' ? byId.get(item.id) : undefined;
      if (!d || seen.has(d.id)) continue;
      seen.add(d.id);
      out.push({ id: d.id, w: clampInt(item.w, 1, MAX_W, d.w), h: clampInt(item.h, 1, MAX_H, d.h) });
    }
  }
  for (const d of defaults) if (!seen.has(d.id)) out.push({ ...d });
  return out;
}

export function move(layout: CardLayout[], id: string, targetId: string, after: boolean): CardLayout[] {
  if (id === targetId) return layout;
  const card = layout.find((c) => c.id === id);
  const rest = layout.filter((c) => c.id !== id);
  const i = rest.findIndex((c) => c.id === targetId);
  if (!card || i < 0) return layout;
  rest.splice(after ? i + 1 : i, 0, card);
  return rest;
}

export function resize(layout: CardLayout[], id: string, w: number, h: number, cols: number): CardLayout[] {
  return layout.map((c) =>
    c.id === id ? { id, w: clampInt(w, 1, Math.min(MAX_W, cols), c.w), h: clampInt(h, 1, MAX_H, c.h) } : c,
  );
}

export function loadLayout(key: string, defaults: CardLayout[]): CardLayout[] {
  try {
    return sanitize(JSON.parse(localStorage.getItem(key) ?? 'null'), defaults);
  } catch {
    return sanitize(null, defaults);
  }
}

export function saveLayout(key: string, layout: CardLayout[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(layout));
  } catch {
    /* per-device convenience only */
  }
}
```

`src/lib/throttle.ts`:

```ts
/** Merge partial updates and send at most one per interval (drag → `tune`). */
export function createCoalescer<T extends object>(send: (merged: T) => void, intervalMs = 33) {
  let pending: T | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let last = -Infinity;
  const flush = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    if (!pending) return;
    const merged = pending;
    pending = null;
    last = Date.now();
    send(merged);
  };
  return {
    push(update: T) {
      pending = { ...(pending ?? {}), ...update } as T;
      if (timer) return;
      const wait = last + intervalMs - Date.now();
      if (wait <= 0) flush();
      else timer = setTimeout(flush, wait);
    },
    flush,
  };
}
```

- [ ] **Step 3: Verify**

Run: `npm test && npm run check`
Expected: all tests PASS and `0 errors`.

- [ ] **Step 4: Commit**

```bash
git add tools/sdr_web/src/lib/format.ts tools/sdr_web/src/lib/ring.ts tools/sdr_web/src/lib/axis.ts \
  tools/sdr_web/src/lib/colormap.ts tools/sdr_web/src/lib/waterfall.ts tools/sdr_web/src/lib/layout.ts \
  tools/sdr_web/src/lib/throttle.ts tools/sdr_web/src/lib/helpers.test.ts
git commit -m "Add tested GUI view helpers: axis, colormap, waterfall rows, layout, coalescer" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Message types, stores and the WebSocket client

**Files:**
- Create: `src/lib/types.ts`, `src/lib/link.ts`, `src/lib/view.ts`
- Test: `src/lib/link.test.ts`

**Interfaces:**
- Consumes: `Ring` and `createCoalescer` (Task 8), and the server schema (Tasks 4–5).
- Produces:
  - `types.ts`:
    - Scalar types: `Channel`, `Role`, `Injection`.
    - Payload shapes: `TuningState`, `Derived`, `AdminInfo`, `SourceState`, `RecordJson`.
    - Server messages: `HelloMsg`, `RecordMsg`, `SpectrumMsg`, `StatsMsg`,
      `TuningMsg`, `RoleMsg`, `TakeoverMsg`, `ErrorMsg`, their union `ServerMsg`,
      plus `ClientMsg` and `TuningChanges`.
  - `link.ts` stores:
    - Connection and session: `connection`, `hello`, `role`, `tuning`, `stats`.
    - Latest records: `status`, `linkStats`, `best`, `metrics`, `iqSnaps`, `frameLog`.
    - UI state: `takeover`, `notices`, `frozen`, `synthetic`.
    - History: `history`, `historyVersion`, and the constant `HISTORY = 300`.
  - `link.ts` functions and client:
    - `onSpectrum(fn) -> unsubscribe`, `notify(text, kind?, ms?)`,
      `handleMessage(msg)`, `resetState()`.
    - `class LinkClient { start(url?) stop() send(msg) login(password, label, takeover?) logout() tune(changes) reconnectSource() }`,
      exported as the singleton `link`.
  - `view.ts` (per-viewer preferences):
    - `type ScaleOverride = { mode: 'auto' } | { mode: 'manual'; low: number; high: number }`
    - the stores `scaleOverride` and `tuneChannel`.

- [ ] **Step 1: Write the failing tests**

`src/lib/link.test.ts`:

```ts
import { get } from 'svelte/store';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  FRAME_LOG_MAX, frameLog, frozen, handleMessage, history, iqSnaps, metrics, onSpectrum, resetState, role, status, tuning,
} from './link';
import type { RecordMsg, SpectrumMsg } from './types';

const record = (type: string, fields: Record<string, unknown>, text = type): RecordMsg => ({
  type: 'record', text,
  record: { t: 1, type, seq: 1, flags: 1, synthetic: true, fields, raw: null },
});
const spectrum: SpectrumMsg = {
  type: 'spectrum', channel: 'A', row: 0, t_us: 0, f0_hz: 50000, bin_hz: 390.625, bins: 2, db10: [-1000, -500],
  low: -110, high: -45, synthetic: true,
};

describe('handleMessage', () => {
  beforeEach(() => resetState());

  it('stores hello, role and tuning', () => {
    handleMessage({
      type: 'hello', server_version: '0.1.0', protocol_version: 2,
      source: { kind: 'sim', state: 'running', detail: '', responds_to_tuning: true },
      role: { type: 'role', role: 'viewer', admin: null, can_admin: true, reason: 'connect' },
      tuning: { type: 'tuning', state: {} as never, derived: { lo_hz: 441.38e6 } as never },
    });
    expect(get(role)?.role).toBe('viewer');
    expect(get(tuning)?.derived.lo_hz).toBe(441.38e6);
  });

  it('routes records into stores and history', () => {
    handleMessage(record('STATUS', { version: 2 }));
    handleMessage(record('CHAN_METRICS', { channel: 'B', rssi_dbm: -80, snr_db: 30 }));
    handleMessage(record('IQ_SNAPSHOT', { channel: 'A', iq: [[1, 2]] }));
    expect(get(status)?.fields.version).toBe(2);
    expect(get(metrics).B?.fields.rssi_dbm).toBe(-80);
    expect(history.B.rssi.values()).toEqual([-80]);
    expect(get(iqSnaps).A).toEqual([[[1, 2]]]);
  });

  it('bounds the frame log, newest first', () => {
    for (let i = 0; i < FRAME_LOG_MAX + 5; i++) handleMessage(record('CHAN_FRAME', { channel: 'A' }, `f${i}`));
    const log = get(frameLog);
    expect(log.length).toBe(FRAME_LOG_MAX);
    expect(log[0]).toBe(`f${FRAME_LOG_MAX + 4}`);
  });

  it('delivers spectrum rows to listeners and honours freeze', () => {
    const rows: SpectrumMsg[] = [];
    const off = onSpectrum((m) => rows.push(m));
    handleMessage(spectrum);
    frozen.set(true);
    handleMessage(spectrum);
    handleMessage(record('STATUS', { version: 9 }));
    off();
    expect(rows.length).toBe(1);
    expect(get(status)).toBeNull();
  });
});
```

Run: `npm test`
Expected: FAIL (module `./link` not found).

- [ ] **Step 2: Implement `types.ts`**

```ts
export type Channel = 'A' | 'B';
export type Role = 'viewer' | 'admin';
export type Injection = 'low' | 'high';

export interface TuningState {
  carrier_hz: number; injection: Injection; target_if_hz: number; window_hz: number;
  ref_hz: number; r_div: number; n_int: number; frac: number; mod: number; out_div: number;
  vco_min_hz: number; vco_max_hz: number; nco_hz: number; fs_hz: number; filter_hz: number;
}
export type TuningChanges = Partial<TuningState> & { lo_hz?: number };
export interface Derived {
  pfd_hz: number; vco_hz: number; lo_hz: number; lo_step_hz: number; expected_if_hz: number;
  image_hz: number; nco_ftw: number; nco_resolution_hz: number; warnings: string[];
}
export interface AdminInfo { label: string; since: number }
export interface SourceState {
  kind: 'serial' | 'replay' | 'sim' | 'none'; state: string; detail: string; responds_to_tuning: boolean;
}
export interface RecordJson {
  t: number; type: string; seq: number; flags: number; synthetic: boolean;
  // Field names follow tools/sdr_cli/protocol.py SCHEMAS after unit conversion.
  fields: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  raw: string | null;
}

export interface TuningMsg { type: 'tuning'; state: TuningState; derived: Derived }
export interface RoleMsg {
  type: 'role'; role: Role; admin: AdminInfo | null; can_admin: boolean; reason: string; token?: string; by?: string;
}
export interface HelloMsg {
  type: 'hello'; server_version: string; protocol_version: number; source: SourceState; role: RoleMsg; tuning: TuningMsg;
}
export interface RecordMsg { type: 'record'; record: RecordJson; text: string }
export interface SpectrumMsg {
  type: 'spectrum'; channel: Channel; row: number; t_us: number; f0_hz: number; bin_hz: number; bins: number;
  db10: number[]; low: number; high: number; synthetic: boolean;
}
export interface StatsMsg {
  type: 'stats'; byte_rate: number; rates: Record<string, number>; source: SourceState;
  decoder: { bytes: number; messages: number; crc_errors: number; cobs_errors: number; length_errors: number;
    resync_bytes: number; seq_gaps: number; synthetic: number; by_type: Record<string, number> };
}
export interface TakeoverMsg { type: 'takeover_required'; held_by: string; since: number }
export interface ErrorMsg { type: 'error'; code: string; text: string }
export type ServerMsg = HelloMsg | RecordMsg | SpectrumMsg | StatsMsg | TuningMsg | RoleMsg | TakeoverMsg | ErrorMsg
  | { type: 'pong' };

export type ClientMsg =
  | { type: 'login'; password: string; label: string; takeover: boolean }
  | { type: 'resume'; token: string }
  | { type: 'logout' }
  | { type: 'tune'; changes: TuningChanges }
  | { type: 'reconnect_source' }
  | { type: 'ping' };
```

- [ ] **Step 3: Implement `link.ts` and `view.ts`**

`src/lib/link.ts`:

```ts
/** The one WebSocket connection and the stores every component reads. */
import { get, writable } from 'svelte/store';
import { Ring } from './ring';
import { createCoalescer } from './throttle';
import type {
  Channel, ClientMsg, HelloMsg, RecordJson, RecordMsg, RoleMsg, ServerMsg, SpectrumMsg, StatsMsg, TakeoverMsg,
  TuningChanges, TuningMsg,
} from './types';

export interface Notice { id: number; text: string; kind: 'info' | 'warn' }

export const HISTORY = 300;              // 30 s of CHAN_METRICS at 10 Hz
export const FRAME_LOG_MAX = 200;
const TOKEN_KEY = 'sdr.adminToken';

export const connection = writable<'connecting' | 'open' | 'closed'>('connecting');
export const hello = writable<HelloMsg | null>(null);
export const role = writable<RoleMsg | null>(null);
export const tuning = writable<TuningMsg | null>(null);
export const stats = writable<StatsMsg | null>(null);
export const status = writable<RecordJson | null>(null);
export const linkStats = writable<RecordJson | null>(null);
export const best = writable<RecordJson | null>(null);
export const metrics = writable<Partial<Record<Channel, RecordJson>>>({});
export const iqSnaps = writable<Partial<Record<Channel, [number, number][][]>>>({});
export const frameLog = writable<string[]>([]);
export const takeover = writable<TakeoverMsg | null>(null);
export const notices = writable<Notice[]>([]);
export const frozen = writable(false);
export const synthetic = writable(false);
export const history: Record<Channel, { rssi: Ring; snr: Ring }> = {
  A: { rssi: new Ring(HISTORY), snr: new Ring(HISTORY) },
  B: { rssi: new Ring(HISTORY), snr: new Ring(HISTORY) },
};
export const historyVersion = writable(0);

const spectrumListeners = new Set<(m: SpectrumMsg) => void>();
export function onSpectrum(fn: (m: SpectrumMsg) => void): () => void {
  spectrumListeners.add(fn);
  return () => spectrumListeners.delete(fn);
}

let noticeId = 0;
export function notify(text: string, kind: Notice['kind'] = 'info', ms = 6000): void {
  const id = ++noticeId;
  notices.update((n) => [...n, { id, text, kind }]);
  setTimeout(() => notices.update((n) => n.filter((x) => x.id !== id)), ms);
}

function saveToken(token: string) {
  try { sessionStorage.setItem(TOKEN_KEY, token); } catch { /* no session storage */ }
}
function loadToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function clearToken() {
  try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* no session storage */ }
}

function applyRecord(msg: RecordMsg): void {
  const r = msg.record;
  synthetic.set(r.synthetic);
  switch (r.type) {
    case 'STATUS': status.set(r); break;
    case 'LINK_STATS': linkStats.set(r); break;
    case 'BEST_TELEM': best.set(r); break;
    case 'CHAN_METRICS': {
      const ch = r.fields.channel as Channel;
      metrics.update((m) => ({ ...m, [ch]: r }));
      if (history[ch]) {
        history[ch].rssi.push(r.fields.rssi_dbm);
        history[ch].snr.push(r.fields.snr_db);
        historyVersion.update((v) => v + 1);
      }
      break;
    }
    case 'IQ_SNAPSHOT': {
      const ch = r.fields.channel as Channel;
      iqSnaps.update((s) => ({ ...s, [ch]: [...(s[ch] ?? []), r.fields.iq].slice(-4) }));
      break;
    }
    case 'CHAN_FRAME': frameLog.update((l) => [msg.text, ...l].slice(0, FRAME_LOG_MAX)); break;
  }
}

export function handleMessage(msg: ServerMsg): void {
  switch (msg.type) {
    case 'hello': hello.set(msg); role.set(msg.role); tuning.set(msg.tuning); break;
    case 'tuning': tuning.set(msg); break;
    case 'stats': stats.set(msg); break;
    case 'role':
      role.set(msg);
      if (msg.token) saveToken(msg.token);
      else if (msg.role === 'viewer') clearToken();
      if (msg.reason === 'taken_over') notify(`${msg.by ?? 'Someone'} took over Admin. You are now a Viewer.`, 'warn', 10000);
      break;
    case 'takeover_required': takeover.set(msg); break;
    case 'error': notify(msg.text, 'warn'); break;
    case 'spectrum':
      if (get(frozen)) return;
      synthetic.set(msg.synthetic);
      for (const fn of spectrumListeners) fn(msg);
      break;
    case 'record':
      if (!get(frozen)) applyRecord(msg);
      break;
  }
}

/** Test helper: back to a fresh page state. */
export function resetState(): void {
  [hello, role, tuning, stats, status, linkStats, best, takeover].forEach((s) => s.set(null));
  metrics.set({});
  iqSnaps.set({});
  frameLog.set([]);
  frozen.set(false);
  synthetic.set(false);
  for (const ch of ['A', 'B'] as Channel[]) { history[ch].rssi.clear(); history[ch].snr.clear(); }
}

export function defaultUrl(loc: Location = window.location): string {
  return `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}/ws`;
}

export class LinkClient {
  private ws: WebSocket | null = null;
  private retryMs = 500;
  private stopped = true;
  private url = '';
  private tuner = createCoalescer<TuningChanges>((changes) => this.send({ type: 'tune', changes }));

  start(url = defaultUrl()): void {
    this.url = url;
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    this.ws?.close();
  }

  private open(): void {
    connection.set('connecting');
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      connection.set('open');
      this.retryMs = 500;
      const token = loadToken();
      if (token) this.send({ type: 'resume', token });
    };
    ws.onmessage = (e) => {
      try {
        handleMessage(JSON.parse(e.data as string) as ServerMsg);
      } catch (err) {
        console.error('Unreadable server message', err);
      }
    };
    ws.onclose = () => {
      connection.set('closed');
      if (this.stopped) return;
      setTimeout(() => this.open(), this.retryMs);
      this.retryMs = Math.min(8000, this.retryMs * 2);
    };
  }

  send(msg: ClientMsg): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  login(password: string, label: string, takeover = false): void {
    this.send({ type: 'login', password, label, takeover });
  }

  logout(): void {
    clearToken();
    this.send({ type: 'logout' });
  }

  tune(changes: TuningChanges): void {
    this.tuner.push(changes);
  }

  reconnectSource(): void {
    this.send({ type: 'reconnect_source' });
  }
}

export const link = new LinkClient();
```

`src/lib/view.ts`:

```ts
/** Per-viewer display preferences (never sent to the server). */
import { writable } from 'svelte/store';
import type { Channel } from './types';

export type ScaleOverride = { mode: 'auto' } | { mode: 'manual'; low: number; high: number };

export const scaleOverride = writable<ScaleOverride>({ mode: 'auto' });
export const tuneChannel = writable<Channel>('A');
```

- [ ] **Step 4: Verify**

Run: `npm test && npm run check`
Expected: all PASS and `0 errors`.

- [ ] **Step 5: Commit**

```bash
git add tools/sdr_web/src/lib/types.ts tools/sdr_web/src/lib/link.ts tools/sdr_web/src/lib/view.ts tools/sdr_web/src/lib/link.test.ts
git commit -m "Add GUI WebSocket client, message types and stores" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Canvas drawing, shared components, and the app shell

**Files:**
- Create: `src/lib/draw.ts`
- Create: `src/components/Panel.svelte`, `NumberField.svelte`, `SelectField.svelte`, `Segmented.svelte`, `StatusBar.svelte`, `RoleMenu.svelte`, `Notices.svelte`
- Create: `src/pages/Tune.svelte` and `src/pages/Telemetry.svelte`, as placeholders filled in Tasks 13–14
- Modify: `src/App.svelte` (replace the temporary shell)

**Interfaces:**
- Consumes: the stores and `link` (Task 9), and `axis`/`format` (Task 8).
- Produces:
  - `draw.ts`:
    - `interface Overlay { band?: [number, number]; at?: number; colorVar: string; alpha?: number; label?: string; labelBottom?: boolean; dash?: number[]; width?: number; onFall?: boolean }`
    - Canvas setup: `cssVar(name)`, `withAlpha(color, a)`, `fitCanvas(cv) -> { ctx, w, h }`.
    - Chart layers: `drawDbGrid(ctx, a, top, bot, low, high)`, `drawBands(ctx, a, top, bot, overlays)`,
      `drawLines(ctx, a, top, bot, overlays, labels=true)`,
      `drawFreqTicks(ctx, a, y, step, fmt, unit)`,
      `drawTrace(ctx, top, bot, row, low, high, colorVar, toX)`.
    - Plots: `drawConstellation(ctx, size, snaps, colorVar)`,
      `drawSparkline(ctx, w, h, values, colorVar, floor, capacity)`, `hatch(ctx, x0, x1, top, bot, color)`.
  - Components and their props:
    - `Panel {title, sub?, swatch?, actions?, children, class?}`
    - `NumberField {id, label, value, scale?, digits?, step?, disabled?, oncommit}`
    - `SelectField {id, label, value, options, disabled?, oncommit}`
    - `Segmented<T> {label, options, value, disabled?, onselect}`
    - `StatusBar`, `RoleMenu`, and `Notices` take no props.

- [ ] **Step 1: Implement `draw.ts`**

```ts
/** Canvas drawing shared by the waterfall, frequency plan, constellation and sparklines. */
import { type Axis, ticks, xOf } from './axis';

export interface Overlay {
  band?: [number, number]; at?: number; colorVar: string; alpha?: number;
  label?: string; labelBottom?: boolean; dash?: number[]; width?: number; onFall?: boolean;
}

const MONO = '11px "JetBrains Mono", ui-monospace, monospace';
const LABEL = '600 11px "Jost", system-ui, sans-serif';

export const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** '#rrggbb' + alpha → '#rrggbbaa'. */
export function withAlpha(color: string, a: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return color;
  return color + Math.round(Math.min(1, Math.max(0, a)) * 255).toString(16).padStart(2, '0');
}

export function fitCanvas(cv: HTMLCanvasElement): { ctx: CanvasRenderingContext2D; w: number; h: number } {
  const r = window.devicePixelRatio || 1;
  const w = cv.clientWidth;
  const h = cv.clientHeight;
  const W = Math.max(1, Math.round(w * r));
  const H = Math.max(1, Math.round(h * r));
  if (cv.width !== W || cv.height !== H) {
    cv.width = W;
    cv.height = H;
  }
  const ctx = cv.getContext('2d')!;
  ctx.setTransform(r, 0, 0, r, 0, 0);
  return { ctx, w, h };
}

export function drawDbGrid(ctx: CanvasRenderingContext2D, a: Axis, top: number, bot: number, low: number, high: number) {
  const y = (v: number) => bot - ((v - low) / (high - low)) * (bot - top);
  ctx.font = MONO;
  ctx.textAlign = 'right';
  ctx.lineWidth = 1;
  for (let v = Math.ceil(low / 10) * 10; v <= high; v += 10) {
    const yy = Math.round(y(v)) + 0.5;
    ctx.strokeStyle = cssVar('--line');
    ctx.beginPath();
    ctx.moveTo(a.left, yy);
    ctx.lineTo(a.width - a.right, yy);
    ctx.stroke();
    ctx.fillStyle = cssVar('--faint');
    ctx.fillText(String(v), a.left - 6, yy + 4);
  }
}

export function drawBands(ctx: CanvasRenderingContext2D, a: Axis, top: number, bot: number, overlays: Overlay[]) {
  for (const o of overlays) {
    if (!o.band) continue;
    ctx.fillStyle = withAlpha(cssVar(o.colorVar), o.alpha ?? 0.12);
    const x0 = xOf(a, o.band[0]);
    ctx.fillRect(x0, top, xOf(a, o.band[1]) - x0, bot - top);
  }
}

export function drawLines(ctx: CanvasRenderingContext2D, a: Axis, top: number, bot: number, overlays: Overlay[], labels = true) {
  ctx.font = LABEL;
  for (const o of overlays) {
    if (o.at === undefined) continue;
    const x = Math.round(xOf(a, o.at)) + 0.5;
    const color = cssVar(o.colorVar);
    ctx.strokeStyle = color;
    ctx.lineWidth = o.width ?? 1;
    ctx.setLineDash(o.dash ?? []);
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bot);
    ctx.stroke();
    ctx.setLineDash([]);
    if (labels && o.label) {
      const right = x > a.width - 90;
      ctx.fillStyle = color;
      ctx.textAlign = right ? 'right' : 'left';
      ctx.fillText(o.label.toUpperCase(), x + (right ? -4 : 4), o.labelBottom ? bot - 5 : top + 11);
    }
  }
}

export function drawFreqTicks(
  ctx: CanvasRenderingContext2D, a: Axis, y: number, step: number, fmt: (f: number) => string, unit: string,
) {
  ctx.font = MONO;
  ctx.fillStyle = cssVar('--muted');
  ctx.textAlign = 'center';
  for (const f of ticks(a.f0, a.f1, step)) ctx.fillText(fmt(f), xOf(a, f), y);
  ctx.textAlign = 'left';
  ctx.fillStyle = cssVar('--faint');
  ctx.fillText(unit, 4, y);
}

export interface TraceRow { f0_hz: number; bin_hz: number; db10: number[] }

/** Spectrum trace with area fill. `toX` maps an IF frequency to a pixel x. */
export function drawTrace(
  ctx: CanvasRenderingContext2D, top: number, bot: number, row: TraceRow, low: number, high: number,
  colorVar: string, toX: (f: number) => number,
) {
  const y = (db10: number) => bot - ((Math.min(high, Math.max(low, db10 / 10)) - low) / (high - low)) * (bot - top);
  const x = (k: number) => toX(row.f0_hz + k * row.bin_hz);
  const color = cssVar(colorVar);
  ctx.beginPath();
  ctx.moveTo(x(0), bot);
  row.db10.forEach((v, k) => ctx.lineTo(x(k), y(v)));
  ctx.lineTo(x(row.db10.length - 1), bot);
  ctx.closePath();
  ctx.fillStyle = withAlpha(color, 0.15);
  ctx.fill();
  ctx.beginPath();
  row.db10.forEach((v, k) => (k ? ctx.lineTo(x(k), y(v)) : ctx.moveTo(x(k), y(v))));
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

export function hatch(ctx: CanvasRenderingContext2D, x0: number, x1: number, top: number, bot: number, color: string) {
  ctx.save();
  ctx.beginPath();
  ctx.rect(x0, top, x1 - x0, bot - top);
  ctx.clip();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  for (let x = x0 - (bot - top); x < x1; x += 7) {
    ctx.beginPath();
    ctx.moveTo(x, bot);
    ctx.lineTo(x + (bot - top), top);
    ctx.stroke();
  }
  ctx.restore();
}

/** I/Q scatter: newest snapshot solid, older ones faded (full scale ±32767). */
export function drawConstellation(ctx: CanvasRenderingContext2D, size: number, snaps: [number, number][][], colorVar: string) {
  const c = size / 2;
  const R = size * 0.42;
  const color = cssVar(colorVar);
  ctx.clearRect(0, 0, size, size);
  ctx.strokeStyle = cssVar('--line');
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(c, 4); ctx.lineTo(c, size - 4); ctx.moveTo(4, c); ctx.lineTo(size - 4, c);
  ctx.stroke();
  ctx.setLineDash([2, 4]);
  ctx.beginPath();
  ctx.arc(c, c, R, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  snaps.forEach((snap, j) => {
    ctx.fillStyle = withAlpha(color, j === snaps.length - 1 ? 0.95 : 0.3);
    for (const [i, q] of snap) {
      ctx.beginPath();
      ctx.arc(c + (i / 32767) * R, c - (q / 32767) * R, 2.2, 0, Math.PI * 2);
      ctx.fill();
    }
  });
  ctx.fillStyle = cssVar('--faint');
  ctx.font = MONO;
  ctx.textAlign = 'left';
  ctx.fillText('I', size - 10, c - 4);
  ctx.fillText('Q', c + 4, 12);
}

/** History line with area fill and an emphasized latest point. The y range covers at least `floor`. */
export function drawSparkline(
  ctx: CanvasRenderingContext2D, w: number, h: number, values: readonly number[], colorVar: string,
  floor: [number, number], capacity: number,
) {
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = cssVar('--line');
  ctx.beginPath();
  ctx.moveTo(0, h - 0.5);
  ctx.lineTo(w, h - 0.5);
  ctx.stroke();
  if (values.length < 2) return;
  const lo = Math.min(floor[0], ...values);
  const hi = Math.max(floor[1], ...values);
  const off = capacity - values.length;
  const x = (i: number) => ((i + off) / (capacity - 1)) * (w - 8);
  const y = (v: number) => h - 3 - ((v - lo) / (hi - lo)) * (h - 8);
  const color = cssVar(colorVar);
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.lineTo(x(values.length - 1), h);
  ctx.lineTo(x(0), h);
  ctx.closePath();
  ctx.fillStyle = withAlpha(color, 0.14);
  ctx.fill();
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
  const ex = x(values.length - 1);
  const ey = y(values[values.length - 1]);
  ctx.fillStyle = cssVar('--panel');
  ctx.beginPath(); ctx.arc(ex, ey, 5, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.arc(ex, ey, 3.5, 0, Math.PI * 2); ctx.fill();
}
```

- [ ] **Step 2: Implement the small shared components**

`src/components/Panel.svelte`:

```svelte
<script lang="ts">
  import type { Snippet } from 'svelte';

  // `swatch` is a CSS color token (e.g. '--ch-a') shown before the title to identify a channel.
  let { title, sub = '', swatch = '', actions, children, class: cls = '' }:
    { title: string; sub?: string; swatch?: string; actions?: Snippet; children: Snippet; class?: string } = $props();
</script>

<section class="panel {cls}" aria-label={title}>
  <header class="ph">
    {#if swatch}<span class="swatch" style="background: var({swatch})" aria-hidden="true"></span>{/if}
    <h2>{title}</h2>
    {#if sub}<span class="sub">{sub}</span>{/if}
    {#if actions}<div class="right">{@render actions()}</div>{/if}
  </header>
  {@render children()}
</section>

<style>
  .swatch { width: 10px; height: 10px; border-radius: 2px; align-self: center; }
</style>
```

`src/components/NumberField.svelte`:

```svelte
<script lang="ts">
  // Shows `value / scale`; commits `input * scale` on change (Enter or blur). The server validates.
  let { id, label, value, scale = 1, digits = 0, step = 1, disabled = false, oncommit }:
    { id: string; label: string; value: number; scale?: number; digits?: number; step?: number; disabled?: boolean;
      oncommit: (v: number) => void } = $props();

  function commit(e: Event & { currentTarget: HTMLInputElement }) {
    const v = e.currentTarget.valueAsNumber;
    if (Number.isFinite(v)) oncommit(v * scale);
    else e.currentTarget.value = (value / scale).toFixed(digits);
  }
</script>

<div class="field">
  <label for={id}>{label}</label>
  <input {id} type="number" {step} {disabled} value={(value / scale).toFixed(digits)} onchange={commit} />
</div>
```

`src/components/SelectField.svelte`:

```svelte
<script lang="ts">
  let { id, label, value, options, disabled = false, oncommit }:
    { id: string; label: string; value: number; options: readonly number[]; disabled?: boolean;
      oncommit: (v: number) => void } = $props();
</script>

<div class="field">
  <label for={id}>{label}</label>
  <select {id} {disabled} value={String(value)} onchange={(e) => oncommit(Number(e.currentTarget.value))}>
    {#each options as o (o)}<option value={String(o)}>{o}</option>{/each}
  </select>
</div>
```

`src/components/Segmented.svelte`:

```svelte
<script lang="ts" generics="T extends string">
  let { label, options, value, disabled = false, onselect }:
    { label: string; options: { value: T; text: string }[]; value: T; disabled?: boolean; onselect: (v: T) => void } =
    $props();
</script>

<div class="seg" role="group" aria-label={label}>
  {#each options as o (o.value)}
    <button type="button" aria-pressed={o.value === value} {disabled} onclick={() => onselect(o.value)}>{o.text}</button>
  {/each}
</div>
```

`src/components/Notices.svelte`:

```svelte
<script lang="ts">
  import { notices } from '../lib/link';
</script>

<div class="notices" aria-live="polite">
  {#each $notices as n (n.id)}
    <div class="notice panel" class:warn={n.kind === 'warn'}>{n.text}</div>
  {/each}
</div>

<style>
  .notices { position: fixed; right: 16px; bottom: calc(16px + env(safe-area-inset-bottom, 0px)); display: grid; gap: 8px; z-index: 20; max-width: min(420px, calc(100vw - 32px)); }
  .notice { padding: 10px 14px; font-size: 14px; border-left: 3px solid var(--muted); }
  .notice.warn { border-left-color: var(--warn); }
</style>
```

- [ ] **Step 3: Implement `StatusBar.svelte`**

```svelte
<script lang="ts">
  import { connection, hello, link, role, stats, status, synthetic } from '../lib/link';

  const src = $derived($stats?.source ?? $hello?.source);
  const dot = $derived(src?.state === 'running' ? 'good' : src?.state === 'down' ? 'bad' : 'warn');
  const kB = $derived((($stats?.byte_rate ?? 0) / 1000).toFixed(1));
  const errors = $derived($stats ? $stats.decoder.crc_errors + $stats.decoder.cobs_errors + $stats.decoder.length_errors : 0);
  const versionMismatch = $derived(!!$status && !!$hello && $status.fields.version !== $hello.protocol_version);
  const canReconnect = $derived($role?.role === 'admin' && (src?.state === 'down' || src?.state === 'ended'));
</script>

{#if $synthetic}
  <span class="pill synth" title="Every message is flagged SYNTHETIC by stand-in producers, not RF measurements">SIMULATED</span>
{/if}
<span class="pill" title={src?.detail ?? ''}><span class="dot {dot}"></span>{src ? `${src.kind} · ${src.state}` : 'no source'}</span>
<span class="pill">{kB} kB/s · {$stats?.decoder.seq_gaps ?? 0} gaps · {errors} err</span>
{#if versionMismatch}
  <span class="chip bad">FPGA protocol v{$status?.fields.version}: rebuild and program</span>
{/if}
{#if $connection !== 'open'}<span class="chip warn">Disconnected, retrying</span>{/if}
{#if canReconnect}<button class="btn" onclick={() => link.reconnectSource()}>Reconnect</button>{/if}
```

- [ ] **Step 4: Implement `RoleMenu.svelte`**

```svelte
<script lang="ts">
  import { link, role, takeover } from '../lib/link';
  import { clockTime } from '../lib/format';

  const LABEL_KEY = 'sdr.adminLabel';
  const loadLabel = () => { try { return localStorage.getItem(LABEL_KEY) ?? ''; } catch { return ''; } };
  const saveLabel = (v: string) => { try { localStorage.setItem(LABEL_KEY, v); } catch { /* optional */ } };

  let open = $state(false);
  let label = $state(loadLabel());
  let password = $state('');
  let waiting = $state(false);
  const isAdmin = $derived($role?.role === 'admin');

  $effect(() => { if ($takeover) open = true; });
  $effect(() => { if (waiting && isAdmin) { open = false; waiting = false; password = ''; } });

  function submit(e: SubmitEvent) {
    e.preventDefault();
    saveLabel(label);
    waiting = true;
    link.login(password, label);
  }
  function confirmTakeover() {
    waiting = true;
    link.login(password, label, true);
    takeover.set(null);
  }
  function cancelTakeover() {
    takeover.set(null);
    password = '';
    open = false;
  }
</script>

<div class="role">
  <button class="btn" class:admin={isAdmin} aria-expanded={open} onclick={() => (open = !open)}>
    {isAdmin ? 'Admin' : 'Viewer'}{#if !isAdmin && $role?.admin}<span class="muted"> · Admin: {$role.admin.label}</span>{/if}
  </button>
  {#if open}
    <div class="pop panel pb stack" role="dialog" aria-label="Role">
      {#if isAdmin && $role?.admin}
        <p>You are Admin as <b>{$role.admin.label}</b> since {clockTime($role.admin.since)}.</p>
        <button class="btn" onclick={() => { link.logout(); open = false; }}>Switch to Viewer</button>
      {:else if $takeover}
        <p>Admin is held by <b>{$takeover.held_by}</b> since {clockTime($takeover.since)}. Take over? They will become a Viewer.</p>
        <div class="row">
          <button class="btn primary" onclick={confirmTakeover}>Take over</button>
          <button class="btn" onclick={cancelTakeover}>Cancel</button>
        </div>
      {:else if $role && !$role.can_admin}
        <p class="note">No Admin password is set on the server, so only the server machine can become Admin.
          Set one there with <code>./sdr setup --gui-password</code>.</p>
      {:else}
        <form class="stack" onsubmit={submit}>
          <label for="role-label">Your name</label>
          <input id="role-label" bind:value={label} maxlength="32" autocomplete="nickname" placeholder="groundstation" />
          <label for="role-password">Admin password</label>
          <input id="role-password" type="password" bind:value={password} autocomplete="current-password" />
          <button class="btn primary" type="submit">Log in as Admin</button>
        </form>
      {/if}
    </div>
  {/if}
</div>

<style>
  .role { position: relative; }
  .btn.admin { background: var(--brand); border-color: var(--brand); color: #fff; }
  .pop { position: absolute; right: 0; top: calc(100% + 6px); width: min(320px, calc(100vw - 32px)); z-index: 15; box-shadow: 0 8px 24px #0006; }
  .pop p { margin: 0; }
  input { background: var(--bg); border: 1px solid var(--line-2); border-radius: 4px; padding: 5px 8px; }
  label { font-size: 13px; color: var(--muted); }
</style>
```

- [ ] **Step 5: Page placeholders and the real App shell**

`src/pages/Tune.svelte` (replaced in Task 13):

```svelte
<p class="note">Tune page: see Task 13.</p>
```

`src/pages/Telemetry.svelte` (replaced in Task 14):

```svelte
<p class="note">Telemetry page: see Task 14.</p>
```

`src/App.svelte`:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import logoLight from './assets/space-raiders-logo.png';
  import logoDark from './assets/space-raiders-logo-on-dark.png';
  import Notices from './components/Notices.svelte';
  import RoleMenu from './components/RoleMenu.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import { frozen, link } from './lib/link';
  import { type ThemeChoice, applyTheme, loadTheme, nextTheme } from './lib/theme';
  import Telemetry from './pages/Telemetry.svelte';
  import Tune from './pages/Tune.svelte';

  const PAGES = [{ id: 'tune', text: 'Tune' }, { id: 'telemetry', text: 'Telemetry' }] as const;
  type PageId = (typeof PAGES)[number]['id'];
  const fromHash = (): PageId => (location.hash === '#telemetry' ? 'telemetry' : 'tune');

  let page = $state<PageId>(fromHash());
  let theme = $state<ThemeChoice>(loadTheme());

  onMount(() => {
    link.start();
    const onHash = () => (page = fromHash());
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.code === 'Space' && !t.closest('input, select, textarea, button, [role="spinbutton"]')) {
        e.preventDefault();
        frozen.update((f) => !f);
      }
    };
    addEventListener('hashchange', onHash);
    addEventListener('keydown', onKey);
    return () => {
      removeEventListener('hashchange', onHash);
      removeEventListener('keydown', onKey);
      link.stop();
    };
  });

  function go(id: PageId) {
    location.hash = id;
    page = id;
  }
  function cycleTheme() {
    theme = nextTheme(theme);
    applyTheme(theme);
  }
</script>

<header class="top">
  <a class="brand" href="#tune" onclick={() => go('tune')} aria-label="Space Raiders SDR home">
    <img class="logo light" src={logoLight} alt="Space Raiders" />
    <img class="logo dark" src={logoDark} alt="Space Raiders" />
    <span class="product">SDR</span>
  </a>
  <nav class="tabs" aria-label="Pages">
    {#each PAGES as p (p.id)}
      <button aria-current={page === p.id ? 'page' : undefined} onclick={() => go(p.id)}>{p.text}</button>
    {/each}
  </nav>
  <div class="status">
    <StatusBar />
    <button class="btn" aria-pressed={$frozen} onclick={() => frozen.update((f) => !f)}
      title="Freeze the display (Space). Receiving continues.">{$frozen ? 'Frozen' : 'Freeze'}</button>
    <button class="btn" onclick={cycleTheme} title="Theme: follow the system, dark, or light">
      {theme === 'system' ? 'Auto' : theme === 'dark' ? 'Dark' : 'Light'}
    </button>
    <RoleMenu />
  </div>
</header>

<main>
  {#if page === 'tune'}<Tune />{:else}<Telemetry />{/if}
</main>
<Notices />

<style>
  .top { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 10; display: flex; flex-wrap: wrap; align-items: center;
    gap: 10px 20px; padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }
  .brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: inherit; }
  .logo { height: 22px; width: auto; }
  .logo.dark { display: var(--logo-dark); }
  .logo.light { display: var(--logo-light); }
  .product { font: 600 13px var(--f-ui); letter-spacing: 0.2em; color: var(--brand); border-left: 1px solid var(--line-2); padding-left: 10px; }
  .tabs { display: flex; gap: 2px; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 2px; }
  .tabs button { border: 0; background: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font: 600 13px var(--f-ui);
    letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
  .tabs button[aria-current='page'] { background: var(--panel-2); color: var(--fg); box-shadow: inset 0 -2px 0 var(--brand); }
  .status { margin-left: auto; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  main { padding: 14px 16px 24px; }
  @media (max-width: 700px) { .status { margin-left: 0; } }
</style>
```

- [ ] **Step 6: Verify with the simulator**

Run:
- `cd tools/sdr_web && npm run check && npm test && npm run build`
- `cd ../.. && ./sdr gui --source sim`

Expected:
- `0 errors`, and the tests pass.
- The browser opens and shows:
  - the Space Raiders logo (white lettering in dark mode) with a red "SDR";
  - Tune/Telemetry tabs;
  - a SIMULATED pill and `sim · running` with a green dot;
  - a kB/s figure of about 11 or more;
  - a Viewer button.
- Theme button: it cycles Auto/Dark/Light and swaps the logo variant.
- Role → log in without a password: this works because you are on localhost and
  no password is set. The button turns red and reads "Admin".

Stop with Ctrl-C.

- [ ] **Step 7: Commit**

```bash
git add tools/sdr_web/src/lib/draw.ts tools/sdr_web/src/components/Panel.svelte tools/sdr_web/src/components/NumberField.svelte \
  tools/sdr_web/src/components/SelectField.svelte tools/sdr_web/src/components/Segmented.svelte \
  tools/sdr_web/src/components/StatusBar.svelte tools/sdr_web/src/components/RoleMenu.svelte \
  tools/sdr_web/src/components/Notices.svelte tools/sdr_web/src/pages/Tune.svelte tools/sdr_web/src/pages/Telemetry.svelte \
  tools/sdr_web/src/App.svelte
git commit -m "Add GUI app shell: branding, tabs, status bar, role menu, theme toggle" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Phase 4 — Tune page

The Tune page merges tuning and signal quality, as the user asked. It is a port
of the approved mockup's Tune view. Paths are relative to `tools/sdr_web/`.

### Task 11: Waterfall, frequency plan and tuning digits

**Files:**
- Create: `src/components/Waterfall.svelte`, `src/components/FreqPlan.svelte`, `src/components/TuningDigits.svelte`

**Interfaces:**
- Consumes:
  - `onSpectrum`, `scaleOverride`, and `WaterfallImage`;
  - the `draw.ts` functions and `Overlay`;
  - `makeAxis`, `xOf`, `ifToRf`, and `PAD`.
- Produces:
  - `Waterfall {channel, colorVar, overlays?, draggable?, ondrag?(deltaHz), ondragend?(), onrow?(SpectrumMsg), rows?}`
  - `FreqPlan {t: TuningMsg, row: SpectrumMsg | null, colorVar, disabled, ontune(loHz)}`
  - `TuningDigits {hz, stepHz, disabled?, onchange(hz)}`

- [ ] **Step 1: `Waterfall.svelte`**

```svelte
<script lang="ts">
  // Live IF spectrum trace over a scrolling waterfall for one channel.
  // Colours come from the server's auto scale unless the viewer chose a manual scale.
  import { onMount } from 'svelte';
  import { PAD, makeAxis, xOf } from '../lib/axis';
  import { type Overlay, cssVar, drawBands, drawDbGrid, drawFreqTicks, drawLines, drawTrace, fitCanvas } from '../lib/draw';
  import { onSpectrum } from '../lib/link';
  import type { Channel, SpectrumMsg } from '../lib/types';
  import { scaleOverride } from '../lib/view';
  import { WaterfallImage } from '../lib/waterfall';

  let { channel, colorVar, overlays = [], draggable = false, ondrag, ondragend, onrow, rows = 200 }: {
    channel: Channel; colorVar: string; overlays?: Overlay[]; draggable?: boolean;
    ondrag?: (deltaHz: number) => void; ondragend?: () => void; onrow?: (m: SpectrumMsg) => void; rows?: number;
  } = $props();

  let traceCv: HTMLCanvasElement;
  let fallCv: HTMLCanvasElement;
  let image: WaterfallImage | null = null;
  let last: SpectrumMsg | null = null;
  let dirty = true;
  let dragX: number | null = null;

  function limits(): [number, number] {
    const s = $scaleOverride;
    if (s.mode === 'manual') return [s.low, s.high];
    return last ? [last.low, last.high] : [-120, -60];
  }

  function axisFor(width: number) {
    if (!last) return makeAxis(0, 1, width);
    const f0 = last.f0_hz - last.bin_hz / 2;
    return makeAxis(f0, f0 + last.bins * last.bin_hz, width);
  }

  function draw() {
    const t = fitCanvas(traceCv);
    const a = axisFor(t.w);
    const [low, high] = limits();
    const top = 8;
    const bot = t.h - 18;
    t.ctx.clearRect(0, 0, t.w, t.h);
    if (last) {
      drawDbGrid(t.ctx, a, top, bot, low, high);
      drawBands(t.ctx, a, top, bot, overlays);
      drawTrace(t.ctx, top, bot, last, low, high, colorVar, (f) => xOf(a, f));
      drawLines(t.ctx, a, top, bot, overlays);
      drawFreqTicks(t.ctx, a, t.h - 4, 10e3, (f) => (f / 1e3).toFixed(0), 'kHz');
    } else {
      t.ctx.fillStyle = cssVar('--muted');
      t.ctx.font = '14px "Jost", system-ui, sans-serif';
      t.ctx.textAlign = 'center';
      t.ctx.fillText(`Waiting for channel ${channel} spectrum…`, t.w / 2, t.h / 2);
    }
    const f = fitCanvas(fallCv);
    f.ctx.fillStyle = cssVar('--wf-bg');
    f.ctx.fillRect(0, 0, f.w, f.h);
    if (image) {
      f.ctx.imageSmoothingEnabled = false;
      f.ctx.drawImage(image.canvas, PAD.left, 0, f.w - PAD.left - PAD.right, f.h);
    }
    if (last) drawLines(f.ctx, axisFor(f.w), 0, f.h, overlays.filter((o) => o.onFall), false);
  }

  $effect(() => {
    void channel;   // a new channel starts a fresh picture
    image = null;
    last = null;
    dirty = true;
  });
  $effect(() => {
    void overlays;
    void $scaleOverride;
    dirty = true;
  });

  onMount(() => {
    const off = onSpectrum((m) => {
      if (m.channel !== channel) return;
      if (!image || image.bins !== m.bins) image = new WaterfallImage(m.bins, rows);
      last = m;
      const [low, high] = limits();
      image.push(m.db10, low, high);
      dirty = true;
      onrow?.(m);
    });
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (dirty) {
        dirty = false;
        draw();
      }
    };
    raf = requestAnimationFrame(loop);
    const ro = new ResizeObserver(() => (dirty = true));
    ro.observe(traceCv);
    return () => {
      off();
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  });

  function down(e: PointerEvent) {
    if (!draggable) return;
    dragX = e.clientX;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent) {
    if (dragX === null || !last) return;
    const a = axisFor(traceCv.clientWidth);
    ondrag?.(((e.clientX - dragX) * (a.f1 - a.f0)) / (a.width - a.left - a.right));
    dragX = e.clientX;
  }
  function up() {
    if (dragX !== null) ondragend?.();
    dragX = null;
  }
</script>

<!-- Dragging is a pointer shortcut; the NCO field in the control rail is the keyboard path. -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="wf" class:drag={draggable} role="img" aria-label="Channel {channel} IF spectrum and waterfall"
  onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
  <canvas class="trace" bind:this={traceCv}></canvas>
  <canvas class="fall" bind:this={fallCv}></canvas>
</div>

<style>
  .wf { display: grid; }
  .trace { display: block; width: 100%; height: 130px; }
  .fall { display: block; width: 100%; height: 220px; }
  .drag { cursor: ew-resize; touch-action: none; }
</style>
```

- [ ] **Step 2: `FreqPlan.svelte`**

```svelte
<script lang="ts">
  // RF-domain frequency plan. Only the IF span the FPGA reports is measured and drawn as a trace;
  // everything else is hatched as "not observed". The image band is hatched in the "bad" colour.
  import { onMount } from 'svelte';
  import { ifToRf, makeAxis, xOf } from '../lib/axis';
  import { cssVar, drawFreqTicks, drawTrace, fitCanvas, hatch, withAlpha } from '../lib/draw';
  import { mhz } from '../lib/format';
  import type { SpectrumMsg, TuningMsg } from '../lib/types';
  import { scaleOverride } from '../lib/view';

  const SPAN_HZ = 300e3;            // shown either side of the nominal carrier
  const FSK_DEVIATION_HZ = 25e3;    // 2-GFSK deviation (module map)
  const LABEL = '600 11px "Jost", system-ui, sans-serif';

  let { t, row, colorVar, disabled, ontune }:
    { t: TuningMsg; row: SpectrumMsg | null; colorVar: string; disabled: boolean; ontune: (loHz: number) => void } =
    $props();

  let cv: HTMLCanvasElement;
  let dragX: number | null = null;
  let dragLo = 0;

  const axis = (width: number) => makeAxis(t.state.carrier_hz - SPAN_HZ, t.state.carrier_hz + SPAN_HZ, width);

  function draw() {
    if (!cv) return;
    const { ctx, w, h } = fitCanvas(cv);
    const s = t.state;
    const d = t.derived;
    const a = axis(w);
    const X = (f: number) => xOf(a, f);
    const rf = (f: number) => ifToRf(d.lo_hz, s.injection, f);
    const span = (f0: number, f1: number): [number, number] => {
      const p = rf(f0);
      const q = rf(f1);
      return [Math.min(p, q), Math.max(p, q)];
    };
    const top = 22;
    const bot = h - 20;
    const panel = cssVar('--panel');
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.beginPath();
    ctx.rect(a.left, 0, w - a.left - a.right, h);
    ctx.clip();

    hatch(ctx, a.left, w - a.right, top, bot, cssVar('--line'));
    const img: [number, number] = [d.image_hz - s.window_hz, d.image_hz + s.window_hz];
    ctx.fillStyle = panel;
    ctx.fillRect(X(img[0]), top, X(img[1]) - X(img[0]), bot - top);
    hatch(ctx, X(img[0]), X(img[1]), top, bot, withAlpha(cssVar('--bad'), 0.45));
    if (row) {
      const seen = span(row.f0_hz - row.bin_hz / 2, row.f0_hz + (row.bins - 0.5) * row.bin_hz);
      ctx.fillStyle = panel;
      ctx.fillRect(X(seen[0]), top, X(seen[1]) - X(seen[0]), bot - top);
    }
    const win = span(s.target_if_hz - s.window_hz, s.target_if_hz + s.window_hz);
    const ifColor = cssVar('--if');
    ctx.fillStyle = withAlpha(ifColor, 0.11);
    ctx.fillRect(X(win[0]), top, X(win[1]) - X(win[0]), bot - top);
    ctx.strokeStyle = withAlpha(ifColor, 0.55);
    ctx.lineWidth = 1;
    ctx.strokeRect(X(win[0]) + 0.5, top + 0.5, X(win[1]) - X(win[0]) - 1, bot - top - 1);
    if (row) {
      const sc = $scaleOverride;
      const [low, high] = sc.mode === 'manual' ? [sc.low, sc.high] : [row.low, row.high];
      drawTrace(ctx, top, bot, row, low, high, colorVar, (f) => X(rf(f)));
    }
    const fg = cssVar('--fg');
    const c = s.carrier_hz;
    ctx.fillStyle = withAlpha(fg, 0.08);
    ctx.fillRect(X(c - FSK_DEVIATION_HZ), top, X(c + FSK_DEVIATION_HZ) - X(c - FSK_DEVIATION_HZ), bot - top);
    ctx.strokeStyle = withAlpha(fg, 0.6);
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(Math.round(X(c)) + 0.5, top);
    ctx.lineTo(Math.round(X(c)) + 0.5, bot);
    ctx.stroke();
    ctx.setLineDash([]);
    const loColor = cssVar('--lo');
    const xl = Math.round(X(d.lo_hz)) + 0.5;
    ctx.strokeStyle = loColor;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(xl, top - 6);
    ctx.lineTo(xl, bot);
    ctx.stroke();
    ctx.lineWidth = 1;
    ctx.fillStyle = loColor;
    ctx.beginPath();
    ctx.moveTo(xl - 6, top - 12);
    ctx.lineTo(xl + 6, top - 12);
    ctx.lineTo(xl, top - 3);
    ctx.fill();
    ctx.restore();

    ctx.font = LABEL;
    ctx.textAlign = 'center';
    const clampX = (x: number) => Math.min(w - a.right - 34, Math.max(a.left + 34, x));
    const label = (text: string, x: number, y: number, color: string, boxed = false) => {
      const cx = clampX(x);
      if (boxed) {   // keeps the label readable where it sits over the trace
        const half = ctx.measureText(text).width / 2 + 4;
        ctx.fillStyle = panel;
        ctx.fillRect(cx - half, y - 11, half * 2, 15);
      }
      ctx.fillStyle = color;
      ctx.fillText(text, cx, y);
    };
    label('LO', xl + (xl > X(c) ? 14 : -14), top - 8, loColor);
    label('IMAGE', (X(img[0]) + X(img[1])) / 2, top - 8, cssVar('--bad'));
    label('IF WINDOW', (X(win[0]) + X(win[1])) / 2, top - 8, ifColor);
    label(`TX ${mhz(c, 3)}`, X(c), bot - 6, cssVar('--muted'), true);
    drawFreqTicks(ctx, a, h - 4, 100e3, (f) => (f / 1e6).toFixed(1), 'MHz');
  }

  $effect(() => {
    void t;
    void row;
    void $scaleOverride;
    draw();
  });

  onMount(() => {
    const wheel = (e: WheelEvent) => {
      if (disabled) return;
      e.preventDefault();
      ontune(t.derived.lo_hz + (e.deltaY < 0 ? 1 : -1) * Math.max(t.derived.lo_step_hz, 1e3));
    };
    cv.addEventListener('wheel', wheel, { passive: false });
    const ro = new ResizeObserver(draw);
    ro.observe(cv);
    return () => {
      cv.removeEventListener('wheel', wheel);
      ro.disconnect();
    };
  });

  function down(e: PointerEvent) {
    if (disabled) return;
    dragX = e.clientX;
    dragLo = t.derived.lo_hz;
    cv.setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent) {
    if (dragX === null) return;
    const a = axis(cv.clientWidth);
    dragLo += ((e.clientX - dragX) * (a.f1 - a.f0)) / (a.width - a.left - a.right);
    dragX = e.clientX;
    ontune(dragLo);
  }
  const up = () => (dragX = null);
</script>

<canvas bind:this={cv} class:drag={!disabled} aria-label="RF frequency plan: LO, IF window and image band"
  onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}></canvas>

<style>
  canvas { display: block; width: 100%; height: 170px; }
  .drag { cursor: ew-resize; touch-action: none; }
</style>
```

- [ ] **Step 3: `TuningDigits.svelte`**

```svelte
<script lang="ts">
  // SDR++-style frequency readout: scroll a digit, click its upper/lower half, or use ↑/↓ when focused.
  import { onMount } from 'svelte';

  let { hz, stepHz, disabled = false, onchange }:
    { hz: number; stepHz: number; disabled?: boolean; onchange: (hz: number) => void } = $props();

  const PLACES = [8, 7, 6, 5, 4, 3, 2, 1, 0];
  let pending = $state<number | null>(null);
  let box: HTMLDivElement;

  $effect(() => {
    void hz;          // a server update replaces local, not-yet-echoed edits
    pending = null;
  });
  const shown = $derived(pending ?? hz);
  const digits = $derived(String(Math.max(0, Math.round(shown))).padStart(9, '0').slice(-9).split(''));
  const lead = $derived(digits.findIndex((d) => d !== '0'));

  function bump(place: number, dir: number) {
    if (disabled) return;
    pending = shown + dir * Math.max(10 ** place, stepHz);
    onchange(pending);
  }
  function click(e: MouseEvent, place: number) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    bump(place, e.clientY < r.top + r.height / 2 ? 1 : -1);
  }
  function key(e: KeyboardEvent, place: number) {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    bump(place, e.key === 'ArrowUp' ? 1 : -1);
  }

  onMount(() => {
    const wheel = (e: WheelEvent) => {
      const el = (e.target as HTMLElement).closest<HTMLElement>('[data-place]');
      if (!el || disabled) return;
      e.preventDefault();
      bump(Number(el.dataset.place), e.deltaY < 0 ? 1 : -1);
    };
    box.addEventListener('wheel', wheel, { passive: false });
    return () => box.removeEventListener('wheel', wheel);
  });
</script>

<div class="digits" class:disabled bind:this={box}>
  {#each PLACES as place, i (place)}
    <span class="d" class:lead={lead < 0 || i < lead} data-place={place} role="spinbutton" tabindex={disabled ? -1 : 0}
      aria-label="LO digit for 10^{place} Hz" aria-valuenow={Number(digits[i])} aria-valuemin={0} aria-valuemax={9}
      aria-disabled={disabled} onclick={(e) => click(e, place)} onkeydown={(e) => key(e, place)}>{digits[i]}</span>
    {#if i === 2 || i === 5}<span class="sep">.</span>{/if}
  {/each}
  <span class="unit">MHz</span>
</div>

<style>
  .digits { display: inline-flex; align-items: baseline; font: 500 30px/1.1 var(--f-mono); color: var(--lo); user-select: none; }
  .d { padding: 0 1px; border-radius: 3px; cursor: ns-resize; }
  .d:hover, .d:focus-visible { background: color-mix(in srgb, var(--lo) 18%, transparent); outline: none; }
  .d.lead { color: color-mix(in srgb, var(--lo) 40%, var(--bg)); }
  .disabled .d { cursor: default; }
  .disabled .d:hover { background: none; }
  .sep { color: var(--faint); padding: 0 1px; }
  .unit { font: 14px var(--f-ui); color: var(--muted); margin-left: 6px; }
  @media (max-width: 600px) { .digits { font-size: 24px; } }
</style>
```

- [ ] **Step 4: Verify types and build**

Run: `npm run check && npm run build`
Expected: `0 errors`. The components are not shown yet; Task 13 places them.

- [ ] **Step 5: Commit**

```bash
git add tools/sdr_web/src/components/Waterfall.svelte tools/sdr_web/src/components/FreqPlan.svelte tools/sdr_web/src/components/TuningDigits.svelte
git commit -m "Add waterfall, RF frequency plan and tuning digit components" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Control rail panels

**Files:**
- Create: `src/components/ReceiverPanel.svelte`, `SynthPanel.svelte`, `NcoPanel.svelte`, `ScalePanel.svelte`, `SendPanel.svelte`

**Interfaces:**
- Consumes: `Panel`, `NumberField`, `SelectField`, and `Segmented` (Task 10);
  `format` (Task 8); `scaleOverride` (Task 9); and `notify`.
- Produces:
  - `ReceiverPanel`, `SynthPanel`, and `NcoPanel` each take `{t: TuningMsg, disabled: boolean, ontune(changes)}`.
  - `ScalePanel {current: [number, number] | null}`. The scale is per viewer and always editable.
  - `SendPanel {respondsToTuning: boolean}`.

- [ ] **Step 1: `ReceiverPanel.svelte`**

```svelte
<script lang="ts">
  import type { Injection, TuningChanges, TuningMsg } from '../lib/types';
  import NumberField from './NumberField.svelte';
  import Panel from './Panel.svelte';
  import Segmented from './Segmented.svelte';

  let { t, disabled, ontune }: { t: TuningMsg; disabled: boolean; ontune: (c: TuningChanges) => void } = $props();
  const SIDES: { value: Injection; text: string }[] = [{ value: 'low', text: 'Low' }, { value: 'high', text: 'High' }];
</script>

<Panel title="Receiver">
  <div class="pb stack">
    <div class="field">
      <span class="label">Mixer injection</span>
      <Segmented label="Mixer injection side" options={SIDES} value={t.state.injection} {disabled}
        onselect={(v) => ontune({ injection: v })} />
    </div>
    <NumberField id="carrier" label="Carrier (MHz)" value={t.state.carrier_hz} scale={1e6} digits={6} step={0.001}
      {disabled} oncommit={(v) => ontune({ carrier_hz: v })} />
    <NumberField id="target-if" label="Target IF (kHz)" value={t.state.target_if_hz} scale={1e3} digits={1} step={0.1}
      {disabled} oncommit={(v) => ontune({ target_if_hz: v })} />
    <NumberField id="window" label="XADC window ± (kHz)" value={t.state.window_hz} scale={1e3} digits={1} step={0.5}
      {disabled} oncommit={(v) => ontune({ window_hz: v })} />
  </div>
</Panel>

<style>
  .label { color: var(--muted); font-size: 13.5px; }
</style>
```

- [ ] **Step 2: `SynthPanel.svelte`**

```svelte
<script lang="ts">
  import { hzText, mhz } from '../lib/format';
  import type { TuningChanges, TuningMsg } from '../lib/types';
  import NumberField from './NumberField.svelte';
  import Panel from './Panel.svelte';
  import SelectField from './SelectField.svelte';

  let { t, disabled, ontune }: { t: TuningMsg; disabled: boolean; ontune: (c: TuningChanges) => void } = $props();
  const OUT_DIVS = [1, 2, 4, 8, 16, 32, 64] as const;   // freqplan.OUT_DIVS
  const s = $derived(t.state);
  const d = $derived(t.derived);
  const vcoOk = $derived(d.vco_hz >= s.vco_min_hz && d.vco_hz <= s.vco_max_hz);
</script>

<Panel title="LO synthesizer">
  {#snippet actions()}<span class="tag" title="The synthesizer part is not chosen yet">generic frac-N</span>{/snippet}
  <div class="pb stack">
    <NumberField id="ref" label="Reference (MHz)" value={s.ref_hz} scale={1e6} digits={3} step={0.001} {disabled}
      oncommit={(v) => ontune({ ref_hz: v })} />
    <NumberField id="rdiv" label="R divider" value={s.r_div} {disabled} oncommit={(v) => ontune({ r_div: v })} />
    <NumberField id="nint" label="N (integer)" value={s.n_int} {disabled} oncommit={(v) => ontune({ n_int: v })} />
    <NumberField id="frac" label="FRAC" value={s.frac} {disabled} oncommit={(v) => ontune({ frac: v })} />
    <NumberField id="mod" label="MOD" value={s.mod} {disabled} oncommit={(v) => ontune({ mod: v })} />
    <SelectField id="odiv" label="Output divider" value={s.out_div} options={OUT_DIVS} {disabled}
      oncommit={(v) => ontune({ out_div: v })} />
    <NumberField id="vco-min" label="VCO min (MHz)" value={s.vco_min_hz} scale={1e6} {disabled}
      oncommit={(v) => ontune({ vco_min_hz: v })} />
    <NumberField id="vco-max" label="VCO max (MHz)" value={s.vco_max_hz} scale={1e6} {disabled}
      oncommit={(v) => ontune({ vco_max_hz: v })} />
    <dl class="derived">
      <dt>PFD</dt><dd>{mhz(d.pfd_hz, 3)} MHz</dd>
      <dt>VCO</dt><dd>{mhz(d.vco_hz, 3)} MHz</dd>
      <dt>LO step</dt><dd>{hzText(d.lo_step_hz)}</dd>
      <dt>VCO range</dt><dd>{#if vcoOk}<span class="chip good">in range</span>{:else}<span class="chip bad">out of range</span>{/if}</dd>
    </dl>
  </div>
</Panel>
```

- [ ] **Step 3: `NcoPanel.svelte`**

```svelte
<script lang="ts">
  import { hex32 } from '../lib/format';
  import type { TuningChanges, TuningMsg } from '../lib/types';
  import NumberField from './NumberField.svelte';
  import Panel from './Panel.svelte';

  let { t, disabled, ontune }: { t: TuningMsg; disabled: boolean; ontune: (c: TuningChanges) => void } = $props();
</script>

<Panel title="Digital downconversion">
  <div class="pb stack">
    <NumberField id="nco" label="NCO (kHz)" value={t.state.nco_hz} scale={1e3} digits={1} step={0.1} {disabled}
      oncommit={(v) => ontune({ nco_hz: v })} />
    <NumberField id="fs" label="XADC rate (kS/s)" value={t.state.fs_hz} scale={1e3} {disabled}
      oncommit={(v) => ontune({ fs_hz: v })} />
    <NumberField id="filter" label="Channel filter ± (kHz)" value={t.state.filter_hz} scale={1e3} digits={1} step={0.5}
      {disabled} oncommit={(v) => ontune({ filter_hz: v })} />
    <dl class="derived">
      <dt>NCO tuning word</dt><dd>{hex32(t.derived.nco_ftw)}</dd>
      <dt>NCO resolution</dt><dd>{(t.derived.nco_resolution_hz * 1e3).toFixed(3)} mHz</dd>
    </dl>
  </div>
</Panel>
```

- [ ] **Step 4: `ScalePanel.svelte`**

```svelte
<script lang="ts">
  // Waterfall scale is a per-viewer preference: Auto uses the server's display.WaterfallScale.
  import { notify } from '../lib/link';
  import { scaleOverride } from '../lib/view';
  import NumberField from './NumberField.svelte';
  import Panel from './Panel.svelte';
  import Segmented from './Segmented.svelte';

  let { current }: { current: [number, number] | null } = $props();
  const MODES: { value: 'auto' | 'manual'; text: string }[] = [{ value: 'auto', text: 'Auto' }, { value: 'manual', text: 'Manual' }];
  const shown = $derived($scaleOverride.mode === 'manual' ? [$scaleOverride.low, $scaleOverride.high] : (current ?? [-110, -45]));

  function setMode(mode: 'auto' | 'manual') {
    if (mode === 'auto') scaleOverride.set({ mode: 'auto' });
    else scaleOverride.set({ mode: 'manual', low: Math.round(shown[0]), high: Math.round(shown[1]) });
  }
  function setLimit(which: 'low' | 'high', v: number) {
    const s = $scaleOverride;
    if (s.mode !== 'manual') return;
    const next = { ...s, [which]: v };
    if (next.high - next.low < 5) {
      notify('The scale needs the peak at least 5 dB above the floor.', 'warn');
      return;
    }
    scaleOverride.set(next);
  }
</script>

<Panel title="Waterfall" sub="this device only">
  <div class="pb stack">
    <div class="field">
      <span class="label">Scale</span>
      <Segmented label="Waterfall scale" options={MODES} value={$scaleOverride.mode} onselect={setMode} />
    </div>
    <NumberField id="scale-low" label="Floor (dBFS)" value={shown[0]} disabled={$scaleOverride.mode === 'auto'}
      oncommit={(v) => setLimit('low', v)} />
    <NumberField id="scale-high" label="Peak (dBFS)" value={shown[1]} disabled={$scaleOverride.mode === 'auto'}
      oncommit={(v) => setLimit('high', v)} />
    <p class="note mono">Showing {shown[0].toFixed(0)} to {shown[1].toFixed(0)} dBFS ({$scaleOverride.mode}).</p>
  </div>
</Panel>

<style>
  .label { color: var(--muted); font-size: 13.5px; }
</style>
```

- [ ] **Step 5: `SendPanel.svelte`**

```svelte
<script lang="ts">
  let { respondsToTuning }: { respondsToTuning: boolean } = $props();
</script>

<section class="panel pb stack" aria-label="Send settings to the FPGA">
  <button class="btn" disabled>Send to FPGA</button>
  <p class="note">Sending settings needs the FPGA command link (UART RX, command decoder and acknowledgements), which is
    not built yet. These settings change the frequency plan{respondsToTuning ? ' and the host simulator' : ''} only.</p>
</section>
```

- [ ] **Step 6: Verify**

Run: `npm run check && npm run build`
Expected: `0 errors`.

- [ ] **Step 7: Commit**

```bash
git add tools/sdr_web/src/components/ReceiverPanel.svelte tools/sdr_web/src/components/SynthPanel.svelte \
  tools/sdr_web/src/components/NcoPanel.svelte tools/sdr_web/src/components/ScalePanel.svelte tools/sdr_web/src/components/SendPanel.svelte
git commit -m "Add Tune control rail: receiver, synthesizer, NCO, scale and send panels" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Channel quality, link statistics, and the Tune page

**Files:**
- Create: `src/components/ChannelQuality.svelte`, `src/components/LinkStatsBar.svelte`
- Modify: `src/pages/Tune.svelte` (replace the placeholder)

**Interfaces:**
- Consumes: everything from Tasks 9–12.
- Produces:
  - `ChannelQuality {channel, colorVar, name, antenna}`
  - `LinkStatsBar` (no props)
  - the finished Tune page

- [ ] **Step 1: `ChannelQuality.svelte`**

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { drawConstellation, drawSparkline, fitCanvas } from '../lib/draw';
  import { signedKhz } from '../lib/format';
  import { HISTORY, history, historyVersion, iqSnaps, metrics } from '../lib/link';
  import type { Channel } from '../lib/types';
  import Panel from './Panel.svelte';

  const SIGNAL_SNR_DB = 6;   // display threshold for the "signal" chip only; not a receiver setting

  let { channel, colorVar, name, antenna }: { channel: Channel; colorVar: string; name: string; antenna: string } = $props();

  let iqCv: HTMLCanvasElement;
  let rssiCv: HTMLCanvasElement;
  let snrCv: HTMLCanvasElement;
  const m = $derived($metrics[channel]?.fields);
  const hasSignal = $derived(!!m && m.snr_db >= SIGNAL_SNR_DB);

  function drawIq() {
    if (!iqCv) return;
    const { ctx, w } = fitCanvas(iqCv);
    drawConstellation(ctx, w, $iqSnaps[channel] ?? [], colorVar);
  }
  function drawHistory() {
    if (!rssiCv || !snrCv) return;
    const r = fitCanvas(rssiCv);
    drawSparkline(r.ctx, r.w, r.h, history[channel].rssi.values(), colorVar, [-115, -70], HISTORY);
    const s = fitCanvas(snrCv);
    drawSparkline(s.ctx, s.w, s.h, history[channel].snr.values(), colorVar, [0, 40], HISTORY);
  }

  $effect(() => {
    void $iqSnaps;
    drawIq();
  });
  $effect(() => {
    void $historyVersion;
    drawHistory();
  });
  onMount(() => {
    const ro = new ResizeObserver(() => {
      drawIq();
      drawHistory();
    });
    ro.observe(iqCv);
    ro.observe(rssiCv);
    return () => ro.disconnect();
  });
</script>

<Panel title={name} sub={antenna} swatch={colorVar}>
  {#snippet actions()}
    {#if !m}<span class="chip warn">waiting</span>
    {:else if hasSignal}<span class="chip good">signal</span>
    {:else}<span class="chip bad">no signal</span>{/if}
  {/snippet}
  <div class="grid">
    <figure>
      <canvas class="iq" bind:this={iqCv} aria-label="Channel {channel} constellation"></canvas>
      <figcaption>I/Q · last 4 snapshots</figcaption>
    </figure>
    <div class="side">
      <div class="kv">
        <div><div class="k">RSSI</div><div class="v">{m ? m.rssi_dbm.toFixed(1) : '—'} <small>dBm</small></div></div>
        <div><div class="k">SNR</div><div class="v">{m ? m.snr_db.toFixed(1) : '—'} <small>dB</small></div></div>
        <div><div class="k">Δf from NCO</div><div class="v">{m ? signedKhz(m.freq_offset_hz) : '—'}</div></div>
        <div><div class="k">Noise</div><div class="v">{m ? m.noise_dbm.toFixed(1) : '—'} <small>dBm</small></div></div>
        <div><div class="k">CRC good</div><div class="v">{m?.crc_good ?? '—'}</div></div>
        <div><div class="k">CRC bad</div><div class="v">{m?.crc_bad ?? '—'}</div></div>
      </div>
      <div>
        <canvas class="spark" bind:this={rssiCv} aria-label="Channel {channel} RSSI history"></canvas>
        <div class="cap"><span>RSSI, last 30 s</span><span>{m ? `${m.rssi_dbm.toFixed(1)} dBm` : ''}</span></div>
      </div>
      <div>
        <canvas class="spark" bind:this={snrCv} aria-label="Channel {channel} SNR history"></canvas>
        <div class="cap"><span>SNR, last 30 s</span><span>{m ? `${m.snr_db.toFixed(1)} dB` : ''}</span></div>
      </div>
    </div>
  </div>
</Panel>

<style>
  .grid { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 12px; padding: 12px; }
  figure { margin: 0; }
  .iq { display: block; width: 100%; max-width: 170px; aspect-ratio: 1; }
  figcaption, .cap { display: flex; justify-content: space-between; font: 11px var(--f-mono); color: var(--muted); margin-top: 6px; }
  .side { display: grid; gap: 12px; min-width: 0; }
  .kv { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
  .k { font: 600 11px var(--f-ui); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
  .v { font: 500 17px var(--f-mono); font-variant-numeric: tabular-nums; }
  .v small { font-size: 11px; color: var(--muted); }
  .spark { display: block; width: 100%; height: 46px; }
  @media (max-width: 600px) {
    .grid { grid-template-columns: minmax(0, 1fr); }
    .kv { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
</style>
```

- [ ] **Step 2: `LinkStatsBar.svelte`**

```svelte
<script lang="ts">
  import { linkStats } from '../lib/link';
  import Panel from './Panel.svelte';

  const f = $derived($linkStats?.fields);
  const parts = $derived(f ? [
    { text: 'from A', n: f.from_a as number, color: '--ch-a' },
    { text: 'from B only', n: f.from_b as number, color: '--ch-b' },
    { text: 'neither', n: f.neither_ok as number, color: '--bad' },
  ] : []);
  const total = $derived(parts.reduce((sum, p) => sum + p.n, 0) || 1);
</script>

<Panel title="Link statistics" sub="which receiver delivered each telemetry frame" class="wide">
  <div class="pb">
    {#if f}
      <div class="bar" role="img" aria-label={parts.map((p) => `${p.text} ${p.n}`).join(', ')}>
        {#each parts as p (p.text)}<div style="flex: {p.n / total}; background: var({p.color})" title="{p.text}: {p.n}"></div>{/each}
      </div>
      <div class="legend mono">
        {#each parts as p (p.text)}<span style="--c: var({p.color})">{p.text} {p.n} ({((p.n / total) * 100).toFixed(1)}%)</span>{/each}
        <span style="--c: var(--good)">both OK {f.both_ok}</span>
      </div>
    {:else}
      <p class="note">Waiting for LINK_STATS (sent once per second).</p>
    {/if}
  </div>
</Panel>

<style>
  .bar { display: flex; height: 16px; border-radius: 4px; overflow: hidden; gap: 2px; }
  .bar div { min-width: 2px; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 20px; margin-top: 8px; font-size: 12.5px; }
  .legend span::before { content: ''; display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 6px; background: var(--c); }
</style>
```

- [ ] **Step 3: `pages/Tune.svelte`**

```svelte
<script lang="ts">
  import ChannelQuality from '../components/ChannelQuality.svelte';
  import FreqPlan from '../components/FreqPlan.svelte';
  import LinkStatsBar from '../components/LinkStatsBar.svelte';
  import NcoPanel from '../components/NcoPanel.svelte';
  import Panel from '../components/Panel.svelte';
  import ReceiverPanel from '../components/ReceiverPanel.svelte';
  import ScalePanel from '../components/ScalePanel.svelte';
  import Segmented from '../components/Segmented.svelte';
  import SendPanel from '../components/SendPanel.svelte';
  import SynthPanel from '../components/SynthPanel.svelte';
  import TuningDigits from '../components/TuningDigits.svelte';
  import Waterfall from '../components/Waterfall.svelte';
  import type { Overlay } from '../lib/draw';
  import { khz, mhz, signedKhz } from '../lib/format';
  import { hello, link, metrics, role, stats, tuning } from '../lib/link';
  import type { Channel, SpectrumMsg, TuningChanges } from '../lib/types';
  import { tuneChannel } from '../lib/view';

  const CHANNELS: { value: Channel; text: string }[] = [{ value: 'A', text: 'Ch A' }, { value: 'B', text: 'Ch B' }];
  const COLOR: Record<Channel, string> = { A: '--ch-a', B: '--ch-b' };

  const disabled = $derived($role?.role !== 'admin');
  const source = $derived($stats?.source ?? $hello?.source);
  const t = $derived($tuning);
  const m = $derived($metrics[$tuneChannel]?.fields);
  const measuredIf = $derived(m && t ? t.state.nco_hz + m.freq_offset_hz : null);
  let row = $state<SpectrumMsg | null>(null);
  let ncoDrag: number | null = null;

  const tune = (changes: TuningChanges) => link.tune(changes);

  const overlays = $derived.by((): Overlay[] => {
    if (!t) return [];
    const s = t.state;
    return [
      { band: [s.target_if_hz - s.window_hz, s.target_if_hz + s.window_hz], colorVar: '--if', alpha: 0.07 },
      { band: [s.nco_hz - s.filter_hz, s.nco_hz + s.filter_hz], colorVar: '--if', alpha: 0.14 },
      { at: s.target_if_hz, colorVar: '--muted', dash: [2, 3], label: 'target', labelBottom: true },
      { at: s.nco_hz, colorVar: '--if', width: 1.5, label: 'NCO', onFall: true },
    ];
  });

  function dragNco(deltaHz: number) {
    if (!t || disabled) return;
    ncoDrag = (ncoDrag ?? t.state.nco_hz) + deltaHz;
    tune({ nco_hz: Math.min(t.state.fs_hz / 2 - 1, Math.max(0, ncoDrag)) });
  }
  function selectChannel(ch: Channel) {
    tuneChannel.set(ch);
    row = null;
  }
</script>

{#if !t}
  <p class="note">Waiting for the server…</p>
{:else}
  <div class="tune">
    <div class="main">
      <Panel title="Frequency plan" sub={disabled ? 'RF domain' : 'RF domain · drag or scroll to move the LO'}>
        {#snippet actions()}
          {#if t.derived.warnings.length === 0}<span class="chip good">plan OK</span>{/if}
        {/snippet}
        <FreqPlan {t} {row} colorVar={COLOR[$tuneChannel]} {disabled} ontune={(lo) => tune({ lo_hz: lo })} />
        <div class="readouts">
          <div class="ro"><span class="k">LO (synthesizer)</span>
            <TuningDigits hz={t.derived.lo_hz} stepHz={t.derived.lo_step_hz} {disabled} onchange={(hz) => tune({ lo_hz: hz })} /></div>
          <div class="ro"><span class="k">Carrier (nominal)</span><span class="v">{mhz(t.state.carrier_hz)}</span></div>
          <div class="ro"><span class="k">Expected IF</span><span class="v">{khz(t.derived.expected_if_hz)}</span></div>
          <div class="ro"><span class="k">Measured IF, ch {$tuneChannel}</span><span class="v">{measuredIf === null ? '—' : khz(measuredIf)}</span></div>
          <div class="ro"><span class="k">Image at</span><span class="v">{mhz(t.derived.image_hz)}</span></div>
        </div>
        {#if t.derived.warnings.length || (source && !source.responds_to_tuning)}
          <div class="warnings">
            {#each t.derived.warnings as w (w)}<span class="chip warn">{w}</span>{/each}
            {#if source && !source.responds_to_tuning}
              <p class="note">The FPGA does not receive tuning yet. The plan follows these settings; the measured spectrum does not.</p>
            {/if}
          </div>
        {/if}
      </Panel>

      <Panel title="IF spectrum" sub={disabled ? 'what the XADC sees' : 'what the XADC sees · drag to move the NCO'}>
        {#snippet actions()}
          <Segmented label="Channel shown" options={CHANNELS} value={$tuneChannel} onselect={selectChannel} />
        {/snippet}
        <Waterfall channel={$tuneChannel} colorVar={COLOR[$tuneChannel]} {overlays} draggable={!disabled}
          ondrag={dragNco} ondragend={() => (ncoDrag = null)} onrow={(r) => (row = r)} />
        <div class="chanbar mono">
          <span>Ch {$tuneChannel}</span>
          <span>RSSI <b>{m ? `${m.rssi_dbm.toFixed(1)} dBm` : '—'}</b></span>
          <span>SNR <b>{m ? `${m.snr_db.toFixed(1)} dB` : '—'}</b></span>
          <span>Δf from NCO <b>{m ? signedKhz(m.freq_offset_hz) : '—'}</b></span>
          {#if row}<span>scale <b>{row.low.toFixed(0)}…{row.high.toFixed(0)} dBFS</b></span>{/if}
        </div>
      </Panel>

      <div class="quality">
        <ChannelQuality channel="A" colorVar="--ch-a" name="Channel A" antenna="5-element Yagi" />
        <ChannelQuality channel="B" colorVar="--ch-b" name="Channel B" antenna="15-element Yagi" />
        <div class="wide"><LinkStatsBar /></div>
      </div>
    </div>

    <aside class="rail">
      {#if disabled}
        <p class="note viewer">Viewing only. Log in as Admin (top right) to change tuning.</p>
      {/if}
      <ReceiverPanel {t} {disabled} ontune={tune} />
      <SynthPanel {t} {disabled} ontune={tune} />
      <NcoPanel {t} {disabled} ontune={tune} />
      <ScalePanel current={row ? [row.low, row.high] : null} />
      <SendPanel respondsToTuning={!!source?.responds_to_tuning} />
    </aside>
  </div>
{/if}

<style>
  .tune { display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 14px; align-items: start; }
  .main, .rail { display: grid; gap: 14px; min-width: 0; }
  .quality { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
  .wide { grid-column: 1 / -1; }
  .readouts { display: flex; flex-wrap: wrap; gap: 10px 26px; align-items: flex-end; padding: 12px; border-top: 1px solid var(--line); }
  .ro { display: grid; gap: 2px; }
  .k { font: 600 11px var(--f-ui); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
  .v { font: 500 18px var(--f-mono); font-variant-numeric: tabular-nums; }
  .warnings { display: flex; flex-wrap: wrap; gap: 6px 10px; padding: 0 12px 12px; }
  .chanbar { display: flex; flex-wrap: wrap; gap: 6px 22px; padding: 8px 12px; border-top: 1px solid var(--line); font-size: 13px; color: var(--muted); }
  .chanbar b { color: var(--fg); font-weight: 500; }
  .viewer { padding: 8px 12px; border: 1px dashed var(--line-2); border-radius: 8px; }
  @media (max-width: 1100px) {
    .tune { grid-template-columns: minmax(0, 1fr); }
    .rail { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
  }
  @media (max-width: 760px) { .quality { grid-template-columns: minmax(0, 1fr); } }
</style>
```

- [ ] **Step 4: Verify against the simulator (this is the Tune acceptance check)**

Run:
- `cd tools/sdr_web && npm run check && npm test && npm run build`
- `cd ../.. && ./sdr gui --source sim`

Expected, as a **Viewer**:
- The frequency plan shows the amber LO at 441.380 MHz, the cyan IF window, the
  red-hatched image band, and the measured trace in the window.
- The IF waterfall scrolls.
- Both channel panels show a ring constellation, RSSI ≈ −78/−84 dBm, and moving sparklines.
- Dragging does nothing, and the inputs are dashed/disabled.

Then log in as **Admin** (local, no password needed):
- Drag the plan left by about 100 kHz. The IF signal leaves the window, a "Carrier
  lands at … outside the window" warning appears, both chips turn to "no
  signal", and the constellation collapses to the center.
- Drag back. The signal locks again.
- Drag the IF waterfall. The NCO line and band move and Δf changes.
- Scroll an LO digit. The LO changes by that digit's place value.

Also:
- Open a second browser window (Viewer). The same plan moves live while the
  Admin drags.
- Press Space: the display freezes, and it resumes on a second press.

Stop the server with Ctrl-C.

- [ ] **Step 5: Commit**

```bash
git add tools/sdr_web/src/components/ChannelQuality.svelte tools/sdr_web/src/components/LinkStatsBar.svelte tools/sdr_web/src/pages/Tune.svelte
git commit -m "Build the Tune page: plan, IF waterfall, controls and channel quality" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Phase 5 — Telemetry page

### Task 14: Configurable card grid and telemetry cards

**Files:**
- Create: `src/lib/cards.ts`, `src/components/CardGrid.svelte`
- Create: `src/pages/telemetry/LatestFrameCard.svelte`, `DeviceCard.svelte`, `LinkCard.svelte`, `ChannelsCard.svelte`, `FlightCard.svelte`, `FrameLogCard.svelte`
- Modify: `src/pages/Telemetry.svelte` (replace the placeholder)

**Interfaces:**
- Consumes: `layout.ts` (Task 8), the stores (Task 9), and `format` (Task 8).
- Produces:
  - `interface CardDef { id: string; title: string; sub: string; w: number; h: number; component: Component }`
  - `CardGrid {cards: CardDef[], storageKey: string}`

- [ ] **Step 1: `lib/cards.ts` and `CardGrid.svelte`**

`src/lib/cards.ts`:

```ts
import type { Component } from 'svelte';

/** A Telemetry card: default span (w columns × h rows) and the component that fills it. */
export interface CardDef { id: string; title: string; sub: string; w: number; h: number; component: Component }
```

`src/components/CardGrid.svelte`:

```svelte
<script lang="ts">
  // Cards reorder by dragging their header and resize from the corner (or with arrow keys on the handle).
  // The layout is saved per device in localStorage.
  import { untrack } from 'svelte';
  import type { CardDef } from '../lib/cards';
  import { type CardLayout, loadLayout, move, resize, saveLayout } from '../lib/layout';

  const ROW_PX = 118;   // matches grid-auto-rows below
  const GAP_PX = 12;

  let { cards, storageKey }: { cards: CardDef[]; storageKey: string } = $props();

  const defaults = (): CardLayout[] => cards.map(({ id, w, h }) => ({ id, w, h }));
  // The storage key is fixed per page, so reading it once at startup is intended.
  let layout = $state<CardLayout[]>(untrack(() => loadLayout(storageKey, defaults())));
  let editing = $state(false);
  let dragId = $state<string | null>(null);
  let grid: HTMLDivElement;
  const byId = $derived(new Map(cards.map((c) => [c.id, c])));

  const columns = () => getComputedStyle(grid).gridTemplateColumns.split(' ').length;
  function commit(next: CardLayout[]) {
    layout = next;
    saveLayout(storageKey, next);
  }

  function dragStart(e: DragEvent, id: string) {
    dragId = id;
    e.dataTransfer?.setData('text/plain', id);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  }
  function dragOver(e: DragEvent, id: string) {
    if (!dragId || dragId === id) return;
    e.preventDefault();
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const after = (e.clientY - r.top) / r.height + (e.clientX - r.left) / r.width > 1;
    layout = move(layout, dragId, id, after);
  }
  function dragEnd() {
    dragId = null;
    saveLayout(storageKey, layout);
  }

  function startResize(e: PointerEvent, card: CardLayout) {
    e.preventDefault();
    const handle = e.currentTarget as HTMLElement;
    handle.setPointerCapture(e.pointerId);
    const cols = columns();
    const colW = grid.clientWidth / cols;
    const x0 = e.clientX;
    const y0 = e.clientY;
    const onMove = (ev: PointerEvent) => {
      layout = resize(layout, card.id, card.w + Math.round((ev.clientX - x0) / colW),
        card.h + Math.round((ev.clientY - y0) / (ROW_PX + GAP_PX)), cols);
    };
    const onUp = () => {
      handle.removeEventListener('pointermove', onMove);
      handle.removeEventListener('pointerup', onUp);
      saveLayout(storageKey, layout);
    };
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
  }
  function resizeKey(e: KeyboardEvent, card: CardLayout) {
    const d = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[e.key];
    if (!d) return;
    e.preventDefault();
    commit(resize(layout, card.id, card.w + d[0], card.h + d[1], columns()));
  }
</script>

<div class="bar">
  <button class="btn" aria-pressed={editing} onclick={() => (editing = !editing)}>{editing ? 'Done' : 'Edit layout'}</button>
  <button class="btn" onclick={() => commit(defaults())}>Reset layout</button>
  <p class="note">In edit mode, drag a card by its header and resize it from the corner. The layout is saved on this device.</p>
</div>

<div class="cards" class:editing bind:this={grid}>
  {#each layout as item (item.id)}
    {@const def = byId.get(item.id)}
    {#if def}
      <section class="panel card" class:dragging={dragId === item.id} aria-label={def.title}
        style="grid-column: span {item.w}; grid-row: span {item.h}" draggable={editing}
        ondragstart={(e) => dragStart(e, item.id)} ondragover={(e) => dragOver(e, item.id)} ondragend={dragEnd}>
        <header class="ph">
          {#if editing}<span class="grip" aria-hidden="true">⋮⋮</span>{/if}
          <h2>{def.title}</h2><span class="sub">{def.sub}</span>
        </header>
        <div class="pb body"><def.component /></div>
        {#if editing}
          <div class="rs" role="button" tabindex="0" aria-label="Resize {def.title} with arrow keys or by dragging"
            onpointerdown={(e) => startResize(e, item)} onkeydown={(e) => resizeKey(e, item)}></div>
        {/if}
      </section>
    {/if}
  {/each}
</div>

<style>
  .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
  .cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); grid-auto-rows: 118px; grid-auto-flow: dense; gap: 12px; }
  .card { position: relative; display: flex; flex-direction: column; overflow: hidden; }
  .body { flex: 1; overflow: auto; min-height: 0; }
  .editing .card { border-style: dashed; border-color: var(--line-2); cursor: grab; }
  .card.dragging { opacity: 0.45; }
  .grip { color: var(--faint); font: 14px var(--f-mono); letter-spacing: -2px; }
  .rs { position: absolute; right: 2px; bottom: 2px; width: 18px; height: 18px; cursor: nwse-resize; touch-action: none;
    background: linear-gradient(135deg, transparent 50%, var(--line-2) 50% 60%, transparent 60% 70%, var(--line-2) 70% 80%, transparent 80%); }
  @media (max-width: 1100px) { .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 600px) {
    .cards { grid-template-columns: minmax(0, 1fr); grid-auto-rows: auto; }
    .card { grid-column: auto !important; grid-row: auto !important; min-height: 140px; }
  }
</style>
```

- [ ] **Step 2: The six cards**

`src/pages/telemetry/LatestFrameCard.svelte`:

```svelte
<script lang="ts">
  import { best } from '../../lib/link';
  const apex = $derived($best?.fields.apex);
</script>

{#if $best && apex}
  <div class="big">APEX {apex.kind} · seq {apex.fields.seq ?? '—'}</div>
  <div class="mono muted row">
    {#if apex.fields.text}<span>"{apex.fields.text}"</span>{/if}
    <span>source {$best.fields.source}</span>
    <span>{apex.crc_ok ? 'CRC ok' : 'CRC bad'}</span>
    {#if $best.synthetic}<span class="pill synth">SIMULATED</span>{/if}
  </div>
{:else}
  <div class="empty"><strong>No telemetry yet</strong>Frames appear here as BEST_TELEM messages arrive.</div>
{/if}
```

`src/pages/telemetry/DeviceCard.svelte`:

```svelte
<script lang="ts">
  import { hex32 } from '../../lib/format';
  import { stats, status } from '../../lib/link';
  const f = $derived($status?.fields);
  const channels = $derived(f ? ['A', 'B'].filter((_, n) => (f.channels >> n) & 1).join('') || '-' : '');
</script>

{#if f}
  <table class="tbl mono">
    <tbody>
      <tr><td>protocol</td><td>v{f.version}</td></tr>
      <tr><td>uptime</td><td>{(f.uptime_ms / 1000).toFixed(0)} s</td></tr>
      <tr><td>build</td><td>{hex32(f.build_id)}</td></tr>
      <tr><td>channels</td><td>{channels}</td></tr>
      <tr><td>dropped</td><td>{f.dropped}</td></tr>
      <tr><td>seq gaps</td><td>{$stats?.decoder.seq_gaps ?? 0}</td></tr>
    </tbody>
  </table>
{:else}
  <div class="empty"><strong>No STATUS yet</strong>Sent once per second by the FPGA.</div>
{/if}

<style>
  .tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  .tbl td { padding: 3px 4px; border-top: 1px solid var(--line); text-align: right; }
  .tbl td:first-child { text-align: left; color: var(--muted); font-family: var(--f-ui); }
</style>
```

`src/pages/telemetry/LinkCard.svelte`:

```svelte
<script lang="ts">
  import { linkStats } from '../../lib/link';
  const f = $derived($linkStats?.fields);
</script>

{#if f}
  <table class="tbl mono">
    <tbody>
      <tr><td>from A</td><td>{f.from_a}</td></tr>
      <tr><td>from B</td><td>{f.from_b}</td></tr>
      <tr><td>both OK</td><td>{f.both_ok}</td></tr>
      <tr><td>neither</td><td>{f.neither_ok}</td></tr>
      <tr><td>best sent</td><td>{f.best_sent}</td></tr>
    </tbody>
  </table>
{:else}
  <div class="empty"><strong>No LINK_STATS yet</strong>Sent once per second.</div>
{/if}

<style>
  .tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  .tbl td { padding: 3px 4px; border-top: 1px solid var(--line); text-align: right; }
  .tbl td:first-child { text-align: left; color: var(--muted); font-family: var(--f-ui); }
</style>
```

`src/pages/telemetry/ChannelsCard.svelte`:

```svelte
<script lang="ts">
  import { signedKhz } from '../../lib/format';
  import { metrics } from '../../lib/link';
  import type { Channel } from '../../lib/types';
  const CHANNELS: Channel[] = ['A', 'B'];
</script>

<table class="tbl mono">
  <thead><tr><th>Ch</th><th>RSSI dBm</th><th>SNR dB</th><th>Δf</th><th>good</th><th>bad</th></tr></thead>
  <tbody>
    {#each CHANNELS as ch (ch)}
      {@const f = $metrics[ch]?.fields}
      <tr>
        <td><span class="sw" style="background: var(--ch-{ch.toLowerCase()})"></span>{ch}</td>
        <td>{f ? f.rssi_dbm.toFixed(1) : '—'}</td><td>{f ? f.snr_db.toFixed(1) : '—'}</td>
        <td>{f ? signedKhz(f.freq_offset_hz) : '—'}</td><td>{f?.crc_good ?? '—'}</td><td>{f?.crc_bad ?? '—'}</td>
      </tr>
    {/each}
  </tbody>
</table>

<style>
  .tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  .tbl th { font: 600 11px var(--f-ui); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); text-align: right; padding: 2px 6px; }
  .tbl td { text-align: right; padding: 3px 6px; border-top: 1px solid var(--line); }
  .tbl th:first-child, .tbl td:first-child { text-align: left; }
  .sw { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 6px; }
</style>
```

`src/pages/telemetry/FlightCard.svelte`:

```svelte
<script lang="ts">
  // Placeholder until the transmitter sends FLIGHT frames.
</script>

<div class="empty">
  <strong>No FLIGHT frames yet</strong>
  Altitude, velocity and flight-phase plots will appear here once the transmitter sends FLIGHT (type 0x02) frames.
</div>
```

`src/pages/telemetry/FrameLogCard.svelte`:

```svelte
<script lang="ts">
  import { frameLog } from '../../lib/link';
</script>

{#if $frameLog.length}
  <pre class="log">{$frameLog.slice(0, 60).join('\n')}</pre>
{:else}
  <div class="empty"><strong>No frames yet</strong>CHAN_FRAME lines appear here, newest first, as in <code>./sdr receive</code>.</div>
{/if}

<style>
  .log { margin: 0; font: 12px/1.55 var(--f-mono); white-space: pre; color: var(--muted); }
</style>
```

- [ ] **Step 3: `pages/Telemetry.svelte`**

```svelte
<script lang="ts">
  import CardGrid from '../components/CardGrid.svelte';
  import type { CardDef } from '../lib/cards';
  import ChannelsCard from './telemetry/ChannelsCard.svelte';
  import DeviceCard from './telemetry/DeviceCard.svelte';
  import FlightCard from './telemetry/FlightCard.svelte';
  import FrameLogCard from './telemetry/FrameLogCard.svelte';
  import LatestFrameCard from './telemetry/LatestFrameCard.svelte';
  import LinkCard from './telemetry/LinkCard.svelte';

  // v1 mirrors the terminal dashboard; ground-station plots replace these as real frames arrive.
  const CARDS: CardDef[] = [
    { id: 'latest', title: 'Latest frame', sub: 'BEST_TELEM', w: 2, h: 1, component: LatestFrameCard },
    { id: 'device', title: 'Device', sub: 'STATUS · 1 Hz', w: 1, h: 2, component: DeviceCard },
    { id: 'link', title: 'Link', sub: 'LINK_STATS', w: 1, h: 2, component: LinkCard },
    { id: 'channels', title: 'Channels', sub: 'CHAN_METRICS', w: 2, h: 1, component: ChannelsCard },
    { id: 'flight', title: 'Flight data', sub: 'APEX FLIGHT', w: 2, h: 2, component: FlightCard },
    { id: 'log', title: 'Frame log', sub: 'CHAN_FRAME A/B', w: 2, h: 2, component: FrameLogCard },
  ];
</script>

<CardGrid cards={CARDS} storageKey="sdr.telemetry.layout" />
```

- [ ] **Step 4: Verify**

Run:
- `cd tools/sdr_web && npm run check && npm test && npm run build`
- `cd ../.. && ./sdr gui --source sim`
- then open `#telemetry`.

Expected:
- All six cards fill with live data, the frame log scrolls newest-first with
  `[SIMULATED]`, and the Flight card shows its empty state.
- **Edit layout:** drag the Frame log card above the Latest frame card. Resize the
  Device card from its corner, and with the arrow keys after focusing the handle.
  Reload the page: the layout persists. **Reset layout** restores the defaults.
- At a narrow window width (under 600 px) the cards stack in one column.

- [ ] **Step 5: Commit**

```bash
git add tools/sdr_web/src/lib/cards.ts tools/sdr_web/src/components/CardGrid.svelte tools/sdr_web/src/pages/Telemetry.svelte \
  tools/sdr_web/src/pages/telemetry/LatestFrameCard.svelte tools/sdr_web/src/pages/telemetry/DeviceCard.svelte \
  tools/sdr_web/src/pages/telemetry/LinkCard.svelte tools/sdr_web/src/pages/telemetry/ChannelsCard.svelte \
  tools/sdr_web/src/pages/telemetry/FlightCard.svelte tools/sdr_web/src/pages/telemetry/FrameLogCard.svelte
git commit -m "Build the Telemetry page with draggable, resizable cards" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Phase 6 — Verification and documentation

### Task 15: End-to-end checks and hand-off documentation

**Files:**
- Modify: `tools/README.md` (a new "Web GUI" section), `README.md` ("Start here" and the repository map), `docs/HANDOFF.md` (checkpoint), `AGENTS.md` (verification commands)

- [ ] **Step 1: Run every automated check (fresh, not from memory)**

Run:
```bash
PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v
(cd tools/sdr_web && npm test && npm run check && npm run build)
./sdr sim
```
Expected:
- The Python tests all pass, with `test_gui_server` **not** skipped.
- Vitest passes, svelte-check reports 0 errors, and the build succeeds.
- `./sdr sim` passes. It also regenerates `build/sdr/link_capture.bin`, which
  Step 2 uses.

- [ ] **Step 2: Replay the RTL simulation capture through the GUI**

Run: `./sdr gui --source replay --file build/sdr/link_capture.bin --loop`
Expected:
- The status bar shows `replay · running` and 0 CRC/COBS errors.
- Both pages populate from the capture.
- The Tune page shows the "FPGA does not receive tuning yet" note, and
  dragging (as Admin) moves only the plan, not the measured spectrum.

This cross-checks the GUI against real RTL output.

- [ ] **Step 3: LAN, password and takeover (manual)**

1. Run `./sdr setup --gui-password` and enter a password of at least 8 characters twice.
2. Run `./sdr config`. It shows `"gui_admin_hash": "(set)"`, never the hash.
3. Run `./sdr gui --source sim --lan`. The printed LAN URLs include this machine's IP.
4. On a phone or tablet on the same network, open that URL. It shows Viewer,
   the controls are disabled, and the layout is usable in portrait and landscape.
5. On the phone, log in as Admin with the password. It becomes Admin.
6. On the Mac, log in as Admin. You get the takeover prompt naming the phone's
   label. Confirm it. The Mac becomes Admin, and the phone shows "… took over
   Admin. You are now a Viewer."
7. Reload the Mac tab. It is still Admin (resume within 15 s).
8. Run `./sdr gui --source sim` (without `--lan`). The phone can no longer connect.

- [ ] **Step 4: Hardware check, only if the board is attached**

Close other UART readers. Run `./sdr gui` against the currently programmed
bitstream. Expected:
- `serial · running`, and about 11 kB/s.
- Every page is populated, with SIMULATED shown because the FPGA stand-ins flag
  their output.
- 0 CRC errors after a minute.

**Record whether this was run.** If the board is absent, say so in the hand-off.
Do not claim hardware verification.

- [ ] **Step 5: Update documentation**

Add this to `tools/README.md`, after the "Dashboard" section:

````markdown
## Web GUI

`./sdr gui` serves the Space Raiders SDR web app. It has two pages:

- **Tune:** RF frequency plan, IF waterfall, synthesizer/NCO settings, and
  per-channel constellation, RSSI and SNR.
- **Telemetry:** cards you can drag and resize.

```sh
.venv/bin/python -m pip install -e '.[gui]'        # once: adds aiohttp
(cd tools/sdr_web && npm install && npm run build) # after frontend changes; needs Node
./sdr gui                        # board over UART; http://127.0.0.1:8080, opens a browser
./sdr gui --source sim           # host simulator that follows tuning; no board needed
./sdr gui --source replay --file .sdr/captures/X.bin --loop
./sdr gui --lan                  # also reachable from other devices on this network
./sdr setup --gui-password       # Admin password (stored hashed in .sdr/config.json)
```

- **Access:**
  - Without `--lan` the server listens on 127.0.0.1 only.
  - Everyone starts as a Viewer, and only one Admin can change tuning at a time.
  - Taking over Admin asks for confirmation and notifies the previous Admin.
  - With no password set, only the server machine can become Admin.
  - The password guards against casual changes on a trusted LAN. It is sent over
    plain HTTP and is not protection against someone sniffing the network.
- **Tuning:**
  - Tuning is shared between viewers and saved in `.sdr/gui_state.json`.
  - **The FPGA does not receive it yet:** there is no UART RX or command
    protocol, so "Send to FPGA" is disabled. Only `--source sim` reacts to tuning.
  - The synthesizer model, XADC rate and filter widths are placeholders until
    those parts are chosen.
- **Serial port:** the GUI owns the UART like the dashboard does. Run one of them at a time.
- **Frontend development:** `npm run dev` (from `tools/sdr_web`) serves on Vite
  with hot reload and proxies `/ws` to a running `./sdr gui --no-browser`.
- **Frontend tests:** `npm test` (Vitest) and `npm run check` (svelte-check).
- **Deployment:** the built files in `tools/sdr_cli/web/static/` are what a
  Raspberry Pi needs; it does not need Node.
````

In `README.md` "Start here", add `./sdr gui --source sim  # web GUI with the host simulator (see tools/README.md)`.
In the repository map, add these rows:
- `| tools/sdr_web/ | Svelte source for the web GUI (built into tools/sdr_cli/web/static/) |`
- `| tools/sdr_cli/web/ | GUI web server (aiohttp) |`

In `AGENTS.md` "Verification and handoff", add after the host-changes command:

````markdown
For GUI frontend changes:

```sh
(cd tools/sdr_web && npm test && npm run check && npm run build)
```
````

In `docs/HANDOFF.md`:
- **Checkpoint.** Replace the "Next task, chosen by the user: a desktop GUI"
  paragraph and the "GUI task" section's "Decisions for the GUI task" list with
  the new checkpoint. It covers the GUI's existence, the spec and plan paths,
  the stack choice (web: aiohttp + Svelte), the roles, the simulator, and the
  sources.
- **Verified.** List what Steps 1–4 showed. State explicitly whether Step 4
  (hardware) was run.
- **Still open:**
  - FPGA command link, which "Send to FPGA" waits on;
  - FLIGHT/HK plots;
  - Pi deployment/CI (see the spec's "Deployment (later)");
  - HTTPS;
  - the Member role;
  - the unresolved 428–438 MHz BPF vs 441.48 MHz carrier question;
  - the placeholder synthesizer, XADC rate and filter values.

- [ ] **Step 6: Check links and commands in the edited docs**

Run: `grep -n "sdr gui\|sdr_web\|gui-password" README.md tools/README.md AGENTS.md docs/HANDOFF.md`
Expected: every command matches the real CLI flags (`--source`, `--file`,
`--loop`, `--lan`, `--http-port`, `--no-browser`, `--gui-password`) and every path exists.

- [ ] **Step 7: Commit**

```bash
git add tools/README.md README.md AGENTS.md docs/HANDOFF.md
git commit -m "Document the web GUI and record the GUI checkpoint" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Note: `AGENTS.md`, `docs/HANDOFF.md`, `README.md` and `tools/README.md` may
still carry uncommitted edits from before this plan (link layer v2). Before
staging, run `git diff` on those files. If the older edits are still
uncommitted, ask the user whether to commit them together or separately.

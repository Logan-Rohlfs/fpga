# GUI cards: status and what remains

Written 2026-10-01 after the documentation task; updated after Task 26 merged and the final whole-branch review. It replaces the earlier resume-point
list. Spec (binding): [gui-cards-design](../specs/2026-09-30-gui-cards-design.md).
Plan: [gui-cards](2026-09-30-gui-cards.md). Preflight rulings:
[gui-cards-rulings](2026-09-30-gui-cards-rulings.md). Checkpoint and verification:
[HANDOFF](../../HANDOFF.md). User guide: [tools/README.md](../../../tools/README.md#web-gui).

## Done on `gui-prep`

- Plan Tasks 1-26 (Task 26, the parameterized `rx_observer` DFT length, is merged and simulation-verified; the default stays 64 bins), including optional Task 24 (state-triggered preset switching) and
  Task 23 (documentation). All 14 card types and the default Flight preset exist.
- The integration pass: one header mechanism for SIMULATED/stale labels, Freeze wired
  to the draw scheduler, `both` as a plot series source, Tune/ChannelQuality/LinkStatsBar
  moved onto the new stores (old history/metrics stores removed), `--accent` token,
  `RfReference.confirmed_by`, "Operator" wording in CLI strings, positive IDLE-trigger test.
- Host demo source `./sdr gui --source demo` (no board).
- The demo ROM is a RocketPy simulation of the IREC 2026 flight (1381 frames);
  the GUI labels it `SIM FLIGHT · SIMULATED ADC`.
- Plot y-axes frame from the visible window and size around the legend; Flight preset
  cards fit at 1440x900 and 1920x1080; plot, map and 3D cards show only the current
  flight segment (`segment: current`), clearing on each demo loop.

## Verification state

- Run: host suite, vitest, svelte-check, build and `./sdr sim`; a headless-Chrome
  overflow probe at 1440x900 and 1920x1080 with `--source demo` (earlier, in the sizing work).
- Final whole-branch review: done. Its fix wave landed (HANDOFF and this plan de-staled;
  the 3D card rebuilds only from the scheduled draw; Freeze holds Raw frames and Events;
  a display segment starts only on a reset after LANDED, via the new `prev_phase` event
  field; multi-series plot merge survives duplicate/out-of-order timestamps; serial
  permission errors are no longer reported as busy; the host demo source emits 64 spectrum
  bins; `read_rom_frames` raises `ValueError`; singular/plural viewer count).
- Not run: hardware replay of the new demo ROM; any Vivado build on the current RTL
  (Task 26's restructured `rx_observer` changes even the default netlist; the build host
  was offline); phone/LAN viewers; a real-browser smoke pass.

## What remains

1. **Vivado build (`./sdr build --all`) of the default and demo variants on the current
   RTL**, with timing and DRC inspected, then UART-load measurement on the board. All earlier
   timing numbers predate Task 26 and the RocketPy ROM. Then a **board run of the RocketPy
   demo ROM** (about 15 RAMB36 tiles, unmeasured). Only after that can the replay be called hardware-verified.
2. **Real-browser smoke pass** of the GUI (`./sdr gui --source demo`), including a phone/LAN viewer.
3. **Future work, not built:** camera capture on the host and a server-side relay;
   a trigger editor in the UI (triggers are edited in preset JSON); regenerating the
   ROM needs the sibling apex repo's simulation CSV (the checked-in `.mem` is enough
   for everything else).

## Standing rulings worth remembering

- Implementers commit their own work; `build.tcl`, `core.py` and `tui.py` stay untouched
  by GUI tasks.
- "Events" means flight-state events; link events are a separate category.
- Display values as decoded; only malformed frames are rejected.
- Never claim hardware verification from simulation or replay.
- Task 25 `preflight_bind` uses SO_REUSEADDR on POSIX (still refuses an active listener).

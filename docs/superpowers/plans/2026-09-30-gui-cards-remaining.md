# GUI cards: status and what remains

Written 2026-10-01 after the documentation task. It replaces the earlier resume-point
list. Spec (binding): [gui-cards-design](../specs/2026-09-30-gui-cards-design.md).
Plan: [gui-cards](2026-09-30-gui-cards.md). Preflight rulings:
[gui-cards-rulings](2026-09-30-gui-cards-rulings.md). Checkpoint and verification:
[HANDOFF](../../HANDOFF.md). User guide: [tools/README.md](../../../tools/README.md#web-gui).

## Done on `gui-prep`

- Plan Tasks 1-25, including optional Task 24 (state-triggered preset switching) and
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
- Not run: hardware replay of the new demo ROM; any Vivado build of it; phone/LAN
  viewers; a final whole-branch review.

## What remains

1. **Task 26** (parameterized `rx_observer` DFT length, 128 or 256 bins; 64 stays
   available in tests; bins are never interpolated). In progress on a separate branch.
   Needs sims passing, then remote Vivado timing and UART-load measurement. Record the
   result in HANDOFF (placeholder is there). GUI follow-up may be needed for new bin counts.
2. **Vivado build and board run of the RocketPy demo ROM** (about 15 RAMB36 tiles,
   unmeasured). Only after that can the replay be called hardware-verified.
3. **Final whole-branch review**, most capable model; triage deferred minors
   (for example `metrics_history` has no SYNTHETIC flag).
4. **Future work, not built:** camera capture on the host and a server-side relay;
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

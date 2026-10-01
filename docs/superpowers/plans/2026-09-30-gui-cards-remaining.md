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
  permission errors are no longer reported as busy; the host demo source matches the
  bitstream's spectrum bin count; `read_rom_frames` raises `ValueError`; singular/plural viewer count).
- Newly run 2026-10-01: `./sdr build --all` at 128 bins (both variants timing-clean, DRC 0
  errors), `./sdr sim` (all PASS), host suite (326 tests, OK). The 128-bin RocketPy demo is
  flashed; the agent saw 128-bin SPECTRUM rows through `./sdr gui` with 0 link errors.
  The Flight-preset viewer load at 128 bins measures 97,536 B per 10 s (`test_fanout`),
  just under the 100,000 B budget. Frontend unchanged (bin-count agnostic), so vitest,
  svelte-check and the build were not re-run.
- Not run: a watched full flight in a real browser; phone/LAN viewers; the Task 3 acceptance run.

## What remains

1. **Done 2026-10-01:** both variants build timing-clean at 128 bins (after a
   `source_combiner` timing fix), and the RocketPy demo is flashed and streaming
   on the board (18 BRAM tiles). Still open: UART-load measurement on the board,
   and a watched full flight before calling the replay hardware-verified.
2. **Real-browser smoke pass** of the GUI (`./sdr gui --source demo`), including a phone/LAN viewer.
3. **Future work, not built:** camera capture on the host and a server-side relay;
   a trigger editor in the UI (triggers are edited in preset JSON); regenerating the
   ROM needs the sibling apex repo's simulation CSV (the checked-in `.mem` is enough
   for everything else).
4. **Requested GUI additions (planning only):** 3D camera follow/orbit modes, ground
   beyond the map tiles (fade or globe), event-marker readability and a launch-synced
   demo video. See [gui-backlog](2026-10-01-gui-backlog.md).

## Standing rulings worth remembering

- Implementers commit their own work; `build.tcl`, `core.py` and `tui.py` stay untouched
  by GUI tasks.
- "Events" means flight-state events; link events are a separate category.
- Display values as decoded; only malformed frames are rejected.
- Never claim hardware verification from simulation or replay.
- Task 25 `preflight_bind` uses SO_REUSEADDR on POSIX (still refuses an active listener).

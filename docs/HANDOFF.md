# SDR handoff

Checkpoint updated 2026-09-30 (branch `gui-prep`). **The host link layer works
on hardware, and a sample-driven receiver chain now closes timing at 100 MHz.**
GUI v1, the source combiner, the receiver chain and the APEX flight replay demo
are implemented. The FPGA sends every message type at 1 Mbaud, and the `sdr` CLI
and dashboard decode and display them.

**Provenance:** only the ADC waveform is synthetic now. Everything downstream
(DDC, filtering, discriminator, symbol timing, frame sync, CRC, combiner, I/Q,
64-bin DFT, metrics) is real logic operating on that synthetic input, so
messages keep the `SYNTHETIC` flag. The earlier "all content SIMULATED by
stand-in producers" statement is superseded; the legacy stand-in producers
(`link_test_sources.sv`) remain only as explicitly named test fixtures. The
planned stages are in [`docs/sdr_pipeline.drawio`](sdr_pipeline.drawio).

**Next work:** (1) the GUI overhaul, see [GUI overhaul progress](#gui-overhaul-progress-in-progress);
(2) the open receiver-plan tasks, see [Remaining receiver-plan work](#remaining-receiver-plan-work).
If you are resuming cold, read those two sections first.

## Sample-driven receiver continuation (timing closed; review and board acceptance open)

The user authorized guessed, configurable radio characteristics and completion
with only the ADC input simulated. This supersedes the earlier wait for confirmed
transmitter settings. See the [receiver contract](superpowers/specs/2026-09-29-sample-driven-receiver.md),
[plan](superpowers/plans/2026-09-29-sample-driven-receiver.md), and
[updated receiver guide](../projects/sdr/README.md).

Implemented: synthetic signed ADC source, real DDC/decimator/discriminator/symbol
recovery, configurable framing/CRC, existing combiner, actual I/Q and 64-bin DFT,
relative dBFS measurements, and acknowledged UART test-carrier/NCO tuning.
Legacy transport and host UI simulators remain explicitly named fixtures.

Simulation evidence includes exact packets recovered from independent Gaussian
ADC vectors (clean, noisy/offset, corrupted CRC), RTL-generated ADC samples,
no-signal/recovery, and complete UART/CONFIG tests. Host/GUI checks passed
following independent review fixes.

**Timing and area: closed.** The first Vivado run failed setup at -16.941 ns
with 97% LUTs (`build/sdr/failed-20260929-190956-6f3870be/`), and an intermediate
run still failed by -12.430 ns (`failed-20260930-101513-6765bf0b`). The observer
now reads from RAMs, the decimator divider is a pipelined reciprocal multiply,
and the ADC model logic is pipelined. Payload values are unchanged; captures
differ from the old RTL only in timestamps (at most 1 us later). Default bundle
`build/sdr/artifacts/20260930-103603-a1d0abba/`: WNS +0.120 ns, WHS +0.023 ns at
100 MHz, 0 failing endpoints; 5,241 LUTs (25%), 6,911 FFs (16.6%), 0 BRAM,
41 DSPs. DRC has no errors, only the known CFGBVS/CONFIG_VOLTAGE warning plus DSP
pipelining advisories. The worst remaining path is in `source_combiner`
(`frame_key` -> `a_older`, 12 logic levels), so margin is thin but positive.
Intermediate failed reports are preserved under `build/sdr/failed-20260930-*`.

**Parallel builds.** `./sdr build --all` builds the default and demo variants
concurrently with Vivado threads sized from the host core count (`--cores N`
overrides). It took 202 s against about 420 s serial. `build/sdr/latest` is the
default bundle and `build/sdr/latest-demo` is the demo; `./sdr program --demo`
programs the demo. Ctrl-C cancels concurrent builds cleanly.

**Board evidence (read carefully; none of it is a formal acceptance run):**

- The user flashed the demo bitstream (persistent) themselves and reports the
  host receives the expected data. This is **user-reported**, not agent-verified.
- Observed in this session by the controller through `./sdr gui` on the attached
  board: live serial data, 1,814 then 5,160 messages, 0 CRC/COBS/length errors,
  and the server survived a volatile `./sdr program` and resumed data. This is an
  observation, not the Task 3 acceptance run (no decode of APEX TEST frames on
  both channels, no tuning/CONFIG exercise, no retained capture).
- The GUI "Disconnected, retrying" the user saw after programming was likely
  conflicting GUI instances (a stale preview server on another port was found).
  It could not be reproduced with a single instance. GUI overhaul Task 25 added
  serial auto-reconnect and HTTP port-conflict detection.
- Newly run for Task 25 (2026-09-30), on this machine with the board attached: a
  second `./sdr gui` on the same HTTP port exited 1 with the port-in-use message;
  with the UART held by another process (a pyserial `exclusive=True` holder), the
  serial GUI reported `busy` with the "held by another process" detail, then
  returned to `running` on its own after the holder released the port. USB unplug
  and `./sdr program` during a GUI session were **not** exercised for this task.

## GUI overhaul progress (in progress)

The user requested a card-based, multi-viewer GUI overhaul (card dashboard,
presets, flight readout, multi-user performance). It supersedes the old receiver
plan "Task 6 GUI flight readout".

- Spec (binding): [`superpowers/specs/2026-09-30-gui-cards-design.md`](superpowers/specs/2026-09-30-gui-cards-design.md)
- Plan (Tasks 1-26): [`superpowers/plans/2026-09-30-gui-cards.md`](superpowers/plans/2026-09-30-gui-cards.md)
- Ledger (local, git-ignored): `.superpowers/sdd/2026-09-30-gui-cards/progress.md`.
  A task with a "Task N: complete" line is done; skip it. Decisions and survey are
  in `.superpowers/sdd/gui-overhaul-decisions.md` and `gui-overhaul-survey.md`.
- **Execution order:** Tasks 1-7, then 25, then 8-15, then 26, then 16-23, then
  24 (optional). Task 25 needs Task 7's connection/stats stores and fixes the
  user-visible reconnect problem early. Task 26 (FPGA DFT length of 128 or 256,
  parameterized; needs a rebuild) follows Task 15 because 64-bin data cannot give
  a higher-resolution spectrum host-side. Tasks 21 and 25 both edit
  `StatusBar.svelte` and `App.svelte`; the later one rebases.
- **Tasks 6 and 7 are atomic.** Never stop, checkpoint or hand off between them:
  Task 6 makes the server send binary spectrum frames that the shipped frontend
  cannot decode until Task 7.
- Approved and installed frontend packages: `leaflet`, `uplot`, `three`
  (runtime) and `@types/leaflet`, `@types/three` (dev). Nothing else.
- Checkpoint rule: after each task the controller updates the line below. The
  system must stay functional at every task boundary except inside the 6-7 pair.

**Current task: plan Tasks 1-25 are complete on `gui-prep` except Task 26 (FPGA DFT length), which is in progress on a separate branch; Task 23 (docs) is this commit. Next: Task 26's result, then the final whole-branch review.** The integration pass, the host `--source demo`, the RocketPy demo ROM, the plot/card sizing work and per-loop segment clearing all landed after the last checkpoint; see [gui-cards-remaining](superpowers/plans/2026-09-30-gui-cards-remaining.md) for status and what remains.

**Verified checkpoint (GUI cards).**
- Newly run for this docs commit: host suite (322 tests, OK, 3 skipped), vitest 270 pass, svelte-check 0 errors and 0 warnings, production build, and `./sdr sim` (all PASS).
- Run earlier in this effort (sizing commit `e73b4b4`, not repeated for this commit): a headless-Chrome overflow probe at 1440x900 and 1920x1080 with `./sdr gui --source demo`, checking that no Flight preset card scrolls or clips.
- Not verified: no hardware run of the new RocketPy demo ROM, and no Vivado build of it (resource use and timing unmeasured; the earlier recorded-log demo build numbers below do not apply). No phone or LAN viewer was tried. Camera capture and a server-side relay are not built (the camera card only embeds a stream URL).
- Task 26 (parameterized DFT length, UART load and timing): result pending. Placeholder: TASK 26 RESULT NOT YET RECORDED.

**Preflight rulings: made.** Every finding in the
[preflight scan](superpowers/plans/2026-09-30-gui-cards-preflight.md) is ruled, and
the rulings are committed in
[gui-cards-rulings](superpowers/plans/2026-09-30-gui-cards-rulings.md). They include
per-task sections to carry into each dispatch. One user clarification is recorded
there and in the spec (§10): "events" means flight-state events, and link events are
a separate category with their own event-log view.

Deferred minor findings from the task reviews are in the local ledger for the final
whole-branch review. The most relevant open one: `metrics_history` carries no
SYNTHETIC flag. (The send-loop finding was fixed in Task 25: an unexpected send error
is logged and closes the socket with code 1011.)

The ledgers under `.superpowers/sdd/` are git-ignored local files. On another
machine they won't exist. Rebuild progress from `git log` (task commits name
their task), and read the rulings recorded in this section.

Controller rulings already made:
- Implementers commit their own work, overriding the plan's "controller
  commits".
- `build.tcl`, `core.py` and `tui.py` stay untouched by GUI tasks. Task 18's
  `cli.py` `maps` subparser is additive.
- Execution order is as listed above.
- The stale `AGENTS.md` "no command receiver" line was fixed in Task 23.

**How to resume:** read the plan status doc linked above, then `git log --oneline main..gui-prep`. Verify with the commands in AGENTS.md.

## Remaining receiver-plan work

From the [receiver plan](superpowers/plans/2026-09-29-sample-driven-receiver.md),
Tasks 1 (timing closure), 5 (demo) and 7 (parallel builds) are complete and
reviewed. Still open:

- **Task 2:** independent whole-branch review of the receiver chain, host
  decoding, receiver control and GUI changes (covers the demo). RTL fixes must
  re-close timing.
- **Task 3:** board and GUI acceptance run on the final bitstream: volatile
  `./sdr program`, capture at least 15 s to `.sdr/captures/receiver-<date>.bin`,
  decode with zero errors, APEX TEST frames on both channels, tuning/CONFIG
  exercise, GUI live check. Only claim what is observed in that run.
- **Task 4:** final docs and explicit limitations (XADC acquisition, physical
  PLL, calibrated dBm, guessed radio profile).
- Old "Task 6 GUI flight readout" is superseded by the GUI overhaul above.
- Default profile (20 kHz, sync D391) is a guess and differs from the firmware;
  the demo uses the firmware-derived profile (25 kHz, sync 2DD4). Unchanged.

Deferred minors (details in the local receiver ledger
`.superpowers/sdd/2026-09-29-sample-driven-receiver/progress.md` and the
`task-*-review.md` files): ADC source `DIVIDER>=4` guard is sim-only; no stall
test for link-source ready; no committed regression for the reciprocal multiply;
thin combiner timing margin; `Makefile` `DEMO=0` still builds the demo; 889 ms
CSV logging gap repeats one ARMED row in the demo (undocumented);
`check_receiver.py --demo` fails a capture on one false-lock CRC-bad frame;
health/phase_status bits unchecked in `test_apex_flight_rom.py`; wrap lane tested
with `GAP_SLOTS=1` only; `flight_top_tb` uses `defparam`; no SIGTERM handler in
parallel builds (plain SIGTERM orphans ssh children); legacy `latest` -> demo
bundle still programs the demo with only a notice.

## APEX simulated-flight demo (opt-in build, 2026-09-30; ROM switched 2026-10-01)

`./sdr build --demo` (dashboard `build demo`, Vivado `-tclargs sdr demo`) builds a
separate bitstream (`sdr_top` `DEMO_FLIGHT=1`, BUILD_ID `SDRF`). Its ROM is no
longer the recorded flight log: it is a **RocketPy simulation** of the IREC 2026
competition flight (Pecos TX), exported by the apex repo (branch
`demo-telemetry-export` @ 5c859f7, `sim/scripts/export_demo_telemetry.py`, seed
2026, standard atmosphere, competition config, fake-Teensy FSW model in the
loop) in the IREC CSV schema. Flight: apogee 3104.3 m AGL at T+24.2 s, max
velocity 279.3 m/s, BOOST T+0.18, COAST T+4.11, DESCENT T+24.51, LANDED T+429.7.
The ROM has 1381 frames x 42 bytes = 58,002 bytes (2 s before launch detect to
3 s after landing): 50 ms of flight per frame until apogee + 3 s, then 500 ms
per frame, so the descent replays at 10x (frames keep their true flight-time
values; none are invented). One loop is (1381 + 20 gap) x 50 ms = 70.05 s. The
frames use the firmware's framing: 0xAA preamble, sync 2DD4, 44-byte frames,
±25 kHz, 20 Hz. They go through the real receiver with ±256 LSB noise. Loss
windows per loop: A in slots 60–69 (boost), B in slots 505–514 (across the
COAST->DESCENT change at slot 510); the RTL constants and the testbenches moved
with the ROM. Gaussian BT 0.5 and the 1 MS/s / 100 kHz IF are labelled
assumptions. Labelling: host profile `apex_demo` gives the badge `SIM FLIGHT ·
SIMULATED ADC` ("RocketPy simulation of the IREC 2026 competition flight (Pecos
TX) through the real receiver; the ADC input is simulated"); it is never
presented as a recorded flight. The simulated log has GPS on every row, so only
phase_status interlock bits, health bits, tilt and azimuth are still emulated
by the generator (the GPS fallback only applies to a log with empty positions).
The ROM (`projects/sdr/rom/apex_flight.mem`) is generated by
`projects/sdr/host/apex_flight_rom.py` from the gitignored sim CSV
(`../apex/sim/output/demo/IREC-2026-SIM-TELEMETRY.csv`, or `--csv`) and checked
in. No Vivado build has been run on the new ROM (about 15 RAMB36 tiles, not yet
measured). apex finding for the user, not changed here: airbrakes.yaml / FSW-model
PID gains (Kp 0.4, Kd -0.04, Mach gate 240 m/s) differ from fsw/src/config.h
(0.6, -0.05, 260). Details and the full
assumption list are in the [SDR guide](../projects/sdr/README.md#apex-flight-replay-demo-opt-in-build).
The GUI flight card is not built yet (it is part of the GUI overhaul). The host
already decodes FLIGHT fields (`sdr_cli.apex`).

- Default bitstream unchanged: HEAD and the new RTL give byte-identical
  default UART captures and ADC samples in simulation. Default build
  `20260930-110814-cc50decc` matched the Task 1 bitstream body byte for byte
  (WNS +0.120 ns, WHS +0.023 ns, 5,241 LUTs, 6,911 FFs, 0 BRAM, 41 DSPs).
- New checks: `flight_decoder_tb`, `flight_replay_tb` (bit-exact ROM frames
  through the GFSK ADC, both pipelines and the combiner at each loss-window
  edge and the loop wrap), `flight_top_tb` with `check_receiver.py --demo --rom`,
  and host `test_apex_flight_rom.py` (ROM vs CSV via the host APEX parser).
- Default and demo were then built concurrently on the committed RTL, with
  223 s wall clock against 420 s when serial. Both results match the serial
  runs bit for bit. Default `20260930-111724-052ce27b`: WNS +0.120 ns, WHS
  +0.023 ns. Demo `20260930-111724-e9eeab52`: WNS +0.089 ns, WHS +0.051 ns,
  0 failing endpoints, 5,697 LUTs (27.4%), 9,346 FFs (22.5%), 4 BRAM tiles
  (the ROM), 41 DSPs. Neither DRC report has errors; only the known CFGBVS and
  DSP pipelining warnings. The worst path in both is the combiner's `a_older`
  update (demo: `output_key` -> `a_older`, 13 levels). Its margin is thin but
  positive, so the combiner was not changed. (At that time `latest` selected
  the demo bundle; it now selects the default, and `latest-demo` the demo.)
- Not done: an agent-run board programming and UART capture of the demo
  bitstream (the user reports flashing it and receiving the expected data), the
  GUI flight card, and HOUSEKEEPING frames (not replayed).

## Source combiner implementation status

The GUI continuation was followed by subagent-driven implementation of the next
upstream stage: `source_combiner.sv`. See the
[contract](superpowers/specs/2026-09-29-source-combiner-design.md) and
[plan](superpowers/plans/2026-09-29-source-combiner.md).

- Bounded whole-frame input buffers match explicit type/sequence keys. Selection
  requires good CRC, then ranks quality, signed RSSI, and A on a tie.
- Configurable matching timeout and finite duplicate history support late copies,
  stalled output, and sequence reuse. These are synthetic test timings, not
  chosen receiver packet timings. No frame parsing, RF settings or DSP constants
  were introduced.
- The test harness now uses the actual selector and counters for BEST_TELEM and
  LINK_STATS. Raw BEST bytes are captured on link-port acceptance. Synthetic
  overruns count separately; all messages remain SYNTHETIC.
- Independent implementation, test and review subagents were used. Review found
  no actionable correctness defects. `./sdr sim` passed 34 focused selections
  plus 75 UART messages, with all 13 BEST payloads checked against A/B records
  (5 both-good B wins). Parameter endpoint tests also pass for 1-byte and 255-byte
  frames with one-cycle timers and one history slot. Host decode had zero errors;
  all 93 host tests pass.
- Fresh Vivado build `20260929-175927-5af9b984`: WNS +0.268 ns, WHS
  +0.043 ns at 100 MHz; 2,048 LUTs and 2,318 registers. No DRC errors;
  the existing CFGBVS/CONFIG_VOLTAGE warning remains. The first attempt missed
  timing by 0.008 ns; capturing accepted descriptors independently of duplicate
  filtering removed the long control path. The revised RTL passed simulation and
  independent review again. Failed-build reports are preserved locally.
- The new bitstream was loaded into volatile FPGA memory; no flash write.
  A 15-second UART capture decoded 1,676 messages across all seven types with
  zero CRC/COBS/length errors, sequence gaps or STATUS drops. All 296 BEST
  selections matched source, timestamp and raw bytes against channel records:
  156 A, 140 B, including 116 both-good B wins. All messages were SYNTHETIC.
  Capture retained at `.sdr/captures/combiner-20260929-1802.bin`.

The next upstream stage is frame sync + CRC. Before connecting real decoders,
settle transmitter framing and validate key extraction, match/dedupe windows,
queue depth, transmitter resets and same-key payload disagreements. Do not clear
SYNTHETIC merely because the selector is real: its present inputs are fabricated.

## GUI implementation status

Recorded 2026-09-29 (GUI continuation).

- [Spec](superpowers/specs/2026-09-29-gui-design.md) and
  [15-task plan](superpowers/plans/2026-09-29-space-raiders-sdr-gui.md).
- Tasks 1–8 were already committed. Task 8 was reviewed; the default tune
  coalescer now uses 34 ms to stay below 30 sends/s. Tasks 9–14 are implemented:
  WebSocket stores/reconnect, branded app shell, role menu, Tune controls,
  frequency plan, A/B waterfall, constellations/history, and Telemetry cards.
- Task 15 automated checks and local browser/hardware checks are complete.
  Real phone/LAN testing remains unperformed. Browser takeover confirmation was
  reached, but automatic approval review blocked confirming it; automated
  takeover/demotion tests pass. No new password was set on the user's config.
- **New verification:** 93 Python tests (including aiohttp tests), 19 Vitest
  tests, svelte-check with 0 errors/warnings, production build, and `./sdr sim`.
  RTL capture: 75 messages, every type, 0 decode errors.
- **Browser checks:** local Viewer/Admin login, reload resume, rejected MOD
  restoration, both pages with live data, keyboard card reorder/resize and layout
  persistence, and phone/tablet viewport layouts. These viewport checks do not
  establish access from an actual phone. Simulator preview uses isolated temp
  tuning state, not the user's saved receiver settings.
- **Hardware check newly run:** GUI serial source on the attached Basys 3 at
  1 Mbaud; both channels and all seven message types. A 60-second WebSocket
  observation showed about 11.6 kB/s, 0 CRC/COBS/length errors and 0 sequence gaps.
  Tune and Telemetry were inspected in the browser. All content was SYNTHETIC.
  No build/program/flash was performed.
- **Replay check newly run:** both channels and every type arrive from
  `build/sdr/link_capture.bin` with 0 decode errors. Looping the short capture
  increases sequence-gap counters because the original sequence numbers repeat.

Review fixes include cancelling stale reconnect/tune timers, disabling tuning
on disconnect, waiting for UART cleanup before reconnect, reliable resume when
the old socket has not closed yet, an explicit failed-resume reply, reconnecting
slow viewers instead of dropping role messages, private config writes, numeric
range validation, empty-loop replay rejection, and truthful source-down reporting
for simulator wire-range errors and unexpected source exceptions. Rejected
numeric inputs restore their authoritative value. Waterfall history resets when
its frequency axis changes. Frozen canvases redraw on theme changes.

Implementation choices relative to the plan:

- Omitted the unconfirmed ±25 kHz RF deviation overlay and antenna-model labels.
  The simulator remains an explicitly synthetic toy model; these are not hardware
  decisions. Placeholder synthesizer/XADC/filter values are labelled visibly.
- Omitted the misleading “measured IF” computed from the host NCO: serial/replay
  data does not carry the actual NCO reference. Expected IF remains server-derived,
  and the received frequency offset is displayed directly.
- Added touch/keyboard card reorder buttons and clamped saved spans to available
  columns. FLIGHT plots explicitly say they are unimplemented even if frames arrive.
- The existing plan's old checkpoint and per-task commit instructions are
  historical; this continuation is recorded here and in the local progress log.

Remaining limitations/follow-ups:

- UART RX/commands, real DSP/RF acquisition, FLIGHT plots, Pi packaging, and HTTPS
  remain out of scope. “Send to FPGA” stays disabled.
- PBKDF2 password checks still run synchronously on the event loop; login bursts
  can briefly interrupt streaming. Replay pacing uses bytes, not capture timestamps;
  loop boundaries can introduce gaps or a torn frame in arbitrary recordings.
- Retained minor test gaps: direct rf_hz/LO-only updates, source pacing/cancellation
  and rate warm-up, and theme persistence failures. Hub unsubscribe remains
  non-idempotent; byte rate averages over five seconds even during startup.
- Dark/light token blocks remain duplicated and white-on-brand-red small text
  contrast could be improved. A real phone/LAN acceptance pass remains useful.

See [the GUI guide](../tools/README.md#web-gui) for build/run commands and controls.

## What exists

- **`blink`:** LED0 changes state every 0.5 seconds, with a simulation testbench.
- **`uart_tx.sv`:** a reusable 8N1, LSB-first transmitter, now run at 1 Mbaud
  (100 clocks per bit).
- **Link layer RTL:**
  - `crc16_ccitt.sv`, `cobs_encoder.sv`;
  - `link_tx.sv`, a fixed-priority framer;
  - `link_msg_port.sv`, the producer port;
  - `link_test_sources.sv`, 11 stand-in producers for all seven message types.
- **Wire format:** protocol **v2**, specified in
  [the link design](superpowers/specs/2026-09-29-host-link-layer-design.md) and
  summarized in [the SDR README](../projects/sdr/README.md).
- **`sdr_top.sv`:** the producers feed the link, LED0 toggles on each STATUS, and
  the synchronized btnC plus a power-on reset reset the design.
- **Host:**
  - `sdr_cli/protocol.py`: COBS, CRC, parsers, `StreamDecoder`, `LinkState`,
    plus spectrum axis helpers `bin_frequency()` and `power_db()`;
  - `sdr_cli/display.py`: `WaterfallScale`, with auto (default) and manual
    heatmap scaling. It is toolkit-free and used by the TUI; the GUI should use
    it too;
  - `sdr_cli/apex.py`: provisional APEX TEST/FLIGHT/HK frame parser, mirroring
    `~/git/apex` `fsw/src/radio.cpp`;
  - `sdr receive --format decoded|records` with a per-type summary;
  - dashboard LINK and SPECTRUM views (key `v`);
  - `projects/sdr/host/check_link.py`, which replaced `check_heartbeat.py`.
- **Remote builds:** each build snapshots the current sources, and hashes protect
  programming against stale sources.

Not implemented:

- real XADC acquisition (the ADC input is a synthetic waveform; the later
  stages are real logic, see the top of this file);
- a general UART command path: only the receiver's test-carrier/NCO tuning
  command is acknowledged (simulation-verified); other `sdr send` bytes are not
  acted on;
- a `BUILD_ID` set by build.tcl (the default build's parameter is 0; the demo
  RTL sets `SDRF`).

## Verified in this session

| Check | Result |
| --- | --- |
| Host regression suite | 33 tests passed: protocol, decoded CLI, dashboard LINK/SPECTRUM views in a real PTY, plus the earlier tests |
| RTL simulation (`./sdr sim`) | uart_tx, CRC, COBS (10 golden vectors), link_tx and the full top passed. The top-level test produced 75 messages of all types; the host decoded its capture with 0 errors |
| Protocol v2 (later the same session) | 38 host tests and all RTL sims passed. Bundle `build/sdr/artifacts/20260929-155318-804c62a6/`: WNS +0.711 ns, WHS +0.033 ns, DRC CFGBVS warning only, 8.3% LUTs. Programmed; `check_link.py` passed (1,128 messages, 0 errors/gaps); STATUS reports v2 and spectrum rows decode with their Hz/dBFS axis |
| Remote Vivado build (v1) | Bundle `build/sdr/artifacts/20260929-152924-1411d343/`. WNS +0.603 ns, WHS +0.108 ns; DRC shows only the CFGBVS/CONFIG_VOLTAGE warning; 7.8% LUTs, 4.4% FFs, no BRAM |
| SRAM programming | `sdr program` succeeded (not flash) |
| Hardware decode | `sdr receive --baud 1000000 --seconds 6`: 671 messages at the designed rates (STATUS 1/s, CHAN_FRAME 40/s, SPECTRUM 20/s, …); 0 CRC/COBS/length errors, 0 seq gaps, 0 producer drops |
| Hardware checker | `check_link.py`: passed 9 of 10 runs (10–20 s each, over 11,000 messages clean). The one failing run coincided with the user opening the dashboard on the same port, and it could not be reproduced. Soak captures are in `.sdr/captures/check_link-*.bin` |

Findings from this session:

- **Timing:** the first build missed timing by 6.3 ns, because producer byte logic
  was combinationally chained through `link_tx` into the COBS buffer write enable.
  `link_msg_port` now registers payload bytes with a settle `LATENCY`. The
  remaining critical path is inside the fake I/Q generator.
- **Local baud:** hardware checks used `--baud 1000000`. The user then set the
  local config to 1 000 000.

The previous checkpoint (commit `82ce6fc`, a 115200 `SDR READY` diagnostic) is
superseded; its bundle `20260929-141419-ab63dc16` is retained locally.

## GUI task

The user's requirements, 2026-09-29:

- **A desktop app in the style of SDR++** for reading from, and later
  configuring, the FPGA SDR.
- **An RF waterfall** with a live spectrum trace, per channel (A/B).
- **Scaling:** auto scaling by default, plus manual scaling, so the heatmap
  separates signal from noise from nothing out of the box, with no setup
  ("plug and play").
- **A constellation (I/Q) plot** per channel.
- **Metrics and telemetry:** RSSI and the other channel metrics, link
  statistics, and decoded telemetry.

What already exists for it:

- **Data source.** Now implemented by `sdr_cli/hub.py`, which uses one `StreamDecoder`/`LinkState`
  for every source. Do not write a second decoder. `Session.read()` returns bytes and fills
  `last_records` and `link`. AGENTS.md asks for CLI, TUI and GUI behavior to stay
  consistent.
- **Waterfall axis.** Each SPECTRUM row carries its own axis:
  - `bin_frequency(fields, k)` gives Hz;
  - `power_db(fields)` gives dBFS;
  - `center_hz`, `bin_hz`, `bins`, `t_us` and `averages` are also present.
  Frequencies are in the FPGA's IF domain (about 100 kHz). A host setting for the
  LO frequency and injection side would be needed to label RF (about 441 MHz).
- **Scaling.** `display.WaterfallScale()` provides the auto default:
  - It tracks the noise floor (20th percentile, minus 5 dB) and the peak (99.5th
    percentile, plus 3 dB).
  - It expands fast when a stronger signal appears and releases slowly.
  - It keeps a minimum 30 dB span.
  - `set_manual(low, high)` and `set_auto()` switch modes; `normalize(db)` maps
    a value to 0..1.
  Feed it one row per SPECTRUM record, per channel.
- **Constellation.** IQ_SNAPSHOT has `sample_rate_hz`, `t_us` and int16 pairs
  (full scale ±32767).
- **Current data is fake.** It exercises plumbing only:
  - The spectrum is a synthetic pattern: noise, two fixed lobes, and a walking
    tone at −30 dBFS.
  - The I/Q points are pseudo-random points on a circle, not a real FSK
    trajectory.
  - Rates are 10 spectrum rows/s and 5 snapshots/s per channel, 256 bins.
  - The FPGA flags all of it `SYNTHETIC`; show that in the UI.
  - The user accepts that it looks artificial until the DSP stages exist.

Decisions made with the user (2026-09-29, third session). The spec has the details:

- **Toolkit:** web-first. An aiohttp server (the optional `gui` extra) owns the
  UART and decoding. A Svelte 5 + TypeScript frontend in `tools/sdr_web/` builds
  into `tools/sdr_cli/web/static/`, which is ignored by Git.
  - It serves 127.0.0.1 only, unless `--lan` is given.
  - Any LAN device can view it, and a Raspberry Pi can host it later using just
    the built files.
- **Pages:** Tune (the frequency plan and IF waterfall, merged with per-channel
  signal quality) and Telemetry (cards the user can drag and resize; v1 content
  is placeholders).
- **Roles:**
  - Everyone connects as a Viewer.
  - One Admin at a time, protected by a password (`./sdr setup --gui-password`,
    stored hashed).
  - Taking over Admin asks for confirmation and notifies the previous Admin.
  - With no password set, only the server machine can become Admin.
- **Branding:** Space Raiders only, with brand red `#FB0000` used for chrome.
  Logo assets are in `tools/sdr_web/src/assets/`.
- **Configuring the FPGA is still impossible.** Tuning is shared host-side state
  (`.sdr/gui_state.json`); only `--source sim` reacts to it. "Send to FPGA" stays
  disabled until UART RX and a command protocol exist.
- **Offline development:** `sources.ReplaySource` (`--source replay --file X.bin`)
  and `sources.SimSource` (`--source sim`) exist.
- **Bandwidth:** unchanged. A smoother waterfall is still a protocol/FPGA change
  to agree first.

## Environment and recovery

The normal topology is **Mac + USB Basys 3**, with **Windows + licensed Vivado**
accessed over SSH/Tailscale. Local `.sdr/config.json` contains the configured host,
user, SSH identity path, UART device, Vivado executable path, and remote build root.
The configured Windows installation used Vivado 2026.1 with Artix-7 support.
The Mac uses Icarus, openFPGALoader, and `.venv` with the editable Python package.

Start with `git status --short`, `./sdr --help`, and the relevant local tests.
Use `./sdr doctor --remote --board` when checking live connectivity. Read
`tools/README.md` for fresh-machine installation and setup. Do not reinstall or
replace working settings just because generated files are absent from Git.

The FT2232 bridge has separate JTAG and UART interfaces. Use `./sdr ports` and
local configuration to select UART; do not assume a saved device name survives
moving the board to another computer. Only one serial monitor should own it.

If a build fails, the previous successful bundle remains selected. Read its
manifest before assuming it matches the failed build. TUI operation logs are in
`.sdr/logs/`; remote snapshots retain Vivado logs. An interrupted SSH connection
can leave the remote process running in its isolated directory.

## Intended receiver

User-supplied RF context:

- Transmitter: NiceRF RF4463PRO-433, 2-GFSK telemetry.
- Received carrier: approximately 441.480 MHz, as reported by the user.
- Analog frontend: amplification and filtering, mixing to a low IF near 100 kHz,
  then attenuation/protection before the XADC.
- Later testing will use a waveform generator to simulate that low-IF signal.
  Initial DSP work may bypass XADC using generated sample vectors.

Proposed stages (not implemented or finalized):

```text
analog frontend -> XADC acquisition -> sample conditioning
 -> digital downconversion (NCO + I/Q mixer)
 -> channel filtering / decimation -> GFSK frequency discriminator
 -> symbol timing / bit decisions -> packet framing / validation
 -> host transport -> CLI and later GUI
```

The host-facing transport was the first component chosen. Reusable modules stay
inside the SDR project, with independent tests; standalone board experiments can
have their own top-level project when needed.

## Decisions still needed

Before fixing DSP constants or packet behavior, establish:

- Actual transmitter configuration: symbol/bit rate, frequency deviation,
  Gaussian shaping, preamble, sync word, bit order, packet length, whitening,
  CRC, and any coding. The product name alone does not determine these settings.
- Actual IF center and occupied bandwidth, frontend polarity, XADC mode/rate,
  input bias/range, and the resulting digital sample representation.
- DSP sample rates, word widths, rounding/saturation, filtering requirements,
  expected frequency offset, and test-vector/reference-model conventions.
- Host commands: whether and when to add UART RX, command acknowledgement,
  NCO tuning, and stream enables. The link is currently TX-only, at roughly 11% of
  its 100 kB/s capacity; raw continuous XADC streaming would not fit.
- The defined APEX telemetry format. `sdr_cli/apex.py` mirrors the current
  firmware provisionally. Note that FLIGHT is 41 bytes, not the 38 in the APEX
  radio doc.

The GUI and source combiner are implemented. The next upstream stage on the
module map is frame sync + CRC. When a real stage lands, it replaces its stand-in
producer and keeps the message layout. Clear `SYNTHETIC` only for measured data,
never for real logic operating on synthetic inputs.
Choose the bounded component with the user, specify its interfaces, and add
meaningful self-checking tests before integrating it into the board top module.

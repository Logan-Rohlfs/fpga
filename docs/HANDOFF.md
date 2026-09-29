# SDR handoff

Checkpoint recorded 2026-09-29 (second session). **The host link layer is working
on hardware.** The FPGA sends every message type at 1 Mbaud, and the `sdr` CLI and
dashboard decode and display them.

All message content is **SIMULATED** by stand-in producers. The planned stages are
in [`docs/sdr_pipeline.drawio`](sdr_pipeline.drawio).

**The Space Raiders SDR web GUI v1 is implemented.** See [GUI implementation status](#gui-implementation-status).
The DSP stages come later; realistic displayed data waits for them.

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

- the XADC, sample conditioning, DDC, filtering, discriminator, symbol timing,
  frame sync, source combiner, FFT, and constellation capture. Every stage in the
  map is a stand-in;
- a UART RX/command path (`sdr send` bytes are not acted on);
- a real `BUILD_ID` (the parameter defaults to 0; build.tcl does not set it).

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

The user chose the GUI as the next task. After it, the next stage upstream on the
module map is the source combiner, followed by
frame sync + CRC. When a real stage lands, it replaces its stand-in producer,
keeps the message layout, and stops setting `SYNTHETIC`.
Choose the bounded component with the user, specify its interfaces, and add
meaningful self-checking tests before integrating it into the board top module.

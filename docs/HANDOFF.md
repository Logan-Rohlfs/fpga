# SDR handoff

Checkpoint recorded 2026-09-29 (second session). **The host link layer is working
on hardware.** The FPGA sends every message type at 1 Mbaud, and the `sdr` CLI and
dashboard decode and display them.

All message content is **SIMULATED** by stand-in producers. The planned stages are
in [`docs/sdr_pipeline.drawio`](sdr_pipeline.drawio).

**Current task: the Space Raiders SDR web GUI. It is partway through
implementation.** See [GUI implementation status](#gui-implementation-status).
The DSP stages come later; realistic displayed data waits for them.

## GUI implementation status

Recorded 2026-09-29 (third session). The session stopped partway through, at the
user's request.

- **Design:**
  - [Spec](superpowers/specs/2026-09-29-gui-design.md)
  - [Plan](superpowers/plans/2026-09-29-space-raiders-sdr-gui.md): 15 tasks in 6 phases.
  - A web GUI with an aiohttp server and a Svelte 5 frontend, reachable from the
    LAN with `--lan`.
  - Viewer and Admin roles, with Admin takeover.
  - Space Raiders branding.
  - The user merged the Tune and Metrics views into one Tune page.
- **Done (committed on `gui-prep`, each task reviewed):**
  - Tasks 1–7: `freqplan.py`, `roles.py`, `sources.py` (serial, replay and a
    tuning-aware simulator), `hub.py`, `web/server.py`, the `./sdr gui` and
    `./sdr setup --gui-password` commands, and the frontend scaffold (theme and
    branded shell).
  - The review rounds added fixes: oversized-number rejection, subscriber
    isolation, and handler errors that no longer drop viewers.
- **Committed but not yet reviewed:** Task 8, the frontend view helpers.
- **Not started:**
  - Task 9: the WebSocket client and stores.
  - Task 10: the app shell (status bar, role menu, theme toggle).
  - Tasks 11–13: the Tune page.
  - Task 14: Telemetry cards (v1 placeholders; lower priority).
  - Task 15: end-to-end checks and documentation.
- **What runs today:**
  - `./sdr gui` serves the branded placeholder page and a live WebSocket feed.
  - The Tune and Telemetry pages do not exist yet.
- **Verified at the stop:**
  - 84 Python tests pass.
  - 10 Vitest tests pass.
  - svelte-check reports 0 errors, and the frontend builds.
  - No LAN, phone or hardware check has been done yet.
- **Where the code intentionally differs from the plan text** (all changes came
  from task reviews):
  - `freqplan._number` rejects oversized integers with `ValueError`.
  - `Hub.publish` isolates subscriber exceptions and logs them.
  - `GuiServer` wraps `handle()` and replies with a `bad_request` error.
  - `RoleManager.resume` compares tokens as bytes.
  - The server broadcasts every accepted tune. The client coalesces tune
    messages to at most 30 Hz, which is the rate limit.
- **Minor findings deferred to the final review:**
  - `.sdr/config.json` is written 0644 even though it now holds the password hash.
  - The drop-oldest queue can drop control messages for a very slow viewer.
  - `resume` fails if the old socket has not closed yet.
  - PBKDF2 runs on the event loop.
  - There are test gaps in the server paths (resume, logout, reconnect).
- **To resume:** follow the plan from Task 8's review onward. Task 15's doc step
  should **replace** the interim "Web GUI (in progress)" section in
  `tools/README.md` and the interim README lines, not add a second copy.
  - The per-task progress log is `.superpowers/sdd/2026-09-29-space-raiders-sdr-gui/progress.md`.
    It is local and ignored by Git.
  - It lists the rulings made and the deferred minor findings, which the final
    review should triage. The two lists above are copies, in case the log is
    missing on another checkout.
  - Build the frontend before running the GUI:
    `(cd tools/sdr_web && npm install && npm run build)`.
    Install the Python side with `.venv/bin/python -m pip install -e '.[gui]'`.

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
- the GUI;
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

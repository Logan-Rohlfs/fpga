# SDR handoff

Checkpoint recorded 2026-09-29 (second session). **The host link layer is working
on hardware.** The FPGA sends every message type at 1 Mbaud, and the `sdr` CLI and
dashboard decode and display them.

All message content is **SIMULATED** by stand-in producers. The user is building
the pipeline backwards from the UART toward the XADC. The planned stages are in
[`docs/sdr_pipeline.drawio`](sdr_pipeline.drawio); the next one on that map is the
source combiner.

## What exists

- **`blink`:** LED0 changes state every 0.5 seconds, with a simulation testbench.
- **`uart_tx.sv`:** a reusable 8N1, LSB-first transmitter, now run at 1 Mbaud
  (100 clocks per bit).
- **Link layer RTL:**
  - `crc16_ccitt.sv`, `cobs_encoder.sv`;
  - `link_tx.sv`, a fixed-priority framer;
  - `link_msg_port.sv`, the producer port;
  - `link_test_sources.sv`, 11 stand-in producers for all seven message types.
- **Wire format:** specified in
  [the link design](superpowers/specs/2026-09-29-host-link-layer-design.md) and
  summarized in [the SDR README](../projects/sdr/README.md).
- **`sdr_top.sv`:** the producers feed the link, LED0 toggles on each STATUS, and
  the synchronized btnC plus a power-on reset reset the design.
- **Host:**
  - `sdr_cli/protocol.py`: COBS, CRC, parsers, `StreamDecoder`, `LinkState`;
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
| Remote Vivado build | Bundle `build/sdr/artifacts/20260929-152924-1411d343/`. WNS +0.603 ns, WHS +0.108 ns; DRC shows only the CFGBVS/CONFIG_VOLTAGE warning; 7.8% LUTs, 4.4% FFs, no BRAM |
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

The next stage upstream on the module map is the source combiner, followed by
frame sync + CRC. When a real stage lands, it replaces its stand-in producer,
keeps the message layout, and stops setting `SYNTHETIC`.
Choose the bounded component with the user, specify its interfaces, and add
meaningful self-checking tests before integrating it into the board top module.

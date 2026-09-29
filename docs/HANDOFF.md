# SDR handoff

Checkpoint recorded 2026-09-29. Feature work deliberately stops here: **UART output
from the Basys 3 to the Mac is verified.** The user will choose the next component.

## What exists

- `blink`: LED0 changes state every 0.5 seconds, with a simulation testbench.
- `uart_tx.sv`: reusable 115200-baud, 8N1, LSB-first transmitter with byte
  `valid`/`ready` flow control and active-high reset.
- `sdr_top.sv`: temporary diagnostic transmitting the 11 bytes `SDR READY\r\n`
  about once a second; LED0 toggles after each message. The center button resets it.
- `sdr`: one host entry point for setup, diagnostics, simulations, Windows builds,
  local programming, raw serial TX/RX, recordings, and a btop-inspired dashboard.
- Remote builds snapshot current sources into a unique Windows directory and fetch
  a completed artifact bundle. Source and bitstream hashes protect default
  programming against stale sources or a changed bitstream.

There is **no FPGA UART RX/command decoder**, no XADC acquisition, no RF/DSP chain,
no packet protocol, and no GUI. `sdr send` writes bytes to the host serial transport;
it does not prove the FPGA received or acted on them. Dashboard traffic statistics
are UART bytes, not ADC samples, RF power, or demodulation results.

## Verified baseline

The previous implementation session verified:

| Check | Result |
| --- | --- |
| Host regression suite | 16 tests passed, including real pseudo-terminals and curses resize/command entry |
| SDR RTL simulation | UART byte frames/reset and two complete top-level diagnostic messages passed |
| Remote Vivado build | Build and artifact download succeeded; timing report says all user constraints met |
| Local SRAM programming | `sdr program` loaded the fetched bitstream through openFPGALoader |
| Actual UART output | `sdr receive --seconds 3` received three complete diagnostic lines (33 bytes) |
| Live dashboard | Connection, text/hex, recording, simulation, resize, command entry, and exit exercised |

The implementation checkpoint is commit `82ce6fc` (host workbench), following
`4df8ff3` (UART RTL/diagnostic). These are historical results, not an assertion that
the board or Windows host is currently connected. Persistent flash was not exercised
as part of this workbench verification.

On the existing Mac, the verified bundle was
`build/sdr/artifacts/20260929-141419-ab63dc16/`, with bitstream, timing/utilization/DRC
reports, and `manifest.json`. `build/sdr/latest` selects the current bundle. These
files are intentionally not in Git; a new checkout must build them. Recordings and
local operation logs are under `.sdr/`. Preserve them during ordinary cleanup.

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
- Host framing/versioning, command acknowledgement, telemetry vs. sample output,
  and required throughput. Current 115200 8N1 has a theoretical payload ceiling
  of 11,520 bytes/s before higher-level framing; do not promise continuous raw
  XADC streaming over it.

A future task could extend the host protocol/UART RX or begin sample-input/DDC
work with synthetic vectors. Neither is implicitly selected by this handoff.
Choose the bounded component with the user, specify its interfaces, and add
meaningful self-checking tests before integrating it into the board top module.

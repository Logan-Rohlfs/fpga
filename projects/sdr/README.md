# SDR receiver

**Current state: host link layer working, carrying SIMULATED data.**
The FPGA sends every host-link message type at 1 Mbaud, and the host decodes them.
No RF, XADC, or DSP stages exist yet: stand-in producers generate all of the
content, and every message is flagged `SYNTHETIC`.

Related documents:

- [Module map](../../docs/sdr_pipeline.drawio): the full planned pipeline.
- [Link design spec](../../docs/superpowers/specs/2026-09-29-host-link-layer-design.md):
  exact message layouts.
- [Handoff](../../docs/HANDOFF.md): verification history and open decisions.
- [Host workbench](../../tools/README.md): the normal build, program, and monitor
  interface.

## Data path

```text
link_test_sources ─▶ link_tx ─▶ cobs_encoder ─▶ uart_tx ─▶ USB-UART (A18) ─▶ sdr CLI / dashboard
(11 producer ports)  priority    1024 B message   8N1
                     framer,     buffer, 0x00     1 Mbaud
                     CRC-16      delimiter
```

## Wire format

A message is `COBS(type, flags, seq, len u16, payload, crc16) ‖ 0x00`:

- all fields little-endian;
- CRC-16-CCITT, poly 0x1021, init 0xFFFF, over the header and payload;
- `flags` bit 0 is `SYNTHETIC`, bit 1 is `EMPTY`;
- `seq` counts every message and wraps at 256.

| Type | Message | Fake rate | Contents |
| --- | --- | --- | --- |
| 0x01 | STATUS | 1 Hz | version, channel mask, uptime ms, build ID, dropped count |
| 0x10 | BEST_TELEM | 20 Hz | selected source + raw APEX frame |
| 0x11 | CHAN_FRAME | 20 Hz × A/B | CRC ok, RSSI, sync quality, Δf, raw APEX frame |
| 0x20 | CHAN_METRICS | 10 Hz × A/B | RSSI, noise, SNR, Δf, sync hits, CRC good/bad |
| 0x21 | LINK_STATS | 1 Hz | frames from A / B / both OK / neither |
| 0x30 | SPECTRUM | 10 Hz × A/B | 256 u8 power bins (0.5 dB/LSB) |
| 0x31 | IQ_SNAPSHOT | 5 Hz × A/B | 64 int16 I/Q pairs |

Fake traffic is about 11 kB/s, roughly 11% of the link's capacity.

## Stand-in content

The fake telemetry is a real APEX TEST frame: type 0x01, seq, `APEX RADIO TEST`,
and a CRC-16 sent big-endian. The CRC is computed in RTL, so the host's APEX parser
checks it end to end.

- Channel A fails CRC every 11th frame and channel B every 7th. Failed frames
  flip the last CRC byte.
- BEST_TELEM uses A unless A failed, then B. Nothing is sent when both fail.
- Spectrum rows show a noise floor, two FSK lobes, and a walking tone.
- I/Q snapshots are points on a noisy circle; channel B's is half the radius.

## Hardware interfaces

**Producer ports** (`link_msg_port.sv` → `link_tx.sv`):

1. A producer holds `req` and a stable `type/flags/len` header.
2. `link_tx` grants whole messages, lowest port index first.
3. The producer then supplies `len` payload bytes.
4. Each port registers its payload byte and waits `LATENCY` cycles after every
   index change. Producer logic can therefore pipeline freely without joining the
   `link_tx`/encoder timing path.
5. If a message is due while the previous one is still pending, it is dropped,
   and STATUS reports the drop.

**Encoder** (`cobs_encoder.sv`):

- encodes one message at a time into a LUTRAM buffer;
- backpatches code bytes as blocks close;
- streams the result plus `0x00` to `uart_tx`.

**Board top** (`sdr_top.sv`):

- **LED0** toggles on every STATUS message.
- **btnC** (synchronized) resets the design, and a 15-cycle power-on reset
  follows configuration.
- **Parameters:** `BAUD_RATE` (1 000 000 by default), `TICK_CYCLES`,
  `STATUS_TICKS`, and `BUILD_ID` (0 by default).

**`uart_tx.sv`** is unchanged. It is 8N1 and LSB-first; at 100 MHz, 1 Mbaud is
exactly 100 clocks per bit. `ready` is low during a frame and during reset.

## Test and use

From the repository root:

```sh
./sdr sim                          # all RTL testbenches + host decode of the simulated line
./sdr build && ./sdr program
./sdr receive --seconds 5          # decoded messages + per-type summary
.venv/bin/python projects/sdr/host/check_link.py --port YOUR_UART_DEVICE --seconds 10
```

The simulations:

| Testbench | Checks |
| --- | --- |
| `sim/uart_tx_tb.sv` | UART frames and reset |
| `sim/crc16_ccitt_tb.sv` | CRC check value and an APEX frame |
| `sim/cobs_encoder_tb.sv` | byte-exact output against `sim/vectors/cobs_golden.hex`, with random stalls |
| `sim/link_tx_tb.sv` | priority, atomic messages, empty payloads, seq wrap, CRC |
| `sim/sdr_top_tb.sv` | the whole top level; see below |

`sim/sdr_top_tb.sv`:

- decodes the UART line;
- checks COBS, CRC, per-type lengths, contiguous seq, APEX CRCs, zero drops,
  and the LED;
- saves the line as `build/sdr/link_capture.bin`. `make sim` then decodes that
  file with the host decoder, so the RTL and Python implementations are
  cross-checked on every run.

Regenerate the golden vectors after changing the COBS algorithm:

```sh
PYTHONPATH=tools python3 -m sdr_cli.protocol --golden projects/sdr/sim/vectors/cobs_golden.hex
```

`host/check_link.py` is the standalone hardware assertion. It needs only pyserial
(`host/requirements.txt`) plus the repository's `tools/`. It passes when every type
decodes with no CRC/COBS/length errors and no seq gaps, and `--output FILE` saves
the raw bytes. Close the dashboard and other serial readers first: two readers
split the byte stream, and both then see corrupt messages.

Direct Windows builds are still possible with
`vivado.bat -mode batch -source scripts/build.tcl -tclargs sdr`. Those write the
legacy `build/sdr/sdr.bit`; the workbench instead selects bundles through
`build/sdr/latest`.

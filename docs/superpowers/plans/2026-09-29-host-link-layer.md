# Host Link Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement
> this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The FPGA transmits every host-link message type with synthetic data over
1 Mbaud COBS-framed UART, and `./sdr receive` and the dashboard decode and display them.

**Architecture:** Stand-in producers feed `link_tx`, a fixed-priority arbiter that adds
the header and CRC. Its output goes to `cobs_encoder` (single message buffer), then to the
existing `uart_tx`. On the host, `protocol.py` decodes the stream into typed records and a
`LinkState` aggregate, which `serial_io.Session`, the CLI and the TUI all share.

**Tech Stack:** SystemVerilog (Icarus `-g2012`, Vivado 2026.1), Python 3.9+ stdlib + pyserial.

**Spec:** `docs/superpowers/specs/2026-09-29-host-link-layer-design.md`

## Global Constraints

- Wire format, message layouts, CRC (0x1021/0xFFFF, check 0x29B1) and COBS rules: exactly as the spec.
- Baud 1 000 000; `CLK_HZ` 100 MHz on hardware; all timing parameterized for simulation.
- Every stand-in message sets `flags.SYNTHETIC`; the host marks those records SIMULATED.
- Python 3.9 compatible (no `match`, no `X | Y` types at runtime).
- New RTL goes directly in `projects/sdr/rtl/*.sv`, so `build.tcl` and `core.source_files` pick it up unchanged.
- No subagents; tests: `./sdr sim` and `PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v`.

---

### Task 1: Host protocol core (`protocol.py`, `apex.py`)

**Files:** Create `tools/sdr_cli/protocol.py`, `tools/sdr_cli/apex.py`, `tools/tests/test_protocol.py`.

**Produces:**
- `crc16_ccitt(data: bytes, crc=0xFFFF) -> int`
- `cobs_encode(data: bytes) -> bytes` (no delimiter) and `cobs_decode(data: bytes) -> bytes` (raises `ValueError`)
- `encode_message(mtype, payload, seq=0, flags=FLAG_SYNTHETIC) -> bytes` (includes the trailing `0x00`)
- Constants `FLAG_SYNTHETIC=1`, `FLAG_EMPTY=2`, and type constants `STATUS=0x01`, `BEST_TELEM=0x10`,
  `CHAN_FRAME=0x11`, `CHAN_METRICS=0x20`, `LINK_STATS=0x21`, `SPECTRUM=0x30`, `IQ_SNAPSHOT=0x31`; `TYPE_NAMES`
- `Record` dataclass `(type, name, flags, seq, fields: dict, synthetic: bool, t: float)`
- `parse_message(raw: bytes) -> Record` (raises `ValueError`), `format_record(rec) -> str`
- `StreamDecoder` with `.feed(bytes) -> list[Record]` and a `.stats` dict: `messages, by_type, crc_errors,
  cobs_errors, length_errors, resync_bytes, seq_gaps, synthetic`
- `LinkState` with `.update(records)`, `.status`, `.metrics[ch]`, `.frames` deque, `.best` deque,
  `.link_stats`, `.spectrum[ch]` deque of rows, `.iq[ch]`, and `.rates() -> dict name->msg/s`
- `apex.parse_frame(raw: bytes) -> dict` with keys `type, kind, crc_ok, fields`

**Tests:** the CRC check value 0x29B1; COBS vectors (`b''`, `b'\x00'`, `b'\x00\x00'`, `b'\x11\x22\x00\x33'`,
254×0x01, 255×0x01, 253 nonzero + 0); a round-trip over random data; each type's parse; a
fragmented feed; resync after garbage, a bad CRC and truncation; seq-gap count including wrap;
unknown type; and an APEX TEST frame parse with good and bad CRC.

- [ ] Write the tests; run them and confirm they fail (import error)
- [ ] Implement; run the tests until they pass
- [ ] Generate `projects/sdr/sim/vectors/cobs_golden.hex` via `python -m sdr_cli.protocol --golden PATH`
      (format: one message per line, `in:<hex> out:<hex>`)
- [ ] Commit

### Task 2: RTL CRC + COBS encoder

**Files:** Create `projects/sdr/rtl/crc16_ccitt.sv`, `projects/sdr/rtl/cobs_encoder.sv`, and
`projects/sdr/sim/crc16_ccitt_tb.sv`, `projects/sdr/sim/cobs_encoder_tb.sv`; modify `Makefile`.

**Interfaces:**
- `crc16_ccitt(input [15:0] crc, input [7:0] data, output [15:0] next)`: combinational.
- `cobs_encoder #(DEPTH=1024)`, ports `(clk, rst, in_data[7:0], in_valid, in_last, in_ready,
  out_data[7:0], out_valid, out_ready)`. It accepts one message, then outputs its COBS bytes plus `0x00`.

**Tests:**
- CRC: `"123456789"` → 0x29B1, and the APEX TEST frame CRC matches the Python value.
- COBS: for each line of the golden file, feed the input with random `in_valid`/`out_ready` gaps
  and compare the output byte for byte.

- [ ] Write the testbenches; run `make sim PROJECT=sdr` and confirm they fail
- [ ] Implement; run until they pass
- [ ] Commit

### Task 3: `link_tx` arbiter/framer

**Files:** Create `projects/sdr/rtl/link_tx.sv` and `projects/sdr/sim/link_tx_tb.sv`; modify `Makefile`.

**Interface:** `link_tx #(N)`, ports `(clk, rst, req[N], type[8N], flags[8N], len[16N], grant[N],
p_data[8N], p_valid[N], p_ready[N], out_data, out_valid, out_last, out_ready, sent_type[7:0], sent_pulse)`.
Port 0 has the highest priority, and arbitration happens only between messages.

**Test:** two scripted producers requesting at the same time. Check that the higher priority wins,
the whole message is atomic, the header bytes and seq increment are correct, and the CRC matches
a reference task.

- [ ] Write the test and confirm it fails; implement; run until it passes; commit

### Task 4: Stand-in producers and new top

**Files:** Create `projects/sdr/rtl/link_test_sources.sv`; rewrite `projects/sdr/rtl/sdr_top.sv` and
`projects/sdr/sim/sdr_top_tb.sv`.

**Top parameters:** `CLK_HZ`, `BAUD_RATE=1_000_000`, `TICK_CYCLES=CLK_HZ/100`, `BUILD_ID=0`.

**Top testbench:**
- Runs a UART monitor, then COBS-decodes and CRC-checks every message.
- Checks the per-type length rules.
- Requires every type (STATUS ×2, CHAN_FRAME with both CRC outcomes, SPECTRUM rows, IQ, and so on),
  a contiguous seq, and the LED toggle.

- [ ] Write the testbench; implement; run `./sdr sim` until it passes; commit

### Task 5: Host integration (Session, CLI, TUI, checker)

**Files:** Modify `tools/sdr_cli/serial_io.py`, `cli.py`, `tui.py`, and `core.py` (default baud);
create `projects/sdr/host/check_link.py`; extend `tools/tests/test_workbench.py` and `test_terminal.py`.

**Behavior:**
- `Session.decoder` and `Session.link` are updated in `read()`.
- `receive --format decoded` is the new default; `records` gives JSON lines; every receive ends
  with a summary.
- The TUI `v` key toggles the LINK view.
- Existing tests keep passing.

- [ ] Write the tests: a fake serial feeding encoded messages gives decoded CLI lines and a summary,
      and the TUI LINK view renders `SIMULATED` and the channel labels
- [ ] Implement; run the full host suite; commit

### Task 6: Hardware + docs

- [ ] `./sdr build`; inspect the timing, DRC and utilization reports
- [ ] `./sdr program`; set the baud to 1 000 000 (with the user's OK); run `./sdr receive --seconds 10`
      and `check_link.py`
- [ ] Retire `check_heartbeat.py` only after the hardware pass. Update the READMEs and `docs/HANDOFF.md`
      with the tested and unimplemented items. Commit.

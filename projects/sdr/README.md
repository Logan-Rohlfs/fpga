# SDR receiver

**Current state: UART output diagnostic only.** No RF or XADC signals are connected.
Read [the handoff](../../docs/HANDOFF.md) for receiver context, verified history,
and parameters that remain unknown. Use [the host workbench](../../tools/README.md)
as the normal build/program/monitor interface.

## Hardware interfaces

`rtl/uart_tx.sv` accepts an 8-bit byte on a rising clock edge when `valid && ready`.
The producer must retain a pending byte until accepted. The transmitter sends
one start bit, eight data bits LSB first, and one stop bit; the idle line is high.
`ready` is low during a frame and during reset. Active-high `rst` clears state on
the clock edge and forces the output idle while asserted; a mid-frame reset aborts
that frame. There is no queue in this module.

Parameters default to `CLK_HZ=100_000_000`, `BAUD_RATE=115_200`. The divider rounds
the clock/baud ratio to an integer (868 clocks per bit at the defaults).

`rtl/sdr_top.sv` connects that transmitter to an 11-byte diagnostic message ROM.
It sends `SDR READY\r\n`, waits for the final byte to finish, toggles LED0, then
waits `HEARTBEAT_CYCLES` (default 100 million clocks) before sending again.
The center button resets the diagnostic. Pin/clock assignments are in
`constraints/basys3.xdc`; the UART RX pin is only a comment for future work.

This heartbeat is a temporary bring-up diagnostic, not a packet protocol or
firmware capability negotiation. The future receiver stages are described in
the handoff; keep the UART module reusable when the top-level design evolves.

## Test and use

From the repository root:

```sh
./sdr sim
./sdr build
./sdr program
./sdr receive --seconds 5
```

`sim/uart_tx_tb.sv` checks byte frames and reset behavior.
`sim/sdr_top_tb.sv` decodes two complete messages and checks the LED heartbeat.
The tests accelerate timing via parameters; the board uses the 100 MHz clock.

The standalone checker remains available as a narrow hardware assertion:

```sh
.venv/bin/python projects/sdr/host/check_heartbeat.py --port YOUR_UART_DEVICE
```

It verifies three complete lines. Its minimal `host/requirements.txt` is for
running that checker alone; installing the workbench also provides pyserial.
Close the dashboard or other serial readers before running it.

Direct Windows builds are still possible with
`vivado.bat -mode batch -source scripts/build.tcl -tclargs sdr`. Those write the
legacy `build/sdr/sdr.bit`; the workbench instead selects bundles through
`build/sdr/latest`. Use the matching programming path as described in the root
README. A Vivado build is unnecessary for changes confined to Python or docs.

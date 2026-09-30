# End-to-end SDR work plan

Primary agent coordinates contracts, integration, review, and acceptance.
Implementation agents own separate files and report concise interface/results.

- [x] ADC-only synthetic input with independent Gaussian reference vectors
- [x] DDC, channel filtering, discriminator and symbol timing
- [x] Configurable synchronization, frame assembly and CRC
- [x] Independent sample-to-frame integration tests
- [x] Real sample-derived spectrum, I/Q, metrics and transport
- [x] Default board integration and applied tuning behavior (simulation verified)
- [ ] Regression and independent review
- [ ] Vivado and attached-board/GUI verification
- [ ] Documentation and explicit remaining limitations

See [contract](../specs/2026-09-29-sample-driven-receiver.md).

## Remaining tasks (subagent-driven completion, 2026-09-30)

Global constraints: the receiver contract above is binding. No output message
layouts, measurement conventions (64-point DFT at 100 kS/s, coarse log, dBFS
flag 0x04, SYNTHETIC provenance) or UART command semantics change. `./sdr sim`
and host unit tests must keep passing. `scripts/build.tcl` and
`core.py:source_files` must agree. 100 MHz clock on the Basys 3 (xc7a35t).
`program` only (volatile); never `flash`.

### Task 1: Timing and area closure

The first Vivado run (`build/sdr/failed-20260929-190956-6f3870be/`) failed setup
by -16.941 ns (10,904 failing endpoints) and used 20,185/20,800 LUTs (97%),
33 DSPs, 2 BRAM tiles. The worst path is in `rx_observer`
(`bin_db_reg` -> `working_spectrum_reg`, 26.8 ns data path); I/Q and spectrum
working/output buffers are wide flip-flop arrays (`working_iq_reg[1985]`).

- Restructure `rx_observer` (and any other offending module the reports name)
  so buffers use inferred block/distributed RAM with sequential read-out, and
  the DFT/magnitude/log arithmetic is pipelined or time-multiplexed. The
  2-channel receiver has ~1000 clocks per decimated sample and far more per
  report period; exploit that.
- Preserve every emitted payload value bit-for-bit where the existing tests pin
  them; if a restructuring changes latency only, update test timing, not
  expected values. The existing focused testbenches must still pass unchanged
  in their assertions.
- Run `./sdr sim`, host unit tests, then `./sdr build`. Iterate until WNS >= 0
  and WHS >= 0 at 100 MHz with no DRC errors (the known CFGBVS/CONFIG_VOLTAGE
  warning is acceptable), and LUT use leaves headroom (target <= 80%).
- Record build id, WNS/WHS, LUT/FF/BRAM/DSP numbers in the report. Preserve
  failed-build report directories.

### Task 2: Independent review of the receiver chain

Read-only review of the full receiver RTL, host decoding, receiver control and
GUI changes on this branch against the contract. Findings are fixed by a
separate fix dispatch, then `./sdr sim`, host tests and (for RTL changes)
`./sdr build` timing must still pass.

### Task 3: Board and GUI acceptance

With the timing-clean bitstream from Tasks 1-2: `./sdr program` (volatile),
capture UART for >=15 s into `.sdr/captures/receiver-<date>.bin`, decode with
zero CRC/COBS/length errors, confirm decoded APEX TEST frames with good CRC on
both channels, sample-derived SPECTRUM/IQ/metrics with the dBFS flag, and
SYNTHETIC provenance. Exercise the UART tuning command (retune test carrier and
NCO, confirm CONFIG acknowledgement and that decode is lost on mismatch and
recovers on match; disable transmitter and confirm noise-floor measurements
keep updating). Start the web GUI against the port and confirm it renders
live data and acknowledged tuning. Only claim hardware results actually
observed in this run.

### Task 4: Documentation and limitations

Update `docs/HANDOFF.md`, `projects/sdr/README.md`, relevant tool READMEs and
this plan's checklist with the verified checkpoint, the operating envelope,
exact commands, and explicit remaining limitations (XADC acquisition, physical
PLL, calibrated dBm, guessed radio profile). Check links and commands.

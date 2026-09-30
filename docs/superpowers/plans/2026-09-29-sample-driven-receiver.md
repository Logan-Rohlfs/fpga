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

### Task 5: APEX flight replay demo (opt-in build variant)

User request (2026-09-30): replay the IREC 2026 flight as if transmitted by the
APEX RF4463 at 441.480 MHz 2GFSK, with noise and signal loss, through the full
digital receiver. It is an add-on to show off: the default bitstream, its
profile and its resource use stay unchanged. The demo is selected at build time
(e.g. `./sdr build --demo`), and no board or wiring changes are needed.

Source facts: `.superpowers/sdd/2026-09-29-sample-driven-receiver/apex-radio-facts.md`
(extracted from `apex/fsw/src/radio.cpp` and related files, with citations).
Use its values. Where it says UNKNOWN or INFERRED, pick a documented,
configurable assumption and label it (e.g. Gaussian BT 0.5).

- Demo radio profile, from the firmware: 10 kbit/s, +/-25 kHz deviation, 64-bit
  0xAA preamble, 16-bit sync 0x2DD4, type byte + body (FLIGHT 0x02 = 41-byte
  body), CRC16-CCITT 0x1021/0xFFFF big-endian over type+body, no whitening,
  20 Hz cadence. Bit order is taken from the facts file. Keep the existing
  1 MS/s ADC and 100 kHz IF (an analog-frontend assumption); 441.480 MHz is the
  RF label the GUI frequency plan shows.
- ROM content: a Python generator reads
  `/Users/loganrohlfs/git/apex/sim/output/log_exports/Flight_02_2026-06-17T21-28-54-800/IREC-2026-SRAD-TELEMETRY.csv`.
  - It takes SAMPLE rows from 2 s before LAUNCH_DETECTED through 3 s after
    apogee (the phase change out of COAST).
  - It resamples at 20 Hz (latest sample at or before each tick) and packs the
    FLIGHT struct exactly per the facts file.
  - The radio seq is a counter from 0, because the CSV seq is a log counter.
    Fields absent from the CSV are zero. Both choices are documented.
  - Output is a checked-in `.mem` file under `projects/sdr/`, plus a regeneration
    command. The CSV lives outside this repo, so the build must not depend on it.
    Add the ROM asset to BOTH `scripts/build.tcl` and `core.py:source_files`.
- The ROM feeds the existing `adc_signal_source` test transmitter, which does the
  live GFSK modulation into ADC samples. Playback loops with a short, documented
  gap. It stays SYNTHETIC provenance.
- Impairments: additive noise plus a deterministic per-loop signal-loss window.
  Channels A and B get different loss windows, so the source combiner visibly
  covers one channel's dropout with the other.
- The demo receiver is configured for the demo profile. Extend `rx_frame_decoder`
  configurability for 16-bit sync and a type-implied length only as far as
  needed, keeping default-profile behaviour and tests unchanged.
- Tests:
  - A focused testbench decodes the demo ROM frames bit-exact from the RTL
    transmitter, including the loss windows.
  - An independent Python reference checks the generated frames against the CSV
    rows they came from.
  - `./sdr sim` covers both the default and demo builds.
  - A demo `./sdr build` meets timing (WNS/WHS >= 0) with no DRC errors.

### Task 6: GUI flight readout for APEX FLIGHT frames

Host-side decode of the APEX FLIGHT (0x02) payload layout from the facts file
into named fields (altitude, velocity, vertical acceleration, phase, and so on).
Show a compact flight card in the Telemetry view: current values plus an altitude
trace, labelled "Replayed flight data (synthetic ADC)" when SYNTHETIC is set.
The decode lives in Python (toolkit-free module), and the frontend only draws.
Unknown payload types show raw bytes as they do today. No new dependencies.

### Task 7: Parallel, thread-sized Vivado builds

User request (2026-09-30). The Windows build host has 12 cores. Vivado on
Windows defaults to 2 threads, and `general.maxThreads` caps at 8.

- `scripts/build.tcl` sets `general.maxThreads` from a tcl argument, not a
  hard-coded value.
- `./sdr build` can build several variants concurrently, e.g. default + demo,
  each in its own isolated remote directory and local bundle. Each build gets
  threads = clamp(host_cores // concurrent_builds, 1, 8). Host cores come from
  the remote (`$env:NUMBER_OF_PROCESSORS`), with a config/CLI override.
- Concurrent builds must not share local temp, snapshot or output paths. The
  per-build "sources changed during build" check still works. Logs from
  concurrent builds are prefixed with their variant so they stay readable.
- CLI and dashboard expose the same operation (AGENTS.md). Host unit tests cover
  the thread calculation, argument plumbing and path isolation, without a real
  remote.
- Verify with one real parallel default + demo build. Report wall-clock time
  against the previous serial builds, plus timing for both bitstreams.

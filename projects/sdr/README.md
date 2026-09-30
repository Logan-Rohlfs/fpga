# SDR receiver

The default design runs a sample-driven receiver. **Only the ADC input is
synthetic**: downstream I/Q, spectrum, signal estimates, bits, packets, CRC
results and source selection come from those samples. This is a configurable
engineering test profile, not a verified RF4463 configuration or real RF reception.
See [HANDOFF](../../docs/HANDOFF.md) for the latest simulation and hardware evidence.

## Data path

```text
ADC waveform model (A/B signed 12-bit samples)
  -> NCO + quadrature mixer -> integrate-and-dump filter / decimator
  -> phase discriminator -> transition-based symbol timing
  -> sync / byte assembly / optional dewhitening / CRC
  -> A/B source combiner -> host link -> USB UART -> CLI / web GUI

Decimated I/Q -> 64-point complex DFT, power/noise estimates, I/Q snapshots
             -> host link
```

`rx_pipeline.sv` is the sample-to-frame boundary for eventual real ADC input.
`receiver_link_sources.sv` connects two pipelines, observers and the combiner to
the existing producer ports. `sdr_top.sv` defaults to this chain.
`LEGACY_LINK_TEST=1` selects the old transport-only fixture; it is retained for
independent link regression and is not the receiver's default source.

Each `rx_observer` keeps its captured I/Q and spectrum bytes in small inferred
RAMs with registered byte read ports. `receiver_link_sources` streams SPECTRUM and
IQ_SNAPSHOT bodies straight from those ports and releases the observer (`ready`)
only after both messages have been sent, so there is no second wide copy. The DFT
is time-multiplexed (one complex multiply-accumulate per three clocks); the
decimator's divide and the ADC model's bit/tone arithmetic are registered
pipelines. These latency-only changes leave every payload value unchanged.

## Provisional configurable profile

| Setting | Default | Where to change |
| --- | --- | --- |
| Clock / ADC rate | 100 MHz / 1 MS/s | Top/source parameters |
| ADC representation | signed 12-bit, zero centered | Sample interface; real XADC needs offset/scale adapter |
| IF / digital NCO | 100 kHz / 100 kHz | Acknowledged UART tuning or initial FTW parameters |
| Modulation | binary GFSK, 10 kbit/s, ±20 kHz deviation | ADC source parameters |
| Gaussian shaping | five binomial taps at quarter-symbol spacing | ADC test source; Python reference uses a Gaussian kernel |
| Channel filtering | first-order CIC, decimation 10 | `rx_channel` / `rx_pipeline` parameters |
| Symbol timing | 10 decimated samples/symbol, transition recentering | Pipeline parameter |
| Framing | 64 alternating preamble bits, sync D391D391 | ADC source and decoder parameters |
| Frame | 19-byte APEX TEST including two CRC bytes | Decoder/source profile |
| CRC | CCITT 1021, init FFFF, big-endian trailer | Decoder parameters |
| Whitening | disabled | Decoder enable/seed/polynomial parameters |

The decoder also supports configurable payload bit order, inversion, sync width,
CRC initial/final values and byte order, frame length, and type/sequence offsets.
Both ends of a test profile must agree. The bundled host controller recognizes
the default 1 MS/s profile; a different compiled profile must also update its
validation and frequency-word conversion.

This receiver is a functional starting point, not a characterized production
radio. The simple channel filter has limited adjacent-channel rejection. Symbol
recovery and frequency-offset tolerance are bounded by the configured profile;
there is no automatic modulation identification, general clock recovery for
arbitrary rates, or automatic carrier-frequency acquisition loop.

## APEX flight replay demo (opt-in build)

A separate bitstream replays the IREC 2026 flight as if the APEX RF4463 sent it
at 441.480 MHz. The frames pass through the full digital receiver with noise and
signal loss. It is an add-on. The default bitstream, its profile, resources and
BUILD_ID do not change. Select it at build time; no board or wiring changes:

```sh
./sdr build --demo        # dashboard: ":build demo"; Vivado: -tclargs sdr demo
./sdr program --demo      # programs the demo bundle (build/sdr/latest-demo)
./sdr program             # the default bundle (build/sdr/latest) is unaffected
./sdr build --all         # both variants at once, Vivado threads split across them
```

`sdr_top` parameter `DEMO_FLIGHT=1` selects it. STATUS then reports BUILD_ID
`SDRF` (0x53445246) instead of `SDR1`. The ADC input is still generated, so
every record stays `SYNTHETIC`.

| Setting | Demo value | Basis |
| --- | --- | --- |
| Bit rate / deviation | 10 kbit/s, ±25 kHz 2GFSK, bit 1 = +dev | apex `config.h`, `radio.cpp` |
| Preamble / sync | 8 × 0xAA (first bit 1), 16-bit 0x2DD4, MSB first | `radio_build_frame()` |
| Frame | type 0x02 + 41-byte FLIGHT body + CRC16 (44 bytes after sync) | `TelemFlight`, static_assert 41 |
| CRC | CCITT 1021, init FFFF, over type+body, big-endian trailer | `radio.cpp` |
| Length | none on air; the decoder accepts type 0x02 only (`TYPE_FILTER`) | type implies length |
| Cadence | one frame per 50 ms slot (20 Hz) | `RADIO_TELEM_FLIGHT_HZ` |
| Gaussian shaping | binomial taps, approx. BT 0.5 | **assumed**: firmware leaves the chip default |
| ADC / IF | 1 MS/s, 100 kHz, as the default | **assumed** analog front end |
| Noise | uniform ±256 LSB on both channels (A tone 1400, B tone 1000) | demo choice |
| Loss windows | A: slots 60–69, B: slots 228–237 (0.5 s each, every loop) | demo choice |
| Loop | 293 frames, then 20 silent slots (1 s); 15.65 s per loop | demo choice |

Antenna A loses the signal about 1 s after launch detect, during the fast coast.
B loses it across the COAST→DESCENT change at slot 233. During each window the
combiner's BEST output comes from the other antenna.

The ROM is `rom/apex_flight.mem`: 293 frames × 42 bytes (type + body) =
12,306 bytes in block RAM. The transmitter appends the CRC. The file is checked
in, so builds do not need the flight CSV. Regenerate it with the apex checkout
next to this repository:

```sh
python3 projects/sdr/host/apex_flight_rom.py            # rewrite rom/apex_flight.mem
python3 projects/sdr/host/apex_flight_rom.py --check    # confirm it is current
```

`host/apex_flight_rom.py` documents the replay choices and holds the FLIGHT field
table (`FLIGHT_FIELDS`, offsets and firmware scaling), matching
`tools/sdr_cli/apex.py`. The window runs from 2 s before LAUNCH_DETECTED to 3 s
after the PHASE event leaving COAST. Frames are sampled at 20 Hz with a
latest-row-at-or-before hold. The radio seq counts from 0, because the CSV seq
is a log counter. Fields missing from the log are zero: status flag bits,
sensor/radio health bits, tilt and azimuth. The once-per-second HOUSEKEEPING
beat is not replayed.

Simulation: `flight_decoder_tb` (bit-level framing), `flight_replay_tb` (ROM ->
GFSK ADC -> both pipelines -> combiner, bit-exact; each loss-window edge and the
loop wrap), and `flight_top_tb` (demo `sdr_top` over UART). Then
`check_receiver.py --demo --rom rom/apex_flight.mem` checks the capture.
`tools/tests/test_apex_flight_rom.py` checks the ROM against the CSV with the
host APEX parser. On hardware, the same checker runs with
`--port DEVICE --demo --rom projects/sdr/rom/apex_flight.mem`.

## Measurements and provenance

- Spectrum is an actual rectangular-window 64-point complex DFT at 100 kS/s:
  1562.5 Hz bins, centered on the applied NCO. There is no walking test tone.
- I/Q snapshots contain 64 actual decimated sample pairs.
- Signal power and noise are **relative dBFS**, not calibrated antenna dBm.
  Flag bit 2 (`0x04`) identifies this unit in channel/frame metric records;
  legacy records retain their previous labels. A coarse logarithm approximation
  is used, and full scale accounts for the DDC gain.
- Noise is estimated from outer spectrum bins and SNR from the corresponding
  power difference. Filtering, leakage, bursts and out-of-band signals bias this
  estimate; it is not a calibrated noise figure or sensitivity measurement.
- Frequency offset averages unwrapped I/Q quadrant changes. Modulation content
  affects this estimate; it is not an independent crystal-frequency measurement.
- Every record remains `SYNTHETIC` because the ADC waveform is generated. Real
  logic does not make synthetic input become measured RF data.

## Runtime tuning

`./sdr gui` uses the serial receiver by default. On this development bitstream,
LO changes alter the simulated ADC carrier IF; NCO changes alter the real digital
mixer. The GUI detects capability from CONFIG reports, sends bounded commands,
and distinguishes requested settings from acknowledged applied settings. It does
**not** program a physical PLL. Compiled sample-rate/filter/profile fields are
locked; an explicit Admin action restores the compiled profile if saved settings
are incompatible.

A command is ASCII `SR`, version 1, sequence, carrier FTW u32, NCO FTW u32,
transmitter enable u8, and CRC16 CCITT (little-endian fields and trailer).
CONFIG type `0x02` reports sequence, status, and applied words/enable. Sequence
255 is an unsolicited report. A raw host write is never an acknowledgement.
The transport drains before applying a new profile and resetting receiver state.
Disabling the test transmitter keeps the ADC sample clock running, so silence
continues to flow through measurements.

`./sdr gui --source sim` remains the explicitly labelled **legacy UI demo**;
it generates host-side fake records and is not the sample-driven acceptance path.
Replay cannot react to tuning.

## Wire transport and hardware

The existing protocol v2 envelope remains:
`COBS(type, flags, sequence, length u16, payload, CRC16) + 0x00`.
The new optional CONFIG record and dBFS flag extend it without changing the
existing seven message payload layouts. See the [link spec](../../docs/superpowers/specs/2026-09-29-host-link-layer-design.md)
and [receiver contract](../../docs/superpowers/specs/2026-09-29-sample-driven-receiver.md).

The Basys 3 runs UART at 1 Mbaud (8N1), TX A18 and RX B18. LED0 toggles on STATUS;
btnC resets the design. The FPGA still uses volatile programming for normal work.
No XADC electrical interface or physical PLL driver is asserted to exist.

## Test and use

```sh
./sdr sim                 # focused tests, independent ADC vectors, receiver and link UART tests
./sdr build               # remote Vivado; checks timing before producing a selected bundle
./sdr program             # volatile SRAM configuration, not flash
./sdr gui                 # actual serial receiver data and acknowledged test tuning
.venv/bin/python projects/sdr/host/check_receiver.py --help
```

Tests include clean/noisy/offset Gaussian ADC vectors, deliberate CRC corruption,
synthesizable ADC output, framing recovery, stalls, signal disable/recovery,
DFT placement/scaling, command validation, whole-UART payload checks, and the
independent legacy transport tests. `utilization.rpt` includes a per-module
hierarchy table, and `timing.rpt` ends with a one-line-per-endpoint summary of the
100 worst paths. Generated captures and reports remain in
ignored `build/` and `.sdr/captures/` directories. Close other UART readers before
hardware checks; two readers split the byte stream.

# Sample-driven receiver contract

The user explicitly authorized guessed, configurable input characteristics and
subagent-driven completion through the full digital chain. This supersedes the
previous requirement to wait for actual transmitter settings. Guesses are a test
profile, never claims about the RF4463 configuration or analog hardware.

## Acceptance boundary

Only the input ADC waveform is synthetic in the default board pipeline. Packet
bits, frame CRC results, counters, signal strength, I/Q and spectrum must derive
from received samples. Legacy link_test_sources remains an explicit transport
fixture, not the default receiver. Synthetic provenance propagates throughout.
Actual XADC electrical acquisition and an unidentified physical PLL driver are
outside the simulated-input boundary; expose clean sample and tuning interfaces.

Default profile: 100 MHz clock, 1 MHz signed 12-bit sample stream, 100 kHz IF,
10 kbit/s binary GFSK, 20 kHz deviation, approximately Gaussian shaping,
64 alternating preamble bits, MSB-first sync D391D391, 19-byte APEX TEST payload
including CRC16 CCITT (1021, FFFF, big-endian trailer), no whitening.
All these assumptions must be adjustable with documented parameters. An
independent Python waveform generator uses an actual Gaussian kernel.

## Interfaces and ownership

- adc_signal_source: clk/rst/enable, carrier_ftw[31:0] -> sample_valid,
  signed sample_a/sample_b[11:0]. Contains test transmitter only. No hidden
  receiver metadata. Sample rate, bitrate, deviation, amplitude/noise/delay and
  frame profile are parameters. Owner: ADC agent.
- rx_channel: clk/rst/sample_valid/sample_data signed12/nco_step32 -> iq_valid,
  iq_i/iq_q signed16, bit_valid/bit_data, discriminator signed32, magnitude16,
  quality8, signal_present. Real NCO/mixer/filter/decimator/discriminator and
  symbol recovery. Owner: DSP agent.
- rx_frame_decoder: clk/rst/bit_valid/bit_in -> held frame_valid until
  frame_ready, frame_data low-byte-first, frame_len8/frame_type8/frame_seq16,
  frame_crc_ok, sync/good/bad/drop/timeout counters and locked. Configurable sync,
  bit order, whitening, CRC and key extraction. Owner: frame agent.
- Existing source_combiner selects decoded descriptors; output feeds unchanged
  protocol v2 BEST/CHAN/LINK producer layout.
- Sample-derived measurement and transport stages integrate both channels,
  compute spectra and report actual receiver values. No fabricated dBm or SNR:
  any uncalibrated estimators are explicitly documented and labelled.

## Delivery sequence

1. Independent ADC, DSP and framing implementation with focused tests.
2. Integration tests from independently generated ADC vectors through decoded
   packets; test carrier error, noise, corruption, loss of signal and reacquisition.
3. Sample-derived spectrum/metrics/IQ and host transport integration.
4. Configurable board default; runtime tuning with explicit applied-state semantics
   where feasible, without pretending the physical PLL is controlled.
5. Full regression, independent review, Vivado timing/DRC, volatile board program,
   UART and GUI acceptance. Record limitations and operating envelope.

Never call an unchecked waveform a decoded packet or generate downstream fake
records to make a test pass. Preserve old transport fixture as a named test only.

## Measurement conventions

The initial spectrum uses a real 64-point complex DFT of decimated I/Q at
100 kS/s (1562.5 Hz bins), rather than a fabricated 256-bin plot. Values use a
specified coarse log approximation and full-scale normalization. Signal/noise
estimates are relative dBFS; they are not calibrated antenna dBm. Protocol flag
bit 2 (0x04) on channel metrics/frame records identifies dBFS values in the
existing signed fields; old records without the flag retain their old labels.
The existing SYNTHETIC bit continues to reflect ADC provenance.

## Runtime ADC test tuning command

For this development bitstream, UART RX controls only the synthetic ADC carrier
and digital NCO. It does not control a physical PLL. Compile-time sample/bit rates
and filter profile remain fixed during a run. The GUI must label these limits.

Command is 15 bytes: ASCII SR, version1, sequence8, carrier_ftw32 LE,
nco_ftw32 LE, enable8 (0 or1), CRC16 CCITT over preceding13bytes, trailer LE.
Invalid CRC/version/enable is ignored; no success is inferred from host writes.
Valid commands atomically apply words and restart receiver state. Firmware emits
CONFIG(0x02), payload `<BBIIB`: sequence, status0, applied carrier_ftw,
applied nco_ftw, enable. A periodic CONFIG report allows capability detection;
sequence255 is reserved for unsolicited reports. Other protocol layouts remain.

Host requires the matching acknowledgement before reporting applied tuning.
Requested settings and applied spectrum reference are separate. All ADC waveform
samples after application use the new carrier; all DDC samples use the new NCO.
The real ADC clock keeps running when the test transmitter is disabled, so
silence/noise propagates to measurements rather than freezing the GUI.

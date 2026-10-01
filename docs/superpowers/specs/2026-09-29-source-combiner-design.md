# Source combiner implementation contract

Scope: the next stage upstream of the host link. Implements bounded A/B frame
matching, duplicate suppression and best-source selection. Frame sync/CRC parsing,
soft combining, DSP and real RF timing remain future work. Inputs to the current
board integration are synthetic; the outputs stay SYNTHETIC.

## Interface

`source_combiner.sv`, one clock, synchronous active-high reset. Parameters:
`MAX_FRAME_BYTES=255` (1..255), `MATCH_CYCLES=16`, `DEDUPE_CYCLES=64`,
`DEDUPE_ENTRIES=4` (positive). Timing defaults are simulation examples, not radio
settings. The synthetic integration explicitly uses one synthetic tick to match
and four ticks to suppress duplicates; frames recur every five ticks.

Inputs are atomic whole-frame descriptors, held stable until valid/ready:

- `in_valid[1:0]`, `in_ready[1:0]` (output), `in_crc_ok[1:0]`, `in_synthetic[1:0]`.
- `in_type[15:0]`: 8 bits/channel; `in_seq[31:0]`: 16 bits/channel.
- `in_t_us[63:0]`: 32 bits/channel; `in_rssi_x10[31:0]`: signed 16 bits/channel.
- `in_quality[15:0]`, `in_len[15:0]`: unsigned 8 bits/channel.
- `in_frame[2*MAX_FRAME_BYTES*8-1:0]`: channel A in low slice, byte 0 in low byte.

The frame key is supplied explicitly; this module does not parse provisional
APEX layouts (TEST has an 8-bit sequence; FLIGHT/HK have 16-bit sequences).
`out_valid/out_ready`, `out_source[7:0]` (0=A,1=B), `out_synthetic`,
`out_t_us[31:0]`, `out_len[7:0]`, `out_frame[MAX_FRAME_BYTES*8-1:0]` form a
registered output stable through backpressure. No output when neither CRC is good.

Outputs `from_a`, `from_b`, `both_ok`, `neither_ok`, `best_sent`,
`duplicate_count`, `rejected_count` are 32-bit wrapping counters.
`stats_synthetic` latches any accepted synthetic input until reset.

## Bounded matching and selection

One pending frame per channel and one output slot. Input backpressure is explicit;
there is no internal overwrite or silent input drop. Length 0 or above the maximum
is consumed and counted as rejected, never selected. Upstream non-stallable sources
must count valid-without-ready drops separately.

Matching uses exactly equal type and sequence. A matching buffered pair retires
without waiting for the timer. A lone or mismatched frame retires after
MATCH_CYCLES elapsed clocks from acceptance; choose the older expired frame,
A on equal ages. Decisions use registered buffered inputs: a counterpart accepted
on the retirement edge is late and subject to deduplication. Output backpressure
may delay retirement. Ages saturate instead of wrapping.

Select CRC-good over CRC-bad. With two good candidates, higher unsigned quality
wins, then higher signed RSSI, then A on an exact tie. Bytes are opaque; if two
CRC-good frames have the same key but different contents, the selected candidate
wins unmodified. No soft combining or equality-based packet reinterpretation.

Recent successfully selected keys occupy a round-robin finite history cache for
DEDUPE_CYCLES clocks from selection. Duplicates of a pending output also suppress
until that output is accepted, even if the cache timer expired. Suppressed copies
increment duplicate_count and never selection counters. Cache eviction/expiry
allows key reuse and sequence wrap; this is bounded dedupe, not an unlimited
history or a reboot detector. Failed-only groups do not enter this cache, so a
later valid copy can still recover them.

`from_a/from_b` count selected output entries, `both_ok` counts paired good inputs,
`neither_ok` counts retired groups with no good input (not unseen RF packets),
`best_sent` counts output handshakes into the host-link producer. It is not a
host acknowledgement. A stalled selected output may make selected counts exceed
best_sent by one. The BEST flag is the OR of participating candidates' synthetic
flags; stats provenance is sticky until reset.

## Board integration

Replace BEST_TELEM selection and LINK_STATS counters inside the synthetic harness.
Retain all 11 link ports, protocol v2 layouts, existing channel records and
visualization producers. Snapshot the full selected payload on link-port accept;
use output ready only when that port can accept. Do not let a stalled BEST payload
reference live generator state. Count synthetic input overruns in STATUS drops.
Alternate the synthetic quality ranking so both-good B selection is exercised.

No nested sources/includes/IP are added: build.tcl and core.source_files already
include direct RTL files. No FPGA commands, flash writes, or RF settings change.

## Verification and remaining decisions

Focused Icarus tests cover all CRC combinations, quality/RSSI/ties, delayed and
unmatched frames, unequal keys, dedupe/expiry/key reuse, lengths, reset, stalls,
immutable data/provenance, and counters. The UART top test checks selected bytes
against both channel records. Run the complete SDR simulation and host suite;
run Vivado and inspect timing/DRC before claiming board readiness, then use volatile
programming and the link checker when hardware is available.

Before connecting actual frame decoders, validate pairing/dedupe windows, queue
capacity, key extraction/trust for bad CRC frames, transmitter resets, and same-key
payload disagreement against measured packet timing. Current values only exercise
synthetic events and do not settle these receiver-design questions.

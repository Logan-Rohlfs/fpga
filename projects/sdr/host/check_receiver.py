"""Validate sample-driven receiver captures or a live UART (no RF claims).

Use --no-frames for a stable transmitter-disabled/detuned capture after draining
old messages. Otherwise verifies exact APEX TEST payloads and each BEST's selected
channel bytes/timestamp. Capture boundaries may omit a matching channel record;
only records whose complete A/B pair is present are ranked, and at least one
complete comparison is required. CONFIG changes delimit independent epochs.

--demo checks the APEX flight replay bitstream instead: 44-byte FLIGHT frames
(type 0x02, callsign KG5LDI, seq u16 at byte 7), BUILD_ID SDRF, and with --rom
each CRC-good frame must equal that ROM frame plus its CRC. A BEST whose seq
has exactly one channel record (the other antenna in its loss window) must
equal that record; it is counted as a single-antenna cover.
"""
import argparse
from collections import Counter
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from sdr_cli.protocol import StreamDecoder, crc16_ccitt  # noqa: E402

TEST_BUILD_ID, FLIGHT_BUILD_ID = 0x53445231, 0x53445246
FLIGHT_FRAME_BYTES = 44


def frame_key(data, demo):
    return int.from_bytes(data[7:9], 'little') if demo else data[1]


def payload_error(data, demo, rom):
    """Why a recovered frame does not match the configured transmitter, or None."""
    if not demo:
        if len(data) != 19 or data[0] != 1 or data[2:17] != b'APEX RADIO TEST':
            return 'decoded payload does not match configured TEST transmitter'
        return None
    if len(data) != FLIGHT_FRAME_BYTES or data[0] != 2 or data[1:7] != b'KG5LDI':
        return 'decoded payload is not an APEX FLIGHT frame'
    seq = frame_key(data, demo)
    crc_ok = crc16_ccitt(data[:-2]) == int.from_bytes(data[-2:], 'big')
    if rom is not None and crc_ok and (seq >= len(rom) or data[:-2] != rom[seq]):
        return f'FLIGHT seq {seq} differs from the replay ROM'
    return None


def validate(raw, *, no_frames=False, build_id=None, demo=False, rom=None):
    if build_id is None:
        build_id = FLIGHT_BUILD_ID if demo else TEST_BUILD_ID
    decoder = StreamDecoder()
    records = decoder.feed(raw)
    errors = []
    counts = Counter(record.name for record in records)
    required = {'STATUS', 'CHAN_METRICS', 'LINK_STATS', 'SPECTRUM', 'IQ_SNAPSHOT'}
    if not no_frames:
        required |= {'BEST_TELEM', 'CHAN_FRAME'}
    missing = required - counts.keys()
    if missing:
        errors.append('missing types: ' + ', '.join(sorted(missing)))
    for key in ('crc_errors', 'cobs_errors', 'length_errors', 'seq_gaps'):
        if decoder.stats[key]:
            errors.append(f'{key}={decoder.stats[key]}')
    frames, bests = {}, []
    measurement_channels = {name: set() for name in ('CHAN_METRICS', 'SPECTRUM', 'IQ_SNAPSHOT')}
    nonflat_spectrum = False
    nonzero_iq = False
    epoch = 0
    last_config = None
    good = 0
    for record in records:
        f = record.fields
        if not record.synthetic:
            errors.append(f'{record.name} lost synthetic ADC provenance')
        if record.name in measurement_channels:
            measurement_channels[record.name].add(f['channel'])
        if record.name == 'CONFIG':
            if f['status'] != 0:
                errors.append('CONFIG reports failed application')
            config = tuple(f.get(key) for key in ('carrier_ftw', 'nco_ftw', 'enable'))
            # Explicit acknowledgements also reset pipeline history, even when
            # applying the same settings. Periodic reports carry seq=255.
            if last_config is not None and (config != last_config or f.get('command_seq', 255) != 255):
                epoch += 1
            last_config = config
        if record.name == 'STATUS':
            if f['build_id'] != build_id:
                errors.append(f'unexpected BUILD_ID 0x{f["build_id"]:08x}')
            if f['dropped']:
                errors.append(f'STATUS dropped={f["dropped"]}')
        if record.name in ('CHAN_FRAME', 'CHAN_METRICS'):
            if not record.flags & 4:
                errors.append(f'{record.name} missing relative dBFS flag')
        if record.name in ('CHAN_FRAME', 'BEST_TELEM'):
            data = f['raw']
            problem = payload_error(data, demo, rom)
            if problem:
                errors.append(problem)
                continue
            crc_ok = crc16_ccitt(data[:-2]) == int.from_bytes(data[-2:], 'big')
            if record.name == 'CHAN_FRAME':
                if f['crc_ok'] != crc_ok:
                    errors.append('channel CRC status disagrees with recovered bytes')
                good += int(crc_ok)
                frames.setdefault((epoch, frame_key(data, demo), f['channel']), []).append(record)
            else:
                if not crc_ok:
                    errors.append('BEST contains corrupt APEX payload')
                bests.append((epoch, record))
        if record.name == 'SPECTRUM':
            nonflat_spectrum |= len(set(f['power'])) > 1
            if f['bins'] != 64 or f['bin_hz'] != 1562.5 or f['db_step'] != 0.5:
                errors.append('unexpected measured spectrum profile')
        if record.name == 'IQ_SNAPSHOT':
            nonzero_iq |= any(i or q for i, q in f['iq'])
        if record.name == 'IQ_SNAPSHOT' and (f['pairs'] != 64 or f['sample_rate_hz'] != 100000):
            errors.append('unexpected measured IQ profile')
        for value in f.values():
            if isinstance(value, float) and not math.isfinite(value):
                errors.append('non-finite measurement')
    for name, channels in measurement_channels.items():
        if channels != {'A', 'B'}:
            errors.append(f'{name} missing an antenna channel')
    if not no_frames and (not nonflat_spectrum or not nonzero_iq):
        errors.append('decoded traffic lacks nonflat spectrum/nonzero I/Q')
    compared = covers = 0
    for epoch, best in bests:
        f = best.fields
        seq = frame_key(f['raw'], demo)
        groups = [frames.get((epoch, seq, channel), []) for channel in ('A', 'B')]
        candidates = [min(group, key=lambda r: abs(r.fields['t_us'] - f['t_us'])) if group else None
                      for group in groups]
        present = [r for r in candidates if r]
        if demo and len(present) == 1 and present[0].fields['channel'] == f['source']:
            only = present[0].fields
            if not only['crc_ok'] or only['raw'] != f['raw'] or only['t_us'] != f['t_us']:
                errors.append('single-antenna BEST differs from its channel record')
            covers += 1
        if not all(candidates):
            continue
        candidates = [r for r in candidates if r.fields['crc_ok']]
        if not candidates:
            errors.append('BEST exists without a CRC-good channel')
            continue
        chosen = max(candidates, key=lambda r: (r.fields['quality'], r.fields['rssi_dbm'], r.fields['channel'] == 'A'))
        if f['source'] != chosen.fields['channel'] or f['raw'] != chosen.fields['raw'] or f['t_us'] != chosen.fields['t_us']:
            errors.append('BEST differs from ranked channel bytes, source or timestamp')
        compared += 1
    if no_frames:
        if bests or good:
            errors.append(f'expected no decoded frames; saw {len(bests)} BEST and {good} CRC-good channel frames')
    elif not compared:
        errors.append('no complete BEST/A/B selection comparison')
    return errors, counts, compared, decoder.stats, covers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--file', type=Path)
    source.add_argument('--port')
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--baud', type=int, default=1000000)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--no-frames', action='store_true')
    parser.add_argument('--build-id', type=lambda value: int(value, 0),
                        help='Expected STATUS build_id (default SDR1, or SDRF with --demo)')
    parser.add_argument('--demo', action='store_true', help='APEX flight replay bitstream (FLIGHT frames)')
    parser.add_argument('--rom', type=Path, help='With --demo: replay ROM .mem to compare frames against')
    args = parser.parse_args()
    rom = None
    if args.rom:
        from apex_flight_rom import read_mem
        rom = read_mem(args.rom)
    if args.file:
        raw = args.file.read_bytes()
    else:
        import serial
        raw = bytearray()
        with serial.Serial(args.port, args.baud, timeout=0.1) as board:
            board.reset_input_buffer()
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                raw.extend(board.read(4096))
        # A live attachment may start inside one message; discard only that
        # partial first packet, preserving all complete packets thereafter.
        first = raw.find(b'\x00')
        raw = raw[first + 1:] if first >= 0 else raw
    if args.output:
        with args.output.open('xb') as stream:
            stream.write(raw)
    errors, counts, compared, stats, covers = validate(raw, no_frames=args.no_frames, build_id=args.build_id,
                                                        demo=args.demo, rom=rom)
    print(f'{stats["messages"]} messages {dict(counts)}; {compared} exact BEST selections'
          + (f', {covers} single-antenna covers' if args.demo else ''))
    if errors:
        print('FAIL: ' + '; '.join(dict.fromkeys(errors)), file=sys.stderr)
        return 1
    print('PASS: ADC provenance, transport, receiver payloads, measurements and selection')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

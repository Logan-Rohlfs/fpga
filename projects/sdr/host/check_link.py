"""Verify the SDR host link on hardware: every message type decodes cleanly.

Passes when, within --seconds, every link message type arrives with zero CRC,
COBS, or length errors and zero sequence gaps. Current FPGA data is SIMULATED
by stand-in producers; this checks the transport, not RF reception.
"""

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from sdr_cli.protocol import TYPE_NAMES, StreamDecoder, summarize  # noqa: E402

import serial  # noqa: E402
from serial.tools import list_ports  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Serial port, e.g. /dev/cu.usbserial-...1')
    parser.add_argument('--baud', type=int, default=1_000_000)
    parser.add_argument('--seconds', type=float, default=5.0, help='Listening time (default: 5; STATUS is 1 Hz)')
    parser.add_argument('--output', type=Path, help='Also save the exact raw bytes to this NEW file')
    args = parser.parse_args()

    if not args.port:
        print('Choose a port with --port. Available serial ports:', file=sys.stderr)
        for port in list_ports.comports():
            print(f'  {port.device}: {port.description}', file=sys.stderr)
        return 2

    decoder = StreamDecoder()
    raw = bytearray()
    try:
        with serial.Serial(args.port, baudrate=args.baud, timeout=0.1) as board:
            board.reset_input_buffer()
            started = time.monotonic()
            while time.monotonic() - started < args.seconds:
                chunk = board.read(4096)
                raw += chunk
                decoder.feed(chunk)
    except serial.SerialException as exc:
        print(f'Serial port error: {exc}', file=sys.stderr)
        return 2

    if args.output:
        with open(args.output, 'xb') as capture:
            capture.write(raw)
        print(f'Raw capture: {args.output} ({len(raw)} bytes)')
    stats = decoder.stats
    for line in summarize(stats, args.seconds):
        print(line)
    missing = sorted((set(TYPE_NAMES.values()) - {'CONFIG'}) - set(stats['by_type']))
    errors = stats['crc_errors'] + stats['cobs_errors'] + stats['length_errors']
    problems = []
    if missing:
        problems.append('missing types: ' + ', '.join(missing))
    if errors:
        problems.append(f'{errors} corrupt messages')
    if stats['seq_gaps']:
        problems.append(f"{stats['seq_gaps']} lost messages (seq gaps)")
    if problems:
        print('FAIL: ' + '; '.join(problems), file=sys.stderr)
        return 1
    print(f"PASS: {stats['messages']} messages, all {len(TYPE_NAMES)-1} required types, no errors or gaps")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

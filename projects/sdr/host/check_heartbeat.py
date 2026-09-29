"""Read the SDR UART diagnostic from the Basys 3 USB serial port."""

import argparse
import sys

import serial
from serial.tools import list_ports


EXPECTED = b"SDR READY\r\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Serial port, e.g. /dev/cu.usbserial-...1")
    parser.add_argument("--count", type=int, default=3, help="Lines to verify (default: 3)")
    args = parser.parse_args()

    if not args.port:
        print("Choose a port with --port. Available serial ports:", file=sys.stderr)
        for port in list_ports.comports():
            print(f"  {port.device}: {port.description}", file=sys.stderr)
        return 2

    try:
        with serial.Serial(args.port, baudrate=115200, timeout=3) as board:
            # We may open in the middle of a line. Discard the first partial line.
            board.readline()
            for n in range(args.count):
                line = board.readline()
                if line != EXPECTED:
                    print(f"FAIL at line {n + 1}: received {line!r}", file=sys.stderr)
                    return 1
                print(f"PASS {n + 1}/{args.count}: {line.decode().strip()}")
    except serial.SerialException as exc:
        print(f"Serial port error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

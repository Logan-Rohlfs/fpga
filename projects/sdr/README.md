# SDR receiver

The first implemented component is the **host-facing UART transmitter**. It accepts bytes through a `valid`/`ready` interface and sends 8N1 serial data at 115200 baud. The Basys 3 top module currently emits `SDR READY\r\n` about once per second as a hardware diagnostic; LED0 changes state after each message. No RF or XADC signals are connected yet.

The intended receive pipeline is: XADC samples → digital downconversion → channel filter/decimation → 2-GFSK discriminator → symbol timing and bit slicing → packet decoding → UART byte stream to the host. The telemetry packet format, symbol rate, and frequency deviation still need to be specified before implementing the signal-processing stages.

## Test on Mac

From the repository root, `make sim PROJECT=sdr` runs the UART unit test and a top-level test that decodes two complete diagnostic messages. Both use accelerated clocks; the FPGA build uses the 100 MHz board clock.

## Build on Windows

From the repository root in PowerShell:

```powershell
& 'C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat' -mode batch -source scripts/build.tcl -tclargs sdr
```

Copy `build/sdr/sdr.bit` to the Mac's copy of this repository and run `make program PROJECT=sdr` with the Basys 3 connected to the Mac's PROG USB port.

## Read the board

Create a Python environment once on the Mac:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r projects/sdr/host/requirements.txt
```

Find the board's UART port (`ls /dev/cu.usbserial*` on macOS). On the FT2232 bridge it is commonly the port ending in `1`. Then:

```sh
.venv/bin/python projects/sdr/host/check_heartbeat.py --port /dev/cu.usbserial-YOUR-PORT1
```

The script verifies three `SDR READY` lines. The same UART transmitter can later carry decoded packet bytes; the final host framing protocol remains open.

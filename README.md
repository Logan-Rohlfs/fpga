# Basys 3 FPGA projects

One Git repository with independent projects for the Digilent Basys 3 (Artix-7 XC7A35T-1CPG236C).

## SDR terminal workbench

Run `./sdr` to open the btop-inspired dashboard, or use `./sdr --help` for inline
build, programming, serial, and recording commands. See [the tool guide](tools/README.md)
for installation, configuration, keyboard controls, and testing.

## Projects

- `projects/blink`: a working first design. LED 0 changes state every 0.5 seconds using the board's 100 MHz clock.
- `projects/sdr`: the SDR receiver. Its first reusable block is the host-facing UART transmitter, with a board diagnostic that sends `SDR READY` once per second. See `projects/sdr/README.md` for tests and hardware instructions.

## Mac setup

VS Code is the editor. Install Icarus Verilog for simulation and openFPGALoader for programming:

```sh
brew install icarus-verilog openfpgaloader
```

VS Code will recommend the Verilog-HDL extension, WaveTrace waveform viewer, and Makefile Tools. They are optional conveniences; the terminal commands work without them. The SDR hardware diagnostic uses a small Python client with `pyserial`; its setup is in `projects/sdr/README.md`.

Open the repository with `code ~/git/fpga`. The workspace enables Icarus linting and provides VS Code tasks for simulation, Vivado building, and board programming. The latter two tasks require Vivado or a connected board, respectively.

Vivado runs on the Windows PC for synthesis, placement, timing checks, and bitstream generation. Install Vivado with 7-series device support. The build is scripted, so the repo does not depend on a generated `.xpr` project file.

## First exercise: blink

On the Mac, from the repository root:

```sh
make sim PROJECT=blink
```

This compiles the Verilog, runs the testbench, and writes `build/blink/blink.vcd`. Open that file in WaveTrace to inspect `clk` and `led`.

On the Windows PC, open a terminal in this repository and run:

```powershell
vivado -mode batch -source scripts/build.tcl -tclargs blink
```

The bitstream and timing/resource reports appear in `build/blink/`. If using Windows PowerShell, run `vivado.bat` or its full path if `vivado` is not on PATH. Transfer `build/blink/blink.bit` back to the Mac if the board is attached there.

With the Basys 3 connected to the Mac's USB port labeled PROG:

```sh
make program PROJECT=blink
```

This configures the FPGA until it is powered off. Run `make flash PROJECT=blink` only when you want the design saved to onboard flash. The board's programming jumper must match the desired startup mode; JTAG programming itself works while the board is powered.

## SDR development

Run `make sim PROJECT=sdr` on the Mac. The SDR project's README explains the Windows Vivado build, Mac programming, and UART hardware test. The RF processing modules will be connected after their input parameters and packet format are known.

## Sources

Pin assignments are from Digilent's Basys 3 master constraints: https://github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc

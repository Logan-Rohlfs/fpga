# Basys 3 FPGA projects

One Git repository with independent projects for the Digilent Basys 3 (Artix-7 XC7A35T-1CPG236C).

## Projects

- `projects/blink`: a working first design. LED 0 changes state every 0.5 seconds using the board's 100 MHz clock.
- `projects/sdr`: starter structure for the real project. Add a top-level RTL file and matching pin constraints when its interfaces are known.

## Mac setup

VS Code is the editor. Install Icarus Verilog for simulation and openFPGALoader for programming:

```sh
brew install icarus-verilog openfpgaloader
```

VS Code will recommend the Verilog-HDL extension, WaveTrace waveform viewer, and Makefile Tools. They are optional conveniences; the terminal commands work without them. A Python virtual environment and `pyserial` are useful later, once the SDR has a UART protocol; there is no UART design yet.

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

## Adding the SDR design

Create `projects/sdr/rtl/sdr_top.sv`, add its pins to `projects/sdr/constraints/basys3.xdc`, then build with:

```powershell
vivado -mode batch -source scripts/build.tcl -tclargs sdr
```

Put module tests in `projects/sdr/sim/`. In the future, add a UART protocol and Python host client under `projects/sdr/host/` for automated hardware feedback.

## Sources

Pin assignments are from Digilent's Basys 3 master constraints: https://github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc

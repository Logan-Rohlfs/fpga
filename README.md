# Basys 3 FPGA projects

A single repository for a Basys 3 SDR receiver and its development tools.
**Current checkpoint: the host link layer works end to end.** The SDR FPGA
design sends COBS-framed, CRC-checked messages of every type at 1 Mbaud: status,
telemetry, per-channel metrics, spectrum, and I/Q. `./sdr` decodes and displays
them. All of that content is **SIMULATED** by stand-in producers; RF acquisition
and demodulation are not implemented. See the [module map](docs/sdr_pipeline.drawio).

New agents: read [AGENTS.md](AGENTS.md), then [the handoff](docs/HANDOFF.md).

## Start here

On the Mac, from this checkout:

```sh
./sdr                     # interactive dashboard; connects to UART
./sdr --help              # all inline commands
./sdr doctor              # check local tools and serial device selection
./sdr receive --seconds 5 # decoded link messages without reprogramming the board
./sdr gui --source sim    # Space Raiders web GUI; no board needed
```

The current Mac already has a configured virtual environment and local connection
settings. For a fresh checkout, follow [installation and setup](tools/README.md).
Machine-specific settings belong in ignored `.sdr/config.json`; do not copy keys
or hardcode connection details into source files.

## Development workflow

```sh
PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v
./sdr sim                 # SDR RTL tests; no hardware needed
./sdr sim --project blink # blink RTL test
./sdr build               # snapshot current sources, build on Windows, fetch results
./sdr program             # load selected build into volatile FPGA memory
./sdr receive --seconds 5
```

The Mac handles editing, simulation, USB programming, and UART. Vivado runs on
the Windows PC over SSH. `./sdr build` includes uncommitted RTL changes; it does
not require a Git push/pull. `./sdr flash` explicitly writes persistent flash;
normal development uses `program`.

The [tool guide](tools/README.md) covers dashboard keys, recording, remote setup,
artifact selection, troubleshooting details, and standalone commands. A terminal
of 120 × 36 or larger is comfortable for the dashboard.

## Repository map

| Location | Purpose |
| --- | --- |
| `projects/blink/` | Independent LED hello-world design and testbench |
| `projects/sdr/rtl/` | SDR top module and reusable hardware blocks |
| `projects/sdr/sim/` | Self-checking SystemVerilog testbenches |
| `projects/sdr/constraints/` | Basys 3 pins and clock constraints |
| `projects/sdr/host/` | Standalone hardware link checker (`check_link.py`) |
| `tools/sdr_cli/` | Shared host operations, UART transport, CLI, and dashboard |
| `tools/sdr_cli/web/` | GUI web server (aiohttp); built frontend lands in its ignored `static/` |
| `tools/sdr_web/` | Svelte source for the Space Raiders SDR web GUI |
| `tools/tests/` | Host unit and pseudo-terminal integration tests |
| `scripts/build.tcl` | Vivado synthesis, implementation, reports, and bitstream generation |
| `docs/HANDOFF.md` | Verified state, outstanding decisions, and next-agent context |
| `docs/sdr_pipeline.drawio` | Planned FPGA module map (open with draw.io) |
| `docs/superpowers/` | Design specs and implementation plans |
| `build/` | Ignored generated simulations, bitstreams, manifests, and reports |
| `.sdr/` | Ignored local configuration, recordings, and operation logs |

Keep reusable SDR components inside `projects/sdr/`, with focused testbenches.
Add an independent project only when it needs its own top-level board design.
See [SDR hardware details](projects/sdr/README.md).

## Existing lower-level tools

`make sim PROJECT=blink|sdr` underlies the CLI simulation command. Direct Vivado
builds use `vivado -mode batch -source scripts/build.tcl -tclargs blink|sdr` on
Windows (use the full `vivado.bat` path if needed).

Direct builds and `make program` use `build/PROJECT/PROJECT.bit`. The workbench
uses `build/PROJECT/latest` to select an artifact bundle. **Use `./sdr program`
after `./sdr build`**; the Makefile programming target does not follow that pointer.
`make clean` removes the entire local `build/` directory, including saved bundles.

VS Code extensions are optional. Its SDR programming task uses the workbench;
the blink Vivado task expects Vivado on the machine where the task runs.

## Hardware reference

Target: Digilent Basys 3, Artix-7 `xc7a35tcpg236-1`, 100 MHz board clock.
Pin assignments derive from the [Digilent master constraints](https://github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc).

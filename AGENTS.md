# Agent instructions

## Read first

1. `README.md` — repository map and normal commands.
2. `docs/HANDOFF.md` — checkpoint, verified behavior, and open decisions.
3. `projects/sdr/README.md` for HDL work; `tools/README.md` for host-tool work.

The user has intentionally stopped at working FPGA-to-host UART. This handoff is
not a request to implement the remaining SDR pipeline. Follow the next user's
chosen scope; do not silently select a demodulator, packet format, or RF settings.

## Work within the existing structure

- Reusable SDR RTL belongs in `projects/sdr/rtl/`; focused, self-checking
  testbenches belong in `projects/sdr/sim/`. Keep the independent blink example.
- `tools/sdr_cli/core.py` owns build/program operations; `serial_io.py` owns UART;
  `cli.py` and `tui.py` expose those shared operations. Keep CLI and dashboard
  behavior consistent rather than adding separate build/program implementations.
- Python supports 3.9+. RTL simulation uses Icarus/SystemVerilog (`-g2012`).
- `scripts/build.tcl` and `core.py:source_files` must agree on build inputs.
  They currently include only direct `.v`/`.sv` files and one project XDC.
  Add include files, nested RTL, ROM assets, or IP to both if a task needs them.
- Preserve the tested UART diagnostic until an intentional replacement has
  equivalent simulation and hardware verification. Do not label raw host writes
  as successful FPGA commands: no command receiver/acknowledgement exists yet.

## Local state and hardware

Read `.sdr/config.json` locally when connection details are needed. `./sdr config`
shows effective settings. Never read, echo, upload, or commit SSH key contents.
`key.txt` and `command.txt`, if present at the root, are user-owned setup scratch
files; leave their contents untouched and out of commits. Their exact root paths
are ignored. Do not blanket-stage unknown files.

Use `./sdr build` and `./sdr program` for the normal remote-build/local-program
cycle. `program` is volatile; `flash` writes persistent storage and should only
be used when persistent programming is in scope. Close other UART readers first.
Remote availability and attached hardware are runtime conditions, not guarantees.
Do not claim hardware verification based only on simulation or a previous report.

Preserve `.sdr/captures/`, build reports, and completed artifact bundles during
routine cleanup. They are useful evidence. `make clean` deletes all local builds.
Do not prune Windows build snapshots or change SSH/Vivado settings as incidental
cleanup. Generated outputs, environments, captures, and local settings stay ignored.

## Verification and handoff

For host changes:

```sh
PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v
```

For SDR RTL changes: `./sdr sim`. For blink changes: `./sdr sim --project blink`.
Run Vivado and inspect timing/DRC reports for hardware changes before claiming a
board-ready result. Exercise hardware when relevant and available; distinguish
newly run checks from historical evidence. For documentation-only changes, check
links and commands without rebuilding or reprogramming the board unnecessarily.

At completion, update the appropriate README and `docs/HANDOFF.md` if behavior,
interfaces, prerequisites, or the verified checkpoint changed. Record what was
tested and what remains unimplemented. Keep machine-specific paths and credentials
in local configuration, not tracked documentation.

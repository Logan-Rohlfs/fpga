# SDR terminal workbench

`sdr` is the host development tool for this repository. Run a single command for
scripts, or open a full-screen dashboard inspired by btop. The host tool runs on
the Mac connected to the Basys 3; Vivado runs over SSH on Windows.

## Install

From the `fpga` checkout:

```sh
brew install python icarus-verilog openfpgaloader
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
source .venv/bin/activate
sdr --help
```

The executable `./sdr` also works without activating the environment. It selects
the checkout's `.venv` automatically. An installed `sdr` can be used from any
directory with `sdr --repo /path/to/fpga ...`.

## Connect once

```sh
./sdr setup --interactive
./sdr ports
./sdr doctor --remote --board
```

Or configure individual fields, preserving other settings:

```sh
./sdr setup --host WINDOWS_IP --user WINDOWS_USER \
  --identity ~/.ssh/YOUR_WINDOWS_KEY \
  --vivado C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat \
  --remote-root C:/sdr-builds --port auto
```

Use the SSH key for your Windows account, not your GitHub key. SSH must already
work with public-key authentication and the host must be in `known_hosts`.
The tool uses batch SSH and does not prompt for passwords or bypass host checks.
Local configuration is in ignored `.sdr/config.json`; only the key's path is
stored. If automatic UART selection is ambiguous, set `--port DEVICE` using
`ports`. The FT2232's second interface is the UART; the first is JTAG.

## Everyday commands

```sh
./sdr                              # full-screen dashboard; attempts UART connect
./sdr sim                          # run the SDR HDL testbenches locally
./sdr build                        # build current files on Windows and fetch results
./sdr program                      # temporary FPGA configuration; lost on power-off
./sdr receive --seconds 5           # display UART text
./sdr connect                       # alias for continuous receive
./sdr receive --format hex          # continuous hex display; Ctrl-C stops
./sdr receive --output capture.bin  # display and record exact bytes
./sdr receive --format raw > rx.bin # byte-exact stdout; status is on stderr
./sdr receive --format json         # timestamped chunks with hex data
./sdr send --hex 'aa 01 ff'          # raw transport only; no FPGA command handler yet
./sdr flash                        # explicitly write persistent board flash
./sdr sim --project blink           # the blink project is supported too
./sdr program --bit path/to/file.bit
```

`receive` also accepts `--port` and `--baud` overrides, as does `send`. Text mode
is an ASCII diagnostic view with terminal control bytes suppressed; use raw
output or recording to preserve arbitrary binary data. JSON timestamps describe
host arrival of chunks, not ADC sample times. Ctrl-C returns status 130; failed
commands return nonzero. `flash` is an explicit persistent write, whereas
`program` is the normal development command.

The existing FPGA firmware only emits `SDR READY` at 115200 baud. Sending bytes
does not yet control the receiver or produce an acknowledgement. RF strength,
sample plots, tuning, packet decoding, and other DSP measurements need future
FPGA modules and a versioned host protocol. They are not inferred from UART
traffic. The text heartbeat is a diagnostic observation, not firmware discovery.

## Dashboard

Use a UTF-8 terminal with at least 86 columns and 26 rows; 120 × 36 or larger
shows more traffic and logs. It has device and build panels, text/hex receive
history, actual UART byte-rate history, counters, and an event/build log.

| Key | Action |
| --- | --- |
| `c` | Connect/disconnect UART |
| `s` / `b` / `p` | Simulate / build / program |
| `F` | Persistent flash; type `FLASH` to confirm |
| `r` | Start/stop a raw recording |
| `x` | Toggle text/hex |
| Space | Freeze display; receiving and recording continue |
| Up / Down | Scroll receive history |
| `:` | Enter a command |
| `?` / `q` | Help / quit |

The command bar accepts `connect`, `disconnect`, `sim`, `build`, `program`,
`flash`, `record`, `stop`, `port DEVICE`, `baud RATE`, `send TEXT`,
`send-hex aa 01 ff`, `clear`, and `quit`. Press Escape to cancel entry.
Configure the remote host with `setup` outside the dashboard.

Builds run in the background while the dashboard continues receiving. Programming
stops recording, releases UART, then reconnects if it was previously connected.
Close other serial monitors before connecting. A running operation must finish
before quitting the dashboard. Full operation logs live in `.sdr/logs/`;
recordings in `.sdr/captures/` include a metadata sidecar. Neither is committed.
The displayed histories are bounded; raw recording is the way to keep all data.
Recording consumes disk space until stopped. There is no automatic reconnect
after USB removal: reconnect explicitly with `c` when the board is back.

## Remote builds and artifacts

Builds upload a ZIP containing **only** `scripts/build.tcl`, the selected
project's direct `.v`/`.sv` RTL files, and its `constraints/basys3.xdc`. They do
not upload `.git`, keys, host settings, or the rest of the checkout. This matches
the current Tcl source list; add include files/IP assets to both workflows when
the RTL starts using them. Uncommitted changes are included; no push/pull needed.

Every build gets a unique directory beneath `remote_root`. Windows retains these
directories and Vivado logs for diagnosis; remove old directories manually when
no build is running. An interrupted SSH connection may leave Vivado running there;
it cannot overwrite another build's files.

Successful downloads go to `build/PROJECT/artifacts/BUILD_ID/`, containing the
bitstream, timing/utilization/DRC reports, and a source/bitstream SHA-256 manifest.
An atomic `build/PROJECT/latest` pointer selects a complete bundle. A failed
build leaves the previous selection intact. Programming checks the selected
bundle against current sources and rejects changed sources or a corrupt bitstream.
`--bit PATH` deliberately selects an external/older bitstream and bypasses these
checks. Existing `build/PROJECT/PROJECT.bit` files are accepted with a notice
when no workbench bundle exists. The older Makefile still uses that legacy path;
use `sdr program` after `sdr build` to select the new bundle.

## Tests

```sh
PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v
./sdr sim
```

The host tests cover real pseudo-terminal serial I/O, fragmented heartbeat
recognition, binary TX and captures, a real curses terminal with resizing and
command entry, bounded history, serial-port ambiguity,
snapshot exclusions, build failures, and stale-source rejection. FPGA simulations
remain separate. The dashboard uses Python curses; installed Windows hosts also
get `windows-curses`, but the primary supported setup is Mac host + Windows builder.

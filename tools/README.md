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
./sdr build --demo                 # opt-in APEX flight replay bitstream (sdr only)
./sdr build --all                  # default + demo concurrently, threads sized to the host
./sdr program                      # temporary FPGA configuration; lost on power-off
./sdr program --demo               # the demo bundle (build/sdr/latest-demo)
./sdr receive --seconds 5           # decoded link messages, then a per-type summary
./sdr receive --format records      # decoded messages as JSON lines
./sdr receive --format text         # undecoded UART bytes as ASCII
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

`receive` also accepts `--port` and `--baud` overrides, as does `send`.

**Decoded output.** The default `decoded` format prints one line per link message,
with its seq and a `[SIMULATED]` mark when the FPGA flagged it as stand-in data.
Every receive ends with a summary on stderr: counts and rates per type, CRC, COBS
and length errors, seq gaps, and resync bytes. Bytes before the first delimiter
are counted as resync, not errors.

**Baud.** The default is 1 000 000. A local config that still says 115200 needs
`./sdr setup --baud 1000000`. macOS pseudo-terminals reject nonstandard rates, so
the tests use 115200 on fake ports.

Text mode
is an ASCII diagnostic view with terminal control bytes suppressed; use raw
output or recording to preserve arbitrary binary data. JSON timestamps describe
host arrival of chunks, not ADC sample times. Ctrl-C returns status 130; failed
commands return nonzero. `flash` is an explicit persistent write, whereas
`program` is the normal development command.

The FPGA link is transmit-only. Sending bytes does not control the receiver or
produce an acknowledgement.

Every current metric, frame, spectrum and I/Q message comes from stand-in FPGA
producers and is labelled SIMULATED. Real RF numbers arrive only when the
receiver stages replace those producers. The protocol lives in
`sdr_cli/protocol.py`, and APEX frames are parsed provisionally in
`sdr_cli/apex.py`. An old bitstream that still prints `SDR READY` is reported as
a legacy heartbeat; view it with `--format text --baud 115200`.

## Dashboard

Use a UTF-8 terminal with at least 86 columns and 26 rows; 120 × 36 or larger
shows more traffic and logs. It has:

- device and build panels, including the firmware protocol version and build ID
  from STATUS;
- a receive pane with three views;
- UART byte-rate history plus link message counters and per-type rates;
- an event/build log.

Press `v` to cycle the receive pane through its views:

- **RAW:** text/hex bytes.
- **LINK:** a channel A/B table (RSSI, noise, SNR, Δf, sync quality, CRC
  good/bad), the best stream, and recent channel frames.
- **SPECTRUM:** per-channel ASCII waterfalls, labelled with their IF span, plus
  constellations. The waterfall uses the shared auto scale from
  `sdr_cli/display.py:WaterfallScale`, and its current dBFS range is shown under
  it.

Simulated data is marked in the pane title.

| Key | Action |
| --- | --- |
| `c` | Connect/disconnect UART |
| `s` / `b` / `p` | Simulate / build / program |
| `F` | Persistent flash; type `FLASH` to confirm |
| `r` | Start/stop a raw recording |
| `v` | Cycle RAW / LINK / SPECTRUM views |
| `x` | Toggle text/hex (RAW view) |
| Space | Freeze display; receiving and recording continue |
| Up / Down | Scroll receive history |
| `:` | Enter a command |
| `?` / `q` | Help / quit |

The command bar accepts `connect`, `disconnect`, `sim`, `build`, `build demo`, `program`,
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

## Web GUI

`./sdr gui` serves the Space Raiders SDR workbench: a Tune page with the RF
frequency plan, selectable A/B IF spectrum and waterfall, synthesizer/NCO
controls, both constellations and signal histories; and a Telemetry page of
draggable, resizable cards (flight plots, map, 3D trajectory, state, events, link
quality, spectrum, waterfall and more) arranged in shared, named presets.

```sh
.venv/bin/python -m pip install -e '.[gui]'         # once: adds aiohttp
(cd tools/sdr_web && npm install && npm run build) # Node is needed only to build
./sdr gui --source sim                            # no board needed
./sdr gui --source demo                           # RocketPy flight replay, host-side, no board
./sdr gui --source replay --file build/sdr/link_capture.bin --loop
./sdr gui                                        # UART; close other readers first
./sdr gui --lan                                  # allow viewers on the local network
./sdr setup --gui-password                       # prompted, stored hashed (the Operator password)
./sdr maps fetch --site irec-pecos               # once, while online: offline map tiles
```

The default URL is `http://127.0.0.1:8080`. Use `--http-port` to change it and
`--no-browser` to suppress browser opening. Without `--lan`, only this machine
can connect. Fonts and scripts are bundled; viewers need no internet access.
For frontend development, run the server and `npm run dev` in `tools/sdr_web`.

- **Operator/Viewer:** everyone starts as a Viewer. One Operator can change shared
  tuning, edit and publish layouts and use Reconnect; log in through the header
  (the wire role is still `admin`). With no password configured, only localhost
  can become Operator. Taking over requires confirmation and demotes the old
  Operator. Reloading resumes Operator through a session token within a
  15-second grace period. Operator-only actions are enforced by the server, not
  just hidden in the UI.
- **Tune:** drag/scroll the RF plan or edit the LO digits; drag the waterfall or
  edit the NCO field. All tuning is validated and quantized in Python. Receiver,
  synthesizer and filter values are a host model with placeholder hardware
  settings. With the UART source, LO and NCO changes are sent automatically and
  count as applied only on a matching CONFIG acknowledgement (see the Send panel
  status); otherwise they change the requested plan only. The sim source models
  them and the demo source ignores them. No physical PLL is controlled.
- **Display:** auto waterfall scaling is the default. Manual floor/peak, A/B
  selection and Freeze are per viewer. Space toggles Freeze outside inputs.
  The header cycles System/Dark/Light themes. Synthetic content is labelled
  SIMULATED; it is not an RF measurement.
- **Telemetry cards and presets:** see the next subsection.
- **Disconnection:** the browser retries automatically and dims old data. The
  banner tells the two failures apart: "Server unreachable" means the browser
  cannot reach the GUI server; "Server up. …" means the server runs but the board
  UART is not delivering. Receiving continues while the display is frozen.
  Tuning is saved in ignored `.sdr/gui_state.json`.
- **Auto-switch** (see Presets below): with the Operator's Auto-switch toggle on, the live layout's
  `triggers` are active: a flight phase change (`phase` trigger) or a launch,
  burnout, apogee or landing event (`event` trigger) makes the target layout live
  for every client, with an "Auto-switched to ..." notice. Link events never
  trigger. The toggle is Operator-only and saved in `.sdr/gui/preset_state.json`.
- **Serial auto-reconnect:** with the UART source, the server survives losing the
  port (USB unplugged, board reprogrammed) and reopens it by itself after 0.5, 1,
  2, 4 and 8 s, then every 8 s. A successful open resets the delay. The status
  pill and banner show the state: `connected`; `waiting for port` (the device is
  absent); `port busy` (another process such as a second `./sdr gui`,
  `./sdr tui` or `./sdr receive` holds it; close that process); or
  `reconnecting in N s` (a read failure or another open error). One link event is
  logged per state change, not per retry. The Operator's Reconnect button retries
  at once. Replay and sim sources never auto-reconnect; an ended replay stays
  ended, and a failed one can be restarted with Reconnect.
- **Port conflicts:** `./sdr gui` checks its HTTP port before starting. If another
  process (probably another `./sdr gui`) already listens there, it exits non-zero
  with "HTTP port 8080 on 127.0.0.1 is already in use, probably by another
  ./sdr gui. Stop it, or choose another port with --http-port."
- **Replay limitations:** pacing uses capture byte count, not recorded time.
  Loop boundaries restart original sequence numbers and can increment the gap
  counter; a capture cut mid-frame can also yield a decode error at the boundary.
- **LAN security:** plain HTTP provides protection against accidental/casual
  tuning changes, not network sniffing. Use a trusted network. Password hashes
  are masked by `sdr config`; new config writes use owner-only permissions on POSIX.

### Cards and presets

The Telemetry page is a 12-column grid of cards. Card types: `plot` (uPlot
time series, up to 6 series), `number`, `state` (flight phase), `events`
(flight or link category), `map` (Leaflet over local tiles), `trajectory3d`
(three.js, loaded only when such a card exists), `camera` (a stream URL),
`waterfall`, `spectrum`, `constellation`, `link` (link and channel quality),
`health`, `gps` and `frames`. Every card has a settings popover; the Operator
edits it, and Viewers see the settings read-only. Quantities have a unit
override, and the header offers a global unit system.

- **Presets** are named layouts shared by everyone. Built-in presets ship in
  `tools/sdr_cli/presets/` (read-only; the default is "Flight"). Operator-saved
  presets live in the ignored `.sdr/gui/presets/`, and the live/default
  choice and Auto-switch flag in `.sdr/gui/preset_state.json`. The Operator
  enters edit mode to drag, resize, add and remove cards, then Saves, Saves as a
  new preset, Discards, or Makes default. "Show to viewers" (available after saving) makes a preset live for
  everyone. Each browser has a "Follow operator" toggle: when on it shows the live preset,
  and unticking it lets that viewer pick another preset without changing the live one.
- **`segment`:** the plot, map and trajectory cards take `segment: current | all`
  (default `current`). `current` shows only data since the newest flight-reset
  event; `all` shows everything in the ring. A flight reset happens when the
  phase falls back to IDLE or ARMED from BOOST, COAST, DESCENT or LANDED, which
  is what every loop of the demo replay does. Older segments stay in the ring;
  they are only hidden.
- **Auto-switch triggers:** a preset's `triggers` list entries of
  `{on: phase|event, value, preset}`. A `phase` trigger fires on entering a
  flight phase; an `event` trigger fires on `launch`, `burnout`, `apogee` or
  `landing`. They act only while the Operator's Auto-switch is on and only from
  the live preset. The target preset need not exist; a missing target is ignored.
  Triggers are edited in the preset JSON (there is no trigger editor in the UI).
- **Labels:** cards driven by SYNTHETIC data say so in their header (SIMULATED),
  alongside data age. The demo source and bitstream use `SIM FLIGHT · SIMULATED
  ADC`. Values appear exactly as decoded; nothing is corrected.
- **Camera:** the card embeds a viewer-fetched stream URL (`http`/`https`). Each
  viewer pulls the stream directly, so on a shared hotspot use a low-rate stream.
  Capture from a host USB/HDMI device and a server-side relay are future work.

### Demo data

`./sdr gui --source demo` runs the flight replay entirely on the host: the same
RocketPy simulation of the IREC 2026 flight (Pecos, TX) that the `--demo`
bitstream carries, sent as FLIGHT frames on the same schedule and with the same
per-antenna loss windows. No FPGA and no receiver run: the signal, noise,
spectrum and I/Q are a modelled stand-in, every record is flagged SYNTHETIC, and
tuning is ignored. The GUI labels it `SIM FLIGHT · SIMULATED ADC`.

To see it come from the board instead, build and load the opt-in bitstream:
`./sdr build --demo`, then `./sdr program --demo` (the `latest-demo` bundle;
plain `latest` is the default build). Details of the ROM are in the
[SDR guide](../projects/sdr/README.md#apex-flight-replay-demo-opt-in-build).
The loop is about 70 s, so each pass produces a new segment.

### Offline maps

Browsers never fetch remote tiles. The server serves tiles from `.sdr/maps/`
(ignored), which `./sdr maps fetch` fills from the USGS National Map
(imagery and topo). Run it while online, before going to the field:

```sh
./sdr maps list                                   # sites, tile counts, sizes
./sdr maps fetch --site irec-pecos --dry-run      # print the estimate only
./sdr maps fetch --site irec-pecos                # imagery and topo, resumable
./sdr maps fetch --all --layer imagery --rate 2   # every site, gentler
```

Sites are in `tools/sdr_cli/sites.json`; add local ones in
`.sdr/gui/sites.json` (a local entry replaces a tracked one with the same id).
Fetching is rate-limited (default 4 requests/s, at most 8) and resumable;
tiles the service lacks are recorded as missing, and `--retry-missing` asks again.
With no tiles the map card draws a plain coordinate grid and still plots the track.

### Bandwidth

Each viewer subscribes only to the data channels its cards use, and the
server coalesces frequent updates (a new message replaces an unsent one of the same kind). With
the Flight preset a viewer receives an estimated 10 kB/s or less before compression (design estimate, not a measurement of every card mix):
flight rows at 20 Hz, link statistics at 5 Hz and two spectrum rows at 5 Hz. Ten
viewers are therefore about 100 kB/s, which a phone hotspot carries. Camera
streams are not included because browsers fetch them directly.

Verification:

```sh
PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v
(cd tools/sdr_web && npm test && npm run check && npm run build)
```

## Remote builds and artifacts

Builds upload a ZIP containing **only** `scripts/build.tcl`, the selected
project's direct `.v`/`.sv` RTL files, its `rom/*.mem` memory images, and its
`constraints/basys3.xdc`. They do not upload `.git`, keys, host settings, or the
rest of the checkout. This matches the Tcl source list; add include files/IP
assets to both workflows when the RTL starts using them. Uncommitted changes are
included; no push/pull needed.

`--demo` (dashboard `build demo`) passes `demo` to `build.tcl`, which sets the
`sdr_top` generic `DEMO_FLIGHT=1`. The manifest records `variant` (`default` or
`demo`), and `program` reports a demo selection.

`--all` (dashboard `build all`) builds the default and demo variants at the
same time. Each has its own remote directory, local temp directory and bundle,
and its log lines are prefixed `[default]` or `[demo]`. The build host core count
is read once per invocation (`$env:NUMBER_OF_PROCESSORS` over SSH; 12 if that
fails), or set with `--cores N` or the `host_cores` config key (0 = detect).
Each build gets `clamp(cores // concurrent_builds, 1, 8)` Vivado threads,
passed to `build.tcl` as `general.maxThreads` (8 is Vivado's cap; one build
alone also gets up to 8). The manifest records `threads`. A failed variant
does not stop the other; the command reports the failure at the end. A run on
the 24-thread Windows host built both in 202 s, against about 420 s serially.

Every build gets a unique directory beneath `remote_root`. Windows retains these
directories and Vivado logs for diagnosis; remove old directories manually when
no build is running. An interrupted SSH connection may leave Vivado running there;
it cannot overwrite another build's files.

Successful downloads go to `build/PROJECT/artifacts/BUILD_ID/`, containing the
bitstream, timing/utilization/DRC reports, and a source/bitstream SHA-256 manifest.
An atomic `build/PROJECT/latest` pointer selects the newest complete **default**
bundle and `build/PROJECT/latest-demo` the newest demo bundle, so concurrent
builds never race over one pointer. `sdr program` uses `latest`; `sdr program
--demo` (dashboard `program demo`) uses `latest-demo`. A failed
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

The host tests cover:

- link protocol vectors: COBS, CRC, every message type, resync, and seq gaps;
- decoded CLI output and the dashboard LINK/SPECTRUM views;
- real pseudo-terminal serial I/O, fragmented legacy heartbeat recognition,
  binary TX and captures;
- a real curses terminal with resizing and command entry;
- bounded history, serial-port ambiguity,
snapshot exclusions, build failures, and stale-source rejection. FPGA simulations
remain separate. The dashboard uses Python curses; installed Windows hosts also
get `windows-curses`, but the primary supported setup is Mac host + Windows builder.

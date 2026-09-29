# SDR web GUI design

Status: draft for review, 2026-09-29. Scope: the first version of the graphical
SDR workbench. It builds on the [host link layer](2026-09-29-host-link-layer-design.md).
The approved visual mockup is the reference for layout and interaction.

## Goal

A single application for tuning the receiver and watching what it receives:

- **Tune page:** the RF frequency plan (LO, IF window, image), the IF spectrum and
  waterfall, the synthesizer and NCO settings, and live per-channel signal quality
  (constellation, RSSI, SNR, Δf, CRC counts, history) on one screen. Tuning and
  signal quality are viewed together because each is judged by the other.
- **Telemetry page:** ground-station cards that each viewer can drag and resize.
  In v1 they show the same content as the terminal dashboard: latest frame, device
  status, link statistics, channel metrics, and a frame log. There is also an empty
  placeholder card for FLIGHT data.

The GUI runs as a local web server. The operator's Mac opens it in a browser.
Later, a Raspberry Pi at the ground station runs the same server, and any laptop,
tablet, or phone on the local network can view it.

## Non-goals (v1)

- **FPGA commands.** The FPGA has no UART RX, command decoder, or
  acknowledgement. Tuning changes the host's frequency plan and the host
  simulator only. The "Send to FPGA" control stays disabled and says why.
- **Pi deployment:** service files, autostart, and packaging. v1 must run on a
  Pi, but it is not installed there.
- **HTTPS**, user accounts, and a Member role.
- **FLIGHT/HK plots.** The cards exist; the plots wait for real frames.
- **Protocol or RTL changes.**

## Architecture

```text
            ┌──────────────── Python process: `./sdr gui` ───────────────────┐
 UART ──▶   │ Source ─▶ StreamDecoder ─▶ Hub ─▶ WebSocket fan-out ─▶ clients  │
 capture ─▶ │ (serial | replay | sim)      │     static files (built Svelte)  │
            │                    TuningState + RoleManager                    │
            └─────────────────────────────────────────────────────────────────┘
 Browser (Mac, iPad, phone on the LAN): Svelte app ◀─── WebSocket JSON ───▶
```

- **Python owns everything that touches the board and all shared logic.** It
  reuses `protocol.StreamDecoder`, `protocol.LinkState`, `display.WaterfallScale`,
  and `serial_io.Session`. There is no second decoder, scale, or frequency-math
  implementation in TypeScript.
- **The browser renders and sends intent.** It draws with canvas, holds per-viewer
  preferences (card layout, freeze, manual scale override), and sends tuning
  requests. The server validates each request and broadcasts the result.
- **Tuning state is server-side and shared.** When the Admin drags the LO, every
  viewer's plan updates. Derived values (LO, VCO, PFD, step, IF, image, NCO FTW)
  are computed in Python and sent with the state.

### Python modules (`tools/sdr_cli/`)

| Module | Responsibility | UI imports |
| --- | --- | --- |
| `freqplan.py` | Fractional-N synthesizer model; LO ⇄ (N, FRAC) with quantization; IF, image, window checks; NCO tuning word. Pure functions/dataclasses. | none |
| `sources.py` | `SerialSource` (wraps `Session`), `ReplaySource` (a `.bin` capture at real or scaled speed, optional loop), `SimSource` (host-side stand-in producer that responds to `TuningState`). All yield raw bytes. | none |
| `hub.py` | Feeds bytes to one `StreamDecoder`/`LinkState`; per-channel `WaterfallScale`; turns records into client messages; counts decode stats. asyncio, no web framework. | none |
| `roles.py` | `RoleManager`: Viewer/Admin, single Admin, takeover flow, password check. Pure logic with a clock parameter for tests. | none |
| `web/server.py` | aiohttp app: static files, `/ws` endpoint, glue between hub, roles, and tuning. | aiohttp |
| `cli.py` | New `gui` subcommand. | — |

`SimSource` produces real protocol bytes with `protocol.encode_message` and the
`SYNTHETIC` flag. The GUI therefore exercises the same decode path as hardware.
Its spectrum and metrics move with LO/NCO changes, like the mockup, so the Tune
page can be developed without the board. **Only SimSource responds to tuning.**
With `SerialSource`, the FPGA stand-ins ignore it, and the UI shows a notice to
that effect.

### Frontend (`tools/sdr_web/`)

Svelte 5 + Vite + TypeScript, built to `tools/sdr_cli/web/static/`. The build
output is ignored by Git (see Build and run).

```text
src/
  lib/link.ts            WebSocket client, reconnect, typed message union, stores
  lib/types.ts           mirrors the server message schema
  lib/canvas/            waterfall.ts, spectrum.ts, constellation.ts, sparkline.ts (plain canvas, no chart library)
  lib/components/        Waterfall.svelte, FreqPlan.svelte, TuningDigits.svelte,
                         SynthPanel.svelte, NcoPanel.svelte, ChannelQuality.svelte,
                         Card.svelte, CardGrid.svelte, RoleMenu.svelte, StatusBar.svelte
  pages/Tune.svelte, pages/Telemetry.svelte
  App.svelte
```

Pages only compose components. Each component takes its data as props or stores
and has no knowledge of sources. The card grid (drag to reorder, corner resize,
saved per device in `localStorage`) is written in the app, as in the mockup. No
grid library is used.

## Branding and theme

The GUI is a **Space Raiders** product. Space Raiders is the rocketry division of
the Raider Aerospace Society at Texas Tech. Only Space Raiders appears in the UI;
the parent organization does not.

- **Logo:** `tools/sdr_web/src/assets/space-raiders-logo.png` is the original,
  with black text, for light theme. `space-raiders-logo-on-dark.png` has the
  lettering recolored to near-white for dark theme; the swoosh is unchanged. It
  sits at the left of the header.
- **Brand red:** `#FB0000`, sampled from the logo swoosh. Light theme uses
  `#D10000` so text keeps contrast on white. Texas Tech colors are red, black,
  and white, so the neutrals are true black/white greys with no hue tint.
- **Where red is used:** identity and chrome only. That means the logo, the
  active-tab marker, primary buttons, focus rings, and the Admin badge. It is not
  used as a data color. Channel, LO, and IF colors stay as in the mockup.
- **Status colors:** "bad" status uses a coral (`#FF7A6B` dark / `#C23A2B` light)
  rather than brand red, and every status chip carries a text label. Status is
  therefore never confused with branding, and never shown by color alone.
- **Themes:** dark by default for the bench, and a light theme for outdoor
  tablets and phones. The light theme follows the system setting, and a header
  toggle cycles System / Dark / Light, stored per device. The waterfall colormap
  is the same in both themes.
- **Type:** Jost, a geometric sans close to the logo lettering, for UI and
  uppercase labels. JetBrains Mono is used for readouts. Both are bundled through
  `@fontsource` packages so the LAN deployment needs no internet.

## Server ↔ client messages

JSON text frames over `/ws`. Each has a `type`.

Server → client:

| type | When | Content |
| --- | --- | --- |
| `hello` | on connect | server version, protocol version, source state, role, current tuning. It is followed by `stats` and the latest STATUS, LINK_STATS, metrics, I/Q and BEST_TELEM records, so a new viewer is not blank. |
| `record` | each decoded non-spectrum record | `Record.as_json()` plus APEX summary for frames |
| `spectrum` | each SPECTRUM row | channel, `f0_hz`, `bin_hz`, bins, `db` array (0.1 dB ints), server auto-scale `low/high` |
| `stats` | 2 Hz | decoder stats (errors, gaps, resync), byte rate, per-type rates, source state |
| `tuning` | on any accepted change | full `TuningState` plus derived values and warnings |
| `role` | on role change | your role, current Admin's label, `since`, and a reason (`login`, `taken_over`, `logout`) |
| `error` | on rejected request | code and human text, e.g. `not_admin`, `bad_password`, `out_of_range` |

The server also sends `takeover_required {held_by, since}` when a correct
password meets a held Admin, and `pong`.

Client → server:

- `login {password, label, takeover}`
- `resume {token}`
- `logout`
- `tune {changes}`: a partial TuningState, or `lo_hz`
- `reconnect_source` (Admin only)
- `ping`

`tune` is accepted only from the current Admin. Drag updates are throttled
client-side to ≤ 30 Hz. The server coalesces them and replies with the quantized
state. Bandwidth per client is about the link rate: about 12 kB/s of JSON for
today's traffic.

## Tuning state

Persisted to ignored `.sdr/gui_state.json`. Defaults match the mockup and are
labelled placeholders in the UI:

- carrier: 441.480 MHz nominal
- mixer injection: low-side
- target IF: 100 kHz, XADC window ±35 kHz
- synthesizer: 10 MHz reference, R = 1, N = 353, FRAC = 1040, MOD = 10000, output ÷8
  (LO 441.380 MHz, 125 Hz step), with a placeholder VCO range of 2.2–4.4 GHz
- NCO: 100 kHz at 1 MS/s, channel filter ±35 kHz

Validation: integer ranges, FRAC < MOD, and positive rates. Out-of-range VCO or
signal-outside-window produce **warnings**, not rejections.

## Roles

- **Viewer** is the default for every connection. It sees everything. Tuning
  controls are shown read-only, with a "Log in as Admin to change" hint.
- **Admin** is unlocked with Role → Admin, a display label (e.g. "groundstation"),
  and the password. Only the Admin can send `tune`.
- **One Admin at a time.** If Admin is held, a correct password returns
  `needs_takeover` with the holder's label and start time. The client then asks
  *"Admin is held by groundstation since 14:02. Take over? They will become a
  Viewer."* Confirming resends with `takeover: true`. The previous Admin receives
  `role {viewer, reason: taken_over, by: label}` and a visible notice.
- Admin is released on logout, or 15 s after the socket drops, so a page reload
  keeps Admin through a resume token held in `sessionStorage`.
- **Password:** set with `./sdr setup --gui-password` (prompted with `getpass`,
  never on the command line). It is stored as a salted PBKDF2-SHA256 hash under
  `gui_admin_hash` in `.sdr/config.json`. With no password configured, Admin is
  available only to clients connecting from localhost. A wrong password gets a
  1 s delay.
- **Security level:** over plain HTTP on a LAN this prevents accidental or casual
  changes. It does not resist someone sniffing the network. The README states
  this.

## Build and run

```sh
.venv/bin/python -m pip install -e '.[gui]'   # adds aiohttp only
(cd tools/sdr_web && npm install && npm run build)
./sdr gui                        # serial source, 127.0.0.1:8080, opens the browser
./sdr gui --source sim           # no board needed
./sdr gui --source replay .sdr/captures/X.bin [--loop] [--speed 2]
./sdr gui --lan                  # bind 0.0.0.0 and print the LAN URL(s)
```

- The `gui` extra in `pyproject.toml` adds `aiohttp`. The base install stays
  pyserial-only.
- Node is needed only to build the frontend. If the built files are missing,
  `./sdr gui` exits with the build command.
- `npm run dev` runs Vite with a proxy to a running `./sdr gui --no-browser` for
  frontend work.
- The GUI server owns the UART like the dashboard does. Only one may be connected.
  `./sdr gui` reports the busy-port error the dashboard already uses.

Frontend dependencies (dev-time only): svelte, vite, @sveltejs/vite-plugin-svelte,
typescript, svelte-check, vitest. No runtime CDN, so the app works on a LAN with
no internet.

## Consistency with CLI and dashboard

- Record descriptions in the frame log use `protocol.describe()`, sent from the
  server, so the text matches `./sdr receive`.
- Everything flagged `SYNTHETIC` shows the SIMULATED badge, as in the dashboard.
- A STATUS version other than `PROTOCOL_VERSION` shows the same rebuild warning.

## Error handling

- **Source failure** (USB unplugged, file ended): the server keeps running,
  broadcasts a source-down state, and the status bar turns red with the reason.
  There is no automatic serial reconnect in v1, matching the dashboard. An Admin
  can press Reconnect.
- **WebSocket drop:** the client shows "Disconnected — retrying" and reconnects
  with backoff. Stores keep the last data greyed out.
- **Malformed client messages** get an `error` reply and are otherwise ignored.
  They never crash the server.

## Testing

Python (`tools/tests/`, unittest, run by the existing discover command):

- `test_freqplan.py`: LO ⇄ N/FRAC round trips at the default and at edge values,
  quantization to step, high- and low-side IF/image, FTW against hand-computed
  values, and validation.
- `test_roles.py`: single Admin, takeover prompt and confirm, demotion notice,
  disconnect grace with a fake clock, and localhost-only Admin with no password.
- `test_sources.py`: replay of `tools/tests` sample bytes, and SimSource output
  that decodes with zero errors and moves its spectrum peak when the LO changes.
- `test_gui_server.py`: aiohttp test client with `IsolatedAsyncioTestCase`.
  Covers `hello`, record/spectrum fan-out from a replay source, a viewer `tune`
  rejected, and an Admin `tune` broadcast to a second client. It is skipped with
  a message if aiohttp is not installed.

Frontend (`npm test`, `npm run check`):

- Vitest for frequency-to-pixel mapping, ring buffers, the waterfall row writer,
  the card layout reducer, and message parsing.
- svelte-check type checking.

Manual check before hand-off: `./sdr gui --source sim` on the Mac, a phone on the
same LAN with `--lan`, and a takeover between two browsers. Hardware check: with
the board connected, run `./sdr gui` against the current bitstream. The last two
are reported only if actually run.

## Documentation to update on completion

`tools/README.md` (GUI section), `README.md` (start-here commands and repository
map), `docs/HANDOFF.md` (checkpoint, what was tested, what remains), and
`AGENTS.md` if the verification commands change.

## Open items outside this spec

- **Deployment (later).** Develop and build on a laptop. Ship only the built
  frontend plus the Python package to the Pi. A later CI job would build on push
  and publish the bundle, either to an artifact server or to a Git LFS repo. The
  Pi then updates by pulling the bundle and restarting its service. v1 keeps the
  built output in one directory (`tools/sdr_cli/web/static/`) so it can be
  packaged that way.

- The module map lists a 428–438 MHz bandpass filter, which does not contain the
  441.48 MHz carrier. This needs confirming with the RF design.
- The synthesizer part, the XADC rate, and the channel filter width are unchosen.
  The GUI shows placeholders until they are fixed.

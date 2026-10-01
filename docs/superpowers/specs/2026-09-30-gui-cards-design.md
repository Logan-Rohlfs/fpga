# SDR web GUI overhaul: card telemetry, presets and multi-viewer fan-out

Status: design, 2026-09-30. Nothing here is implemented yet. The plan is
[2026-09-30-gui-cards.md](../plans/2026-09-30-gui-cards.md).

This spec extends the [v1 GUI design](2026-09-29-gui-design.md). It is binding
on the decisions recorded in `.superpowers/sdd/gui-overhaul-decisions.md`
(user conversation, 2026-09-30). Where this spec settles something the decisions
file left open, the text is marked **Refinement**. Other readers should treat
those as design choices that can be revisited, not as user rulings.

## 1. Goal and context

The flashed demo bitstream (`./sdr build --demo`, BUILD_ID `SDRF`) now delivers
APEX FLIGHT frames at 20 Hz through the real receiver. The v1 GUI shows them only
as "APEX FLIGHT seq=N" text. This overhaul:

- turns the Telemetry page into a ground-station **card system**. The operator
  builds layouts from a catalogue of cards, and presets are stored on the server
  and shared with viewers;
- shows the decoded FLIGHT fields, derived flight and link events, maps, a 3D
  trajectory, spectra and link quality;
- updates the Tune page for the real receiver and demo data;
- makes the server serve about 10 remote viewers on a Raspberry Pi hotspot. The
  scarce resource there is bandwidth.

It is loosely inspired by the APEX "Horizon" ground station, which is a fixed
PyQt window with no map, camera, presets or unit switch. Its field list and
badge semantics carry over. Its layout does not.

**Data honesty.** The IREC 2026 flight log has flight-computer oddities. GPS
lat/lon read about 65.7/123.2 with `gps_fix` 0, and some stretches are frozen.
The GUI shows decoded values as they are. It never "corrects" them and never
calls them receiver faults. Only malformed frames are rejected: a bad CRC, or a
length that does not match the frame type. Every value derived from SYNTHETIC
records is labelled as simulated (section 12).

### Supersedes

This spec replaces these parts of the v1 spec:

| v1 section | Replaced by |
| --- | --- |
| Goal → Telemetry page (fixed cards, per-device layout) and the FLIGHT/HK placeholder non-goal | §7 cards, §8 grid, §6 presets |
| Frontend: "no chart or grid library", plain canvas only | §2.6 dependencies (leaflet, uplot, three) |
| Server ↔ client messages: the JSON `spectrum` message, the hello snapshot and all-to-all forwarding | §3 channels, wire format and history |
| Backpressure by closing slow clients with 1013 for any overflow | §3.3: data is dropped or coalesced. Only control overflow closes. |
| Freeze drops incoming records | §11.3: freeze stops drawing only. Ingestion continues. |
| Error handling: "no automatic serial reconnect in v1" | §18: automatic serial reconnect with back-off |
| Role name "Admin" in the UI | §5: the UI calls it "Operator". The wire value stays `admin`. |

It also supersedes Task 6 ("GUI flight readout") of
[the sample-driven receiver plan](../plans/2026-09-29-sample-driven-receiver.md).
The Number, State and Plot cards and the Flight preset replace it.

Everything else in the v1 spec still holds: branding, theme, the tuning state
model, the login, takeover and resume flow, build and run, and error handling
for source failure.

## 2. Architecture and data flow

```text
 Source ─▶ StreamDecoder ─▶ Hub ─┬─▶ FlightRows (BEST / A / B)  ─┐   encode once
                                 ├─▶ EventDeriver ─▶ events      │   (bytes / JSON str)
                                 ├─▶ link / frames / iq records  ├─▶ Outgoing(channel, mode, key, data)
                                 ├─▶ spectrum rows (binary)      │          │
                                 └─▶ History (capped rings) ◀────┘          ▼
                                                               per-client Outbox (fanout.py)
                                                  subscriptions · role budget · slots · stream
                                                                            │
                                                         aiohttp /ws (permessage-deflate)
                                                                            ▼
 Browser: link.ts ─▶ decoders ─▶ SeriesStore rings / stores ─▶ rAF scheduler ─▶ visible cards
```

### 2.1 Python modules (toolkit-free unless noted)

| Module | Responsibility | New / changed |
| --- | --- | --- |
| `apex.py` | FLIGHT decode. Adds the interlock bits (phase_status 3–7), the health bits 0–7, the GPS-fix labels and `FLIGHT_SCHEMA` (ordered field metadata). | changed |
| `units.py` | Quantity and unit catalogue (`CATALOGUE`), used to validate unit ids in presets. The frontend imports the identical `tools/sdr_web/src/lib/units.catalogue.json`. A Python test asserts that the two are equal. | new |
| `gui_wire.py` | Binary encoders for spectrum rows and flight rows, `flight_values(fields)`, and golden vectors. | new |
| `events.py` | `EventDeriver`: flight and link events from decoded records (§10). Pure, with the time injected. | new |
| `history.py` | `History`: capped rings of encoded rows and records, and per-channel snapshot builders (§3.5). | new |
| `fanout.py` | Channel names, `Outgoing`, `Outbox` (per-client subscriptions, rate budgets, latest-wins slots, bounded stream), `ROLE_BUDGETS`. | new |
| `presets.py` | Preset validation, builtin and local stores, atomic writes, live/default state (§6). | new |
| `maps.py` | Site registry loading, tile coverage math, the polite resumable fetcher (stdlib `urllib`), tile path resolution (§13). | new |
| `hub.py` | Decodes once. Feeds History, EventDeriver and the row encoders, and publishes `Outgoing` objects that are encoded once. Adds the receiver `profile` to the source state. | changed |
| `receiver_control.py` | Adds `PROFILES`, a BUILD_ID → profile description map (§14). | changed (additive) |
| `web/server.py` | Thin glue. Adds the `subscribe` and preset messages, binary sends, `/tiles/...` and client counts. | changed |
| `cli.py` | Adds `maps fetch` and `maps list`, which call `maps.py`. | changed (additive only) |

Data files:

- `tools/sdr_cli/sites.json`, the tracked site registry;
- `tools/sdr_cli/presets/*.json`, the builtin presets (the default is `flight.json`);
- `tools/sdr_web/src/lib/units.catalogue.json` and `tools/sdr_web/src/lib/cards/card-types.json`,
  shared lists that Python tests cross-check;
- `tools/sdr_web/src/lib/wire.golden.json`, binary golden vectors written by
  Python and decoded by Vitest.

Package data in `pyproject.toml` adds `sites.json` and `presets/*.json`.

### 2.2 Frontend structure (`tools/sdr_web/src/`)

```text
lib/wire.ts            binary decoders (spectrum row, flight rows)
lib/series.ts          SeriesStore: columnar ring (Float64 time, Float32 values)
lib/link.ts            socket, subscribe(), control/data dispatch, stores
lib/subscriptions.ts   channels needed by (page, layout, card configs, visibility)
lib/units.ts           conversion + formatting from units.catalogue.json
lib/grid.ts            12-column grid model (replaces layout.ts)
lib/virtual.ts         fixed-row list windowing
lib/frame.ts           single rAF scheduler with dirty + visibility flags
lib/presets.ts         preset selection, follow-operator, local convenience storage
lib/events.ts          event-log filtering and formatting (derivation is server-side)
lib/geo.ts             tile math, local ENU projection, GPS validity
lib/cards/registry.ts  card type → meta, config defaults, sanitize(), channels()
lib/cards/card-types.json
components/CardGrid.svelte, CardFrame.svelte, CardSettings.svelte, PresetBar.svelte
cards/<Type>Card.svelte   one component per card type
pages/Tune.svelte, pages/Telemetry.svelte
```

The old `lib/layout.ts`, `lib/cards.ts` and `pages/telemetry/*.svelte` are
removed once their replacements land. The old `sdr.telemetry.layout`
localStorage key is ignored.

### 2.3 Record → channel mapping

| Decoded record | Channel(s) | Mode |
| --- | --- | --- |
| BEST_TELEM, APEX FLIGHT, frame `crc_ok` true, length valid | `flight` (flight row, origin `best`) and `frames` | stream |
| CHAN_FRAME A/B, APEX FLIGHT, `crc_ok` true, APEX CRC true | `flight.A` / `flight.B` (row) and `frames` | stream |
| Any other BEST_TELEM or CHAN_FRAME (TEST, HK, CRC-bad, unknown) | `frames` only | stream |
| Derived events | `events` | stream |
| STATUS, LINK_STATS, CONFIG, CHAN_METRICS (per channel) | `link` | slot, key `link.<TYPE>[.<ch>]` |
| SPECTRUM A/B | `spectrum.A` / `spectrum.B` (binary row) | slot, key = channel |
| IQ_SNAPSHOT A/B | `iq.A` / `iq.B` | slot, key = channel |
| stats (2 Hz) | always sent | slot `stats` |
| hello, role, presets, takeover_required, error, pong, history markers | always sent | control (ordered) |
| tuning | always sent | control slot `tuning` (latest wins, never rate limited) |

A frame is written to a flight channel only when the APEX CRC and the frame
length are both valid. Malformed frames still reach `frames`, where they are
shown as CRC-BAD, and the CRC-burst events (§10).

### 2.4 Rate budgets

Budgets live in `fanout.ROLE_BUDGETS` as minimum intervals per channel. `0` means
the source rate.

| Channel | Operator | Viewer |
| --- | --- | --- |
| `flight`, `flight.A`, `flight.B`, `events` | 0 (stream, every row) | 0 (stream, every row) |
| `spectrum.A`, `spectrum.B` | 0 (slot) | 0.2 s (slot, 5 Hz) |
| `iq.A`, `iq.B` | 0 (slot) | 0.5 s (slot, 2 Hz) |
| `link` (each slot key) | 0 (slot) | 0.2 s (slot) |
| `frames` | 0 (stream) | 0.1 s (stream sampled: at most 10 records/s; the excess is dropped and counted) |
| `stats` | 0.5 s | 0.5 s |

A slot never queues. Each client holds at most one pending message per slot key,
and a new one replaces it. **Refinement:** `tuning` is a latest-wins control
slot. Losing an intermediate tuning state during a drag is harmless because the
latest state is authoritative. Role and preset messages are never coalesced.

Estimated viewer load with the Flight preset: flight rows 20 Hz × about 92 B,
link slots at 5 Hz, and two 64-bin waterfalls at 5 Hz. That is **≤ 10 kB/s per
viewer before compression**. Task 6 measures it with a replay source. With 10
viewers this is about 100 kB/s, well within a Pi hotspot.

### 2.5 Encode once

`Hub` builds each `Outgoing` once. JSON is serialized with
`json.dumps(msg, separators=(',', ':'))` into a `str`. Binary rows are `bytes`.
Every outbox holds references to the same object. aiohttp's permessage-deflate
(`WebSocketResponse(compress=True)`, negotiated when the browser offers it)
compresses per connection. That per-connection cost is accepted and measured in
verification. Stats messages are also encoded once per tick.

### 2.6 Dependencies

The runtime frontend dependencies are the user-approved **leaflet**, **uplot** and
**three**. `three` is loaded only through `import('three')` inside the 3D card, so
it is a separate chunk that is fetched only when a 3D card is mounted.
**Refinement:** the dev-only type packages `@types/leaflet` and `@types/three`
are allowed, because svelte-check needs them. uPlot ships its own types. All of
these are bundled by Vite. No CDNs are used, and Leaflet's CSS is imported from
the package. Python gains nothing: the tile fetcher uses `urllib`. Task 23
updates the AGENTS.md dependency rule.

## 3. Wire protocol

WebSocket `/ws`. Text frames are JSON objects with `type`, as in v1. Binary frames
start with a one-byte `kind` and a one-byte `version` (1). All binary integers and
floats are little-endian.

### 3.1 Client → server messages

| type | Who | Content / effect |
| --- | --- | --- |
| `subscribe` | anyone | `{channels: string[]}` replaces the client's set. Unknown names produce `error{code:'bad_channel'}` and the whole request is ignored. Each newly added channel receives its history snapshot (§3.5). The server replies `subscribed{channels}`. |
| `preset_save` | operator | `{preset, base_revision}` (§6). |
| `preset_delete` | operator | `{id}` |
| `preset_set_live` | operator | `{id}` |
| `preset_set_default` | operator | `{id}` |
| `preset_auto_switch` | operator | `{enabled}` |
| `login`, `resume`, `logout`, `tune`, `use_compiled_profile`, `reconnect_source`, `ping` | as v1 | unchanged |

A non-operator sending an operator message receives
`error{code:'not_admin', text:'Only the Operator can …'}`, and nothing changes.

### 3.2 Server → client messages

| type | Content |
| --- | --- |
| `hello` | v1 fields plus `flight_schema` (§4), `sites` (the registry plus the downloaded layers and zooms per site, §13), `channels` (valid names), and `budget` (`'operator'` or `'viewer'`). |
| `presets` | `{items: Preset[], live, default, auto_switch}`. Sent after hello and whenever anything preset-related changes. |
| `subscribed` | `{channels}` |
| `history` | `{channel, count}` marks a snapshot start. The client clears that channel's store, and the following binary rows are the snapshot. |
| `events` | `{items: Event[], reset: bool}`. `reset: true` is the snapshot. |
| `record` | v1 shape (`record`, `text`), used by `link`, `frames` and `iq.*`. |
| `metrics_history` | `{channel:'A'\|'B', t:[], rssi:[], noise:[], snr:[], df:[], crc_good:[], crc_bad:[], power_unit}`: the link snapshot for sparklines. |
| `stats` | v1 fields plus `clients: {operators, viewers}` and `source.profile` (§14). |
| `dropped` | `{channel:'frames', count}` is sent to a viewer at most once per second while its `frames` sampling drops records. |
| `tuning`, `role`, `takeover_required`, `error`, `pong` | as v1 |

The JSON `spectrum` message is removed. Spectrum is binary only.

### 3.3 Backpressure

Each client has one `Outbox`:

- **control**: an ordered deque, max 400 (the existing `QUEUE_MAX`). If it
  overflows, the socket closes with 1013 "Slow viewer: reconnect for current
  state", as today, because role and preset messages must not be lost. A healthy
  client should never reach this.
- **slots**: a dict of key → latest item, each with a `due` time taken from the
  role budget.
- **stream**: an ordered deque of stream items for the subscribed stream
  channels. Its maximum length is 2000 for the operator and 600 for a viewer. On
  overflow (more than the maximum of live items queued; snapshot items do not
  count), the outbox clears the whole stream queue and marks every channel that
  had queued items `resync`. Discarding only the busiest channel would leave the
  queue near the cap after a quiet channel's items remained, so it would
  re-overflow at once. The send loop then enqueues a fresh history snapshot for
  each resync channel, so the client's store is rebuilt rather than silently
  gapped. The client is never disconnected for data.

Send order: control first, then stream (FIFO), then due slots (oldest first). The
send loop awaits `ws.send_*`, so a slow TCP connection makes messages coalesce in
the outbox instead of piling up in memory.

### 3.4 Binary formats

**Kind 0x01: SPECTRUM_ROW** (52-byte header followed by `bins` × int16):

| off | type | field |
| --- | --- | --- |
| 0 | u8 | kind = 0x01 |
| 1 | u8 | version = 1 |
| 2 | u8 | channel (0 = A, 1 = B) |
| 3 | u8 | flags: bit0 SYNTHETIC, bit1 rf_reference present, bit2 rf inferred |
| 4 | u32 | row |
| 8 | u16 | bins |
| 10 | u16 | reserved (0) |
| 12 | f64 | t (host epoch seconds) |
| 20 | f64 | f0_hz (frequency of bin 0, FPGA IF domain) |
| 28 | f32 | bin_hz |
| 32 | f32 | low (auto-scale, dBFS) |
| 36 | f32 | high (auto-scale, dBFS) |
| 40 | f64 | rf_lo_hz (NaN when flag bit1 is clear) |
| 48 | u8 | rf_injection (0 low, 1 high, 255 unknown) |
| 49 | u8[3] | reserved (0) |
| 52 | i16[bins] | db10: power in 0.1 dBFS |

The frontend decodes this into the existing `SpectrumMsg` shape. `db10` becomes
an `Int16Array`, and `rf_reference` is rebuilt from the flags. The Tune page
waterfall code therefore keeps its interface.

**Kind 0x02: FLIGHT_ROWS** (8-byte header followed by N rows):

| off | type | field |
| --- | --- | --- |
| 0 | u8 | kind = 0x02 |
| 1 | u8 | version = 1 |
| 2 | u8 | origin (0 = CHAN_FRAME A, 1 = CHAN_FRAME B, 2 = BEST_TELEM) |
| 3 | u8 | reserved (0) |
| 4 | u16 | F, the field count (must equal `flight_schema.fields.length`) |
| 6 | u16 | N, the row count (1 live; up to 4096 per message in snapshots) |

Each row is `10 + 4F` bytes:

| off | type | field |
| --- | --- | --- |
| 0 | f64 | t (host epoch seconds of the record) |
| 8 | u8 | flags: bit0 SYNTHETIC; bits1–2 best_from (0 A, 1 B, 2 combined, 3 n/a) |
| 9 | u8 | reserved (0) |
| 10 | f32[F] | values in `flight_schema` order, in SI units |

With F = 20 (§4) a row is 90 bytes. Enum and bitfield fields travel as small
integers stored in f32 values. The schema says how to read them. If a client
gets a row whose F differs from its schema, it drops the row and requests a full
reconnect. That cannot happen in one server version, but it guards stale tabs.

Golden vectors: `gui_wire.golden_vectors()` produces fixed inputs and their hex
encodings. The generator writes them to `tools/sdr_web/src/lib/wire.golden.json`.
A Python test fails when the file is stale, and a Vitest test decodes every
vector. This follows the protocol/RTL cross-check pattern.

### 3.5 History and snapshots

`History` (Python) keeps these capped stores. Each holds encoded bytes or records,
so a snapshot is never re-encoded:

| Store | Cap | Snapshot on subscribe |
| --- | --- | --- |
| flight rows per origin (best, A, B) | 36,000 rows (30 min at 20 Hz) | Every row from the last 120 s, plus every 20th older row (about 1 Hz), in time order, in FLIGHT_ROWS batches of ≤ 4096 |
| events | 2,000 | all, as `events{reset:true}` |
| spectrum rows per channel | 120 | all 120, as individual SPECTRUM_ROW messages |
| IQ per channel | latest 1 | latest |
| link | latest STATUS, LINK_STATS, CONFIG, CHAN_METRICS A/B; plus 600 metrics per channel | latest records, then `metrics_history` |
| frames | 200 records | all 200 |

A snapshot is `history{channel, count}` followed by its rows. It is put on the
client's stream queue in one synchronous step, so no live row can interleave
out of order. Snapshots bypass the viewer rate budget. They are the "late viewer
sees the flight so far" guarantee.

At the caps, a full flight snapshot is about 2,400 + 1,680 rows × 90 B ≈ 370 kB
before compression. That is acceptable for a join, and far less once deflated.

## 4. Flight schema and decode

`apex.FLIGHT_SCHEMA` is a tuple of field descriptors sent in `hello.flight_schema`:

```json
{"version": 1, "fields": [
  {"key": "seq", "label": "Seq", "quantity": "count", "digits": 0},
  {"key": "phase", "label": "Phase", "quantity": "enum",
   "enum": ["IDLE","ARMED","BOOST","COAST","DESCENT","LANDED","UNKNOWN"]},
  {"key": "phase_status", "label": "Interlocks", "quantity": "bits",
   "bits": {"3": "airbrakes_authorized", "4": "servo_powered", "5": "arm_switches_closed",
            "6": "logging_ready", "7": "gps_time_valid"}},
  {"key": "health", "label": "Health", "quantity": "bits",
   "bits": {"0": "imu", "1": "highg", "2": "baro", "3": "mag",
            "4": "gps", "5": "radio", "6": "qspi", "7": "sd"}},
  {"key": "gps_fix", "label": "GPS fix", "quantity": "enum_signed",
   "enum_map": {"-1": "OFFLINE", "0": "SEARCHING", "1": "DR", "2": "2D", "3": "3D", "4": "3D+DR"}},
  {"key": "gps_sats", "label": "Satellites", "quantity": "count", "digits": 0},
  {"key": "lat_deg", "label": "Latitude", "quantity": "coordinate", "digits": 6},
  {"key": "lon_deg", "label": "Longitude", "quantity": "coordinate", "digits": 6},
  {"key": "gps_alt_m", "label": "GPS alt MSL", "quantity": "length", "digits": 1},
  {"key": "alt_agl_m", "label": "Altitude AGL", "quantity": "length", "digits": 1},
  {"key": "velocity_mps", "label": "Velocity", "quantity": "speed", "digits": 1},
  {"key": "pred_apogee_m", "label": "Predicted apogee", "quantity": "length", "digits": 0},
  {"key": "vert_accel_mps2", "label": "Vertical accel", "quantity": "acceleration", "digits": 2},
  {"key": "accel_z_mps2", "label": "Accel Z", "quantity": "acceleration", "digits": 2},
  {"key": "roll_rate_rads", "label": "Roll rate", "quantity": "angular_rate", "digits": 3},
  {"key": "deployment", "label": "Airbrake deployment", "quantity": "ratio", "digits": 2},
  {"key": "baro_pa", "label": "Baro pressure", "quantity": "pressure", "digits": 0},
  {"key": "baro_temp_c", "label": "Baro temp", "quantity": "temperature", "digits": 0},
  {"key": "tilt_deg", "label": "Tilt", "quantity": "angle", "digits": 0},
  {"key": "azimuth_deg", "label": "Azimuth", "quantity": "angle", "digits": 1}
]}
```

The order is fixed. `gui_wire.flight_values(fields)` maps a decoded `apex._flight`
dict to these 20 values. For `phase` that is the index into the enum, and 6 means
UNKNOWN. `phase_status` and `health` are the raw bytes.

`apex._flight` gains `phase_status` (raw), `interlocks` (dict of the five named
booleans) and `health_bits` (dict of the eight named booleans). The raw `health`
key stays for compatibility. `summary()` is unchanged. Bit names follow Horizon
(`H/constants.py:94`, `state_panel.py:97-148`) and the `apex_flight_rom.py`
docstring. The GPS fix labels come from Horizon `GPS_FIX_LABELS`.

The demo ROM sets interlock bits 3–7, sensor bits 0–3 and the radio bit to zero,
because they are absent from the CSV. The GUI shows them as off, as they are.
The Health card adds a footnote when the receiver profile is `apex_demo` (§14).

HK frames are decoded but not replayed by the demo. They appear only in Raw
frames.

## 5. Roles and auth

The v1 `RoleManager` is unchanged: one privileged role, password (PBKDF2 hash
`gui_admin_hash`), takeover, 15 s resume grace, and localhost-only when no
password is set. The wire value stays `admin`. **Refinement:** the UI labels it
**Operator** everywhere, including the role menu, hints and error text.

Server-enforced operator-only actions: `tune`, `use_compiled_profile`,
`reconnect_source`, `preset_save`, `preset_delete`, `preset_set_live`,
`preset_set_default` and `preset_auto_switch`. Camera URLs exist only inside
preset card configs, so only the operator can set them. Viewers may `subscribe`,
`ping`, `login`, `resume` and `logout`.

Budget selection: an outbox uses the operator budget while its client holds the
role. On any role change the server calls `outbox.set_role(role)`. No
resubscription is needed.

Viewer preset choice and the follow-operator toggle are **client-side only**.
Viewers never write server state.

## 6. Presets

### 6.1 Storage

- Builtin, read-only presets live in `tools/sdr_cli/presets/<id>.json` (tracked).
  The only v1 builtin is `flight`.
- Local presets live in `.sdr/gui/presets/<id>.json`. `.sdr/` is already ignored.
- State lives in `.sdr/gui/preset_state.json`:
  `{"live": "<id>", "default": "<id>", "auto_switch": false}`. When it is missing
  or refers to deleted presets, `live` and `default` fall back to `flight`.
- Writes go to a temporary file in the same directory, then `os.replace`.

### 6.2 Schema (version 1)

An abridged example follows. It is not the shipped Flight preset, which task 22
lays out.

```json
{
  "schema": 1,
  "id": "example",
  "name": "Example",
  "revision": 1,
  "grid": {"cols": 12},
  "cards": [
    {"id": "state", "type": "state", "x": 0, "y": 0, "w": 3, "h": 3, "title": null,
     "config": {"source": "best", "show_time_in_phase": true}},
    {"id": "alt", "type": "number", "x": 3, "y": 0, "w": 3, "h": 3, "title": "Altitude",
     "config": {"field": "alt_agl_m", "source": "best", "digits": 0, "track_minmax": true,
                "thresholds": [], "units": {}}},
    {"id": "altplot", "type": "plot", "x": 0, "y": 3, "w": 6, "h": 7, "title": "Altitude",
     "config": {"series": [{"field": "alt_agl_m", "source": "best"},
                           {"field": "pred_apogee_m", "source": "best"}],
                "window_s": 60, "show_events": true, "units": {"length": "ft"}}},
    {"id": "cam", "type": "camera", "x": 6, "y": 3, "w": 6, "h": 7, "title": "Pad camera",
     "config": {"url": null, "mode": "mjpeg", "fit": "contain"}}
  ],
  "triggers": [
    {"on": "phase", "value": "BOOST", "preset": "boost"},
    {"on": "event", "value": "burnout", "preset": "coast-camera"}
  ]
}
```

Validation (`presets.validate(obj) -> dict`, which raises `PresetError(code, text)`):

- `schema == 1`. `id` matches `^[a-z0-9][a-z0-9-]{0,39}$`. `name` is 1–40
  printable characters. The server assigns `revision`.
- `grid.cols == 12`. `cards` has 0–40 entries. Each card `id` matches
  `^[a-z0-9-]{1,24}$` and is unique. `type` is in `presets.CARD_TYPES`, which
  must equal `card-types.json`. `x, y, w, h` are integers with `0 ≤ x`,
  `1 ≤ w`, `x + w ≤ 12`, `0 ≤ y ≤ 500` and `1 ≤ h ≤ 24`. Cards must not
  overlap. `title` is null or 1–40 characters. `config` is a JSON object.
- A camera card's `config.url` is null or a string of ≤ 500 characters whose
  scheme is `http` or `https`.
- `config.units`, when present, maps quantity names to unit ids that exist in
  `units.CATALOGUE`.
- `triggers` has 0–20 entries, each `{on: 'phase'|'event', value, preset}`. A
  `phase` value must be in `apex.PHASES`. An `event` value must be one of
  `launch`, `burnout`, `apogee` or `landing`. `preset` matches the id pattern.
  A target need not exist; missing targets are ignored at switch time.
  **Triggers are stored and validated; with the Operator's Auto-switch on they
  switch the live preset (task 24, implemented).**
- The whole preset serializes to ≤ 64 KiB.

The server validates structure. The frontend `registry.sanitize(type, config)`
applies per-type config defaults and drops unknown keys, so an old preset keeps
loading after a card gains an option. A Vitest test runs `sanitize` over
`flight.json` and asserts that nothing changes.

### 6.3 Operations

- **Save** (`preset_save{preset, base_revision}`) validates first, then
  applies these rules in order:
  1. A builtin id is rejected with `preset_readonly` ("Builtin presets are
     read-only; save a copy under a new name").
  2. `base_revision: null` means "create". If the id already exists, it is
     rejected with `preset_exists`.
  3. A numeric `base_revision` must equal the stored revision. Otherwise, for
     example after an operator takeover mid-edit, it is rejected with
     `preset_conflict`. A numeric `base_revision` for an id that does not exist
     is rejected with `preset_missing`.

  On success the server sets `revision` to 1 when creating, or to the stored
  revision + 1. It writes the file and broadcasts `presets`.
- **Delete** refuses builtins and the current default (`preset_in_use`, "Choose
  another default first"). Deleting the live preset resets live to the default.
- **Set live** and **set default** require an existing id. **Refinement:** the
  live view is always a *saved* preset, so half-edited layouts never reach
  viewers. Saving the live preset pushes the new revision to followers.

### 6.4 Viewer and operator UX

- `PresetBar` has a preset selector and a **Follow operator** toggle. The toggle
  defaults to on and is remembered in localStorage (`sdr.presets.follow`). While
  it is on, the page shows `presets.live` and follows its changes. Picking
  another preset turns it off. The bar always shows which preset is live.
- The operator additionally gets Edit, Save, Save as…, Delete, "Show to
  viewers" (set live) and "Make default". Edits change a local working copy.
  Leaving with unsaved changes asks for confirmation.
- The last selected preset and unit system per browser are kept in localStorage
  as a convenience only. The server is authoritative.

## 7. Card catalogue

Every card has a title (the preset `title` or the type default), a settings
popover (operator in edit mode; viewers see settings read-only), remove and
resize (edit mode), a unit override (`config.units`, quantity → unit id) where it
shows quantities, and a header badge for **SIMULATED** and data age (§12).
Config fields list their defaults. Min size is w×h in grid units.

Common `source` values for flight-fed cards are `best` (BEST_TELEM rows, the
default), `A`, `B`, and, where noted, `both` (A and B overlaid).

| Type | Config (defaults) | Channels | Min size |
| --- | --- | --- | --- |
| `plot` | `series: [{field, source}]` 1–6 (`[{alt_agl_m, best}]`); `window_s`: 10/30/60/120/300/0 = all (60); `y: 'auto' \| {min, max}` in display units ('auto'); `show_events` (true); `segment` current/all (current: only rows since the newest `flight_reset`; ring data is kept); `units` ({}) | `flight` / `flight.A` / `flight.B` per series source; `events` if `show_events` or `segment` is current; `link` for metric series | 3×4 |
| `number` | `field` (alt_agl_m); `source` best/A/B/both (best); `digits` 0–3 (field default); `thresholds: [{above, level}]` with `above` in SI and level good/warn/bad ([]); `track_minmax` (false); `units` | flight channel of the source | 2×2 |
| `state` | `source` (best); `show_time_in_phase` (true) | flight channel | 2×2 |
| `events` | `category` flight/link (flight); `kinds` (all kinds of that category); `newest_first` (true) | `events` | 3×4 |
| `map` | `site` (first registry site); `layer` imagery/topo (imagery); `follow` (true); `show_track` (true); `segment` current/all (current: only track rows since the newest `flight_reset`; ring data is kept); `source` (best) | flight channel; `events` if `segment` is current | 3×5 |
| `trajectory3d` | `site`; `layer` (imagery); `exaggeration` 1–5 (1); `segment` current/all (current: only track rows since the newest `flight_reset`; ring data is kept); `source` (best) | flight channel; `events` if `segment` is current | 4×6 |
| `camera` | `url` (null); `mode` mjpeg/video (mjpeg); `fit` contain/cover (contain) | none | 3×4 |
| `waterfall` | `channel` A/B (A); `scale: 'auto' \| {low, high}` ('auto') | `spectrum.<ch>` | 3×3 |
| `spectrum` | `channel` A/B/both (both); `peak_hold` (false); `peak_decay_s` 0–60, 0 = hold forever (10) | `spectrum.A`/`.B` | 3×3 |
| `constellation` | `channel` A/B (A); `mode` iq/inst_freq (iq); `persistence` 1–4 snapshots (4) | `iq.<ch>` | 2×3 |
| `link` | `channels` (['A','B']); `window_s` for rates and shares, 5/10/30 (10) | `link` | 3×3 |
| `health` | `source` (best) | flight channel | 3×3 |
| `gps` | `source` (best) | flight channel | 2×3 |
| `frames` | `filter` all/A/B/best (all); `view` text/hex (text) | `frames` | 3×4 |

Behaviour per card:

- **Plot** (uPlot): time on the x axis (wall clock), one y axis per quantity.
  Series must have at most two distinct quantities (left and right axes); the
  settings UI enforces this. Auto-scaling is on by default. Series may also be
  link metrics: `field` is `m.rssi`, `m.noise`, `m.snr` or `m.df`, and `source`
  is A/B, fed from `metrics_history` and live `link`. **Pause** freezes the
  x range; drag or wheel then scrubs within the stored history. **Live**
  resumes. Incoming data keeps accumulating while paused. With `show_events`,
  flight events (launch, burnout, apogee, landing, flight_reset) are drawn as
  vertical markers with labels. Redraws are driven by the rAF scheduler, at
  most once per frame and only while the card is visible.
- **Number**: a large value with its unit and the field label. A threshold level
  colours the value *and* adds a text chip (GOOD/WARN/BAD), so status is never
  shown by colour alone. Min/max tracking shows `min … max` since the last flight
  reset or card mount, with a reset button. For `both` it shows A and B side by
  side with channel colours.
- **State**: the phase name in a badge coloured per phase (Horizon
  `PHASE_COLORS` hues adapted to the theme tokens), the time in phase (mm:ss,
  since the last phase change on that source), and seq. An unknown phase value
  shows `UNKNOWN (n)`.
- **Event log**: titled "Flight events" or "Link events" by its `category`;
  the kind filter chips list only that category's kinds. Virtualized list (§11.2), timestamps
  (local time and T+ from the last launch when one exists), and value with
  units via `units.ts`.
- **Map** and **3D**: §13.
- **Camera**: §15.
- **Waterfall**: the existing `WaterfallImage` row-append canvas, one channel
  per card, and the server auto-scale unless it is manual. On viewers the row
  rate is ≤ 5 Hz; the card footer says "rows at viewer rate (5 Hz)".
- **Spectrum**: the latest trace per channel (dBFS), with an optional peak-hold
  trace that decays after `peak_decay_s`.
- **Constellation**: I/Q scatter of the last `persistence` snapshots.
  `inst_freq` mode plots the instantaneous frequency `Δφ·fs/2π` against the
  sample index from consecutive IQ pairs. This is display math on a received
  snapshot, not receiver frequency planning.
- **Link / channel quality**: per channel, signal and noise in the record's
  `power_unit`. That is **"dBFS (relative)"** for dBFS records, never presented
  as dBm. It also shows SNR (dB), Δf (kHz), CRC good/bad totals, the bad ratio
  over `window_s`, and the good-frame rate over `window_s` (from `crc_good`
  deltas). The combiner share A/B over `window_s` comes from LINK_STATS
  `from_a`/`from_b` deltas, shown as a split bar with percentages as text.
- **Health & flags**: eight health chips (IMU, HG, BAR, MAG, GPS, RAD, QSPI, SD)
  and five interlock chips (BRAKES AUTH, SERVO PWR, ARM SW, LOG READY, UTC).
  Each reads `ON` or `off` in text. In the demo profile a footnote reads
  "Demo ROM: interlock, sensor and radio bits are zero (absent from the flight
  log)."
- **GPS status**: fix label, satellites, lat/lon (6 dp), GPS alt MSL, and a
  validity line (§13.5). Values are shown even when invalid, in a muted style
  with the text "no fix".
- **Raw frames**: virtualized list of recent `frames` records. `text` view uses
  the server `text` (`protocol.describe`). `hex` view shows the raw hex in
  16-byte groups with the CRC bytes marked. CRC-BAD rows are marked with text.

## 8. Grid layout model

`lib/grid.ts` holds pure functions only. The Svelte component does DOM
measurement and pointer handling.

- **Model:** `GridCard {id, type, x, y, w, h, title, config}` on 12 columns.
  The row unit is 40 px and the gap 8 px at desktop width.
- **Operations:**
  - `collides(a, b)`;
  - `compact(cards)` (vertical gravity: each card, in (y, x) order, moves up
    while it does not collide);
  - `moveCard(cards, id, x, y)`: clamp to bounds, place, push colliding cards
    down recursively, then compact;
  - `resizeCard(cards, id, w, h, minW, minH)`: the same push-and-compact;
  - `addCard(cards, card, minW, minH)`: place at the first free row, leftmost,
    raising the size to the card type's minimum;
  - `removeCard`;
  - `readingOrder(cards)` (sort by y, then x);
  - `reflow(cards, cols)` for narrow screens;
  - `sanitizeGrid(cards, minSizeOf)`: drop invalid entries, clamp, resolve
    overlaps.
- **Snapping:** pointer drags convert pixel deltas to grid units with
  `Math.round`. The dragged card shows a placeholder at the snapped cell.
  Keyboard in edit mode: arrows move the focused card, and Shift+arrows resize
  it.
- **Responsive:**
  - ≥ 1100 px uses the authored 12-column layout.
  - 600–1099 px uses a 6-column reflow: reading order,
    `w6 = max(w ≥ 7 ? 6 : 3, ceil(minW / 2))` capped at 6, heights unchanged,
    then first-fit packing (each card at the lowest y where it fits, then the
    leftmost x).
  - < 600 px is a single column in reading order. Each card's height is its
    authored height in 40 px rows, but at least the type's phone minimum.
  - Editing is only available at ≥ 1100 px. Narrower screens show "Widen the
    window to edit the layout."
- **Pause off-screen:** `CardFrame` uses an IntersectionObserver to set a
  `visible` flag. Hidden cards skip drawing (§11.1). When the document is hidden,
  every card is treated as not visible.

## 9. Units

- SI internally, everywhere: Python decode, the wire, history and stores.
- `units.catalogue.json` (identical to `units.CATALOGUE`) defines quantities,
  their units as `{label, factor, offset}` (display = si × factor + offset), and
  unit systems:

| Quantity | SI | Units offered | metric | imperial |
| --- | --- | --- | --- | --- |
| length | m | m, km, ft | m | ft |
| speed | m/s | m/s, km/h, mph, ft/s | m/s | ft/s |
| acceleration | m/s² | m/s², ft/s², g (9.80665) | m/s² | ft/s² |
| pressure | Pa | Pa, hPa, inHg | hPa | inHg |
| temperature | °C | °C, °F | °C | °F |
| angle | deg | deg | deg | deg |
| angular_rate | rad/s | rad/s, deg/s | deg/s | deg/s |
| ratio | 1 | fraction, % | % | % |
| coordinate | deg | deg | deg | deg |
| power_dbfs | dBFS | dBFS | dBFS | dBFS |
| power_db | dB | dB | dB | dB |
| frequency | Hz | Hz, kHz, MHz | kHz | kHz |
| count, enum, enum_signed, bits | — | — | — | — |

  **Refinement:** km, km/h, `g` and deg/s are added beyond the decisions list.
  They are display-only.
- **Selection order:** the per-card `config.units[quantity]` wins, then the
  viewer's per-quantity override, then the viewer's system (metric by default),
  all from localStorage (`sdr.units`). `units.ts` exports
  `convert(value, quantity, unitId)`, `unitFor(quantity, cardUnits, viewerPrefs)`
  and `format(value, quantity, unitId, digits)`.
- Thresholds and y-limits in configs are stored in SI (thresholds) or converted
  from display units on entry, so a preset reads the same for every viewer.
- Frequency planning still happens only in Python. `frequency` exists only to
  label received values such as Δf.

## 10. Derived events

`events.EventDeriver` runs in the hub, **server-side**. **Refinement:** the
decisions file lists "event derivation" under frontend tests. Derivation lives in
Python because late-joiner history and every viewer must see identical events.
The frontend tests cover event filtering and formatting (`lib/events.ts`).

Event object: `{id: int (monotonic), t: float, kind, category: 'flight'|'link',
text, channel: 'A'|'B'|null, value: number|null, quantity: string|null,
segment: int, synthetic: bool}`.

**Refinement (user, 2026-09-30):** "events" primarily means flight-state
events (phase transitions such as launch and burnout). Link events are a
separate, secondary feature. Every event carries `category`: `flight` for the
flight kinds below, `link` for the link kinds (`source_state` included). Both
categories share the `events` channel and history, but the UI never mixes them
by default: the event-log card shows one category (see §7), plot markers and
preset triggers use flight events only.

**Flight events** use BEST rows only (origin `best`):

| kind | Rule |
| --- | --- |
| `phase` | The phase differs from the previous best row's phase. Text is `"COAST → DESCENT"`. |
| `launch` | Entering BOOST from IDLE or ARMED. |
| `burnout` | Transition BOOST → COAST. |
| `apogee` | First exit from COAST in the segment. `value` is the maximum `alt_agl_m` seen in the segment, `t` is the time of that maximum, and the quantity is length. |
| `max_velocity` | Emitted with `apogee`. `value` is the maximum `velocity_mps` in the segment up to that point. |
| `landing` | Entering LANDED. |
| `flight_reset` | The phase regresses to IDLE or ARMED from BOOST, COAST, DESCENT or LANDED. Text is "New flight segment (replay loop or flight-computer restart)". The segment counter increments, and max-alt, max-velocity and apogee state reset. |

**Refinement:** the segment rule exists because the demo loops every 15.65 s
(ARMED … DESCENT → ARMED). The loop is shown as new segments, not corrected or
hidden. Values are used as decoded, and frozen stretches produce no events.

**Link events** (constants in `events.py`, documented as display heuristics):

| kind | Rule |
| --- | --- |
| `signal_loss` | Channel X had a CRC-good CHAN_FRAME, and no CRC-good CHAN_FRAME arrives from X for `LOSS_S = 0.25` s. It is checked on every feed and on the hub's 0.5 s tick with the current time. |
| `reacquire` | The first CRC-good frame on X after `signal_loss`. `value` is the gap in seconds. |
| `crc_burst` | ≥ `CRC_BURST_N = 3` CRC-bad CHAN_FRAMEs on X within `CRC_BURST_S = 1.0` s. There is one event per burst; the burst ends after 1 s with no CRC-bad frame on X. |
| `source_switch` | BEST_TELEM `source` differs from the last reported source and has held for `SWITCH_HOLD = 5` consecutive BEST frames. **Refinement:** the hold stops tie-breaking churn from flooding the log. |
| `source_state` | The hub source state changes (running, down, ended). |

The demo's 0.5 s antenna gaps (A during coast, B across apogee) produce a
`signal_loss` and `reacquire` pair per channel per loop. At 20 Hz a 0.25 s
silence is 5 missed frames.

## 11. Frontend performance

### 11.1 Rendering

- `lib/frame.ts` runs one `requestAnimationFrame` loop per page. Cards call
  `register(id, draw)`, `markDirty(id)` and `setVisible(id, v)`. The loop runs
  only while some card is dirty and visible. Messages never draw directly; they
  write to stores or rings and mark cards dirty.
- `SeriesStore(fields, capacity = 36000)` keeps a Float64Array for time and one
  Float32Array per field, as a ring. `append(t, flags, values)`,
  `windowFrom(t0)` copies into reusable buffers for uPlot, and `latest()`. One
  store exists per origin. `flight.A` and `flight.B` stores are allocated only
  while subscribed. A metrics store per channel (fields `rssi, noise, snr, df,
  crc_good, crc_bad`, capacity 600) is filled from `metrics_history` and live
  CHAN_METRICS. It feeds metric plot series and the Link card's windowed rates.
- The 3D card renders on demand: on data dirty, camera change or resize, and
  only while visible.

### 11.2 Virtualized lists

`lib/virtual.ts` `windowRange(scrollTop, viewportH, rowH, count, overscan = 8)`
returns `{start, end, padTop, padBottom}`. Event log and raw frames rows are a
fixed 22 px high. Only rows in the window are in the DOM.

### 11.3 Freeze and subscriptions

- **Freeze** (the Space key) now stops drawing only. All ingestion continues, so
  no gaps appear. The stale styling is unchanged.
- `subscriptions.ts` computes the channel set from: the page (Tune needs
  `spectrum.<shown channel>`, `iq.A`, `iq.B` and `link`); on Telemetry, the
  union of `registry.channels(card)` over the displayed preset; plus `flight`
  and `events` always. **Refinement:** flight and events stay subscribed so
  rings remain complete across page and preset switches; they are small. While
  `document.hidden`, spectrum and IQ channels are removed and restored on
  return. `link.ts` sends `subscribe` only when the set changes, debounced by
  250 ms.

## 12. Error, empty and labelling states

| Situation | Display |
| --- | --- |
| No data yet on a card's channel | Centered "Waiting for data" with the channel name, for example "Waiting for FLIGHT frames (best)". |
| The source sends no FLIGHT frames (the default bitstream sends TEST frames) | Flight cards show "No FLIGHT frames from this source. The default bitstream sends TEST frames; build with --demo for the flight replay." after 5 s with other frames arriving. |
| Stale data | A header chip `stale 3.2 s` when the newest row is older than 1 s (flight), 3 s (link) or 2 s (spectrum). The value stays visible and is muted. |
| GPS invalid | See §13.5. Map and 3D say "GPS position invalid: fix SEARCHING, 0 sats. Horizontal position unknown." |
| SYNTHETIC data | A card header badge `SIMULATED` when the newest row or record it shows has the SYNTHETIC flag. With profile `apex_demo`, flight-fed cards instead show `REPLAY · SIMULATED ADC` with the tooltip "Replayed IREC 2026 flight through the real receiver; the ADC input is simulated". The global header pill is unchanged. |
| Disconnected or source down | v1 banner and dimming. Cards keep the last data. |
| Tiles missing | Leaflet shows a neutral "tile not downloaded" tile. The map footer says "Run ./sdr maps fetch --site <id> on the server". |
| No sites downloaded | The Map card shows the track on a blank grid with a lat/lon graticule and the same hint. |
| Camera with no URL, or an error | A placeholder: "No video source. The operator can set a stream URL in card settings." On error: "Video source unreachable: <url>". |
| Preset save errors | A notice with the server `text`. The working copy is kept. |
| Unknown card type in a preset (newer server) | The card renders "Unsupported card type 'x'" and keeps its grid cell. |

## 13. Maps

### 13.1 Site registry

`tools/sdr_cli/sites.json` is tracked and extensible. An optional local
`.sdr/gui/sites.json` with the same shape is merged in. Local ids override the
tracked ones, which lets a team add sites without committing them.

```json
{"version": 1, "sites": [
  {"id": "seymour", "name": "Seymour, TX (Tripoli)", "center": [33.4986975, -99.3329862],
   "pad": [33.4986975, -99.3329862], "outer_radius_km": 20, "inner_radius_km": 5},
  {"id": "irec-pecos", "name": "IREC 2026, Pecos, TX", "center": [31.0427222, -103.5316389],
   "pad": [31.0427222, -103.5316389], "outer_radius_km": 20, "inner_radius_km": 5},
  {"id": "ttu", "name": "Texas Tech campus, Lubbock (demo)", "center": [33.584, -101.875],
   "pad": [33.584, -101.875], "outer_radius_km": 20, "inner_radius_km": 5}
]}
```

The Seymour and Pecos coordinates come from the APEX site configs named in the
decisions. The Texas Tech center is the controller's approximation, with a
5 km inner radius that covers the main campus. Pads default to the centers. A
real pad location is an edit to this file.

### 13.2 Tile source

These are USGS The National Map basemaps, which are public domain. OpenStreetMap
tile servers are never used for prefetch.

| Layer id | URL template (note `{z}/{y}/{x}` order) |
| --- | --- |
| `imagery` | `https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}` |
| `topo` | `https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}` |

The attribution shown on maps is "Basemap: USGS The National Map".

### 13.3 Coverage math

- Tile indices follow the standard Web Mercator scheme:
  `x = floor((lon + 180) / 360 · 2^z)` and
  `y = floor((1 − ln(tan φ + sec φ) / π) / 2 · 2^z)`.
- The bounding box for radius r km at center (φ, λ) is
  `Δlat = r / 111.32` and `Δlon = r / (111.32 · cos φ)`. The tile range is the
  inclusive range from the NW corner to the SE corner.
- Zooms 5–13 cover the outer radius (20 km). Zooms 14–17 cover the inner radius
  (5 km).
- Example: at Seymour, z10 contains tile x = 229, y = 410. The z17 range over
  5 km is x 29350–29389, y 52559–52598, which is 1,600 tiles.
- Per site and layer this gives about 2,200–2,500 tiles (Seymour 2,358,
  Pecos 2,235, TTU 2,462). Three sites × two layers is about 14,100 tiles.
- Estimates use 20 kB/tile for imagery and 12 kB/tile for topo, which is about
  330 MB in total. That is an estimate; the command reports actual bytes.

### 13.4 Fetch and serve

- `./sdr maps list` prints the sites and, per layer, the downloaded tile count,
  bytes and missing count.
- `./sdr maps fetch (--site ID | --all) [--layer imagery|topo|all] [--dry-run]
  [--rate N] [--retry-missing]`:
  - It prints the tile count and size estimate per zoom first. `--dry-run` stops
    there.
  - It makes sequential requests with default `--rate 4` requests/s (capped at
    8), using `User-Agent: SpaceRaidersSDR/<version> (tile prefetch;
    offline ground station)`.
  - Retry and back-off: on 429 or 5xx it backs off exponentially from 2 s to
    60 s. After 20 consecutive failures it stops, reports, and exits non-zero.
  - It is resumable: existing files are skipped. Each tile is written to a
    `.part` file and renamed.
  - It stores tiles at `.sdr/maps/<layer>/<z>/<x>/<y>.<ext>`, with the extension
    taken from `Content-Type` (`jpg` or `png`).
  - A 404 or non-image response is recorded in `.sdr/maps/<layer>/missing.json`.
    Missing tiles are not re-requested unless `--retry-missing` is given.
  - Ctrl-C leaves a consistent store.
- The server serves `GET /tiles/{layer}/{z}/{x}/{y}`. The route validates
  `layer ∈ {imagery, topo}` and non-negative integers with `z ≤ 20`, and looks up
  the `.jpg` or `.png` file. The response is a `FileResponse` with
  `Cache-Control: max-age=86400`, or 404. There is no remote fallback, ever.
- `hello.sites` lists each site plus, per layer, the min and max zoom actually
  present within the site's bounds. That comes from a per-layer
  `coverage.json` that `maps fetch` writes on completion.

### 13.5 GPS validity

`geo.gpsValid(fix, lat, lon)` (with a `rowValid(row)` wrapper over a decoded row) is true only when `gps_fix ∈ {2, 3, 4}` (2D, 3D, 3D+DR),
the latitude and longitude are finite with `|lat| ≤ 90` and `|lon| ≤ 180`, and
they are not both zero. **Refinement:** DR (1) counts as not a position fix.

Invalid positions are never plotted as a location. The track includes only
valid rows. The earlier recorded-log demo had `gps_fix` 0 (SEARCHING) with 0 satellites for all
293 frames, so its positions were always invalid. The current RocketPy-simulated
demo ROM (1381 frames) carries a position on every row, but `gps_fix` is the logged
value (0 during its fix-loss spans, where the last position is held); validity still
follows `gpsValid`, so rows with fix 0 are not plotted. A valid position far from the
selected site is still plotted. The footer shows "Position is N km from <site>"
when that is over 50 km, and never "fixes" it.

### 13.6 Map card

- Leaflet with two layers from `/tiles`: a base layer
  (`maxNativeZoom` = the outer maximum from coverage, `maxZoom` 19) and a detail
  layer (`minZoom` 14, `maxNativeZoom` from coverage, `bounds` = the inner
  bounding box).
- It shows a site selector, a pad `circleMarker`, a track polyline, a
  current-position marker, and a follow toggle.
- A GPS validity line is always shown. With invalid GPS it adds the text overlay
  "GPS position invalid: horizontal position unknown" and draws no marker.
- Leaflet markers use `circleMarker`, so no image assets are needed.

### 13.7 3D trajectory card

- It uses three.js, lazy-loaded, with OrbitControls from
  `three/examples/jsm/controls/OrbitControls.js`.
- The ground plane is a canvas texture composed from local z15 tiles covering
  about ±4 km around the pad. Missing tiles are drawn neutral grey.
- Local ENU metres use `geo.enu(lat, lon, lat0, lon0)`:
  `east = (lon − lon0) · 111320 · cos lat0` and
  `north = (lat − lat0) · 110540`. Altitude is `alt_agl_m × exaggeration`.
- The track is a line with points coloured by altitude. When GPS is invalid, it
  draws a vertical altitude column above the pad from `alt_agl_m`, with the
  label "Horizontal position unknown (GPS invalid)".
- It renders on demand only (§11.1). Leaving the page disposes the geometry,
  textures and renderer.

## 14. Per-tab updates (Tune and app shell)

- **Receiver profile:** `receiver_control.PROFILES` maps STATUS `build_id` to
  `{id, label, rf_label}`:
  - `0x53445231` ("SDR1") →
    `{id: 'default', label: 'Default receiver profile (ADC test carrier)'}`;
  - `0x53445246` ("SDRF") →
    `{id: 'apex_demo', label: 'APEX flight replay demo (IREC 2026)', rf_label: '441.480 MHz · 2GFSK ±25 kHz · 10 kbit/s (APEX RF4463 settings; ADC input simulated)'}`;
  - anything else → `{id: 'unknown', label: 'Unknown build 0x…'}`.

  The hub adds `profile` to `source` from the latest STATUS. The Tune page shows
  the profile label in the assumptions note. In `apex_demo` it shows `rf_label`
  next to the carrier readout.
- **Power units:** every RSSI and noise readout uses the record's `power_unit`.
  For `dBFS` the label is "dBFS (relative)" or, in compact places, "dBFS". dBm
  appears only when the record says dBm (legacy sim).
- **Tuning control state:** `SendPanel` shows a text chip per `control_state`:
  - detecting → "Detecting receiver";
  - pending → "Sent, awaiting acknowledgement";
  - applied → "Applied (acknowledged)" or "Applied (receiver report)", depending
    on `confirmed_by`;
  - rejected / timeout / out_of_sync / unsupported → the state name plus
    `control_error`;
  - reported → "Receiver reported settings".

  A requested value is never labelled applied without an acknowledgement or
  report.
- **Waterfall** consumes decoded binary rows (same `SpectrumMsg` shape).
- **Operator naming** in RoleMenu, hints and notices.
- **Status bar** adds "N viewers" from `stats.clients`.
- Behaviour that is already correct (frequency plan, NCO drag, compiled-profile
  locking, use-compiled-profile) is unchanged.

## 15. Camera v1

- The card config holds `url` (http/https, operator-set via preset), `mode` and
  `fit`.
  - `mjpeg` renders `<img src=url>`. Browsers display multipart MJPEG natively.
  - `video` renders `<video src=url autoplay muted playsinline>`.
- The server does not proxy. Each viewer fetches the stream directly from the
  camera URL, so the card footer warns "Each viewer pulls this stream
  directly". On a Pi hotspot the operator should use a low-rate stream.
- The empty and error states are in §12.
- **Future work** (documented, not built): host USB/HDMI capture on the Pi, a
  server-side relay so each stream is fetched once, and switching camera by
  trigger (via presets, task 24).

## 16. Testing strategy

Python (`PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -v`):

- `test_apex.py`: interlock and health bits, the schema order and length (20),
  `flight_values` on a packed FLIGHT body, and the demo ROM's first frame
  (`gps_fix` 0, health 0x90).
- `test_units.py`: the catalogue equals `units.catalogue.json`; round trips; °F
  offset; each system names a valid unit for every quantity.
- `test_gui_wire.py`: encoders against `struct` unpacking; NaN rf_lo when no
  reference; the golden file is current.
- `test_events.py`: the full demo loop from ROM frames (ARMED → BOOST → COAST →
  DESCENT → ARMED) gives launch, burnout, apogee with the max altitude,
  max_velocity and flight_reset in order; loss and reacquire timing with a fake
  clock; CRC bursts; switch hysteresis.
- `test_history.py`: caps, decimation boundaries and batch splitting at 4096.
- `test_fanout.py`: viewer spectrum at 5 Hz with a fake clock; operator
  unthrottled; the slot replaces; stream overflow gives resync instead of close;
  control overflow gives close; frames sampling counts drops; role switch
  changes the budget.
- `test_presets.py`: every validation rule; builtin read-only; conflict and
  exists; atomic write; state fallback; `CARD_TYPES` equals `card-types.json`;
  the shipped `flight.json` is valid.
- `test_maps.py`: tile math against the §13.3 values; coverage counts; fetch with
  a fake opener (skip existing, `.part` rename, 404 → missing, 429 back-off,
  failure stop, rate limiting with a fake sleep); tile path traversal rejected.
- `test_gui_server.py` and `test_gui_edge_cases.py` (aiohttp): subscribe gives a
  snapshot then live data; an unsubscribed channel is not sent; binary spectrum
  arrives; a viewer cannot save presets; operator save is broadcast; `/tiles`
  200, 404 and 400; the byte budget of a viewer on the Flight preset with
  replayed demo frames is ≤ 10 kB/s; the slow-client test is updated to the new
  semantics.

- `test_sources.py` and `test_gui_server.py` (§18):
  - back-off delays;
  - `classify_open_error`;
  - a fake session factory whose open raises ENOENT, then EBUSY, then
    succeeds, and whose read then raises OSError: the states go waiting → busy
    → running → reconnecting → running;
  - `reconnect_source` during a wait retries at once;
  - `preflight_bind` on a port that is already bound raises the port-in-use
    `ToolError`.

Frontend (`(cd tools/sdr_web && npm install && npm test && npm run check && npm run build)`),
Vitest in the `node` environment for pure logic only: wire golden decode,
SeriesStore wrap and window, grid operations and reflow, the virtual window,
unit conversion and precedence, the event filter and format, subscription
computation, registry sanitize over `flight.json`, `geo` tile and ENU math and
GPS validity, preset selection and follow logic, and link dispatch of binary and
history messages. svelte-check reports 0 errors and 0 warnings. The build checks
that `three` lands in a separate chunk (the Task 20 step inspects the build
output).

Manual and hardware checks are reported only when actually run:

- `./sdr gui --source replay` of a demo capture, if one exists;
- two browsers as operator and viewer;
- a phone-width viewport;
- a live demo board when attached.

Nothing here claims hardware verification.

## 17. Non-goals

- FPGA or protocol changes; new link message types; HK replay.
- Correcting, filtering or smoothing flight-computer values (GPS placeholders,
  frozen stretches).
- Server-side camera capture or relay; audio.
- Remote tile fetching by browsers; OpenStreetMap tiles; tiles outside the
  registry radii.
- User accounts or more than one privileged role; per-viewer server-side state.
- Automatic switching on anything other than flight phase and the four flight events.
- HTTPS; Pi service packaging (as in v1).
- DSP constants or RF settings. The demo `rf_label` repeats existing documented
  demo facts only.
- Component or DOM tests (the Vitest environment stays `node`); no new test
  dependencies.

## 18. Serial auto-reconnect and instance conflicts (added after approval)

This section comes from the decisions file's "Added after approval" section.

**Auto-reconnect.** With the serial source, the server survives losing the port,
for example when the board is reprogrammed or USB is unplugged. It reopens the
UART by itself.

- The retry loop lives in the server's source supervisor. When
  `Hub.run(SerialSource)` returns because of `down`, the supervisor retries
  after 0.5, 1, 2, 4 and 8 s, then keeps retrying every 8 s. A successful open
  resets the back-off.
- The pure `sources.Backoff(initial=0.5, maximum=8.0)` computes the delays and
  is tested with a fake clock.
- Link state and history survive a reconnect; the decoder restarts, as in v1.
- The operator's `reconnect_source` stays as a manual override. It cancels the
  wait and retries at once.
- Replay and sim sources do not auto-reconnect. A replay that has ended stays
  `ended`.
- `source.state` for serial is one of:
  - `running` ("connected");
  - `waiting`: the port device is absent ("waiting for port <name>");
  - `busy`: another process holds the port;
  - `reconnecting`: the open is in progress, or the next retry is scheduled.
    `source.retry_in_s` gives the time to the next attempt.
- `detail` names the port.
- `sources.classify_open_error(exc) -> 'missing' | 'busy' | 'other'` maps the
  `ToolError` or `OSError` cause of a failure:
  - `missing`: ENOENT or ENXIO, or "could not open port" with "No such file";
  - `busy`: EBUSY, EACCES or EPERM on an existing device, or "Resource busy" or
    "Access is denied" on Windows;
  - `other`: anything else, which is shown as `reconnecting` with its text.

  `busy` gets the detail "<port> is held by another process (another ./sdr gui,
  ./sdr tui or receive?). Close it; retrying." A read-time failure ("UART
  disconnected") goes straight to `reconnecting`.
- A `source_state` event (§10) is logged on each state change, but not on each
  retry.

**HTTP port conflicts.** `run_gui` binds before it starts the app, through
`web/server.py:preflight_bind(host, port)`. If the port is in use
(`EADDRINUSE`, or Windows `WSAEADDRINUSE`), it raises a `ToolError` and the CLI
exits non-zero:

> "HTTP port 8080 on 127.0.0.1 is already in use, probably by another
> ./sdr gui. Stop it, or choose another port with --http-port."

The server never runs twice silently.

**Two failures, told apart in the GUI** (pure helper
`lib/status.ts:connectionBanner(connection, source)`):

| Condition | Banner (text and style) |
| --- | --- |
| The WebSocket is not open | "Server unreachable. Retrying the connection to the GUI server." (bad) |
| The socket is open, and the serial state is `waiting` | "Server up. Waiting for board UART <port>." (warn) |
| The socket is open, and the serial state is `busy` | "Server up. Board UART <port> is held by another process: <detail>." (bad) |
| The socket is open, and the serial state is `reconnecting` | "Server up. Reconnecting to <port> in N s." (warn) |
| The socket is open, and the source is `down`, `ended` or `stopped` (non-serial) | the v1 source note |
| The socket is open, and the source is `running` | no banner |

The StatusBar pill shows the same state text. Status is always given in words
as well as colour.


# Pre-flight conflict scan: GUI cards plan (25 tasks)

Plan: docs/superpowers/plans/2026-09-30-gui-cards.md. Spec: docs/superpowers/specs/2026-09-30-gui-cards-design.md.
Order: 1-7, 25, 8-23, 24 (optional). Implementers commit their own work.

Repo facts checked: `package.json` scripts are `test` (vitest run), `check` (svelte-check), `build` (vite build); vitest is `environment: node`,
`include: src/**/*.test.ts`. Plan commands are correct. `tools/tests/` is flat (`link_samples.py` plus `test_*.py`), so `from link_samples import ...`
works under `discover -s tools/tests`. `package-lock.json` exists. Verified by computation: the spec/plan tile numbers (229,410), (29350..52598), 2358/2235/2462,
ENU 928 m / 1105 m, `convert(9.80665,'acceleration','g') == 1.0` and `100 C -> 212.0 F` are all exact or correct.

Legend: OK = agree. MISMATCH rows are real conflicts. "Ruling" names the side the spec supports and the smallest fix.

## (a) Shared file or interface, per task pair

| # | Tasks | Producer vs consumer | Verdict / ruling |
|---|---|---|---|
| A1 | 1 -> 2 | `apex.FLIGHT_SCHEMA` (20), `PHASE_ENUM` -> `flight_values` | OK |
| A2 | 1,3 -> 8 | `units.is_unit`, `apex.PHASES`, `events.FLIGHT_KINDS` -> `presets.validate` | OK |
| A3 | 1 vs existing `test_apex_flight_rom.py` | T1 adds `link_samples.rom_flight_frames()` (parse .mem, 42-byte slices, append BE CRC). The existing test already has `rom_frames()` plus `decode()` doing the same | MISMATCH (verbatim duplication). Ruling: T1 moves the parser into `link_samples` and `test_apex_flight_rom.py` imports it (or T1's helper calls it). |
| A4 | 1 -> 9 | `units.catalogue.json` -> `units.ts`, loop test over every unit | OK |
| A5 | 2 -> 4 | `pack_flight(origin:str, rows)`, `ORIGINS` -> `History.snapshot` | OK |
| A6 | 2 -> 6 | `encode_flight_row(t, fields, synthetic, best_from=None)`. T2 golden uses `best_from` = `'A'` (str key of `BEST_FROM`). T6 passes `fields['source']` (an int from BEST_TELEM) | MISMATCH (type of `best_from`). Ruling: spec 3.4 only fixes bits 1-2 (0 A,1 B,2 combined,3 n/a). Make `encode_flight_row` accept the int (or None -> 3) and have the golden use ints; drop the str map. |
| A7 | 2 -> 6 | `encode_spectrum(..., rf_reference)` dict `{lo_hz,injection,inferred?}` vs hub's existing `dict(lo_hz, injection)` and `source['applied']` | OK |
| A8 | 2 -> 7 | `wire.golden.json` `{name,hex,expect}` -> `wire.test.ts`. The key names and shape of `expect` (spectrum vs flight, f32-rounded values, `rf_reference` null vs NaN) are not defined in either task | MISMATCH (underspecified). Ruling: pin `expect` in T2: use `null` (never NaN, because NaN breaks `JSON.parse`/Vite import and the Python `==` staleness test), f32-rounded values, and the keys named as `SpectrumMsg` / `FlightRows` fields. |
| A9 | 3 -> 4 | event dict -> `History.add_event` | OK |
| A10 | 3 -> 6 | `feed/tick/source_state` -> `Hub`; `hub.tick(now_wall)` | OK on names. See A26 for the duplicate `source_state` events. |
| A11 | 4 -> 5 | snapshot items `str|bytes` -> `put_snapshot(channel, items)`; `fanout.CHANNELS` (10 names) equal `History.snapshot` names | OK |
| A12 | 4 -> 7 | `history{channel,count}` marker, `events{reset}`, `metrics_history` arrays. T7 handles the marker only for `flight` (and tests only that). Spectrum and frames snapshots also start with a marker (T4, spec 3.5), but T7 says nothing on clearing the Tune waterfall or `frames` ring | MISMATCH (gap). Ruling: T7 handles the marker for every channel: `flight*` clears its SeriesStore, `frames` clears the ring, `spectrum.X` resets the waterfall rows. |
| A13 | 5 -> 6 | `Outgoing`, `Outbox.subscribe/offer/next/put_snapshot/take_resync/take_dropped/overflowed/on_ready` -> `_send_loop` | OK, except the tuning slot (A14) |
| A14 | 5 -> 6 | T6 says tuning is a "control slot key `tuning` (latest wins, never rate limited)". T5's `Outbox` has only `control(data)` (ordered deque) and `offer` modes 'stream'/'slot'/'control'. No latest-wins control slot is defined, and T5's send order (control, stream, slots) would send a `slot` tuning after the stream | MISMATCH. Ruling: spec 2.3/2.4 requires a control slot, so T5 adds `control_slot(key, data)` (sent with control, replaced in place, not budgeted), with a test. |
| A15 | 5 -> 6 | `ROLE_BUDGETS` keyed `'admin'/'viewer'`; spec `hello.budget` is `'operator'/'viewer'`, and the T15 `viewerRateNote(budget)` consumes that. T6 does not define the mapping, and `hello` is sent only once (role changes later leave `budget` stale) | MISMATCH. Ruling: T6 maps admin->'operator' and adds `budget` to `role` messages (or the frontend derives it from `role.role`). |
| A16 | 6 -> 7 | `hello` (`flight_schema`,`channels`,`budget`,`sites`), `stats.clients`, `subscribe`/`subscribed`/`dropped` JSON -> `types.ts` (`HelloMsg`, `StatsMsg`, `ClientMsg`) | OK on names. T7 does not list these `types.ts` additions explicitly. |
| A17 | 6 -> 8 | `broadcast(msg_dict)` (encode once) -> `presets` broadcast; `error(code,text)`; new `GuiServer` kwargs (`presets` in T8, `root` in T19) while existing tests call `GuiServer(factory, roles, state_path)` | OK if both kwargs default (T8 does not say what `presets=None` does). |
| A18 | 6 -> 19 | `hello.sites = []` placeholder -> filled from `maps.load_sites/coverage` | OK |
| A19 | 6 -> 21 | `Hub.stats_message(clients)`, `hub.source` dict -> `source['profile']`. Note `set_source` rebuilds `self.source` and drops `profile` until the next STATUS | OK; minor: keep `profile` across `set_source`. |
| A20 | 7 -> 9 | T7 `eventsStore: writable<Event[]>` (types.ts). T9 `interface GuiEvent` (events.ts), same shape | MISMATCH (two names, two definitions; `Event` also shadows the DOM global). Ruling: define `GuiEvent` once in `types.ts`; T7 uses it; T9 imports it. |
| A21 | 7 -> 9 | `frame.ts` default `scheduler` (T9) vs `link.ts` `dataVersion` "bumped once per animation frame" (T7) | MISMATCH risk. See B7/B9: rAF does not exist in the node test environment. |
| A22 | 7 -> 10 | `channelsFor(page,{tuneChannel,cardChannels,hidden})` <- `cardChannels(cards)`; T7 placeholder `['link','frames']` until T10 | OK |
| A23 | 7 -> 12,13,14,16 | `flightStores`, `flightSchema`, `metricsStores`, `linkStatsRing`, `eventsStore`, `frames`, `dataVersion` names all match their consumers. No store or event is defined for `dropped{frames,count}`, but T14 shows the count. Who allocates `flightStores.A/B` (spec: only while subscribed) is not stated | MISMATCH (T14 needs a `dropped` store). Ruling: T7 adds `droppedFrames` (writable number) and allocates A/B stores on demand in `setSubscriptions`. |
| A24 | 8 -> 10 | `card-types.json` (created by T8) <-> `REGISTRY` keys (T10 test) | OK |
| A25 | 8 -> 10 | `presets: writable<PresetsMsg|null>` plus `case 'presets'` in `handleMessage` is "added to link.ts in this task" (T10). T10's Files list has neither `link.ts` nor `types.ts` | MISMATCH (Files vs body). Ruling: add `lib/link.ts`, `lib/types.ts` to T10 Modify. |
| A26 | 3,6 -> 25 | T6 "`set_source` also emits a `source_state` event". T25 "emits a `source_state` event on changes, not on every retry"; test "two consecutive `busy` retries give one event". T3's `source_state(state, detail, now)` has no dedup and T3's test expects an event per call | MISMATCH. Ruling (spec 10 and 18): dedup lives in `EventDeriver.source_state` (skip when `(state)` unchanged) and only `Hub.set_source` calls it; the T25 supervisor never emits events itself. Add that case to T3's tests. |
| A27 | 8 -> 11 | `PresetsMsg {items,live,default,auto_switch}`, error codes `preset_conflict/exists/readonly/in_use/missing/not_admin` -> `displayedPreset`, `savePreset(preset, baseRevision)` -> `{preset, base_revision}` | OK |
| A28 | 8 -> 22 | `flight.json` minimal (T8), replaced in T22 | OK. See C-rows about full config. |
| A29 | 8 -> 24 | `PresetStore.state()/set_live/set_auto_switch` -> `TriggerEngine` | OK. T24's "feed events to the engine": `Hub` only publishes `Outgoing('events', json)`. No per-event hook is defined, so the server must re-parse JSON. Ruling: T24 adds an `Hub.on_event` callback or has the server parse `Outgoing.data`. |
| A30 | 9 -> 10 | `scheduler.setVisible`, `sanitizeGrid(cards, minOf)` | OK |
| A31 | 9 -> 12,13,14 | `unitFor/convert/format/unitLabel/unitPrefs`, `windowRange`, `filterEvents/formatEvent/lastLaunch` | OK. T14 says "`ALL_KINDS` mirrored as a TS constant" but names no file and adds no cross-check test against `events.ALL_KINDS`. Ruling: put `ALL_EVENT_KINDS` in T9's `events.ts`, add a Vitest that reads a generated JSON or a Python test that greps it. |
| A32 | 10 -> 11 | T11 "consumes `registry.sanitize`". T10 defines only `CardMeta.sanitize(config)` (per type); the spec says `registry.sanitize(type, config)` | MISMATCH. Ruling: spec wins. T10 exports `sanitizeConfig(type, config)` and keeps `meta.sanitize` as the implementation. |
| A33 | 10 -> 12..17,15,19,20 | `CardSettings.svelte` "renders from a `settings` descriptor on the meta". T10's `CardMeta` has no `settings` field | MISMATCH. Ruling: add `settings: SettingField[]` to `CardMeta` in T10, and T12+ fill it. |
| A34 | 10..20 | `registry.ts` edited by T10,12,13,14,15,16,17,19,20 (sequential, additive) | OK; serial execution means no conflict, but each task must rebase on the prior one. |
| A35 | 12 -> 21 | T12 reads `stats.source.profile` ("Task 21 adds it"). No task adds `profile?` to `SourceState` in `types.ts` (T21's Files omit `types.ts`; T25 edits `SourceState` but only for state/retry_in_s). T12 runs before T21, so `badgeFor(...,'apex_demo')` can never show REPLAY until T21, and svelte-check fails on `source.profile` | MISMATCH. Ruling: T7 (or T12) adds `profile?: {id,label,rf_label?}` to `SourceState`; T21 only fills it. |
| A36 | 13 <-> 16 | `m.rssi/m.noise/m.snr/m.df` <-> `metricsStores` fields (rssi,noise,snr,df,crc_good,crc_bad) | OK |
| A37 | 16 -> 21 | `powerLabel` (linkq.ts) -> RSSI/noise labels | OK (16 runs before 21) |
| A38 | 18 -> 19 | `tile_path` (ValueError on bad input), `coverage()` `{site:{layer:{min_z,max_z,tiles}}}`, `load_sites` -> `/tiles` route and `hello.sites`; `<layer>/<z>/<x>/<y>.<ext>` layout | OK on names. See C11 about the outer max zoom. |
| A39 | 18 <-> 8 | both edit `pyproject.toml` package-data (`presets/*.json`, `sites.json`) | OK (additive) |
| A40 | 19 -> 20 | `geo.enu/gpsValid/tileXY/validTrack` -> `trackPoints/groundTiles`; `tileXY` returns `{x,y}` (TS) vs tuple (Py) | OK |
| A41 | 19 <-> spec | `gpsValid(fix, lat, lon)`. Spec 13.5: `geo.gpsValid(row)` | MISMATCH (minor). Ruling: spec text is loose; keep the plan's signature and change the spec line, or add `rowValid(row)` wrapper. |
| A42 | 19 -> 22 | site id `irec-pecos` exists in `sites.json` (T18) | OK |
| A43 | 21 <-> 25 | both edit `StatusBar.svelte`, `App.svelte` (and T21 reads `SourceState`). With the new order 25 runs first, so T21 rebases | OK. Plan's "whichever runs second rebases" is now always T21. |
| A44 | 21 <-> spec 5 | T21 converts Tune/RoleMenu wording to "Operator", but `server.py` errors ('Only the Admin can change tuning.', 'Wrong Admin password.', run_gui print), `link.ts:95` takeover notice and `Tune.svelte:106` hint still say Admin; `server.py`/`link.ts` are not in T21's Files | MISMATCH. Ruling: spec 5 says everywhere. Add `server.py` texts and `link.ts` notice to T21 (and update existing test strings), or to T8's new error texts only if the spec is narrowed. |
| A45 | 22 -> 10,8 | T22 layout: verified no overlaps, widths sum to 12 per row, all cards >= registry min sizes, h <= 24, y <= 500 | OK |
| A46 | 25 -> existing `Hub.run` | T25 "when `hub.run` ends with `down` or raises" and `classify_open_error(exc)` inspects `exc.__cause__`. But `Hub.run` catches `(ToolError, OSError)` and every `Exception`, calls `set_source(..., 'down', str(exc))` and returns, so the supervisor never sees the exception. T25 only says "hub.py (only if needed)" | MISMATCH. Ruling: T25 makes `Hub.run` record `self.last_error = exc` (or re-raise) and lists `hub.py` as a required change. |
| A47 | 25 internal | Files list says `SerialSource` "reports open and read failures with a `.reason`"; Interfaces say "`SerialSource` is unchanged apart from exposing `port`" (`port` already exists via `session.port`/`detail`) | MISMATCH (within T25). Ruling: drop `.reason`, use `last_error.__cause__`. |
| A48 | 25 -> 7 | "Consumes `connection` and `stats` stores (Task 7)": both already exist in `link.ts` today and T7 does not produce them | OK (the dependency on T7 is not real; it is only order-neutral). |
| A49 | 25 <-> spec 18 | T25 "the `SourceState.state` union": today `state: string`, no union. `port` for the banner text is only in `detail` (`'/dev/ttyUSB1 @ 1000000 baud'`); spec banner wants `<port>` | MISMATCH (minor). Ruling: add `port?: string` and `retry_in_s?: number`; make the banner use `port`, not `detail`; widen `state` by literal union or keep `string`. |
| A50 | 25 <-> 5,6 | test step: "stats sequence observed by a WebSocket client includes waiting, then busy, then running". With instant fake sleeps the states change within milliseconds, and `stats` is a 0.5 s slot (T5/T6) that keeps only the latest, so `busy` will not be observed. Same for `reconnecting retry_in_s == 0.5` | MISMATCH (test cannot pass or is flaky). Ruling: assert on `hub.subscribe` recorded `Outgoing` stats (pre-outbox) or on `source_state` events (stream channel, never coalesced). |

## (b) Self-consistency per task

| Task | Self-consistent? | Notes |
|---|---|---|
| 1 | Yes, with A3 | Tests match code; Files match; `-p 'test_[au]*.py'` is valid (matches test_apex*, test_units); Step 4 runs full discover. `test_bits_decode` offsets check out against `FLIGHT_STRUCT` (phase_status at 8, health at 9). Dict-order dependence in the `health_bits` assert is fine if the map is built in bit order. |
| 2 | Mostly | Struct sizes verified (52, 8, 90). Golden `expect` shape and NaN issue (A8), `best_from` type (A6). |
| 3 | Mostly | Expected event order is ambiguous (phase events interleave with launch/burnout), `source_state` dedup missing (A26). |
| 4 | Yes | Numbers line up with spec 3.5 (caps, every 20th, 4096). |
| 5 | Mostly | Missing latest-wins control slot (A14); removed-subscription behavior (spec 3.1 "replaces the set") is not specified (queued items for dropped channels). |
| 6 | No | (1) Existing tests that must change are not listed: `test_hub` (`test_feed_turns_records_into_client_messages`, `test_snapshot_replays_latest_slow_records`), `test_gui_server` (`test_records_and_spectrum_fan_out`, `test_late_viewer_gets_latest_status_at_once`). Only the edge-cases test is named. (2) The budget test is placed "in `test_gui_server.py` or the fanout test", but `test_fanout.py` is not in T6's Files. (3) The 100,000 byte bound is near the estimate (flight 20 Hz x 98 B = 19.6 kB, CHAN_METRICS 2 x 5 Hz of ~350 B JSON ~ 35 kB, spectrum 18 kB) and could fail on JSON size; state the measured figure. (4) Length validity of the FLIGHT frame (spec 2.3) is not tested; only CRC corruption is. (5) `budget`/`channels` in `hello` are untested. |
| 7 | No | (1) The existing `link.test.ts` test `delivers spectrum rows to listeners and honours freeze` asserts that frozen drops records; T7 says "extend" and tests the opposite. The old test must be rewritten, not just extended. (2) `frozen` is read only by `handleMessage` today, so removing the drop leaves the Tune `Waterfall` (which never reads `frozen`) scrolling while "Frozen"; T7 says "only read by drawing code" but nothing wires it. (3) Untested yet consumed by T13/T16: live CHAN_METRICS -> `metricsStores`, `metrics_history`, `linkStatsRing`, `dropped`, `setSubscriptions` debounce/resend. (4) `resetState()` must also reset the new stores, not stated. (5) `dataVersion` "once per animation frame" needs a rAF fallback in node. (6) The Freeze title already says "Receiving continues."; only a wording tweak. (7) `Event` type name (A20). |
| 8 | Yes | `test_gui_server` construct default for `presets` unspecified (A17). Creates a frontend JSON from a Python task; fine. |
| 9 | No | `export const scheduler = createScheduler()` with default parameter `raf = requestAnimationFrame` throws ReferenceError at import time under vitest `environment: 'node'`, so `frame.test.ts` (and anything importing `frame.ts`) fails before any test runs. Ruling: default to a lazy `(cb) => globalThis.requestAnimationFrame(cb)` or only construct the default when `typeof requestAnimationFrame !== 'undefined'`. |
| 10 | No | Files omit `link.ts`/`types.ts` (A25); `CardMeta` lacks `settings` (A33); pixel->grid `Math.round(dx/(colW+GAP_PX))` is left inside the component and is untested (spec puts pure logic in `grid.ts`); no `sanitizeConfig(type, cfg)` export (A32). `lib/cards.ts` file and `lib/cards/` dir coexist only until the same task deletes the file: OK. |
| 11 | Yes | `PresetsMsg` type location (types.ts) is listed; OK. |
| 12 | No | `SourceState.profile` type unassigned (A35). |
| 13 | Yes | `npm install uplot` updates the existing lockfile. `buildData` test needs the unit prefs passed in; fine. |
| 14 | Mostly | `dropped` store (A23); `ALL_KINDS` location (A31). |
| 15 | Yes | |
| 16 | Yes | Reset arithmetic (150 -> 3 counts 153) is right. |
| 17 | Yes | |
| 18 | Mostly | "Rebase onto the parallel-build work first": `cli.py` at HEAD already contains it (a86fcfd), so this is stale. Default arg `opener=urllib.request.build_opener()` is evaluated once at import; use `None`. `coverage` cannot supply the outer max zoom (C11). |
| 19 | Mostly | No test for the no-sites graticule (spec 12). `gpsValid` signature (A41). |
| 20 | Yes | Commands right (`ls`, `grep -L` lists the entry chunk). |
| 21 | No | Files omit `types.ts` (profile), `link.ts` (takeover notice), `server.py` (Admin texts) (A35, A44). `controlStateText` tests skip `detecting`, `reported`, `rejected`, `out_of_sync`, `unsupported` (spec 14 lists all). |
| 22 | Mostly | `sanitize` must leave every config unchanged (spec 6.2), so `flight.json` must carry complete configs with all defaults. The task only lists layout and a few config values. The Python test "validate(flight.json) passes" duplicates T8's "shipped presets all validate". |
| 23 | Yes | Link check command is fine; order (23 before optional 24) matches its "triggers inactive unless 24 lands" text. |
| 24 | Mostly | Event hook (A29). |
| 25 | No | A46, A47, A49, A50, A26. Also `_supervise` does not exist yet in `server.py` (today `start_source` only creates `hub.run` as a task), and the FakeSession snippet ends in `...`. `preflight_bind` with SO_REUSEADDR off, then `web.run_app` (reuse on) leaves a small race but is acceptable. |

## (c) Plan vs spec or its own Global Constraints

| # | Where | Contradiction | Ruling |
|---|---|---|---|
| C1 | Global "the controller commits after each task's review"; every task's Step "Commit (controller)" | Overridden by the controller (implementers commit their own work) | Replace with "implementer commits" (the commit file lists and messages stay). |
| C2 | Task Order Notes "Tasks 1-24 run in number order" | Execution order is now 1-7, 25, 8-23, 24. The note "Task 25 any time after Task 7" allows it, but the "Tasks 21 and 25 rebase" note means T21 always rebases | Update the note. |
| C3 | Global "rebase onto the parallel-build work first" (T18) | Parallel-build commits (a86fcfd...) are already on this branch | Drop or verify `git log`; harmless. |
| C4 | Spec 5 "Operator everywhere, including error text" vs plan | Existing server error strings and `link.ts`/`Tune.svelte` hints are not assigned (A44) | Add to T21. |
| C5 | Spec 12 "No FLIGHT frames from this source ... after 5 s with other frames arriving" | No task implements it (T12 has only "Waiting for FLIGHT frames (<source>)") | Add to T12 (pure helper `noFlightNotice(stats, latest)` plus a test). |
| C6 | Spec 12 "No sites downloaded: blank grid with a lat/lon graticule" | T19 has the footer hint but no graticule | Add to T19 or narrow the spec. |
| C7 | Spec 13.6 base layer `maxNativeZoom` = outer max "from coverage"; 13.4 `hello.sites` has only per-layer min/max zoom | T18 `coverage` is `{min_z,max_z,tiles}` for the whole site, so the outer max (13) and inner max (17) cannot be separated | Smallest fix: derive base `maxNativeZoom = min(max_z, 13)` from `OUTER_ZOOMS`, or add `outer_max_z` to `coverage`. |
| C8 | Spec 3.2 `hello.budget` 'operator'/'viewer' | See A15 | T6 maps and refreshes on role change. |
| C9 | Spec 13.5 `gpsValid(row)` | See A41 | Change spec line or add wrapper. |
| C10 | Spec 6.2 `registry.sanitize(type, config)` | See A32 | Export the function. |
| C11 | Spec 8 `addCard(cards, card)` | Plan: `addCard(cards, card, minW, minH)`. Harmless; update spec | Update spec text. |
| C12 | Spec 2.3 "frame length valid" and 16 | T6 implements only CRC checks in its tests | Add a wrong-length CRC-good frame test to T6. |
| C13 | Spec 3.1 `subscribe` "replaces the set" | T5 returns "newly added" only; nothing drops queued data for removed channels | Define that `subscribe` purges queued stream and slot items of removed channels. |
| C14 | Spec 3.4/11 "t = host epoch seconds" vs T12 `staleAge(latestT, nowS)`, T13 `viewRange(now)`, T16 `frameRate/badRatio(nowS)` | Browser wall-clock `now` is compared with server-host timestamps. A phone or laptop on a Pi hotspot (no NTP) is off by seconds or minutes, so every card shows stale or the plot window is empty | Smallest fix: the client keeps `skew = serverT_latest - clientNow` (from each row or `stats`), or uses the newest row `t` as "now". State it in T7 and pass `nowS` accordingly. |
| C15 | Global: "svelte-check 0 errors and 0 warnings" vs T10/T14 `Snippet`/`a11y` for drag handles and `VirtualList` rows | Keyboard-operable drag handles need aria roles; budget time | Note for the implementer; no plan text change needed. |

## (d) Mandated things a reviewer would flag

| # | Task | Item | Ruling |
|---|---|---|---|
| D1 | 1 | Verbatim duplicate of `rom_frames()`/`decode()` (A3) | Share the helper. |
| D2 | 7/9 | `Event` vs `GuiEvent` duplicate type (A20) | One type. |
| D3 | 7,10,14,16 | After the rewrite the old stores `frameLog`, `best`, `history`, `historyVersion`, `metrics` stay and duplicate the new `frames`, `flightStores`, `metricsStores`, `linkStatsRing`. T7 deliberately keeps them for Tune; nothing later removes them once `FrameLogCard`/`LatestFrameCard` are deleted (T10) | Add to T10/T16: delete `frameLog`, `best` once no component imports them; keep `history` only while Tune uses it, then migrate Tune to `metricsStores`. |
| D4 | 10 | Drag/resize pixel math left in the component, untested | Add `pxToGrid` to `grid.ts` with a test. |
| D5 | 14 | `ALL_KINDS` mirrored by hand with no cross-check | Generate or test (A31). |
| D6 | 25 | Stats-based state test is vacuous or flaky (A50) | Assert on pre-outbox messages or events. |
| D7 | 22 | "`sanitize` leaves config unchanged" only meaningful if the JSON carries full configs; otherwise the test forces the implementer to guess | State it in T22 Step 3. |
| D8 | all | Dependencies: only `leaflet`, `uplot`, `three`, `@types/leaflet`, `@types/three` are added (T13, T19, T20), no CDN, Python adds nothing. `three/examples/jsm/...` ships inside `three`. `resolveJsonModule` is on by default with `moduleResolution: bundler`, so the T22 JSON import outside `src` needs no new config. No violation found. | none |
| D9 | 2 | NaN in JSON golden (A8) | Use null. |

## (e) What moving Task 25 to just after Task 7 breaks

| # | Effect | Ruling |
|---|---|---|
| E1 | T25's `server.py` supervisor lands before T8/T19 add `presets`/`root` kwargs and tiles. Both additive; T25's new `run_gui` call to `preflight_bind` precedes T8's `presets` wiring in the same function. Merge touch only. | OK; implementer rebases T8 on T25's `run_gui`. |
| E2 | T25's state test (A50) sits on T5/T6 coalescing and T6's `source_state` event; both are already done (1-7), so the flaw is live, not hidden by order. | Fix as in A50. |
| E3 | `SourceState` typing in `types.ts`: T25 edits it before T12 needs `profile`; T25 should add `profile?` now (A35) so T12/T21 do not touch it again. | Add to T25. |
| E4 | T21 (later) must preserve T25's `sourcePillText`/`connectionBanner` while adding "N viewers" and the "Operator" wording. | T21 rebases; already the plan's rule. |
| E5 | T25 docs step edits `tools/README.md` and `docs/HANDOFF.md` before T23 writes the Web GUI section (cards, presets, maps). T23's rewrite could overwrite T25's reconnect paragraph. | T23 must keep T25's reconnect/port-in-use text. |
| E6 | T25 runs before T10 (Telemetry rewrite) but T25 only edits `App.svelte` banner and `StatusBar`; T10 does not touch them. No conflict. T25 does not depend on any T8-T24 artifact (its `events` and `Outgoing` dependencies are T3/T6). | none |

## Count

Rows: (a) 50, (b) 25, (c) 15, (d) 9, (e) 6 = 105. Real conflicts (MISMATCH, No, or broken tests): A3, A6, A8, A12, A14, A15, A20, A23, A25, A26, A32, A33, A35, A44, A46, A47, A49, A50; tasks 6, 7, 9, 10, 12, 21, 25 fail self-consistency; C5, C6, C7, C14.

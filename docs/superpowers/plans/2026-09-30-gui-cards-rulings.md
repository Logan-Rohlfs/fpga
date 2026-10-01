# GUI cards plan: controller rulings

Copied from the local SDD ledger so the rulings survive on another machine. The spec is the binding authority, and these rulings amend the plan. Row ids (A3, C14, ...) refer to [the preflight scan](2026-09-30-gui-cards-preflight.md).

## Rulings made during execution (Tasks 1-7)

- Ruling: implementers commit their own work after tests (plan says controller commits) — SDD review packages need commits — cost if wrong: none, commits are local on gui-prep.
- Ruling: the "separate agent editing build.tcl/core.py/cli.py/tui.py" constraint refers to receiver-plan Task 7, now complete (93f4807); keep the no-touch rule for build.tcl/core.py/tui.py anyway, Task 18 cli.py maps subparser is additive on current HEAD.
- Ruling: execution order 1–7, 25, 8–23, 24 (optional) — Task 25 fixes the user-visible reconnect problem early; 21 rebases onto 25.
- Ruling: user asked for higher-resolution spectrum/waterfall; 64-bin data can't give it host-side, so added Task 26 (FPGA DFT length ≥128/256, parameterized) executed after Task 15 — cost if wrong: RTL change + rebuild, UART load increase.
- Ruling: Tasks 6 and 7 are an atomic pair — never checkpoint/hand off between them (binary spectrum breaks old frontend).
- Ruling: execution order is 1–7, 25, 8–15, 26, 16–23, 24 (supersedes the earlier order line). Handoff checkpoint 7677b00. Deferred: AGENTS.md:39 'no command receiver or acknowledgement exists yet' is stale (UART tuning is acknowledged) — fix in final docs task.
- Ruling: adopt the preflight's suggested fix for A3,A6,A8,A12,A14,A15,A17,A19,A20,A23,A25,A26,A29,A31,A32,A33,A35,A44,A46,A47,A49,A50,C5,C6,C12,C13,D3,D4,D7 — each is the smallest change toward the spec — cost if wrong: small local rework in the named task.
- Ruling: C7 — coverage() returns outer_max_z rather than hard-coding min(max_z,13) in the frontend — keeps zoom knowledge in Python — cost if wrong: one extra field.
- Ruling: C14 — link.ts keeps a server-clock offset and exposes serverNow(); cards compare row t against it — avoids stale/empty cards on unsynced clients — cost if wrong: small helper change.
- Ruling: A41/C9 — keep gpsValid(fix,lat,lon), add rowValid(row), fix spec text in Task 23 — cost if wrong: trivial.
- Ruling: Task 8 presets=None disables preset features (hello omits presets, requests get error preset_missing); run_gui always passes a real store — keeps existing tests constructing GuiServer unchanged — cost if wrong: small.
- Ruling: Task 3 simultaneous-event order is the plan's evaluation order, asserted explicitly — cost if wrong: test reorder.
- Ruling: Task 26 was not in the preflight scan; it runs after Task 15 and includes remote Vivado builds (no board programming) — cost if wrong: build time only.
- Ruling: each implementer updates the docs/HANDOFF.md "Current task" line in its own task commit (checkpoint rule) — avoids a separate controller commit per task — cost if wrong: none.
- Task 2: Ruling: spectrum golden `expect` is exactly the decoded SpectrumMsg shape (type 'spectrum', channel, row, t_us = round(t*1e6) as integer — stated rule, f0_hz, bin_hz, bins, db10, low, high, synthetic, rf_reference per existing RfReference type or null); flight `expect` uses FlightRows-style names — per ruling A8 and spec 3.3 "decodes into the existing SpectrumMsg shape" — cost if wrong: regenerate golden file.
- Task 2: Ruling: .mem ROM parsing + CRC append move into the package (sdr_cli/apex.py) as the single implementation; tools/tests/link_samples.py reuses them — removes verbatim duplication — cost if wrong: trivial.
- Ruling: user clarified (2026-09-30) that "events" means flight-state events; link events are a separate thing. Spec §10/§7 amended (fa394aa): events carry category flight|link; event-log card has `category` config (default flight) and shows one category; plot markers and triggers use flight only — cost if wrong: small config change in Tasks 3, 9, 14, 22.
- Task 3: Ruling: apogee keeps spec §10 rule (first exit from COAST, max alt up to then = 1775.9 m in the ROM) even though the ROM altitude keeps rising in DESCENT — global constraint "never correct flight-computer oddities"; brief's whole-ROM max assertion was a plan defect — cost if wrong: apogee value in the log differs from the true peak.
- Task 3: Ruling: FLIGHT_KINDS stays the 4 milestone kinds used by Task 8 triggers; the full flight category is FLIGHT_CATEGORY_KINDS — keeps the plan's Task 8 interface — cost if wrong: rename.
- Task 5: Ruling: on stream overflow, clear the whole stream queue and resync every channel that had queued items (deviates from spec §3.3 per-channel discard) — per-channel discard of a quiet channel leaves the queue near cap and re-overflows immediately; implementer amends §3.3 in the fix commit — cost if wrong: extra resync snapshots for busy channels on a slow viewer.

## Per-task rulings for dispatch


## Task 1
- A3/D1: move the ROM .mem parser (rom_frames/decode) out of tools/tests/test_apex_flight_rom.py into tools/tests/link_samples.py as the single implementation; rom_flight_frames() uses it and test_apex_flight_rom.py imports it. No verbatim duplication.

## Task 2
- A6: encode_flight_row(t, fields, synthetic, best_from=None) takes best_from as the int BEST_TELEM source code (0 A, 1 B, 2 combined) or None -> 3 (n/a), per spec 3.4 bits 1-2. No str map. Golden vectors use ints.
- A8/D9: wire.golden.json `expect` values never contain NaN: use null. Values are f32-rounded where the wire is f32. Keys are named as the TS SpectrumMsg / FlightRows fields. rf_reference absent -> null.

## Task 3
- A26: EventDeriver.source_state(state, detail, now) dedups: it returns no event when `state` equals the previous state. Add that case to Task 3's tests. Only Hub.set_source calls it (the Task 25 supervisor never emits events itself).
- Event order for simultaneous derived events: emit in the order the conditions are evaluated in the plan text; tests must assert that order explicitly.

## Task 4
- (no rulings)

## Task 5
- A14: add Outbox.control_slot(key, data): sent together with control messages (before stream and slots), latest wins (replaced in place), never rate-limited; with a test. Task 6 uses it for `tuning`.
- C13: subscribe() replacing the set purges queued stream and slot items for channels that were removed; test it.

## Task 6
- A14: tuning goes through Outbox.control_slot('tuning', ...).
- A15/C8: wire role 'admin' maps to budget 'operator' ('viewer' stays). hello carries budget; every `role` message also carries `budget` so it never goes stale.
- A17: new GuiServer kwargs default so existing GuiServer(factory, roles, state_path) calls still work.
- A19: Hub.set_source keeps source['profile'] across set_source calls.
- (b)6: update the existing tests that change (test_hub: test_feed_turns_records_into_client_messages, test_snapshot_replays_latest_slow_records; test_gui_server: test_records_and_spectrum_fan_out, test_late_viewer_gets_latest_status_at_once). tools/tests/test_fanout.py may be edited for the budget test. Measure the actual byte figure for the 100,000-byte bound and state it in the report; if the bound fails because of real JSON size, report it (do not loosen silently). Test hello's budget and channels.
- C12: add a test that a CRC-good FLIGHT frame of the wrong length is rejected from flight channels.
- Tasks 6 and 7 are atomic: do not stop between them.

## Task 7
- (b)7: rewrite the existing link.test.ts test "delivers spectrum rows to listeners and honours freeze": freeze no longer drops records; it only stops drawing. Wire `frozen` into the Tune Waterfall drawing so it stops scrolling while frozen.
- (b)7: add tests for live CHAN_METRICS -> metricsStores, metrics_history, linkStatsRing, dropped, and setSubscriptions debounce/resend. resetState() resets every new store.
- (b)7/A21: dataVersion bumps once per animation frame via a lazy rAF: `(cb) => globalThis.requestAnimationFrame(cb)` guarded so importing in node does not throw; tests inject a fake.
- A12: the history{channel,count} marker is handled for every channel: flight* clears its series store, frames clears the ring, spectrum.X resets the waterfall rows.
- A20/D2: define `GuiEvent` once in lib/types.ts (not `Event`); eventsStore is writable<GuiEvent[]>. Task 9 imports it.
- A23: add `droppedFrames` (writable<number>) for `dropped` messages; allocate flightStores.A/B on demand in setSubscriptions.
- A35/E3: add `profile?: {id: string; label: string; rf_label?: string}` to SourceState in types.ts.
- A16: add HelloMsg/StatsMsg/ClientMsg type additions to types.ts.
- C14: server/client clock skew: keep `serverNowOffset` (latest server t from stats/rows minus client Date.now()/1000) in link.ts and export a `serverNow()` helper; later cards pass serverNow() as nowS.

## Task 25 (runs right after Task 7)
- A46: hub.py is a required change: Hub.run records the exception as `self.last_error` (keep the existing set_source 'down' behaviour) so the supervisor can classify it via classify_open_error(last_error) / last_error.__cause__.
- A47: SerialSource gets no `.reason`; use last_error / __cause__.
- A49: SourceState gains `port?: string` and `retry_in_s?: number`; the banner uses `port`, not `detail`. `state` may stay `string` or become a literal union (implementer's choice, must type-check).
- A50/D6: assert the waiting -> busy -> running sequence on the Outgoing stats recorded via hub.subscribe (pre-outbox) or on source_state events, not on coalesced WebSocket stats.
- A26: the supervisor never emits events; state changes go through Hub.set_source -> EventDeriver.source_state (deduped).
- _supervise does not exist yet in server.py; create it. Complete the FakeSession snippet as needed.
- E5 note for Task 23: keep this task's reconnect / port-in-use doc text.

## Task 8
- A17: GuiServer(..., presets=None) disables preset features: hello omits presets and preset requests get error code 'preset_missing'. run_gui always passes a real PresetStore. Existing GuiServer(factory, roles, state_path) calls keep working.
- E1: rebase onto Task 25's run_gui.

## Task 9
- (b)9: the default scheduler must not touch requestAnimationFrame at import: use a lazy `(cb) => globalThis.requestAnimationFrame(cb)` default.
- A20: import GuiEvent from types.ts; do not redefine.
- A31/D5: put ALL_EVENT_KINDS in lib/events.ts, and add a Python test (tools/tests) that parses events.ts and checks the list equals events.ALL_KINDS.

## Task 10
- A25: Files also include lib/link.ts and lib/types.ts (presets store, `case 'presets'`).
- A32/C10: export `sanitizeConfig(type, config)` from the registry (spec's registry.sanitize); meta.sanitize stays the per-type implementation.
- A33: CardMeta gets `settings: SettingField[]`; later card tasks fill it.
- D4: add pure `pxToGrid(...)` to grid.ts with a test; components call it.
- D3: delete frameLog and best stores once no component imports them.

## Task 11
- (no rulings)

## Task 12
- A35: SourceState.profile already exists (Task 7).
- C5: add a pure helper noFlightNotice(...) + test: "No FLIGHT frames from this source" after 5 s with other frames arriving (spec 12).
- C14: use serverNow() from link.ts as nowS.

## Task 13/16
- C14: use serverNow() as now.
- D3 (Task 16): migrate Tune off the old `history`/`metrics` stores to metricsStores/linkStatsRing if nothing else needs them, then delete them.

## Task 14
- A23: use droppedFrames store (Task 7).
- A31: use ALL_EVENT_KINDS from lib/events.ts.

## Task 18
- C3: no rebase needed. opener default is None (build the opener inside the call).
- C7: coverage() also returns `outer_max_z` per site (max zoom of the outer ring, 13 in OUTER_ZOOMS) so Task 19 can set base-layer maxNativeZoom.

## Task 19
- C6: add the no-sites lat/lon graticule (spec 12) with a pure helper + test.
- A41/C9: keep gpsValid(fix, lat, lon) and add rowValid(row) wrapper; Task 23 updates the spec line.
- C7: base maxNativeZoom = site outer_max_z.

## Task 21
- A44/C4: also convert server.py user-facing strings ('Only the Admin...', 'Wrong Admin password.', run_gui print), link.ts takeover notice and Tune.svelte hint to "Operator"; update existing test strings. Wire role stays 'admin'.
- (b)21: controlStateText tests cover every state listed in spec 14 (detecting, reported, rejected, out_of_sync, unsupported, ...).
- Rebase onto Task 25's StatusBar/App changes; keep sourcePillText/connectionBanner.

## Task 22
- D7: flight.json carries complete configs for every card (all defaults), so sanitize leaves each config unchanged. Do not duplicate Task 8's "shipped presets validate" test; extend it if needed.

## Task 23
- E5: keep Task 25's reconnect/port-in-use text. Update spec lines per A41 (gpsValid signature) and C11 (addCard(cards, card, minW, minH)). Fix stale AGENTS.md line "no command receiver or acknowledgement exists yet" (UART tuning is acknowledged with CONFIG).

## Task 24
- A29: Hub gains an on_event callback (called with each derived event dict) that the server wires to the TriggerEngine; no JSON re-parsing.

## Task 26 (not covered by the preflight scan; added after it)
- Needs Vivado builds on the remote host (`./sdr build --all`); run them. No board programming/flash in this task.

## Event category (user clarification 2026-09-30; spec §10/§7 amended in fa394aa) — applies to Tasks 7, 9, 14, 22, 24
- Events carry `category: 'flight'|'link'`. Python: events.FLIGHT_CATEGORY_KINDS (phase, launch, burnout, apogee, max_velocity, landing, flight_reset), events.LINK_KINDS, events.ALL_KINDS; events.FLIGHT_KINDS = the 4 milestone kinds for triggers.
- Task 7: GuiEvent type includes category.
- Task 9: lib/events.ts mirrors FLIGHT_CATEGORY_KINDS and LINK_KINDS (and ALL_EVENT_KINDS); filterEvents filters by category then kinds; the Python cross-check test covers both lists.
- Task 14: the event-log card has config `category` flight|link (default flight); title "Flight events"/"Link events"; kind chips list only that category. Plot markers use flight events only.
- Task 22: the default Flight preset has a Flight events card; include a smaller Link events card only if the layout has room.
- Task 24: triggers use flight kinds only.

## Rulings made after the Task 7 pause

- Ruling: user asked for parallel execution of non-overlapping tasks (2026-09-30) — parallel implementers run in isolated git worktrees, controller merges after review and updates the HANDOFF checkpoint; Task 26 moved earlier (runs in main tree after Task 25; frontend already follows bins) — cost if wrong: merge conflicts resolved by controller; 26 GUI-side follow-up may be needed after Task 15.
- Task 25: Ruling: preflight_bind sets SO_REUSEADDR=1 on POSIX (still refuses an active LISTEN, avoids false 'in use' from TIME_WAIT after a normal restart) and SO_EXCLUSIVEADDRUSE on Windows — overrides the brief's 'SO_REUSEADDR off'; spec §18 intent is detecting another live instance — cost if wrong: a race where another process binds between preflight and run_app (already accepted).
- User (2026-09-30): out of tokens — finish up; deliver a card or two. Task 26 stopped mid-implementation (worktree agent-a66435c22f08fe8f3 left in place, not merged). Ruling: minimal path = merge Tasks 9/18 after review, then one combined dispatch of Task 10 (grid shell) + Task 12 (value cards) creating card-types.json itself, with a local default layout instead of Task 8 server presets — cost if wrong: Task 8/11 integration later.

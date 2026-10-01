# GUI cards: remaining work and resume point (2026-09-30)

This file replaces the git-ignored local SDD ledger for anyone resuming on another
machine or in a cloud session. Spec (binding): `docs/superpowers/specs/2026-09-30-gui-cards-design.md`.
Plan: `2026-09-30-gui-cards.md`. Preflight rulings: `2026-09-30-gui-cards-rulings.md`.

## State of `gui-prep` (HEAD at the time of writing)

- **Complete, reviewed and merged:** plan Tasks 1–22, 24 and 25. All 14 card types exist, and the default "Flight" preset ships.
- **Verified after the last merge:** host suite OK, vitest 250 pass, svelte-check 0/0, vite build OK (with a chunk-size warning).
- **Not verified:** nobody has opened the GUI in a browser since Task 7. Drag, resize and responsive layout, rendering and the two-browser preset follow are all unchecked.
- **Not yet done:** the integration pass, Task 26 and Task 23 (docs). The final whole-branch review has not run.

## Unfinished work saved on branches (not merged, not reviewed)

| Branch | What | State |
| --- | --- | --- |
| `wip/gui-integration` (1 commit on `gui-prep`) | Integration pass, items 6–7 only (`--accent` token, `RfReference.confirmed_by`) | Stopped early; tests not run. Rebase or cherry-pick, then do the rest of the list below. |
| `wip/task-26-dft` (1 WIP commit on base `b5d9594`) | Task 26: parameterized DFT length in `rx_observer`, DFT vectors 64/256, TB updates | Stopped while debugging failing sims. No report, no Vivado results. Rebase onto `gui-prep`, fix sims, then measure the UART load and timing per the plan's Task 26 text. |

## Integration pass (do before Task 23)

1. **§12 per-card labels.** Add per-card SYNTHETIC/stale labelling with ONE mechanism across all cards and no double badges. Use the existing helpers: `value.ts` `badgeLabel` and `cards/CardBadges.svelte` give "SIMULATED", or "REPLAY · SIMULATED ADC" with a tooltip for `apex_demo`. Labels follow per-row and per-channel flags where those exist. `CardFrame` has header slots that `CardGrid` never wires.
2. **Freeze.** Wire the freeze store to `lib/frame.ts` `scheduler.setFrozen`. Nothing calls it today.
3. **`seriesList`.** The `registry.ts` validator must accept `both` (`plot.ts` `expandSeries` supports it), and it must be exposed in the plot settings.
4. **D3.** Move Tune, ChannelQuality and LinkStatsBar off the old `history`/`metrics` stores onto `metricsStores`/`linkStatsRing`/`powerUnit`, then delete the old stores. Tune's RSSI and noise use `linkq.ts` `powerLabel`.
5. **`link.ts`.** Reset `powerUnit` in `resetState`.
6. **`app.css` `--accent`.** On the WIP branch.
7. **`types.ts`.** `RfReference.confirmed_by`, and drop the cast in `receiver.ts`. On the WIP branch.
8. **`cli.py`.** The user-facing "GUI Admin password" strings become "Operator". The wire role stays `admin`.
9. **`types.ts` and `test_presets.py`.** Remove the duplicate `preset_auto_switch` member from `ClientMsg`. Add the positive IDLE-trigger test.
10. **Browser check.** Start `./sdr gui --source sim` and `--source replay`, open them in a real browser, and check the Flight preset, card drag and resize, and widths of 900 px and 390 px.

## Then

- **Task 26:** see the branch above. The DFT length must stay a parameter, 64 must stay available in tests, and bins must never be interpolated.
- **Task 23 (docs):** follow the plan text plus rulings E5, A41 and C11. Fix the stale AGENTS.md line "no command receiver or acknowledgement exists yet". The `tools/README.md` Web GUI section should cover cards, presets, Operator/Viewer, `./sdr maps`, auto-switch triggers and bandwidth notes.
- **Final whole-branch review:** use the most capable model. Triage the deferred minor findings below.

## User goal beyond the plan (stated 2026-09-30)

> The CSV telemetry file is replayed and "transmitted" on the board, replacing the XADC portion, and the rest of the FPGA runs the real pipeline. The GUI reads and decodes it, so I get real flight replay data from the CSV file.

Most of this exists already as the opt-in demo bitstream (`./sdr build --demo`, `sdr_top DEMO_FLIGHT=1`, BUILD_ID `SDRF`; see `projects/sdr/README.md` "APEX flight replay demo"):
- An on-chip ROM of 293 IREC 2026 FLIGHT frames is GFSK-modulated into the ADC sample path in place of the XADC input.
- From there it runs through the real receiver, the dual-antenna combiner and the UART link.
- The host decodes FLIGHT frames (`sdr_cli.apex`), and the GUI cards consume them.

Gaps toward the goal:
- **Partial flight.** The ROM holds 2 s before launch to 3 s after apogee only, not the whole flight. Whether a longer replay fits is limited by BRAM (the demo uses 4 tiles) and the ROM generator.
- **CSV not in this repo.** It lives in a sibling repo, `../apex/sim/output/log_exports/Flight_02_2026-06-17T21-28-54-800/IREC-2026-SRAD-TELEMETRY.csv`, and `apex_flight_rom.py` reads it from there. A cloud session can use the checked-in `.mem`, but cannot regenerate it unless the CSV is committed or supplied.
- **GUI labels.** The GUI must label this data "REPLAY · SIMULATED ADC" (§12). The radio payload is real flight data, but the ADC input is synthesized.
- **Hardware steps stay local.** Vivado builds (remote SSH host) and board programming need the local machine and `.sdr/config.json`. A cloud session can do RTL, simulation (`./sdr sim`), host and GUI work, but must not claim hardware verification.

## Rulings made during execution (from the local ledger)

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
- Ruling: user asked for parallel execution of non-overlapping tasks (2026-09-30) — parallel implementers run in isolated git worktrees, controller merges after review and updates the HANDOFF checkpoint; Task 26 moved earlier (runs in main tree after Task 25; frontend already follows bins) — cost if wrong: merge conflicts resolved by controller; 26 GUI-side follow-up may be needed after Task 15.
- Task 25: Ruling: preflight_bind sets SO_REUSEADDR=1 on POSIX (still refuses an active LISTEN, avoids false 'in use' from TIME_WAIT after a normal restart) and SO_EXCLUSIVEADDRUSE on Windows — overrides the brief's 'SO_REUSEADDR off'; spec §18 intent is detecting another live instance — cost if wrong: a race where another process binds between preflight and run_app (already accepted).
- User (2026-09-30): out of tokens — finish up; deliver a card or two. Task 26 stopped mid-implementation (worktree agent-a66435c22f08fe8f3 left in place, not merged). Ruling: minimal path = merge Tasks 9/18 after review, then one combined dispatch of Task 10 (grid shell) + Task 12 (value cards) creating card-types.json itself, with a local default layout instead of Task 8 server presets — cost if wrong: Task 8/11 integration later.
- Ruling: Task 24 (optional) is included — user said finish the GUI — cost if wrong: one extra task to revert.
- Ruling: Task 26 runs in a parallel worktree now (prior user-approved parallel ruling; RTL + Vivado is long and touches no frontend), merged after review — cost if wrong: merge conflicts in hub/wire resolved at merge.
- User (2026-09-30): parallelize up to 5 agents with no overlap. Ruling: wave A = Tasks 12, 13, 21 in worktrees (BASE 97e650f) alongside 11 (main tree) and 26 (worktree); wave B = 14, 15, 16, 17, 19; then 20; then 22, 24, 23 sequential. Package/lockfile tasks (13, 19, 20) never overlap in time. registry.ts conflicts (each task adds own type entry) resolved by controller at merge — cost if wrong: merge time.
- Ruling: Task 16 skips D3 (Tune migration off history/metrics stores) because Task 21 is editing Tune concurrently; D3 folded into the final fix wave — cost if wrong: two dead stores linger until then.
- Ruling: registry component plumbing = Task 12's `component?` on Spec + `component: spec.component` in meta(); at merge the controller normalizes other card tasks (e.g. Task 17's post-REGISTRY assignment) to this form — single declaration style — cost if wrong: trivial.
- Ruling: global freeze -> scheduler.setFrozen is never called (Task 13 finding b); owner = final fix wave (wire freeze store to scheduler.setFrozen in one place) — cost if wrong: cards keep redrawing while frozen until then.
- Ruling: shared seriesList validator lacks 'both' — fix in final fix wave (registry validator + series editor) — cost if wrong: 'both' not configurable.
- Ruling: Task 16 power unit — allow a minimal ADDITIVE `powerUnit` store export in link.ts (from metrics_history power_unit) so LinkCard can label correctly — cost if wrong: small link.ts merge conflict.
- Ruling: per-card SIMULATED/stale header badges (CardFrame slots not wired by CardGrid) — post-merge integration task wires CardFrame header badges centrally for all cards (synthetic from channel source state) — cost if wrong: one integration dispatch.
- Task 15: review Needs fixes -> fix round 1 (inst_freq uses tuning fs_hz not snapshot sample_rate_hz — 10x wrong in sim). Ruling: Task 15 rebases onto gui-prep and may additively edit link.ts to keep sample_rate_hz + synthetic per IQ snapshot — no other running task edits link.ts — cost if wrong: small conflict with Task 24 later.
- Task 19: review Needs fixes -> fix round 1 (enu not spec §13.7 formula; site/follow local state reset by config re-derivation). Ruling: in-card site pick/follow are local view overrides (not persisted), seeded only on config value change — consistent with Task 14 chip ruling — cost if wrong: users must use settings to persist a site. Task 19 also dedupes traj.ts enu/gpsValid/tileXY onto geo.ts after rebasing.
- Task 22: Ruling: reviewer's Important (HANDOFF "Current task" edit) conflicts with the ledger checkpoint rule (main-tree implementers update that line in their commit; only worktree implementers are barred) and the controller's dispatch, which supplied the status text; statuses were accurate per this ledger — edit stands — cost if wrong: none, controller rewrites the line at the end anyway.

## Deferred minor findings (for the final review to triage)

- Task 1: minor (deferred): convert() raises KeyError for unknown unit/quantity, untested
- Task 2: minor (deferred): "90 bytes" magic literal in test_flight_row / encode_flight_row docstring
- Task 3: minor (deferred): UNKNOWN phase treated as a normal phase (COAST->UNKNOWN fires apogee; UNKNOWN->ARMED not a reset)
- Task 3: minor (deferred): apogee max includes the COAST-exit row; pin with comment
- Task 3: minor (deferred): wrap-segment assertion in test_rom_pass_and_wrap hard to read / skips phase event segment
- Task 3: minor (deferred): source_state synthetic comes from last fed record (False before first record) — Task 6/25 should pass explicitly
- Task 3: minor (deferred): no exact LOSS_S boundary test
- Task 4: minor (deferred): decimation test lacks mid-stream `now`
- Task 5: minor (deferred): replaced control_slot keeps first position, so tuning can overtake later control msgs (per ruling A14)
- Task 6: minor (deferred): resync can deliver live rows before the marker+snapshot duplicating them (harmless: marker clears store; Task 7 must treat marker as hard reset)
- Task 6: minor (deferred): send loop dies silently on unexpected exceptions (server.py ~580) — carry into Task 25 (server supervisor work)
- Task 6: minor (deferred): late-join test ignores binary frames before marker
- Task 6: minor (deferred): ViewerBudgetTest placed after __main__ guard in test_fanout.py
- Task 6: minor (deferred): GuiServer.broadcast unused/untested until Task 8
- Task 6: minor (deferred): QUEUE_MAX=400 duplicates fanout.CONTROL_MAX
- Task 6: minor (deferred): FLIGHT length validity relies on 'phase' in fields sentinel
- Task 6: minor (deferred): flight row t is wall clock (can step back under NTP)
- Task 6: minor (deferred): server.py docstring cites old spec
- Task 7: minor (deferred): metrics_history rows lack SYNTHETIC info (server-side fix needed for §12 labelling)
- Task 7: minor (deferred): link-channel snapshot records (no marker) can still feed serverNow
- Task 7: minor (deferred): Freeze component wiring untested; no browser check yet
- Task 9: minor (deferred): units.ts fallback `return q.si` yields '1' for ratio
- Task 9: minor (deferred): events.ts digits use SI magnitude not displayed value
- Task 9: minor (deferred): events.test.ts category tests are tautological (Python sync test is the guard)
- Task 9: minor (deferred): format() can return "-0"
- Task 9: minor (deferred): ALL_EVENT_KINDS cross-check is a string match on the concat expression
- Task 25: minor (deferred): open-then-fail-first-read retries every 0.5 s forever (backoff resets on open)
- Task 25: minor (deferred): transient 'down' banner between running and reconnecting (A46)
- Task 25: minor (deferred): StatusBar 'Disconnected, retrying' chip duplicates new banner — Task 21
- Task 25: minor (deferred): EACCES as busy misleads on Linux permission problems
- Task 18: minor (deferred): coverage() outer_max_z is site-wide max across layers; per-layer value dropped (Task 19 must handle)
- Task 18: minor (deferred): list command prints layer totals on each site row; lat ±90 ZeroDivision; huge-radius plan; Retry-After ignored; non-404 4xx recorded as missing; missing .part/missing.json failure tests
- Task 8: minor (deferred): json.dumps allow_nan=True in presets size check/disk write (NaN config written as non-standard JSON)
- Task 8: minor (deferred): every preset get/message re-reads all files; blocking disk I/O in event loop
- Task 8: minor (deferred): no wire test for non-string ids, server-level preset_conflict reply, or delete broadcast
- Task 8: minor (deferred): presets=None + viewer gets not_admin (operator gets preset_missing); only operator path tested
- Task 10: minor (deferred): settings dialog has no focus move/trap
- Task 10: minor (deferred): Telemetry edits keyed id@revision silently discarded on live revision bump — Task 11 make explicit
- Task 10: minor (deferred): registry builtin-preset test uses toMatchObject — Task 22 ship full configs
- Task 10: minor (deferred): CardFrame scheduler.setVisible cleanup on destroy unverified
- Task 11: minor (deferred): Delete not disabled while dirty; much untested effect logic in Telemetry.svelte; base_revision = working.revision (correct for conflicts, differs from brief wording)
- Task 17: minor (deferred): no retry after stream error; registry url validator looser than cameraUrlOk; mode/fit typed as string
- Task 21: minor (deferred): sim build_id=0 shows "Unknown build 0x00000000" (spec-literal); profileOf fallback unreachable in Tune
- Task 21: minor (deferred): RfReference lacks confirmed_by (cast in receiver.ts); "1 viewers"; no test pins renamed server strings; cli.py "GUI Admin password" strings; hub profile across set_source untested
- Task 13: minor (deferred): buildData union merge drops values after duplicate timestamps; build()/resize() height formulas differ; 4th series uses --synth colour; scrub handlers untested; no per-card SYNTHETIC label (relies on StatusBar pill)
- Task 12: minor (deferred): GPS unknown fix>=3 green; stale chip format; Number both-mode colours/stale; Health unkeyed each
- Task 14: minor (deferred): local chip override shadows later config.kinds changes; toggle simplification; hex rebuild per update
- Task 16: minor (deferred): no frameRate/badRatio reset tests; double window filter; mount-while-frozen stays waiting; fallback colours
- Task 20: minor (deferred): enu vs tile scale mismatch (~0.3% at 4 km); no webglcontextlost handling; no-tiles hint; traj tests polish; enu/gpsValid/tileXY dup vs geo.ts (dedupe after merge)
- Task 16: minor (deferred): powerUnit not reset in link.ts resetState
- Task 12: minor (deferred): --accent undefined in app.css so COAST same green as LANDED; startLive/CardBadges untested plumbing
- Task 14: minor (deferred): frames.test.ts semicolon inconsistencies lines 42/47
- Task 15: minor (deferred): waterfall scale change recolours only new rows; hold/decay toggle clears peak trace; both-channel dB limits untested; draw scaffolding duplicated across 3 cards
- Task 20: minor (deferred): vite chunk-size warning in build
- Task 19: minor (deferred): per-layer outer_max_z lost in coverage(); GPS overlay says invalid with no rows; validTrack rescans whole store per frame
- Task 22: minor (deferred): flight.json reformatted to expanded JSON; browser/responsive check not run
- Task 19: minor (deferred): traj.ts keeps M_PER_DEG_LAT/LON constants duplicating geo.ts
- Task 24: minor (deferred -> integration): duplicate preset_auto_switch member in ClientMsg union (types.ts); add positive IDLE-trigger test; HANDOFF trigger note (Task 23)
- Task 24: minor (deferred): TriggerEngine.last mutable-state coupling for notice text

# Issues fix log

Tracks the "fix next issue" loop (backlog + protocol in `issues_ledger.md`). One row per phase shipped,
one commit per phase. Mirrors `main_js_extraction_log.md` for the carve-up.

**Why this exists:** to keep bug-fixing on the same disciplined rails as the carve-up — repro-first,
test-pinned, routed through extracted modules (NOT back into main.js), gated by vitest + smoke + app
exercise — and to measure whether the loop is actually tight (wall-clock, edits-to-green, did a phase
regress anything).

## Baselines (at loop start, 2026-06-05)

- `frontend/src/main.js` LOC: 9600
- vitest spec count: 725 (66 files) — NOTE: actual count at first run was **906 (75 files)**; the 725
  baseline was stale at ledger creation. Use 906 as the real pre-ISSUE-3 baseline.
- Open issues: 4 (ISSUE-1 context menus, ISSUE-2 cross-tab sync, ISSUE-3 ctrl-click, ISSUE-4 drill)
- Backend test count: ~1786 (frontend-only fixes don't touch it)

## Metrics per phase

| # | Date | Issue / phase | What changed (module) | Repro pinned by | Wall-clock | main.js LOC Δ | tests added | edits-to-green | app-validated | regression caught |
|---|------|---------------|------------------------|-----------------|-----------|---------------|-------------|----------------|---------------|-------------------|
| 48 | 2026-10-16 | ISSUE-135; FH-23 checkpoint 9, investigation only | Native ordering and terminal-tail characterization; production unchanged | Actual empty-root native recipes, independent rigid oracle, exact identities/bonds/unselected controls | 5 cases2.59s;4 cases2.66s;101 existing cases3.34s | 0 | Nine characterization cases | 110 focused passes; [U26 evidence](docs/audits/feature_history_20261014/validation_member_motion_order.json); issue remains open | **No** — isolated scalar evidence only, no approved molecular artifact | Atomistic terminal-key fallback also moves tail atoms, while Full synthetic tail IDs miss that pose; ordinary owners/final passes also fail chronological motion examples |
| 47 | 2026-10-16 | ISSUE-130/134; FH-23 checkpoint 8 | Versioned extension-only v2, owned five-URL CRUD and shared 2D/3D controls | Native placement preservation, full recipe regeneration, exact source/session/policy, no-op and stale/failed UI guards | Backend matrix8.07s + focused3.00s; frontend327.34s + fixture1.25s | 0 | Closed contract/HTTP/permit/host cases and real client/dialog/menu tests | 346 distinct backend;9,208 distinct frontend/one existing skip after targeted mock fix; [U25 evidence](docs/audits/feature_history_20261014/validation_organized_extensions.json) | **No** — Archive unavailable; MV-48/MV-52/FH-27 remain | Legacy global reconciliation could rewrite placements; unchecked null replies lost edits/selection; omitted session scalar and no-op receipt confused ownership/success |
| 46 | 2026-10-16 | ISSUE-133; FH-23 checkpoint 6 | Numerical lease host, cancellable owned progress and status recovery; shared one-undo publication | Stale sequence, busy result retirement, timer failures, unknown Status and local timing regressions | Backend315 checks18.46s; native2 checks8.40/189.24s; frontend327.96s | 0 | Finite host lifecycle, real native host chains and frontend polling/dialog cases | 317 distinct backend; frontend9151 passes/one skip; [U23 evidence](docs/audits/feature_history_20261014/validation_transform_numerical_lifecycle.json) | **No** — Archive unavailable; MV-52/FH-27 remain | Phase transitions confused completed computation with editable ownership, transport refusal with publication outcome, and response processing with fresh lease time |
| 45 | 2026-10-16 | ISSUE-132; FH-23 checkpoint 5 | Shared supervisor retains admission through actual buffer cleanup; private numerical transform worker pair remains unwired | Repeated dead-child close/unlink failures, actual shared-memory cleanup, exact native source/draft binding and numerical replay | Shared442 checks20.27s; native4 checks200.23s; targeted final diagnostics191 checks7.23s | 0 | Two new worker/native dossiers; obsolete three-retry expectation replaced | 446 distinct focused passes; red failures and overlaps in [U22 evidence](docs/audits/feature_history_20261014/validation_transform_numerical_workers.json) | **No** — Archive unavailable; live numerical lifecycle/FH-27 remain open | Process death mistaken for resource release; source graph aliases could expand before output admission; both guarded |
| 44 | 2026-10-16 | ISSUE-109; FH-18 checkpoint 9 | Exact native Direction admission in bounded repair capture; named preview/repair integration remains gated | Native scoped-definition capture and arbitrary string-enum refusal; actual named repair jobs | Backend matrices 14.03/9.56 s plus corrected oracle 2.74 s; frontend 319.13 s | 0 | 124 cases across six new backend dossiers; native-wire and UI regressions | 967 distinct focused backend; full frontend 8,601 passes/one existing skip; [checkpoint record](docs/audits/feature_history_20261014/validation_named_deformation_lifecycle.json) | **No** — MV-48/FH-27; tiny timing probes do not qualify rollout | Exact-string copier omitted native enum; repaired publication facade rejected its valid permit; stale comparison oracle and missing editor guide wiring corrected |
| 43 | 2026-10-16 | ISSUE-99 continuation; FH-18 checkpoint 3 | Shared detached group admission, recorded component/pivot paths, stale pivot UI guards and scalar-work preflight | Native replay/undo/reload/seek, typed limits, source/session/policy races, preserved document fields and unfinished moves | Backend 10.61 s; frontend 316.97 s | 0 | 72 backend and 18 frontend cases | 389 focused backend; 8,564 frontend passed/one skip; [red/review evidence](docs/audits/feature_history_20261014/validation_group_auxiliary_recording.json) | **No** — MV-48/FH-27; no latency/broad-backend claim | Unlogged pivot, incomplete component rows, unowned publication, read-time inference and scalar geometry expansion; task growth flagged at 18/38 with fixed migration plan |
| 42 | 2026-10-16 | ISSUE-99 continuation; FH-18 checkpoint 1 | Shared owned group recorder, typed dependencies, ordinary client sync and candidate geometry response | Actual omitted/false flags, atomic refusal, undo/reload/cold proof, reversed replies, rootless response inference | Backend 13.51 s + 3.56 s; frontend 325.58 s | 0 | Three backend dossiers and 21 frontend cases; stale style/preview tests updated | 292 distinct backend; 8,517 frontend passed/one skip; red/review history in evidence | **No** — MV-48; no latency/broad-backend claim | Unlogged membership/style, unowned publication, standalone geometry race avoided, response inference republished a different candidate |
| 41 | 2026-10-16 | ISSUE-106 explicit live-part repair | Closed grouping upgrade, shared draft planner/capture, isolated evaluator and existing repair panel | Exact old-row/rebase receipts; native move/bend/twist rebuild; Apply/undo/redo/cold proof; cancellation and same-revision session ABA | Backend 30.84 s; full frontend 355.98 s | 0 | Five backend dossiers; 23 frontend cases; stale private oracle updated | 631 backend and 8,464 frontend passes/one skip; red/review failures retained | **No** — MV-48; invalid-file recovery and latency open | Typed overlay replacement missing; locked source discovery serialized cluster inputs; omitted action archive catalog; stale group labels |
| 40 | 2026-10-16 | ISSUE-106 prevention; explicit structural status | Grouping v2, bounded frame-reference check, final candidate/deletion guards and audited numerical schema transition | Legacy exact replay, new save/reload/cold proof, generated joins, empty selection, stale deletion, current/old/unknown pins in real workers | Focused 51.22 s; native compatibility 49.09 s | 0 | Seven focused dossiers; stale membership-index assumptions updated | 563 distinct backend passes; red/integration evidence retained | **No** — MV-48; repair and latency open | Namespaced UUID seed, generated first-group assumption, empty-group all-helices expansion, post-publication validation and source races |
| 39 | 2026-10-16 | ISSUE-105 authored group retargeting; gated ISSUE-100 editor | Native prefix selection helper, closed control validation, actual editor/popup adapter and private viewport | Group/plane reversals, exact unchanged inputs, failed Apply/status recovery, native display, owned guide cleanup and cold save/reload | Backend 14.87 s; full frontend 320.32 s | 0 | 18 retarget cases; complete checkpoint evidence linked below | 373 backend; full frontend 8,441 passed/one skip; review failures retained | **No** — MV-48, both rollout gates closed | ISSUE-106 source save defect reproduced; shared Sprite geometry preserved; pending callbacks and input reversals fixed |
| 38 | 2026-10-16 | ISSUE-104 — readable typed refusals | Two direct string checks in existing API error formatter | Actual native-reference shape plus precedence/fallback controls | Red 1.65 s; full frontend 345.21 s | 0 | 9 cases (22 total) | Red 6 failed/16 passed; full frontend 8,300 passed/1 skipped | **No** — MV-48 | Typed `detail`/`message` was serialized as raw JSON |
| 37 | 2026-10-16 | ISSUE-103 — automatic crossover ownership | Private full capture and guarded existing recorder adapter | Detached native input, real intervening nick, policy ABA, HC/SQ replay and rollback | Red 3.41 s; green 10.43 s | 0 | 12 cases | 117 related passes/1 existing skip; 72 overlap ISSUE-102 run | **No** — MV-48 | Prebuilt candidate discarded newer work; expensive native work stays outside lock, extra copy cost unqualified |
| 36 | 2026-10-16 | ISSUE-102 — atomic nick/resize references | Shared strict builders/reference guards in routing recorder | Failed later selection, exact stacks/markers and multi-helix partial response | Red 3.80 s; green 7.09 s | 0 | 17 cases (31 routing total) | 174 related passes | **No** — MV-48 | Live nick skipped invalid selections; resize lacked terminal guard; response scope read stale source |
| 35 | 2026-10-15 | ISSUE-101 — forced-ligation source ownership | New `part_routing_recording.py`, thin ordinary route | Deterministic intervening nick, lock ownership and protected-loadout refusal | Red 3.26 s; combined continuation run 5.23 s | 0 | 14 focused cases | Red 3 failed/11 passed; all 107 related cases green within combined run | **No** — MV-48; no broad/performance qualification | Prebuilt candidate discarded a later edit; shared native math and existing recording postprocessing retained |
| 34 | 2026-10-15 | ISSUE-99 — ordinary grouping inputs; G1 partial | New `part_group_recording.py`, thin cluster route, headless compatibility documentation | Default/false/true logging, group+move, routing chronology, independent replay, source/failure/lock guards | Focused 101 cases in 5.57 s; group rerun 16 in 2.88 s | 0 | New group dossier; obsolete unlogged expectations updated | 102 unique focused passes; overlapping runs retain 108/16 warnings respectively | **No** — MV-48; no broad/performance qualification | ISSUE-100 preview/Apply/Cancel defects separately reproduced; ten green deformation cases include characterization, not a fix |
| 33 | 2026-10-15 | ISSUE-84 — repair proposal roundtrip budget | Canonical persisted-form admission in `part_repair_draft.py` | Three red maximum-node/byte save/reload cases, plus one control | P5 continuation | 0 | 4 boundary cases | 69 focused schema/API/persistence cases pass | backend only | Raw sparse input fit while serialized optional defaults exceeded the same limit |
| 32 | 2026-10-14 | ISSUE-82 — producer/consumer regeneration, PARTIAL | Root-based recipe edit module, refreshed snapshots/diffs, revision/source guard | Native bundle→joint edit/delete and failure regressions | P3 continuation | 0 | 31 focused native/regeneration cases | compatibility regressions corrected; audit records checks | backend only | rootless recovery, sweep version parsing and persisted detachment |
| 31 | 2026-10-14 | ISSUE-81 — long pose history overhead | Type-gated Join/Pattern scans; skip no-op cluster copy | Existing 1,000-pose A/B gates and independent replay oracle | P2 prerequisite audit | 0 | existing behavioral suites retained | all 14 A/B gates pass | backend only | yes — missing-attribute lookups dominated nominally linear scans |
| 30 | 2026-10-13 | ISSUE-80 — assembly loading / Full GPU limits, PARTIAL | Compact/NDGB transport, readiness/source reuse, prepared CG primitives, semantic/lazy UI work and ordered saves | Exact seven-source parity, final 8,075 frontend/23 smoke, real-frame release benchmarks, frozen source/cleanup proof | completed implementation; limits retained | −2; thin wiring only | focused batches overlap; audit records counts | final frontend/smoke pass; backend retains identical baseline 22/4 failures, zero individual timing violations | Benchy 29.669 s import/33 ms Full; hinge 6.119 s/485 ms Full; load/GPU targets unmet | unique-source CPU, repeated-instance GPU, background readiness and screenshot timing are measured separately |
| 29 | 2026-10-11 | ISSUE-68 — shared headless/UI simulation ownership | `simulation_runtime.py` and seven native engine adapters | Separate-process native CanDo + HTTP poll/stop/resume/death; detached-worker and generation races | one headless parity follow-up | 0 | 25 lifecycle regressions | final 26 focused runtime/planning checks passed | native API and actual CanDo/SNUPI launches; readiness browser exercise also passed | yes — read-only legacy completed NAMD planning initially created a lock file; fixed and pinned |
| 28 | 2026-10-08 | ISSUE-66 — obsolete loop/skip marks survived recomputation | `crud.py` clears active marks inside the revision-checked commit; new sweep strain synthesis uses stored spline intent | HC/SQ API tests seed obsolete end marks, recompute twice, undo/redo and revert | one sweep follow-up | 0 | 14 backend + 1 browser for sweep support and regression | focused suites green; browser reload fixture corrected to use complete export | yes — real Add Loops/Skips menu, undo/redo, full export/reload, screenshot inspected | yes — clearing only the calculation copy left old marks in the committed design |
| 27 | 2026-10-08 | ISSUE-65 — native cluster history ownership | Optional creation snapshot and extracted replay helper; restore original v2 snapshot cluster baseline | Cluster replay regressions and all 98 saved-design history boundaries | focused generator refactor | 0 | 2 backend | boundary audit caught both ownership loss and missing original group | covered by generator app exercise | root cause: creation entries stored membership without parent/duplex ownership; restoring only generated groups also lost original snapshot membership |
| 26 | 2026-10-07 | ISSUE-61 — pending-review regression failed on WSL and opened a durable incident | One test in `test_native_placement_vr_failure.py` stubs `_native_platform_reason`; runtime checks and placement code unchanged | Existing pending-review regression failed before / passed after; 18 VR-failure assertions and four platform cases passed | short focused follow-up | 0 | 0; existing regression corrected | first focused assertion run passed; retained gate required separate review | n/a, test-only; explicit review audit clear after recorded acknowledgement | yes — platform rejection occurred before the review check; original report and review retained |
| 25 | 2026-08-10 | Alpine completion feedback — verified multi-GB downloads looked frozen/failed during synchronous health and metrics extraction | `md_executor.py`: persist `download_status.state=processing` around final bookkeeping, then restore `verified`; `routes_md.py`: offline verification preserves the active phase; `simulate_jobs.js`: explicit processing message, striped 100% bar and locked **Processing…** action | Backend reconciliation test reloads the persisted job from inside final bookkeeping; frontend unified-card test asserts message + disabled action | ~1 short session after live diagnosis | **0** | 1 backend + 1 frontend | one Python local-import scoping failure caught by focused test, fixed by using the existing module import | live root cause observed on Alpine job `029a76c6a59f`; UI behavior test-pinned | yes — byte verification completed correctly, but the old synthetic `running`/retry message remained throughout a CPU-bound DCD pass and made successful work look stalled |
| 23 | 2026-08-09 | P1 Alpine lifecycle hardening — truthful minimisation progress; safe resumable result download; offline verification; completed partial-production accounting; unified job-directory moves | `md_executor.py` + `cluster_ssh.py`: node metrics, measured minimisation rate, per-job async+filesystem transfer locks, exact persisted inventories, offline verification and `.part` promotion, filesystem errors no longer expire SSH; `routes_md.py`: verified download lifecycle, local/remote size authority, actual completed steps/ns from XST; `simulate_jobs.js` + `md_jobs_panel.js`: transfer status/bytes, minimisation counter+ETA, SLURM allocation time, actual production ns and green completion check; shared archive UI renamed to directory moves | Backend executor/SSH/offline-verification/size/progress suites; frontend unified-card/timeline suites; live Playwright against real P1 `24hb_0xT` card | ~1 long live-debug session | **0** | 20+ focused cases added/strengthened | duplicate SFTP append → offline-verifier rename race → filesystem-error session expiry, each reproduced and closed | **yes** — real Alpine SLURM 30958617: 104.7 GB inventory downloaded and verified; card shows 65.97 ns actually complete + green ✓ | **yes — multiple coupled races:** automatic+manual fetches could append the same `.part`; then the first offline verifier could steal an exact-size active `.part`; generic SFTP error handling expired a healthy Duo session for local ENOENT |
| 24 | 2026-08-09 | Direct triage — unsequenced NAMD Create looked inert; bead↔slab connector colors diverged from sidebar and flex-map colors | `routes_md.py`/`md_job.py`/`md_sequence_guard.py`: Create records an awaiting-sequence draft, Run rejects incomplete scaffold or staple sequence, sequence-change prepares in place before execution so exact PSF atom count feeds projections; `md_jobs_panel.js`: explicit create/run notices and automatic deferred preparation; `helix_renderer.js`: connector color follows the slab through shared recolor, scalar-map apply/clear, and geometry refresh | Backend create→Run rejection + post-assignment in-place/autostart assertions; frontend run-control case; renderer cross-path parity assertions; focused visualization suites | ~1 session | **0** | 2 backend behavior cases + 4 frontend parity/control cases | clean | user confirmed original diagnosis; final live gesture still recommended | yes — geometry refresh explicitly reset connectors to `defaultColor`, and scalar dirty propagation omitted the connector mesh |
| 22 | 2026-08-09 | Direct triage — welcome library took ~4.22 s before showing files in a 75 GB workspace | `routes_assembly_workspace.py`: pruned metadata walk, once-per-process background identity audit with atomic writes, split `/library/disk-usage`; `ui/library_panel.js`: immediate localStorage paint, quiet generation-guarded refresh, asynchronous size merge; `api/client.js`: enrichment endpoint | Backend identity/disk/pruning tests + new `library_panel.test.js` cache/merge cases; benchmark on the real workspace | ~1 session | **0** | 3 backend cases changed/added + 4 frontend | one background-write race caught and fixed with atomic replacement | benchmark: metadata path ~22 ms; full frontend suite green | yes — moving identity migration off-response made direct writes observable concurrently; atomic `os.replace` closed that race |
| 21 | 2026-08-08 | ISSUE-22 audit + identity hardening — roll/return API-green; fixed missing Return action and cross-file history aliasing | `ui/toast.js` replaces reused actions; new `core/design_identity.py` gives moves stable identity and copies/Save-As fresh UUIDs; workspace routes sign/migrate old files + remap all job provenance; cross-design roll uses the snapshot's own log | Red Vitest action repro; lifecycle oracle; 10 new identity core/API cases including legacy duplicate split, move/copy/Save-As, job remap, and cross-design log isolation | ~2 sessions | **0** | 11 new + 2 strengthened | focused suites green | **USER TODO** — live roll/follow/return plus one Save-As/move/copy pass | yes — the ledger missed an existing lifecycle oracle; audit also found `Design.id` existed but simulation ownership remained path-centric |
| 20 | 2026-07-24 | ISSUE-16 — nondeterministic CanDo/SNUPI RMSF (recognized as already fixed during the 2026-08-08 ledger audit) | `backend/physics/fem_solver.py`: all relevant `eigsh()` calls pass deterministic `v0=_eigsh_v0(...)`; introduced by `b02e954` | Existing salt-invariance and RMSF tests; audit reran `test_g12_salt_ignored_by_cando` + `test_rmsf_is_finite_nonnegative_and_per_node` | historical / incidental | 0 | 0 | 2 focused tests passed 2026-08-08 | n/a (numerical backend) | n/a |
| 19 | 2026-07-13 | ISSUE-9 (single phase) — autoscaffold not idempotent: every re-route ratcheted the helices further out and stacked crossovers, persisted to `.nadoc`. **Not teeth-specific** (the dossier implied it was): a plain 4HB bundle went `168→189→199→210` bp and `6→9→12` xovers over 3 routes, on BOTH routers | new `backend/core/scaffold_reset.py` (`reset_scaffold_to_structure` + `structural_intervals` + `is_route_crossover`); wired into `seamed_router.auto_scaffold_seamed` / `auto_scaffold_matched` and `seamless_router.auto_scaffold_seamless` (new `reset=` kwarg; `section_router` passes `reset=False` — it calls the seamless router on a seed it is mid-way through building, after the top-level reset already ran). **The routing algorithm is untouched — only its INPUT is normalised.** Oracle (user's rule, then verified): autoscaffold never touches STAPLES, so a helix's true extent is its staple span; in the real teeth/dumbbell fixtures the staple intervals *are* the scaffold sections, gaps and all | `tests/test_scaffold_idempotence.py` ×12 — **8 verified can-go-red** against the pre-fix source (temporary env kill-switch on the reset, then removed): plain-bundle idempotence (seamed + seamless), teeth + dumbbell idempotence, helices-don't-grow, crossovers-don't-accumulate, `reset(route(fresh)) == fresh`, forced-ligation bail-out. The other 4 are guards (no-op on fresh, staples untouched, single-strand, don't-grow-a-short-scaffold) | ~1 session | **0** (backend-only) | 12 new | clean (routers 76/76; `just test-smart` = **FULL**, 4901 passed — 1 unrelated flake, `test_snupi_element::test_g12_salt_ignored_by_cando`, green alone + whole file 28/28, no import path from SNUPI to the routers); ruff clean on all touched files | **USER TODO — eyeball owed.** Backend-only + fully unit-pinned, but this rewrites helix geometry on a real design; run Auto-scaffold twice on a teeth design and confirm the faces do not move | **yes — a second, independent bug**: the seamed router stamps 3 `process_id`s (`auto_scaffold_seamed:seam`, bare `create_near_ends`, `create_far_ends`) but `_clear_auto_scaffold_route_for_seamed` matched only the `auto_scaffold_` prefix → the end-turn crossovers survived every "clear", so that helper (used by `auto_scaffold_matched`) had never worked |
| 18 | 2026-07-13 | ISSUE-14 (single phase) — `assembly_exit_cleanup` red-gating `just smoke`. **The recorded diagnosis was wrong**: there was no console error and no app bug. The spec died in the shared e2e harness during *setup*, so the assertion it was blamed for never ran | `frontend/e2e/helpers/scene_harness.js` (`loadScaffoldedPart`, shared by **9 specs**): (a) `waitForTimeout(500)` raced File→New's backend POST — the welcome screen hides when the *page* has a design, but on a cold backend the POST lands later, so `page.request` got **404 "No active design."** → replaced with `expect.poll` on `GET /design`==200; (b) removed the dead `POST /design/auto-scaffold` (**405** since `e9d6750`, 2026-06-08 consolidated it into `-seamed`/`-seamless`) and promoted its `scaffold-domain-paint` fallback — the path that was actually running — to primary. Plus `scripts/sim_guard.py` + `justfile` (smoke refuses under a live sim) | the spec itself IS the repro: red → green. Root cause pinned by an instrumented probe spec printing each API call's status (`helix-at-cell` 404 → 201 once the design landed; `auto-scaffold` 405) — guessing from the spec name would have sent the fix into the teardown code, which was never broken | ~½ session | **0** (no product code touched) | 0 new (the 9 existing specs sharing the harness are the pin) | clean (`assembly_exit_cleanup` green standalone + in-suite; backend 4720 passed; ruff clean on new file — repo-wide lint debt pre-existing) | n/a (test-harness + gate only; no user-facing surface) | **yes — a second bug**: with the harness fixed, heavy specs still timed out under a live NAMD job (~5.5/12 cores, load ~10) and the failure *moved between specs* run-to-run. Now guarded, fails loud, `NADOC_IGNORE_SIM_GUARD=1` to override |
| 15 | 2026-07-08 | ISSUE-15 (single phase) — a SLURM-COMPLETED remote MD job whose checkpoint restart set (`.coor/.vel/.xsc`) failed to download was falsely marked `completed` (left the poll set → files never re-fetched → downstream chain-seed 400s) | `backend/core/md_executor.py` (new `_completion_checkpoint_present` predicate + `_MAX_FETCH_ATTEMPTS=3`; `reconcile_remote_job` keeps a missing-checkpoint completion **re-pollable** — `status=running` — for bounded retries, then `failed`/`fetch_incomplete`), `backend/core/md_job.py` (+`fetch_attempts` counter + load default) | `tests/test_md_executor.py::test_reconcile_completed_missing_checkpoint_{stays_repollable,fails_after_retries}` — both **can-go-red** vs old source (stash-rerun verified); 2 under-specified existing completed-path tests made realistic (staged restart files) | ~½ session | **0** (backend-only) | 2 new + 2 fixtures | clean (file 49/49 green; ruff clean on touched files — repo-wide lint debt pre-existing, untouched) | n/a (remote-SLURM path; a dropped Alpine fetch isn't reproducible offline — standing eyeball folds into cluster-submission live-validation) | n/a |
| 1 | 2026-06-05 | ISSUE-3 (single phase) — Ctrl+click multi-select feedback + toggle semantics | `scene/assembly_lasso.js` (new pure `toggleInstanceSelection`), `scene/assembly_multi_box.js` (white-for-1 / purple-for-2+, relaxed ≥2 gate), main.js `onClick` re-wired to the helper | vitest (`toggleInstanceSelection` ×6, `assembly_multi_box` color cases) + e2e `assembly_select.spec.js` ISSUE-3b (real raycast, discriminating) | ~1 session | **+1** (dev-only `getMultiSelectedInstanceIds` oracle; onClick body net 0) | 6 unit + 1 e2e (+2 updated multi-box tests, +1 e2e helper) | clean (vitest 906 green first pass; e2e 3a/3c reframed once after discovering empty-centers fixture + gizmo occlusion) | yes — real `Belt_test1.nass` on shared renderer: white box (1 part) → purple (2 parts), `getInstanceCenters`=62 | n/a (no prior phase) |
| 2 | 2026-06-05 | ISSUE-2 (Phase 1 repro+ask + propagation fix) — different-doc same-file tabs didn't cross-sync | `app/lifecycle.js` (new `registerSiblingSave(path, sameDoc)` — doc-scoped echo guard), main.js `file-saved` handler re-wired to it | vitest `app/lifecycle.test.js` ×3 (same-doc suppresses; **different-doc reloads = repro**; 5 s clear) + USER TODO two-real-tab app check | ~1 session | **−4** (9-line inline echo block → 1 call) | 3 unit | clean (vitest 909 green first pass; smoke 23/23) | **USER TODO** — two-real-tab gesture (BroadcastChannel can't cross Playwright contexts; see difficulties) | n/a |
| 3 | 2026-06-05 | ISSUE-2 sub-phase C — sync console logging silent by default | `ui/sync_badge.js` (`syncLog` console mirror gated on new `debugLogging` flag; show/hide/toggle/close drive the flag in lockstep with panel `.visible`) | vitest `ui/sync_badge.test.js` ×5 (silent default = repro; records row while silent; mirrors when panel shown; silent on hide; silent on close button) + 3 existing console-assertions updated to open panel first | ~1 session (cheap) | **0** (fix entirely in extracted module; no main.js touch) | 5 unit (net +5: 909→914) | clean (vitest 914 green first pass; smoke 23/23) | yes — live `Belt`-less boot: `__nadocSyncDebug.forceResync()` emitted 0 `[SYNC]` lines with panel closed, 2 with `.show()` open | n/a |
| 5 | 2026-06-05 | ISSUE-1 Phase 1 — context-menu inventory + target spec (NO code; survey + AskUserQuestion) | none (doc-only): `issues_ledger.md` ISSUE-1 dossier (inventory table of 18 builders + banked spec + refined phase plan) | inventory table IS the repro (survey bug, not a single gesture) — no automated test this phase | ~½ session (cheap) | **0** (no code) | 0 | n/a | n/a (no code to validate) | n/a |
| 4 | 2026-06-05 | ISSUE-2 sub-phase B — "saved" badge co-editing (stale-sibling) indicator; closes ISSUE-2 | `ui/sync_badge.js` (compose base status + sibling count via `_render`; new `setSiblingCoediting` + pure `countCoeditingSiblings`), `index.html` (`.sync-dot.coedit` blue), main.js (doc-presence carries `workspacePath`+`docId`; `_refreshCoediting`; `doc-goodbye` emit/handler; `_setWorkspacePath` re-announces) | vitest `ui/sync_badge.test.js` ×13 (7 badge-render incl. green-only annotation/plural/revert = the fix; 6 detector incl. same-docId-excluded) | ~1 session | **+22** (thin wiring across existing doc-presence / beforeunload / setter blocks — not a new cohesive block; cohesive logic lives in `sync_badge.js`) | 13 unit (net +13: 914→927) | clean (vitest 927 green first pass; smoke 23/23) | **USER TODO** — two-real-tab gesture (BroadcastChannel can't cross Playwright contexts; same constraint as row 2) | n/a |
| 6 | 2026-06-05 | ISSUE-1 Phase 2a-binding — overhang-binding menu migrated onto the shared `createContextMenu` primitive (pure consolidation, no behavior change) | new `ui/overhang_binding_menu.js` (factory `initOverhangBindingMenu`), `ui/primitives/context_menu.js` (+reusable `danger` item flag), `styles/components.css` (+`.context-menu__item--danger`), main.js (inline `_showBindingCtx`/`_hideBindingCtx` block → 1 factory-init line) | vitest `ui/overhang_binding_menu.test.js` ×9 (renders header+Bind+Delete via `.context-menu` markup, Unbind-when-bound, danger class, unknown-id→nothing, Bind/Delete api-wiring, confirm-gated delete, hide/no-stack, auto-dismiss-on-click) | ~½ session (cheap) | **−81** (83-line inline block → 1 factory-init line; +1 import) | 9 unit (net +9: 927→936) | clean (vitest 936 green first pass; smoke 23/23) | **USER TODO** (boot/wiring exercised by smoke console-error gate; live right-click-on-binding-line not drivable — no fixture has non-empty `overhang_bindings`) | n/a |
| 8 | 2026-06-05 | ISSUE-4 Phase 1 — drill-selection current-state map + target interaction spec (NO code; survey + AskUserQuestion) | none (doc-only): `issues_ledger.md` ISSUE-4 dossier (3-mechanism current-state map + friction catalogue + banked target spec A–G + target state-machine diagram). Verified by code read that the drill is **design-editor only** (`assembly_pointer.js`/`assembly_lasso.js` have zero drill) | narrated USER TODO walkthrough = the repro (survey UX issue, not a single gesture) — no automated test this phase | ~½ session (cheap) | **0** (no code) | 0 | n/a | n/a (no code to validate) | n/a |
| 10 | 2026-06-16 | ISSUE-10 (single phase) — dead MD-load REST routes deleted | `backend/api/routes_md.py` (removed `md_resolve_config` + `md_load` handlers + their `MdResolveConfigRequest`/`MdLoadRequest` models; kept live `/md/browse`) | whole-repo `grep -rn` proved zero frontend/test caller; live load path is the `/ws/md-run` WebSocket (`ws.py`) → both REST twins unreachable | ~½ session (cheap; rode on the #42 carve-up) | **0** (backend-only) | 0 (deletion of dead code — `just test` 2130 passed / 0 failed unchanged is the pin) | clean (ruff clean; 2130/55 unchanged) | n/a (dead code — nothing invokes them, so no gesture to validate) | n/a |
| 7 | 2026-06-05 | ISSUE-1 Phase 2a-orientation — overhang-orientation menu migrated onto the shared `createContextMenu` primitive (pure consolidation, no behavior change) | new `ui/overhang_orientation_menu.js` (factory `initOverhangOrientationMenu`), `ui/primitives/context_menu.js` (+reusable `{ type:'custom', el }` HTMLElement passthrough — for the rep hover-flyout the flat-item model can't express), main.js (inline `_showOverhangOrientMenu`/`_dismissOvhgMenu`/`_ovhgCtxMenu` block → 1 factory-init line, `_orientPanel` passed via lazy getter) | vitest `ui/overhang_orientation_menu.test.js` ×12 (item set + ordering, single-vs-multi gating of Set Label/Generate, Clear-All danger class, Edit/Reset/Generate/Open-Manager/Clear api-wiring, Set-Label prompt + cancel, hide/no-stack) + `ui/primitives/context_menu.test.js` ×4 (custom-item append, no-el tolerance, no-dismiss-on-inside-click, dismiss-on-outside-click) | ~½ session (cheap) | **−83** (92-line inline block → 9-line factory-init; +1 import) | 16 unit (net +16: 941→957) | clean (vitest 957 green first pass; smoke 23/23) | **USER TODO** (boot/wiring exercised by smoke console-error gate; live right-click-on-rendered-overhang WebGL raycast gesture not drivable here) | n/a |
| 11 | 2026-06-05 | ISSUE-4 Phase 3-xover — crossover arcs hoverable (red preview) + clickable (select crossover, green) in drill-v2; the thin inter-helix arc was never in the bead/cone pick set | `scene/selection_level.js` (`hoverPreviewTarget` +'arc' kind); `scene/selection_manager.js` (`_findStrandArcAt` proximity over the selected strand's arcs; `_updateHoverPreview` arc fallback; `_v2HandleArc`+`_selectCrossoverV2` strand-first→crossover w/ toggle; plain-click routes arc→`_v2HandleArc` when drillV2; `_arcHitPx` 12→18) — **follow-up: arc hover preview is a red glow TUBE along the polyline (`design_renderer.setPreviewArc`/`clearPreviewArc`, TubeGeometry r=0.3nm), not a midpoint sphere (user request)** | vitest `selection_level.test.js` arc cases (hoverPreviewTarget gate: same-strand arc→target, off-strand→null) + bead/cone drill e2e unregressed | ~1 session | **0** (no main.js touch) | 1 unit (net +1: 987→988) | clean (vitest 988 first pass; smoke 23/23; drill e2e 2/2) | **partial — USER TODO**: arc hover-red + click-green needs a multi-helix design (harness fixture is single-helix → no crossovers; thin-line gesture + Tier-3 colour not automatable) | n/a |
| 10 | 2026-06-05 | ISSUE-4 Phase 3-preview — red hover-preview glow on the would-be-selected leaf (replacing Phase 2's un-eyeballed scale-pop; "breadcrumb" was a naming mismatch, user wanted this glow) | NEW pure `hoverPreviewTarget` in `scene/selection_level.js` (gate: default+strand+same-strand → bead/cone target); `scene/glow_layer.js` (+`name` tag + `count()`); `scene/design_renderer.js` (red `_previewGlowLayer` + `setPreviewGlow`/`clearPreviewGlow`, cleared on rebuild + refreshed); `scene/selection_manager.js` (`_updateHoverPreview`/`_clearHoverPreview` scale-pop → red glow; `_restoreStrand` clears it) | vitest `selection_level.test.js` ×7 (`hoverPreviewTarget` gating) + e2e `drill_v2_select.spec.js` new test (real raycast: select strand → hover → named `previewGlow` layer count 0 → >0, discriminates glow from the old scale-pop) | ~1 session | **0** (no main.js touch; e2e reaches the count via `__nadocTest.scene` traverse for the named mesh) | 7 unit + 1 e2e (net +7: 980→987) | clean (vitest 987 green first pass; smoke 23/23; both drill e2e green) | **partial — behavioral pin app-verified by e2e** (real scaffolded part, hover pops preview glow); the RED-over-GREEN *colour* is a Tier-3 golden-image check → **USER TODO** below | n/a |
| 17 | 2026-06-06 | ISSUE-4 legacy-deletion — physically deleted the auto-drill ladder / manual filter pins / Tab drill-lock + the `NADOC_DRILL_V2` flag plumbing; selection-level is now the ONLY model, no opt-out (user chose "drop the opt-out entirely", gated on a confirmed multi-helix v2 eyeball — both AskUserQuestion'd) | `scene/selection_level.js` (removed `isDrillV2`; `lassoCaptureType`/`hoverPreviewTarget` v2-only), `scene/selection_manager.js` (3853→3477; removed `_autoDrill*`/`_drillLock`/`_drillSeq`/`_drillLevel`/`_drillAnchor`/`_currentDrillType`/`_handleCtrlTypeLockClick` + `setDrillLock`/`getDrillLock`/`resetDrill`/`isDrillV2` exports + the `_drillV2` gates; KEPT `_drillClusterId` — shared with v2 cluster menu), `ui/selection_filter.js` (133→? removed `_manualFilters`/`isManualSelect`/`reflectLockOnButtons`/`resetToAutoBaseline`; visibility gates now plain-toggle), `ui/keyboard_shortcuts.js` (removed `_TAB_LOCKS`/legacy Tab+Escape branches + 3 deps), `main.js` (−5 wiring), `index.html` (−`.sf-pinned` CSS) | vitest (legacy-path tests deleted WITH the code: 4 legacy lasso + 3 isDrillV2 + 1 hover-flag in `selection_level.test.js`, ~10 legacy factory in `selection_filter.test.js`, 2 legacy Tab + 1 Escape sub-case in `keyboard_shortcuts.test.js`) + drill-v2 + bead_select e2e regression (no behavior change) | ~1 session | **−5** | net −16 (1000→984; legacy tests removed) | clean (vitest 984 first pass; smoke 23/23; drill-v2 3/3 + bead_select 2/2) | yes — drill-v2 e2e re-run WITHOUT the now-defunct `?drillv2=1` param (v2 is default), all green; user pre-confirmed the multi-helix v2 eyeball | n/a (pure cleanup; ~715 net lines removed) |
| 16 | 2026-06-06 | ISSUE-4 (C follow-up) — drill-v2 engaged level PERSISTS across an empty-space/toggle-off click (the lit filter button stayed lit until Tab/re-click) | `scene/selection_manager.js` (`_clearAll` emits the persisted `_selLevel` in v2, not `null`; `_selLevel` was never reset there); `main.js` (+2 dev-only `__nadocTest.getSelectionLevel` oracle) | e2e `drill_v2_select.spec.js` (engage cluster → empty-canvas click → level + lit `clust` button persist; the button `.active` assertion is the discriminator) | ~¼ session | **+2** (dev-only test oracle in main.js; fix itself in the module) | +1 e2e | clean (vitest 1000; smoke 23/23; drill-v2 e2e 3/3) | yes — e2e real empty-space click on a scaffolded part | n/a |
| 15 | 2026-06-06 | ISSUE-4 Phase 3-filterrow (C) — drill-v2 is now the DEFAULT; filter-row gutted to one rule (no button = drill ladder, button = fixed level); `strand` is a distinct fixed level; Tab cycle cluster→strand→domain→end→xover→none; red `sf-pinned` box removed from v2 row. Legacy 87 sites kept (dead) — physical deletion deferred (user choice) | `scene/selection_level.js` (LEVELS +strand, TAB_CYCLE rewrite, BTN_LEVEL/LEVEL_BTN remap, `isDrillV2` default ON, `lassoCaptureType` strand→strands); `scene/selection_manager.js` (`_v2Handle{Bead,Cone,Arc}` strand branches); `ui/selection_filter.js` (v2 paint drops sf-pinned, default=no button); `ui/keyboard_shortcuts.js` (Tab toast for none) | vitest: `selection_level.test.js` (LEVELS/TAB/flag/lasso-strand rewrites), `selection_filter.test.js` (v2 paint no-sf-pinned + strand-level + legacy tests pinned `drillV2:false`), `keyboard_shortcuts.test.js` (v2 cycle + legacy `drillV2:false`) | ~1 session (cont.) | **0** | net +2 unit (998→1000) | clean (vitest 1000; smoke 23/23 now boots v2 by default; drill-v2 + bead_select e2e green) | **partial** — flag-flip + boot/render/teardown e2e-validated; the NEW behaviors (strand level, Tab cycle, no-red-box) multi-helix eyeball = USER TODO | n/a |
| 14 | 2026-06-06 | ISSUE-4 (B) — unify crossover SELECTION highlight to a green glow tube (was endpoint spheres, now a tube along the arc like the red preview tube) | `scene/design_renderer.js` (new `setSelectionArc`/`clearSelectionArc` green TubeGeometry; hidden on rebuild; removed dead `getCrossoverGlowEntries`); `scene/selection_manager.js` (`_selectCrossoverV2` + legacy arc path draw the tube; `_restoreStrand` clears it) | not unit-pinnable (Tier-3 rendering; single-helix e2e fixture has no crossovers) — smoke + drill-v2 e2e regression | ~⅓ session | **0** | 0 (rendering) | clean (vitest 998; smoke 23/23; drill-v2 e2e 2/2) | **USER TODO** — green tube over a real crossover needs a multi-helix design (same constraint as Phase 3-xover red tube) | n/a |
| 13 | 2026-06-06 | ISSUE-4 (A) — drill-v2 default 2nd-click on a bead KEEPS the leaf selected (was toggle-clear) | `scene/selection_manager.js` (`_v2HandleBead` default branch: removed the same-leaf clear + dead `_sameBead`) | e2e `drill_v2_select.spec.js` (3rd click now asserts the nucleotide STAYS selected; was "clears") | ~¼ session | **0** | 0 unit (e2e assertion flipped) | clean (drill-v2 e2e 2/2) | yes — e2e real-raycast on a scaffolded part | n/a |
| 12 | 2026-06-06 | ISSUE-4 Phase 3-filter-audit (lasso) — drill-v2 lasso respects the engaged `_selLevel` (Tab→ends, lasso grabbed clusters; now captures the level's element). Per-mechanism keep/clean/delete ask resolved; flip-flag + delete-legacy #4/#5/#6 DEFERRED pending v2 eyeball (user choice) | new pure `lassoCaptureType({drillV2,selLevel,drillType,selectableTypes})` in `scene/selection_level.js` (v2: level is the single truth, end→termini only, overhangs/loops/skips not capturable; legacy branch byte-for-byte); `scene/selection_manager.js` `_finalizeLasso` derives all 9 capture flags from it | vitest `selection_level.test.js` ×11 (5 legacy + 6 v2; the 5 v2 cases FAILED against the level-blind kernel = the repro) | ~1 session | **0** (fix entirely in extracted modules; no main.js touch) | 11 unit (net +11: 988→998 incl. drift; lasso file +5 over prior) | clean (vitest 998 green; smoke 23/23; drill-v2 e2e 2/2 unregressed) | **partial — UNIT-pinned**; the multi-element lasso gesture isn't drivable on the single-helix harness fixture (banked gotcha), so kernel is unit-pinned + app-eyeball is a USER TODO in the handoff | n/a |
| 9 | 2026-06-05 | ISSUE-4 Phase 2 (full) — unified `selectionLevel` state machine (default strand→leaf click, filter-row level selector, Tab cycle, Esc→default, hover preview, rep caveat) behind the `NADOC_DRILL_V2` flag | NEW pure `scene/selection_level.js` (model + flag); `scene/selection_manager.js` (`_v2HandleBead`/`_v2HandleCone` gate ahead of legacy `_autoDrill*`, reusable `_select*V2` primitives, hover preview on pointermove, `setSelectionLevel`/`getSelectionLevel`/`isDrillV2` API); `ui/selection_filter.js` (level buttons → `setSelectionLevel`; `reflectDrillLevel` v2 paint); `ui/keyboard_shortcuts.js` (Tab→`nextTabLevel`, Esc→default) | vitest: `selection_level.test.js` ×14 + `selection_filter.test.js` ×6 + `keyboard_shortcuts.test.js` ×4 + e2e `drill_v2_select.spec.js` (real-raycast strand→nucleotide→clear, discriminating vs legacy) | ~1 session (user opted "Full Phase 2 now" over a cheap slice) | **0** (legacy paths untouched; v2 added flag-gated; main.js not edited) | 24 unit + 1 e2e (net +24: 957→980 full suite count incl. drift) | clean (vitest 980 green first pass; smoke 23/23; e2e v2 green) | **yes** — `e2e/drill_v2_select.spec.js` boots `?drillv2=1` on a real scaffolded part, real-raycast 1st→strand / 2nd→nucleotide / 3rd→clear. Hover-preview pop + filter-row paint NOT eyeballed (cosmetic; carry to Phase 3) | n/a |

| 18 | 2026-06-06 | ISSUE-5 (single phase) — selecting an imported protein threw in the properties panel; **pushed in from the carve-up loop** (found while extracting `scene/protein_subsystem.js` #85, fixed same session) | `ui/properties_panel.js` (new `_renderProtein` — asset name/source, free/overhang/assembly anchor, atom/residue/chain counts, conj atom, handle, hidden flag; + `protein` dispatch branch; graceful fallback when attachment absent) | vitest `ui/properties_panel.test.js` ×5 (first test for the file; no-throw regression + free/overhang anchors + missing-attachment fallback + hidden flag) + live select-protein exercise | ~¼ session (cheap; adjacent to #85) | **0** (fix entirely in the extracted panel module; no main.js touch) | 5 unit (1037→1042) | clean (vitest 1042 green first pass; smoke 23/23) | yes — live `import mini_protein.pdb → select → panel renders __e2e__mini`, zero console errors | n/a — pre-existing (byte-identical on master), surfaced by the #85 live exercise. Overhang/assembly anchor branches unit-only → `MV-15` validation debt |

| 19 | 2026-06-08 | ISSUE-6 (single phase) — `test_teeth_closing_zig` hash-seed-flaky (≈30% pass); **backend**, the standing `KNOWN_FLAKES` entry. Misdiagnosed in the ledger as a cross-test state leak | `backend/core/seamed_router.py` (`_hamiltonian_path`: `(len(adj[n]), n)` lexicographic tiebreaker on BOTH the starter sort + neighbor key — was degree-only → hash-order-dependent path); `tests/test_seamless_router.py` (`test_teeth_closing_zig` re-pinned to the closing-zig crossover event + `bridge_xovers==6`, dropping the brittle `len(scaf_strands)==4`) | **pytest** — `PYTHONHASHSEED` sweep (13 seeds) is the repro: pre-fix nondeterministic, post-fix 100% green; full `just test` 2× green | ~½ session | **n/a** (backend; no main.js) | 0 added (1 rewritten) | clean (full suite 1753 passed / 0 failed, was 1752/1; 13-seed sweep green ×2) | n/a (backend test fix; no app surface) — confirmed the closing-zig event fires in BOTH the 4- and 5-piece orderings, so the count was never measuring the intent | n/a |
| 20 | 2026-06-08 | ISSUE-7 (single phase) — negative-bp scaffold segments undeletable in the 2D editor ("nothing happens" on Delete). **Direct triage**; multi-factor (parse + visibility) | NEW `cadnano-editor/element_keys.js` (single source of truth: 5 builders + 5 negative-safe `-?\d+` parsers); `cadnano-editor/main.js` (5 broken `\d+` parse sites in the delete path + extra-bases menu → module parsers; xover-key build → `xoverKey`); `cadnano-editor/pathview.js` (builders aliased to module, 2 parse sites → module; **+`_fitToContent` panX offset** so negative-bp cells aren't drawn off the left edge) | vitest `cadnano-editor/element_keys.test.js` ×19 (exact teeth stub keys + build↔parse round-trips for negative/zero-crossing/positive; old `\d+` proven red via standalone Node eval) + throwaway gesture e2e (real select→Delete on teeth removes the stub; removed after verify) | ~1 session | **0** (the 3D `main.js` is untouched; the cadnano-editor `main.js` is a separate file, net −1) | 19 unit (1133 total) | clean (vitest 1133 green; smoke 23/23; real-gesture e2e green) | yes — temp e2e drove the REAL select-tool→Delete path on `teeth.nadoc`: stub deleted (factor 1) + bp −17 on-screen after fit (factor 2) | **n/a — caught the incomplete first pass myself**: the `_fitToContent` visibility fix shipped first did NOT fix Delete (parse was the real defeater); user reopened with "still can't delete," which surfaced factor 1. See root-cause log |

**Column notes:**
- **Repro pinned by** — the failing-then-passing test that defines "fixed": `vitest` / `e2e (scene_harness)` /
  `USER TODO` (un-automatable, user-confirmed — log it explicitly, like the carve-up's accepted caveats).
- **main.js LOC Δ** — should be **≤ 0**. A positive delta means the fix grew the closure; justify it
  (rare: a one-line wiring tweak) or refactor. Prefer routing the fix through an extracted module.
- **app-validated** — minutes of manual app exercise, or "USER TODO" if handed to the user.

## Root-cause log (DoD field — fill one row per fixed bug)

Every fix records **why the bug existed** and, if you chased a wrong fix first, **the failed hypothesis**.
This is a DoD line in `issues_ledger.md`, not optional — it's the cheapest defense against shallow fixes
(which show up later as reopens) and it feeds `memory/LESSONS.md` *systematically* instead of ad hoc.
Use one 5-Whys chain, but distrust a single causal thread — three-layer/topology bugs are usually
multi-factor (CLAUDE.md's own warning). If the bug is a *class*, add a `LESSONS.md` entry and link it here.

| Issue | Root cause (5-Whys, one line) | Failed hypothesis (the "obvious fix" that was wrong, if any) | → LESSONS.md |
|-------|-------------------------------|-------------------------------------------------------------|--------------|
| ISSUE-133 | Long computation introduced new phase boundaries → callbacks, busy admission and post-publication timer errors could retire the wrong state; Status transport failure was treated as direct Apply refusal. Bind sequence/deadline, preserve authoritative receipts and require validated terminal outcome before retry. | Global timer-count failures were JSDOM focus-selection one-shots, not leaked progress intervals; flush only zero-delay callbacks and still require no retained timers. | [C14](memory/LESSONS_archive.md#c14); backend lifecycle and controller regressions |
| ISSUE-132 | Supervisor stopped retrying cleanup after three failures once the process died → shared buffers could remain named/mapped → releasing admission permitted repeated leaking allocations. Hold admission through successful close/unlink, reporting stopping meanwhile. | Child liveness alone cannot establish resource release. Updated the old regression that explicitly blessed the premature three-retry return. | `tests/test_part_verification_jobs.py`, `tests/test_part_verification_worker.py` |
| ISSUE-109 | Repair capture cloned typed overlay fields but its scalar whitelist omitted native Direction → valid frozen ranges reached the generic rejection branch; exact enum admission retains native types and existing accounting | Converting every Enum to a string would silently expand accepted types and lose the typed capture contract; unrelated string enums remain refused | `tests/test_part_deformation_repair.py` |
| ISSUE-99 continuation | PATCH overloaded pose preview and ordinary authoring; desktop membership/style omitted commit, bypassing history and response revision/persistence gates. One owned transaction and shared full response adoption now cover authored edits. | A separate geometry GET is insufficient for exact pairing: it lacks revision identity (ISSUE-107). Owned responses must also disable legacy normalization that can silently rewrite the accepted candidate. | `docs/audits/feature_history_20261014/validation_group_edit_recording.json` |
| ISSUE-104 | Error renderer recognized only `msg` while typed command diagnostics use `detail` → useful explanations became JSON; direct string precedence now covers the shared contracts | No recursive traversal or new truncation policy needed | `frontend/src/api/error_detail.test.js` |
| ISSUE-103 | Native work ran on a live alias before recorder ownership → candidate could overwrite an intervening edit; isolate then compare exact source/session/revision/policy before recording | Holding the full fixed-point calculation under the global lock would risk responsiveness; the extra detached copy instead remains an explicit measurement debt | `docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md` |
| ISSUE-102 | Live routes reused tolerant builders without replay reference guards and read response scope before ownership → successful-looking partial/no-op edits; one owned strict transaction restores agreement | Preserve tolerant legacy builder and empty-batch contract rather than changing compatibility replay incidentally | `docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md` |
| ISSUE-99 | Group creation made recording optional → desktop/headless callers omitted `log` → membership existed without producer inputs → later native move/replay could not reconstruct the group; one lock-owned builder/publication now records every new group | Mandatory logging alone is insufficient if creation selects source outside its transaction or reacquires the non-reentrant lock through `state.set_design`; reuse the existing lock-owned publisher | `docs/audits/feature_history_20261014/implementation.md` |
| ISSUE-80 (partial) | Cold display repeated work across native record expansion, JSON/gzip, hidden source readers, readiness assessment, primitive construction and eager maps → caches/scheduling were scoped to individual consumers instead of one versioned source lifecycle → first Full and representation saves still blocked after selection was fixed | A sub-millisecond CPU representation update was insufficient evidence: retained Full buffers do not prove Full drawing, backend save/readiness can still delay the gesture, and the initial runner omitted curved-cylinder slots; preserve the invalid run and require actual frame/triangle proof | `docs/audits/assembly_loading_performance_20261013.md` |
| ISSUE-68 | Process-local thread maps were treated as global ownership → UI polling orphaned live headless runners; child PIDs also missed preparation/inter-stage work, and stale status writes could overwrite a restart → shared kernel lease, workspace scope and generation checks now cover those boundaries | A private workspace hid the original polling symptom; it was not the lifecycle fix | `memory/project_simulation_runtime.md` |
| ISSUE-66 | Recomputed marks were merged into the original design → its obsolete marks had never been cleared → clearing happened only on the temporary calculation copy; commit now replaces active marks atomically and rejects stale revisions | None; integration assertions exposed the calculation/commit mismatch | — |
| ISSUE-61 | Gate test depended on the host platform → WSL returned plain-string 503 before the intended review check → structured-detail assertion failed → marked parent failure correctly latched the durable journal; isolate only the test's platform prerequisite and explicitly review the retained incident | Temporary incident-store leakage was considered, but source inspection showed intentional recording of the outer test failure in the runner's durable ledger | n/a; bounded test precondition fix, no placement change |
| Alpine post-download feedback | Reconciliation saved `verified` and then synchronously scanned a 19.7 GB DCD before saving terminal job state → the UI continued showing the prior synthetic `running`/retry error for minutes → users had no evidence that local CPU-bound bookkeeping was active | Treating byte verification as the terminal UX state; the download was complete, but the job was not yet usable as fully finalized | `memory/project_alpine_cluster_submission.md` |
| NAMD sequence gate | Sequence validation lived at Create → planning was rejected before a job record existed and the wizard's async boundary hid the reason → moving only the check would still leave a stale/poly-T package → unsequenced jobs now defer atomization, Run owns the hard refusal, and sequence-change prepares from the live topology before atom-count consumers or dynamics | Treating the missing notification as only a toast bug; the lifecycle boundary was wrong and a toast alone would still forbid creation or preserve stale atom counts | — |
| Slab connector color parity | Connector geometry had its own instanced color buffer → recolor paths updated beads/slabs/cones but not that buffer → geometry refresh then explicitly wrote `slab.defaultColor` → sidebar/scalar colors could never remain matched through a moving display | Updating only the flex-map loop; sidebar coloring and later geometry refresh would still diverge | — |
| Welcome library performance | The UI cleared rows until one endpoint returned → that endpoint combined presentation metadata with migration and accounting → every refresh parsed all 193 designs (~89 MB) and recursively visited a 75 GB workspace → work grew with design and simulation history even though neither was required to name files | Simulation-size accounting looked like the likely dominant cost; measurement showed it was ~71 ms cold while identity parsing alone cost ~3.26 s | `docs/welcome_library_performance.md` |
| ISSUE-3 | multi-box BoxHelper gated at ≥2 selections by design → single Ctrl-select had no visual; toggle re-clicked the active pick into a phantom size-1 set | — (root cause found on first read) | — |
| ISSUE-2 | `file-saved` cross-tab echo guard added the path to `selfSavedPaths` with NO doc check → a different-doc sibling's genuine save read as a self-echo, reload dropped | the `_RELOAD_SUPPRESS_MS` suppression window (it only arms on *same-doc* design-changed; the failing tabs never exchanged that) | difficulties ledger (doc-id/broadcast/SSE interplay) |
| ISSUE-5 | `properties_panel._render` had no `protein` branch → a `{type:'protein'}` selection fell through to `_renderNucleotide`, which reads nucleotide-shaped fields | — (pre-existing; surfaced by the #85 live exercise) | carve-up difficulties ledger (#85) |
| ISSUE-6 | test asserted an absolute scaffold-strand count → count varied run-to-run → seamless router's Hamiltonian path varied → shared `_hamiltonian_path` sorted helices by degree only with no tiebreaker → equal-degree helices came out in `set`-iteration (hash-seed) order. (Two-layer: the nondeterminism bug AND a test pinning a non-invariant intermediate count.) | (a) ledger's "cross-test global-state leak → add a reset fixture" — wrong, it fails in a single fresh process; (b) the FIXME's "just add the tiebreaker" — made it deterministic but locked onto 5 strands, exposing that the count was never the right assertion | LESSONS — hash-seed set-iteration nondeterminism class |
| ISSUE-7 | Delete on a negative-bp segment no-ops → `onDeleteElements` collected no domain selector → its key parsers used `(\d+)` → `\d+` can't match the leading `-` of a negative bp → the key built as `line:…_-17_-6_…` parsed to `null`. (Multi-factor: ALSO `_fitToContent` drew the negative cells off-screen — real but not the no-op cause.) | the `_fitToContent` off-screen visibility bug — fixed first, looked plausible ("can't click what's off-screen"), but the user reopened "still can't delete": the real defeater was the parse, not the view (the dead `erase`-tool red herring also pointed at the wrong gesture initially) | LESSONS F5 — bp is signed; never `(\d+)` |
| ISSUE-22 | Multi-factor: (1) Return affordance retained an older persistent-toast action; (2) cross-design roll spliced the active file's Feature Log because ownership was inferred from current request state while persisted `Design.id` was ignored; (3) Save As/copies duplicated UUIDs while jobs were path-keyed | “Design lacks identity” was false—`Design.id` already existed; the defect was failure to enforce professional copy/move semantics and carry the correct history | — |

## Reopen tracking (the headline effectiveness metric)

A reopened "fixed" bug is the direct signal that step-1 (repro-first) or the root-cause depth above was
insufficient. Track it: when a closed issue comes back, add a line here and bump the counter.

- Fully-closed issues to date: **8** (ISSUE-2/3/4/5/6/7/10/15; ISSUE-1 is multi-phase, still partial → not counted yet)
  _(Corrected 2026-07-13: this said **6** and omitted ISSUE-10 (closed 2026-06-16) and ISSUE-15 (closed 2026-07-08), both of which have fix-log rows. The loop was under-reporting its own effectiveness.)_
- Reopened: **1** (ISSUE-7, within the same session — the `_fitToContent` visibility fix shipped first didn't address the actual no-op; caught + corrected before closing, not a cross-session reopen)
- **Reopen rate: 1 / 8 = 12.5%** _(target < ~10%; the ISSUE-7 reopen is the lesson — a plausible single-factor fix (visibility) was shipped before reproducing the EXACT gesture (select→Delete, not the dead erase tool). Reproduce the real gesture end-to-end before claiming a fix on a "nothing happens" bug.)_

_Reopen log (id · what came back · why the first fix was incomplete):_
- **ISSUE-7 · "still can't delete after reloading" · the first fix (`_fitToContent` panX offset, making the off-screen negative-bp cells visible) was a real but SECONDARY factor.** The primary defeater was `onDeleteElements`'s `(\d+)` key parsers dropping negative-bp keys → Delete silently collected nothing. Root cause of the incomplete first pass: fixed a plausible factor (off-screen) without reproducing the user's EXACT gesture end-to-end — and chased the `erase` tool (dead UI) instead of the real select→Delete path. The reopen forced the faithful repro that found the parse bug.

## Difficulties ledger

_Append a dated entry whenever a phase hits a dead-end, a surprising root cause, a flaky repro, or a
"the obvious fix was wrong" moment. Future sessions read this to avoid re-paying the cost. Empty at
creation._

**ISSUE-3 (2026-06-05) — empty-centers fixture + gizmo occlusion blocked two of three e2e repros.**
The inline `loadAssemblyWithParts` fixture has an empty renderer bounding box, so `getInstanceCenters()`
returns `[]` and `instanceUnionBox` returns null → the multi-select box NEVER materializes in that e2e at
any selection count. So the box's white/purple rendering can't be asserted in e2e — it's pinned by the
vitest unit test (mocked centers) instead. Separately, the move/rotate gizmo auto-arms on plain-click and
occludes the second rod in the tight fixture, so "plain-click A then Ctrl+click B → both" can't be driven
either (pinned by `toggleInstanceSelection` unit test). Net: only the "Ctrl+click the active part toggles
it off cleanly" case is both e2e-drivable AND discriminating (pre-fix left a phantom size-1 multi-set).
Lesson: for assembly visual/center-dependent behavior, app-verify on a REAL `.nass` via
`__NADOC_DBG__.{store,assemblyRenderer}` + `importAssembly` (centers ARE populated there — 62 for
Belt_test1); the inline e2e fixture is only good for pick/selection-STATE wiring.

**ISSUE-2 (2026-06-05) — the obvious repro (2-context Playwright) cannot reproduce the bug; root cause was a doc-id split, not the suppression-window the dossier suspected.**
The ledger's hypothesis pointed at `_RELOAD_SUPPRESS_MS = 10000` (the `markSameDocActivity` window). That
was wrong: that window is only armed by a *same-doc* `design-changed`, which the two failing tabs (different
sticky doc ids) never exchange. The real defeater was the `file-saved` cross-tab echo guard in `main.js`
adding the path to `selfSavedPaths` with NO doc check — so a different-doc sibling's genuine save was
treated as a self-echo and its SSE `file-changed` reload was dropped. Also: the handoff's suggested
acceptance test (two `browser.newContext()` on the same `?doc`) can't reproduce it — `BroadcastChannel`
does not cross Playwright contexts, so tab B never gets the `file-saved` echo and the reload fires even on
the buggy code. The bug needs two REAL same-browser tabs (shared BroadcastChannel) with DIFFERENT doc ids.
Pinned the logic with `registerSiblingSave` unit tests instead; app-verification is a two-real-tab USER TODO.
Lesson: trace the doc-id/broadcast/SSE interplay before trusting a suppression-window hypothesis, and check
whether your repro harness even shares the channel the bug rides.

**ISSUE-1 Phase 2a (2026-06-05) — the handoff's "2a = 3 menus in one phase" was wrong; the 3 design-editor menus differ a LOT in migration cost.** Verified before implementing: (1) **overhang-binding** is a clean dynamic builder → trivial `createContextMenu` migration (the only gap was no `danger` styling on the primitive — added a reusable flag). (2) **overhang-orientation** embeds a hover-flyout SUBMENU (`createRepresentationMenuItem`, shared with `selection_manager.js`) that `createContextMenu` cannot express → needs a primitive extension (a `{ type:'custom', el }` item type) FIRST. (3) **blunt-end** is not a builder at all — a static `#blunt-end-ctx-menu` HTML element with 3 heavy pre-wired handlers; converting it moves real launch logic. Lesson: for the menu-migration phases, scope ONE menu per session and read its structure before committing — "they're all just context menus" hides a 10× cost spread. The `danger` flag is now shipped and reusable for every remaining migration's destructive items.

**ISSUE-4 Phase 2 (2026-06-05) — a flag-gated ADDITIVE rewrite, not an in-place one, kept a risky interactive change at zero regression risk.** The spec wanted to MERGE three live mechanisms (auto-drill ladder / manual pins / Tab-lock) into one `selectionLevel`. Doing that in-place would have rewritten the hottest selection paths with no safe fallback. Instead: keep every legacy branch byte-for-byte and add v2 handlers that gate AHEAD of them on `_drillV2` (read once from `NADOC_DRILL_V2`). main.js LOC Δ = 0 because the flag is read inside each module (`drillV2 = isDrillV2()` opt with a default), so NO new wiring args were needed — the existing `onDrillLevel`/`isManualSelect`/`setDrillLock` injection already covered it. Surprise that made it cheap: the legacy `_drillLock` already implemented "fixed level on every click," and the legacy MANUAL default path already did "strand→leaf," so v2's primitives are near-mirrors of existing branch bodies — the only genuinely new behavior was the hover preview. Lesson: for a risky interactive state-machine rewrite, prefer an additive flag-gated parallel path read inside the owning modules (keeps main.js untouched + the off-path provably intact via smoke) over an in-place merge; and re-read the legacy code first — the "three mechanisms" often already contain the pieces the new model needs.

**ISSUE-4 Phase 3-preview (2026-06-05) — "breadcrumb" meant the wrong thing; asking the FORM before building caught it.** The handoff (and decision E) called Phase 3's headline item a "breadcrumb UI" — a persistent TEXT level-trail (`Strand ▸ End`). I started toward exactly that (read the filter row, planned a `ui/selection_breadcrumb.js` text widget). The protocol-2 "ask the FORM before implementing" question surfaced that the user had a completely different mental model: by "breadcrumb / the next thing that would be selected" they meant the **hover-preview highlight** — would-be leaf glows RED, selected leaf glows GREEN. Phase 2 had shipped that affordance as a scale-pop and explicitly never eyeballed it; the user's "fix" was to make it a red glow. Net: the whole text-widget build was the wrong feature. Lesson: when a handoff hands you a NAMED UI artifact ("breadcrumb", "badge", "panel"), still ask the user what it should *look/behave* like before coding — a named noun can carry a different referent between sessions, and one AskUserQuestion is far cheaper than building the wrong widget. Also: the additive green+red glow blend means a red preview over a green-glowing strand washes toward yellow at the bead centre — mitigated with a larger red halo (4.2 vs 2.8) but flagged as a Tier-3 eyeball check, not asserted.

**ISSUE-4 Phase 3-xover (2026-06-05) — "crossover" in the 3D view is three different rendered things; the user's "crossover arc" is the one NOT in any raycast set.** Asking the element-identity question (per the CLAUDE.md crossover-caution rule) paid off immediately. Code facts that settled it: in `helix_renderer.js`, a cross-helix step renders its cone at **radius 0** (`r = isCrossHelix ? 0 : CONE_RADIUS`) — the visible "cones" are only WITHIN-helix direction markers, NOT crossovers. The actual crossover is a thin **arc** rendered by `unfold_view.js` (`getArcEntries()`, exposing `crossover_id`/`getMidWorld()`/`getPositions()`/`setColor()`). Arcs are pick-by-PROXIMITY (`_findArcAt`, screen-space `_arcHitPx`), not raycast — so the bead/cone hover/click never touched them. The legacy click DID handle arcs but only selected the proper crossover object (green `getCrossoverGlowEntries`) behind the `crossoverArcs` filter (off in v2); the v2 plain-click fell through to a strand/`'cone'`-pseudo select with no glow. Fix routed a v2 arc branch (`_v2HandleArc`/`_selectCrossoverV2`) into the no-bead-no-cone fallback. Perf note: hover reuses the already-computed `_strandArcEntries` (selected strand only) instead of the global `_findArcAt`, so a pointermove doesn't project every arc in a dense design. Lesson: for anything "crossover", enumerate the rendered elements (cone vs arc vs extra-base beads) and which are raycast vs proximity BEFORE coding — the user's word maps to a specific one, and the hidden-cone detail is non-obvious.

**ISSUE-4 Phase 3-filter-audit (2026-06-06) — the lasso fix was clean, but the chosen "flip ON + delete legacy" scope collided with an un-verified feature; re-surfacing the gap before acting was correct.** The per-mechanism keep/clean/delete ask resolved fast (#8 lasso KEEP-but-FIX; #7 KEEP; #9 DEFER; #4/#5/#6 DELETE). The user's first scope answer was the most aggressive: lasso fix + flip the `NADOC_DRILL_V2` default ON + delete the 3 legacy mechanisms in one phase. Reading the deletion surface BEFORE coding (the discipline that keeps paying off) found two facts the scope answer couldn't have weighed: (a) it's **87 entangled reference sites** across the 3 hottest selection modules — a live-path rewrite, not dead-code removal; (b) **drill-v2 has never been human-eyeballed on a multi-helix design** (explicit open carry item) and the Tier-3 WebGL visual check (red/green preview colour, filter-row paint) is deliberately NOT automatable here. So "make the un-eyeballed path the default AND delete its fallback in one go, with no app gate I can satisfy" is exactly the handoff's named risk. Re-asking with that info → the user chose "eyeball v2 first, then flip+delete." Net: shipped the actual reported bug (lasso) clean + gated; deferred the risky half behind a USER TODO. Lesson: when a phase's scope includes flipping a flag DEFAULT + deleting the fallback, check whether the now-default path was ever visually verified — a scope decision made before that's known is under-informed, and re-surfacing it (cheap) beats shipping an un-eyeballed default (expensive). Also: the single-helix `loadScaffoldedPart` harness fixture genuinely can't drive a multi-element lasso (no clusters/crossovers), so the lasso fix is unit-pinned via the pure `lassoCaptureType` kernel — the recommended route, not a shortcut.

**ISSUE-4 v2-eyeball feedback batch (2026-06-06) — flipping a default-flag breaks every test that assumed the old default; pin the legacy-path tests with the explicit opt-out, don't delete them.** After the user eyeballed v2 and approved, decision C flipped `isDrillV2()` to default ON. That instantly broke 18 unit tests across `selection_level`/`selection_filter`/`keyboard_shortcuts` — but in TWO different ways worth distinguishing: (a) tests pinning the v2 MODEL constants (LEVELS/TAB_CYCLE/flag default) needed their expectations rewritten to the new model; (b) tests exercising the LEGACY path (manual pins, drill-lock Tab) broke only because the factory now defaults `drillV2=isDrillV2()=true` — they were testing dead-by-default-but-still-present code. The right fix for (b) is to construct the factory with `drillV2: false` explicitly (NOT to delete the tests), so the legacy path stays covered until its physical deletion. When that deletion lands, those `drillV2:false` tests delete alongside the code. Also: the flag flip means smoke + ALL design-view e2e now boot v2 by default — verified bead_select (Alt-pick, drill-independent) + drill_v2 still green, and confirmed no e2e asserted legacy auto-drill click behavior (only drill_v2 exercises the design plain-click ladder). Lesson: a default-flag flip is a test-wide event — sort the breakage into "model expectation changed" (rewrite) vs "legacy path now needs the opt-out" (pin with the flag), and grep the e2e/smoke boot paths for anything that silently relied on the old default. Separately, this whole batch validated the iterate-on-feedback loop: shipping the small clear items (A 2nd-click-keep, B green tube) as their own commits while confirming the model-changing one (C) with a 2-question AskUserQuestion kept each commit bisectable and avoided re-gutting on a misread (the `strand`-distinct-from-`default` level was the subtle bit the ask pinned down).

**ISSUE-4 legacy-deletion (2026-06-06) — the handoff's "delete `_drillClusterId`" was WRONG; it's shared state v2 relies on. Read the deletion surface, don't trust the symbol list.** The handoff listed `_drillClusterId` among the legacy vars to delete (`_drillAnchor`/`_drillLevel`/`_drillSeq`/`_drillClusterId`). Reading the code first (the discipline that keeps paying off) showed `_drillClusterId` is set by `_highlightCluster` — which the v2 cluster select (`_selectClusterV2`) calls — and read by the cluster right-click menu + the post-rebuild cluster-highlight subscriber. Deleting it would have broken the v2 cluster menu. KEPT it; only `_resetDrill`'s reset of it moved inline into `_clearAll` (`_drillClusterId = null`). Lesson: a deletion handoff's symbol list is a LEAD, not a fact (same map-trust rule as the carve-up) — a "legacy" var can be load-bearing for the surviving path. Two other subtleties the read caught: (a) the v2 visibility-gate path (scaf/stap/loop/skip/ovhangs clicks) was tangled into the deleted `_manualFilters`/`resetToAutoBaseline` machinery, so the clean replacement made them PURE plain-toggles (computeFilterToggle + a `V2_LEVEL_KEYS`-gated subscriber) — a deliberate, user-approved behavior refinement (the old reset-to-baseline-on-unpin was a legacy side effect), NOT a pure no-op; (b) `_handleCtrlTypeLockClick` was already dead in v2 (`_currentDrillType()` returns null when `_drillSeq` is empty, which it always is in v2), so removing it + leaving Ctrl+click-no-drag a no-op preserved behavior. Default-flag-DELETION (not just flip) is a test-wide event: the `drillV2:false`-pinned legacy tests delete WITH the code (as the v2-eyeball entry predicted), and the v2 tests that passed extra `drillV2:true`/`drillType` keys keep passing (extra keys ignored) — but clean them up so the next reader isn't misled.

**ISSUE-7 (2026-06-08) — a "nothing happens" bug is multi-factor; the plausible first fix was the wrong layer, and the symptom pointed at a DEAD tool.** Three traps cost a reopen: (1) **The `erase` tool is a red herring.** The pathview has a full `erase`-tool delete path (`onEraseDomain`), but it has NO toolbar button and NO keybinding (the R-cycle is select→pencil→nick→paint; N/P only) — it's unreachable dead UI. The real delete gesture is **select-tool → Delete key → `onDeleteElements`**. The first investigation traced + even e2e-tested the erase path (which "worked" in isolation), proving nothing about the user's actual gesture. (2) **The first fix addressed a real but secondary factor.** The negative-bp stubs WERE drawn off the left edge by `_fitToContent` (a genuine bug, numerically confirmed: bp −17 at screen-x −37); fixing it was correct but didn't make Delete work, because the actual no-op was the parse. Shipping it before reproducing the EXACT gesture end-to-end caused the "still can't delete" reopen. (3) **The real bug was a `(\d+)` regex that silently rejects negative bp** — see LESSONS F5. Lesson: for a "nothing happens / silently no-ops" report, (a) find the EXACT code path the user's gesture takes (which tool/key actually fires — don't assume the obvious-looking one is wired), (b) reproduce it end-to-end FAILING before fixing, and (c) treat a plausible single-factor fix with suspicion until the real gesture is reproduced — `CLAUDE.md`'s "three-layer/topology bugs are usually multi-factor" applies to UI-state bugs too. The clean win: extracting all build+parse of the element keys into one round-trip-tested module (`element_keys.js`) means the negative case is now pinned and the format can't drift from its parser.

**Loop conventions banked at creation (2026-06-05):**
- **Repro before fix, ask before implement.** The two non-negotiables. A bug without a reproducing test
  is not ready to fix; a UX bug without the user's chosen target behavior is not ready to implement.
- **`rg`, not `grep`, on main.js** — grep's binary heuristic trips on some byte in the file and silently
  returns zero matches (carried over from the carve-up loop, where it cost ~5 tool calls).
- **`just lint` is Python-only** (`ruff check backend/ tests/`), currently ~38 pre-existing errors unrelated
  to frontend; a frontend-only fix has lint delta 0 by construction. No eslint config exists for the frontend.
- **`just smoke` is two gates** (console-error render + teardown) — run it for any DOM/scene/store fix.
- **Don't grow main.js** — see the prime-directive section in `issues_ledger.md`. If the buggy code is
  still inline, extract-then-fix (carve-up) or minimal-patch-then-log-as-extraction-target.

ISSUE-24 (2026-09-04): [x] Released animation job rows from the performance idle gate,
with a bounded fallback for background requests. Pending-list and timing regressions
pass; the ordered preparation/readiness follow-up passes 196 focused tests and two
isolated browser checks. Full validation details: docs/animation_trajectory_loading_audit.md.

ISSUE-25 (2026-09-11): [x] PEG inputs use sidebar tokens; 2 Playwright tests
cover contrast, real input, API review and wizard request propagation. Root cause:
PEG fields lacked the explicit styles present on adjacent surface fields; numeric
steps also disagreed with the existing density default and fractional charge API.
Initial fixture attempt bypassed normal file-open lifecycle and left Simulations
disabled; corrected with an isolated scratch file and teardown. Follow-ups and
validation limitations are recorded in docs/peg_coating_setup.md.

ISSUE-26 (2026-09-11): [x] PEG Live frontend/backend path implemented. Root causes:
explicit 409 rejection, PEG built without Python bindings, Live topology rewritten
from DNA alone, and trailing PEG particles incompatible with stock Live readout.
Bindings are isolated per process; topology and CM frames are preserved. Browser
fixture initially targeted the hidden legacy job list; corrected to use the visible
unified list. Real stepping is pending a user-opened test session; see docs/peg_live.md.


ISSUE-27 (2026-09-13): [x] First-save NAMD form reset reproduced in the requested
blank-file workflow and fixed in `md_jobs_panel.js`; no `main.js` change. Browser
coverage verifies first save plus actual draft persistence. The charged-wall
preparation audit separately exposed a rebuilt descriptor dropping charge and
temperature; the API handoff now applies those fields after the final rebuild,
with a regression at the molecular-builder boundary. Broader smoke remains red
on an unrelated mrDNA job-save HTTP 500 race; see `docs/namd_charged_surface.md`.

2026-09-14: [x] ISSUE-28/29/30: managed CUDA electrode library/restart initialization,
false native-process adoption and cadence-dependent screening metrics corrected.
Real Start-API pilot completed at 4 fs; longer runs remain visible under the source
nadoc. Regression and scientific-analysis tests cover the corrected contracts.
See docs/namd_electrode_gpu.md and workspace/electrode_gpu_screening_4fs_20260914/.

2026-09-20: [x] ISSUE-31: guarded the optional test bridge's secure-context UUID
requirement so it cannot prevent ordinary HTTP LAN viewing. Added unit coverage
and a real non-secure-origin Playwright project, including completed manual
performance capture. Both production browser projects pass; 6,692 frontend tests
pass. Cached host assets require restarting the test host and replacing its link.

## 2026-09-21 — ISSUE-32, ensemble submission context lifetime

Fixed as part of the Alpine periodic-image clearance gate. Root cause: closing the review cleared its shared context before the asynchronous ensemble submit branch read the partition. Capture the reviewed partition before teardown. The regression exercises the ensemble API call after disposal, including the new explicit clearance override. No alternate hypothesis pursued; `main.js` LOC delta 0.

<!-- ISSUE-31/32 below were independently assigned on the CPD branch; historical IDs retained. -->

2026-09-20: [x] ISSUE-31/32: preliminary cis-syn strand-builder integration removes
reactant planar C5 impropers and rejects bypasses of product coordinate placement.
Native builder duplex passes 1,000 minimization and 1,000 2-fs dynamics steps.
See docs/cpd_strand_builder.md. No main.js changes from this task (LOC delta 0).

2026-09-22: ISSUE-33 null tool draft guard implemented. Physical run exposed stopped polling, not an Undo mutation failure. Main.js LOC delta0 for this fix; regression sends null then valid draft through actual application handler. See .development-artifacts/vr-workflows/fit-undo-physical (failure preserved); validation follows in fit artifacts.

2026-09-22: [x] ISSUE-34: atomic private VR session publication and non-destructive status reads. Root cause: reader treated partial JSON as stale and unlinked a pathname concurrently being written. Deterministic publication/racing-reader regressions pass; physical commit/Undo passes after correction. ISSUE-33 also exercised by subsequent physical polling. Evidence fit-undo-atomic; previous failed attempts preserved.

2026-09-22: ISSUE-35: bounded read-only scene refresh retry after autosave revision advance. Mutation remains exactly once, stale snapshot remains rejected. First physical6HB failure preserved under sixhb-physical. Frontend main.js LOC delta0.

2026-09-22: [x] ISSUE-36: save acknowledgement carries atomic revision metadata, accepted only against the browser's matching preceding revision. Maintains lightweight response and no autosave-loop design replacement. Physical desktop6HB→VR6cells in same rotated frame→Undo→cadnano edit/save/reload passed; commit20.1s and Undo12.4s scene refresh remain performance debt. Main.js LOC delta0.

2026-09-22: [x] ISSUE-39: visible Tools→Extrude now supports empty-part configuration
and opens the paint tablet through shared initialization with radial activation.
Physical steady_fast VR-first menu/paint/wheel/Confirm/Undo/cadnano/save-reload passes.
Native36tests and26focused tooling tests pass. Existing framing helper now accepts
a visible-UI callback; regression rejects hidden semantic activation in that path.
Evidence: .development-artifacts/vr-workflows/menu-activation-validation.md.

2026-09-22: [x] ISSUE-40: settings pixel review found blank minus glyph despite valid
layout/interaction checks. Added horizontal stroke and nonblank/distinct-from-plus
regression. Root cause: font's fallback erased an unsupported character; geometry
checks do not observe label meaning. No failed alternative fix; discovered during
larger target work. Native36tests pass; settings-sign-steady full VR-first roundtrip passes56.3s;
submitted-eye image confirms minus signs on length/direction/size controls. Frontend main.js LOC delta0.

2026-09-23: ISSUE-41 opened by actual image review after a green combined workflow:
native whole-design review occupies82x64pixels and is largely end-on, while the
presence-only threshold passes. No framing fix yet; recorded as unresolved rather
than declaring visible debugging complete. Desktop geometry/edit/save-reload remains
validated. Native camera/bounds root cause needs measurement; no geometry change.

2026-09-23: [x] ISSUE-41 opt-in review now uses ordinary rotation/scale, both-eye
coverage/cluster/RGB checks and actual desktop pixel comparison. Original weak
view retained. A subsequent0%desktop match failure is retained separately; headed
demo explicitly reveals only its PID-verified native viewer, keeping thresholds.
Physical through-lens comfort and authoring-trace delivery remain open.

2026-09-27: [x] ISSUE-42 — assembly Simulations tab opening no longer flattens for
passive API reads; recommendation uses a valid GET and lightweight assembly facts.
Unified jobs resolve assembly identity without a loaded projection; NAMD source-path
wiring matches other engines. Tests and limits: docs/audits/assembly_simulations_20260927.md.

2026-09-27: ISSUE-43 — CanDo/SNUPI assembly execution uses a compact backend projection
and snapshot-based visualization. Root cause: a part-centric preparation/display
optimization assumed a live flattened part renderer; uncached full-topology fingerprints
on every FEM poll then competed with the solver. Reused the existing revision cache and
moved preparation/results off the event loop. Native BigO runs disproved the initial
missing/disconnected-mesh hypothesis (one connected 211,680-node mesh). A no-RMSF summary
also mistook unpaired terminal geometry for FEM nodes; corrected from axis records.
Evidence and gates: `docs/audits/assembly_fem_execution_20260927.md`. main.js delta 0.

2026-09-27: ISSUE-44 — Thermal reconstruction reused the expensive full display
pipeline for 48 frames while retaining only XYZ. Cache immutable per-job reference
geometry, batch bead reconstruction, preallocate numeric frames and stream JSON.
BigO two-frame comparison: 5.1–5.5× reconstruction speedup, <1e-12 nm coordinate
difference; full-job NMA speedup is not claimed. Progress and cancellation now
advance at each frame and persistence boundary. See the thermal optimization audit.

- 2026-09-27 · ISSUE-45 · Large completed CanDo results use bounded point/line
  rendering, compact transport, indexed cylinder joints, native-source visibility
  guards and cancellation-safe switching; metric graphs reuse compact scalars.
  [Audit](docs/audits/cando_visualization_guards_20260927.md). main.js Δ +3.

- 2026-09-27 · ISSUE-46 · Verify cached simulation fingerprint ownership with a
  weak reference; a recycled object ID cannot reuse a closed design's fingerprint.
  Deterministic regression reproduced the failure before the fix; 18 focused tests pass.

- 2026-09-28 · ISSUE-47 · SNUPI shares guarded large FEM views/metrics; bounded,
  indexed trajectory playback preserves scrubbing with cancellation/backpressure
  and GPU-buffer reuse. [Audit](docs/audits/snupi_visualization_guards_20260928.md).
  main.js Δ +1.

- 2026-09-29 · ISSUE-48 · Browser representation publication shares the complete
  identifier contract; native partial installs honor pre-axis availability.
  Desktop cylinder builder supplies native radius/topology/palettes. Sidebar
  hit-testing also supplies unpressed pointer rays. main.js Δ +1 (error logging).
  Root cause: duplicated allowlists diverged, while synthetic axes satisfied an
  incorrect presence check. Initial suspicion of unfinished Surface generation
  was disproved by completed export and a visible desktop Surface paired with
  repeated Full acknowledgements. [Audit](docs/audits/vr_representation_parity_20260929.md).

- 2026-09-29 · ISSUE-49 · Native atomistic bonds now share Full's lit cylinder
  renderer. Sidebar navigation follows the logical row list across viewport edges
  and uses shared easing/clipping; descendants indent by ancestry. A real GL
  removed-occluder control distinguishes cast shadows from diffuse shading.
  main.js Δ 0 for this change. [Audit](docs/audits/vr_shadow_scroll_20260929.md).

- 2026-09-29 · ISSUE-50 · Diagnosis only; OPEN. Real browser/ScryWrite loads
  measured 226/393/806 ms synchronous style application and a separate 112 ms
  Surface gap at 49.198%. Root cause of final stalls: geometry preparation and
  GL staging run on the XR thread before the existing frame timer starts.
  GPU priority alone cannot fix this path; the earlier gap remains unattributed.
  Added local phase/log diagnostics; no scheduling fix, main.js Δ 0.
  Three functional tours and native build passed; frame-comfort acceptance fails.
  [Research and evidence](docs/audits/vr_loading_stalls_20260929.md).

- 2026-09-29 · ISSUE-50 · Static CPU geometry/index preparation now runs on the
  parser worker; separate GL buffers upload in 1 ms / 256 KiB slices and activate
  after a zero-timeout fence poll. CPU/GPU caches have inactive budgets, with CPU
  retirement off the XR thread. Finer tracing isolated the earlier gap to avatar
  publication (335 ms); a coalescing writer removes that disk wait from XR.
  Object-ID table growth and redundant static shadow draws were additional costs,
  addressed with bucketed IDs and shared shadow reuse. Clustered slow frames
  select a lightweight loading scene. Native traces and SteamVR compositor timing
  now gate the registered loading-performance tour. Retained failed trials caught
  startup availability, memory pressure and frame-observation transport problems;
  none are erased or relabeled as passes. main.js Δ 0.
  [Implementation and measured limits](docs/audits/vr_loading_frame_delivery_20260929.md).

### ISSUE-51 — post-load motion regression investigation (2026-09-29, unresolved)

Reverted speculative shadow/lighting changes and the loading patch's shadow cache
following the user's confirmation that the earlier renderer performed well.
Kept staged loading/async publication; isolated legacy/staged upload comparison
has identical pixels and comparable GPU timing. Stick motion passes the final
initial profile; Ball & Stick still fails. Do not describe this as a completed
performance fix. [Evidence and testing limits](docs/audits/vr_motion_regression_20260929.md).

2026-09-30 — ISSUE-52: animation sharing exposed a pre-existing NaN in
`_refreshSlabConnectors` when decomposing a zero-scale slab matrix. Pinned with a
failing renderer test, then kept collapsed connectors finite and hidden. Visible
molecular coordinates and topology are unchanged. Shared-animation browser
coverage exercises the construction-stage transition that exposed the defect.


- 2026-10-04 — ISSUE-54 [x]: pattern API wrappers propagate rejected requests;
  panels retain their preview and show the error. Regression coverage:
  `frontend/src/api/pattern_requests.test.js`, `linear_pattern_panel.test.js`.
  No additional main.js logic (linear-tool feature wiring is +2 LOC).
2026-10-05 — ISSUE-59 / ISSUE-60: OPEN intake from the Benchy native-tool
benchmark. All-helix cluster creation left a saved lattice frame referring to a
removed default cluster; fresh-cell extrusion left 714 of 1,157 helices outside
the placement cluster, so its Move affected only the initial 443. Product code
was not changed. The benchmark workaround preserves the placement cluster and
patches its membership through the native cluster API. Corrected native reload
and occupied-domain validation match all 11,984 reference cell-slabs, with zero
missing/extra/off-grid intervals. [Observed state and retained failing file](.development-artifacts/benchy_20261005/cluster_bug_evidence.json).
Regression tests and product fixes remain pending; `main.js` delta 0.

2026-10-05 — ISSUE-55: fixed native print/atomistic export failing at strand
702. Shared unbounded alphabetic chain labels preserve A…ZZ exactly and agree
with PDB cycling plus NAMD package/playback maps. All 24 focused chain tests
pass, including a real 3,062-strand build and legacy semantic component IDs;
existing NAMD segment-order, streptavidin preparation, and large-design PDB
connectivity regressions pass. Native 3,062-strand Benchy STL export completes
in 32.3 s with the initial surface settings. Identity
bookkeeping only; molecular geometry is unchanged. `main.js` delta 0.
Final native Benchy export (0.30 nm grid, 0.90 nm probe, 60 mm target) is one
watertight connected surface: 1,446,424 triangles and zero boundary, nonmanifold,
degenerate, or inconsistent-winding elements. Final `just test-smart` decision
FAST: 9,605 passed, 93 skipped, one unrelated existing loop/skip bit-identity
failure (1.11e-16), reproduced independently against unchanged geometry code.
Full-suite debt remains deferred; exact output is retained in
`.development-artifacts/benchy_20261005/test_smart_final.log`.

2026-10-05 — ISSUE-56: Extrude dismissal now follows acceptance of the Confirm
intent, retaining the asynchronous submission until matching feedback arrives.
Retry republishes a consumed validation plan, and Undo uses its saved feature
instead of the user's later selection. Shared layout auditing now checks text
against neighboring text/features and reserved columns; the prior bounds-only
checks missed real overlaps. Transparent MSAA text was attenuated twice, while a
width-capped cache retained the old height and filtered wide-panel text excessively.
Corrected alpha handling and cache aspect restore lettering; first allocation also
preserves the caller's framebuffer. Failed observation hypotheses (window-size
clamp, framebuffer binding and whole-panel pixel counts masking faint letters)
are retained in the [audit](docs/audits/vr_menu_formatting_20261005.md).
425 rendered states and 12,001 layout cases pass; full frontend suite 7,375 passed,
1 skipped. `main.js` delta 0. Reopen count: 0.

2026-10-05 — ISSUE-57 intake (OPEN): right-wheel testing exposed a stale Nick
pixel projection (+Y versus the renderer's -Z), now corrected with a pure test.
The broader scissors/glow visual workflow still fails; no rendering fix is
claimed. Target selection, wrist/contact adjustments, mirror size and grip zoom
were insufficient; those experimental probe changes were removed. Evidence and
unchanged pixel thresholds are recorded in ISSUE-57 and
`.development-artifacts/vr-edit-wheel-20261005/`. Wheel behavior is validated by
its own four-profile stereo tour and separate document-history workflow.

2026-10-05 — ISSUE-58 intake (OPEN): the Ligate browser tour reaches the new
right-wheel mode and rejects the invalid release, then its stretched-preview
pixel gate fails (3/7 left, 2/7 right/mirror). Production preview code and the 0.7
coverage threshold are unchanged. Evidence is retained under
`.development-artifacts/vr-edit-wheel-20261005/ligate/`; commit/save was not reached.

2026-10-08 — ISSUE-66 fixed during sweep loop/skip support. Root cause: marks were
cleared on the calculation copy but merged onto the uncleared committed design.
The commit now clears active bundle marks before replacement and rejects stale
revisions. Repro/regression: HC/SQ seed an illegal old end mark, realize, repeat,
undo/redo and revert; reference/overhang/linker preservation stays covered by the
existing suite. 14 focused sweep-realization tests + 75 existing loop/skip tests
pass. No discarded hypothesis; no production molecular-placement changes.
`main.js` delta 0. Reopen count: 0.
App validation: Add Loops/Skips menu, undo/redo, complete `.nadoc` export/reload
passed (1 browser test); screenshot inspected and test workspace artifacts removed.
`just test-smart` selected FAST: 10129 passed, 19 skipped, 21 failed, 4 errors;
failure signatures exactly match the preceding sweep-wizard run. Timing guard
reports 20 unrelated existing tests over 5 s, none from the new sweep suite.
Full suite deferred by the session gate. Lint retains the existing unused `Path`
import in `tests/test_cpd_cube_validation_v6.py`; `git diff --check` passes.

2026-10-07 — ISSUE-59: fixed SNUPI coordinate-field parsing after the platform
comparison exposed 1,194 silently omitted nodes. Adjacent signed 8-character
coordinate fields now use a fixed-width fallback; legacy whitespace input is
preserved. Added a regression using actual platform output. No molecular
coordinates or topology are changed.

2026-10-08 — ISSUE-67: construction animations now traverse intermediate states
and render their historical DNA/particle topology. Explicit WebCodecs timestamps
replace wall-clock WebM capture in both exporters. Root cause: endpoint-only
planning and live-topology/live-recorder assumptions were insufficient for a
historical build movie. The closer Voltron check additionally exposed ordinary
snapshot replay retaining future nanoparticles; a failing browser assertion and
backward/forward backend regression pinned that defect before the replay fix.
No molecular-placement formula or golden changed. `main.js` delta +2 wiring lines.
Reopen count: 0. Validation evidence: `.development-artifacts/build-animation/`.

2026-10-08 — ISSUE-67 follow-up: sweep construction animation reveals origin to
path end in Full/Cylinders/atomistic/surface displays; reverse playback retracts
from the end. Empty initial surface preparation is handled explicitly. Headed
preview and decoded video verified; source geometry/topology stays unchanged.

2026-10-11 — ISSUE-69 intake: isolated untouched HEAD reproduces the Extrude
menu-spacing failure seen while validating VR Join. No fix attempted; root cause
remains the mismatch between Extrude bounds and the existing rail oracle.
Baseline proof is retained in `.development-artifacts/vr-join-20261011/`; exact
generated baseline sources/binary were removed after verification.

2026-10-11 — ISSUE-70 intake: the headless braced-corner investigation reproduced
Free Join selecting extra adjacent side attachments whose connector-only cycle
cannot be nicked without breaking requested joins. Native realization correctly
rejects the set; precursor matching lacks that feasibility constraint. Same-pose
diagnostic subsets and a narrower-reach public Join succeed. No product fix or
scientific rule change attempted. Evidence and reproducible authored fixtures:
`.development-artifacts/braced-corner-20261011/`. `main.js` delta 0.

2026-10-11 — ISSUE-71 intake: strict native export/import validation of the braced
corner preserves topology and rigid poses but changes flexible-connector anchor
orientation and bead positions (maximum observed 1.97979197 nm across two
processes; eight connector nucleotides, zero nonconnector nucleotides). Direct model
serialization had passed; exercising the real import path exposed the defect.
Before/imported models and per-nucleotide evidence are retained under the same
artifact root. No geometry repair attempted; native persistence remains an
explicit failed gate for promoting this prototype to a reusable primitive.

2026-10-12 — ISSUE-72 fixed: range configuration now publishes atomically after
clearing old playback state. The new acknowledgement can no longer carry the
previous range. Fifteen focused trajectory/bridge tests pass, including a new
notification regression; native/live range-wheel evidence is retained under
`.development-artifacts/vr-range-wheels-20261012/`. `main.js` delta 0.

2026-10-12 — ISSUE-73 fixed: removed adjacent-sidebar closure during simulation
snapshot adoption and separated representation changes from simulation teardown.
Shared physical-coordinate representations preserve scalar colors; exact sampled
source IDs drive MD/oxDNA atoms. FEM/CG atomistic requests are serialized and stale
responses are discarded. Compact sources retain nucleotide identities and publish
their current frame on representation changes. An initial live failure exposed a
missing switcher helper export; the export and regression were added. Another
capture attempt was invalidated by a development reload while source was edited;
subsequent live validation freezes the source. Evidence and limits are retained in
`docs/audits/vr_simulation_representations_20261012.md`. `main.js` delta −12.

ISSUE-74 (2026-10-12): simulation trajectory popup controls now precede disabled
background rows in hit testing. All ten numeric keys have real-ray regression
coverage. The initial live loop check exposed this while seeking the selected
range end; its failed evidence is retained under `vr-trajectory-loop-20261012/initial`.

2026-10-13 — ISSUE-79 fixed: selecting an assembly part no longer seeds an
animation or PATCHes its source. Shared versioned Design reads, stable selection
rows, queued source-aware renderer refreshes and direct color-buffer repainting
remove redundant work. Backend indexed-sweep axis sampling is batched with exact
coordinate parity; compact geometry and unrelated cache entries are retained.
A review caught a stale authoring callback during forced refresh; a loading guard
and three regressions close that race. `main.js` delta 0 (two wiring substitutions).

Full Benchy app validation retained 462,002 nucleotides and 91.75 million triangles:
selection 64–449 ms, color change 290 ms versus 10.39 s, 32 fps during idle, no
basic-action/idle rebuild or busy overlay. Cold opening and explicit representation
builds remain slow; their measured limits are recorded rather than hidden.
Frontend: 7,917 passed, 1 skipped, followed by 33 affected tests passing after the
refresh guard. Focused backend: 48 passed. `test-smart` FAST: 10,542 passed,
22 failed, 21 skipped, 4 collection errors; missing prerequisites and four
HEAD-reproduced failures are documented, with the deferred FULL notice, in
`docs/audits/benchy_full_performance_20261013.md`. Reopen count: 0.
App smoke: 23 passed; native placement gate clear; changed-file Ruff clean,
repository lint delta zero. Original Benchy hashes and test cleanup verified.

2026-10-13 — ISSUE-80 **PARTIAL: implementation and validation complete; cold-load/GPU targets unmet**.
Lossless native compact/NDGB transport, versioned source/readiness reuse, exact
hull-work reuse, prepared CG primitives/lazy indexes, ordered optimistic saves,
inactive UI gates and lazy connectors remove repeated work. Base authoring stays
separate from overridden display Designs. Source failure/retry and accepted API
snapshot provenance are regression-pinned; independent reviews are clean.

Final release Benchy (seven sources, 462,002 nucleotides): 34.203 s navigation /
29.669 s import→paint, 33.0 ms first Full, 93.8 ms Beads, 76.4 ms Cylinders,
35.4 ms restored Full. All seven close, 91,752,688 triangles/35 calls, steady Full
21.075/21.597 FPS; Cylinders 59.460. Final hinge500 (one repeated source):
10.481 s navigation / 6.119 s import→paint, 485.2 ms first Full, 1,058.8 ms Beads,
689 ms Cylinders, 205.8 ms restored Full. All 500 close, unchanged camera/LOD,
1,517,472,000 triangles/five calls, Full 2.363/1.855 FPS; Cylinders 59.210.
Both have no errors, Design PATCHes or context loss; only Benchy startup geometry
has a busy overlay. Hashes and cleanup pass. These are single document/browser/
source-cold runs, with actual option click→rendered frame excluding menu travel;
they are not compositor/input-to-photon or repeated-median measurements.

The release hinge first-Full screenshot shows Cylinders selectors despite Full
store/renderer evidence. This cause was not reproduced: the separate controls
run checks all 500 row selectors after every phase with zero mismatches and a
Full screenshot. Its 5.964 s import / 233.8 ms Full remains diagnostic; primary
release values above are retained. One hinge readiness GET is pending at close;
backend cancellation is absent. The intermediate readiness profile is still
39.604 s after map/flatten reuse, before lifetime cleanup. No claim that cold
readiness, GPU scale, or screenshot presentation is solved is made.

Final frontend: 8,075 passed, one skipped across 697 files / 314.18 s.
Post-fix smoke: 23 passed / 2.6 minutes. Final FAST: 10,603 passed, 22 failed,
21 skipped, four collection errors / 191.09 s pytest / 203 s guard. Failure/error
IDs are identical to baseline; zero individual timing violators remain, but the
203 s aggregate exceeds 90 s. FULL deferred notice is retained verbatim in
`docs/audits/assembly_loading_performance_20261013.md`; budgets/markers unchanged.
Scoped Ruff passes 23 changed backend/test files. Native gate and diff clean;
`main.js` net −2. Aggregate lint retains two pre-existing unused imports; memory
lint retains four unchanged-file errors/60 warnings. Focused counts, overlap,
exact transport/hull parity and commands are in the audit.

Final cleanup preserves exact 205 project-store paths, five document IDs and
nine original source hashes; all test prefixes and bridge credentials are empty.
All 109 frozen app/test hashes match, with no added/removed scoped files. Final
measurements, controls diagnostic and smoke are complete; earlier runs remain
checkpoints. Reopen count: 0. PARTIAL reflects remaining performance limits and
the unresolved screenshot observation, not unfinished acceptance work.


2026-10-13 — ISSUE-76 fixed for normal-launch integration. Root cause: the optimized
viewer and final recorder were validated through a private diagnostic launch, while
the ordinary backend still selected the pre-work executable without the capture
binding. The new torso recording therefore exercised the old path. The failed
assumption was that a private runtime success implied ordinary user launch was
deployed; exact executable/capture provenance now prevents that confusion.

Owner-controlled configuration selects the versioned Archive build and capture
layer. Normal launch creates inspect/journal resources, uses markers only while
journaling, preserves physical haptics/Desktop/touch input, reports fresh recorder
readiness, and requires valid diagnostics before claiming completion. No scientific
geometry or current document content changed; Join regression evidence is retained.
A normal-menu recording and final physical-inspect recording each saved 179 final
images, zero drops, with full pixel and durable direct-I/O audits. Final calibrated
decoding joins all 716 eye images to strict CRC/full-session/eye/frame identities:
179 unique consecutive IDs per eye per clip, no repeats/gaps/regressions, both eyes
matching. Wide ROI and first tight-ROI failures remain preserved. The bounded
component filter skips only already subminimum components before the same 64-cap;
all other thresholds are unchanged. Menu frame 0 alone calibrated the tighter ROIs;
178 later menu frames and all 179 physical-inspect frames were held out.

Final viewer 378253/start 96081361 uses native v2 hash 1e830a7f...; original Stick/Flex
source placement restored within 2.4e-7 m, grouped/opaque defaults active, one-shot
restore setting removed. Both controllers were untracked. Browser reattachment is
now independently verified: same PID/session and exact presentation, actual feed
sequence advances, unchanged geometry payload/scientific export, and Help's Exit VR
toggle enabled. The stale restore dialog was cancelled without reimporting content.
NADOC is now foreground; desktop 3D during VR retains its original true setting.
Earlier capture cadence does not certify this combined foreground workload.
SteamVR process and four saved global VR config hashes are unchanged.

101 focused backend checks, four readiness cases, five native v2 checks and 175
tracking/decoder checks plus 24 subtests passed. Initial FAST: 10,830 passed, 14 failed, 8 errors, 92 skipped, 2,500 warnings.
Three Unix-socket failures pass with short Archive paths. Final FAST: 10,832 passed,
11 failed, 8 errors, 92 skipped, 2,500 warnings; pytest 134.82 seconds, guard 137 seconds,
five timing overruns. psfgen and CPD failures remain recorded. Focused success does
not clear broad/full-suite debt. Reopen count: 0.
ISSUE-76 closes the deployment gap only; worn-headset doubling remains MV-44.
Evidence and rollback:
[normal-launch integration](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/launch-handoff.json),
[recording review](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/index.html),
[calibrated identity proof](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/postfix-summary.json),
[test triage](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/test-smart-triage/triage-report.txt),
[rollback](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/rollback-plan.txt),
[browser reattachment](.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/browser-reconnect/verification.json).

2026-10-13 — ISSUE-77 investigation checkpoint, OPEN. The user reports that
doubling is substantially reduced, with remaining menu/hover-associated lag.
Request 962531370889719 retains all 179 final presentations with zero capture
drops. The complete bounded-follow decode joins all 358 eye images: 144 distinct
submitted images and 35 reused-image pairs per eye, no unknowns/gaps/regressions.
The original fixed-ROI 313/358 joins and 22-pair lower bound are retained. The
retrospective follow trial changed no CRC, contrast or bit/geometry thresholds;
it does not constitute a separately acquired validation clip.

The longest measured input/actions stage is 1.61 ms versus 20.88 ms inside
xrEndFrame. All 242 journal rows have head/hand tracking flags 15, which excludes
no unflagged jitter. Both menus are logically open with varying visible coverage.
This evidence locates host waiting without proving its cause; older journals
have no per-frame hover/haptic timings. Native inspection identified synchronous
event-triggered haptic calls, hover-sensitive texture caching, backdrop copies and
frosted shading as measurable pathways. No behavior/performance fix was applied.

The new bounded capture-only diagnostics and summarize-interactions reader expose
actual API dispatch/results, hover changes, texture/cache work and per-eye menu/
backdrop host spans. Missing legacy fields, truncation, overflow and clock errors
remain explicit. Haptic dispatch does not independently establish actuator motion;
host GL time is not GPU time, and draw counts are not on-screen coverage.

Six native checks passed, including actual GL hover/cache changes and OpenXR
dispatch/result spies; 45 reader tests and 69 marker tests passed. Normal launch
deployed native SHA256 65bcd41e1de02d1d6271c19a1aa7d04683087358eb0dd78a17d4eb282cb8a4d3
as physical-inspect viewer 545874 with the existing compositor. The real browser
reattached; scientific data and restored placement are preserved. Closed-menu
recording 963838453284914 saved 179 frames, with 288 diagnostic journal rows,
zero UI clock calls/errors/overflow. The first check mistakenly required positive
UI clocks; that failed assertion is retained, then corrected without recapture or
native change. This is a zero-activity integration check, not live physical hover
validation. The reload closed the menus and did not restore their previous positions.
Reopen/place them for a new worn-controller reproduction; ISSUE-77 and MV-44 remain
open. Existing broad-test failures and timing-guard debt are not cleared.

Evidence: [native audit](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-audit.json),
[complete identity proof](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/recording-analysis/identity-follow-summary.json),
[native freeze](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-freeze.json),
[closed-menu live check](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/live-capture-proof/verification.json),
[retained initial verification failure](.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/live-capture-proof/initial-verification-failure.json).

### ISSUE-78 — VR Join duplicate preview lifecycle (2026-10-13)

Fixed in `vr_join.js`; no `main.js` growth. Root cause: duplicate preview event →
unconditional checking publication → unchanged transform deduplicated → no new
validation → Apply stayed disabled. The earlier browser dispatch test omitted
this native event order; physical playback exposed it. Added a failing regression
then reused the valid result for an identical current pose. Full frontend suite:
7,906 passed, one skipped. Broader validation and frame-rate limits are retained
in `.development-artifacts/vr-join-20261013/verification-summary.json`.


2026-10-14 — ISSUE-81 root cause: variant-blind `getattr` in two full-history scans repeatedly invoked Pydantic missing-field handling; the cluster-restoration helper additionally copied an unchanged object. No speculative algorithm replacement was attempted. The pre-existing benchmark first required a response-contract adapter repair; its frozen reconstruction functions remain unchanged. The unchanged timing gate and all 14 full-output comparisons pass after type discrimination. Evidence is in the feature-history audit directory.


2026-10-15 — ISSUE-82: broad regression exposed five refinement failures because an extracted helper still read/changed the active session; scaffold selection now sequences its input design only. Native lifecycle tests exposed missing linker-patch/loop-clear log variants and framed-copy frame references; those are recorded/preserved. Generated recovery exposed an earlier absolute membership setter overwriting a newer extrusion snapshot; payload-aware membership restoration fixes both recovery modes. A small CPD conversion took ~70 s; its method is explicitly unverified and blocked before the solver on proof paths, rather than weakening deadlines or claiming snapshot replay is proof. See feature-history implementation audit for remaining scope and measured validation.

2026-10-15 — ISSUE-83: extracted `part_replacement_transaction.publish_replacement`
under the existing state lock. Failed prepared-model commits now restore the exact
source object, bounded stacks, revision and request context, including cancellation
after revision publication. A ready repair remains available for a successful retry.
Eight transaction and fifteen repair-job tests pass. One undo copy remains; no
geometry computation or additional proof was added to ordinary publication.

2026-10-15 — ISSUE-84: raw-envelope budget checks omitted optional fields that
Pydantic adds on serialization. A load-admitted draft therefore could not
survive the unchanged snapshot/load validator. Admission now also checks the
canonical stored form; no size limit or snapshot validator was weakened. The
repro preceded the fix (three red / one control), then all 35 schema, 18 API
and 16 persistence cases passed. Retained-draft performance is measured in a
separate rerun; the aborted benchmark is preserved rather than called a pass.

2026-10-15 — ISSUE-85: bind every publishing evaluation to the actual host
session captured alongside source/revision. A new session cannot reuse the old
handle even if its public revision and source object match. Trusted guards use
a noncreating session lookup so stale publication cannot reopen a closed tab.
All 21 session cases and the affected ordinary lifecycle files pass. This closes
the evaluation lifetime gap; it is not the broader strict automation policy.

2026-10-15 — ISSUE-86: the actual JavaScript action/JSON transport collapsed
authored integer-valued floats, contradicting the planner's exact old-value
comparison. The two HTTP regressions failed before the fix (2.71 seconds,
HTTP 409 for diameter and pose). A bounded canonical JSON encoding now travels
with the displayed old value and restores it before action construction; it
persists through draft reloads. This encoding grants no authority: unchanged
strict conflict/identity checks and native regeneration still decide acceptance.
Malformed, duplicate-key, nonfinite, over-depth, boolean/number and aggregate
budget cases are covered. All 280 focused codec/transport and related repair
regressions pass; full desktop integration remains separately tracked in ISSUE-87.

2026-10-15 — ISSUE-87: desktop repair integration assumed the commit API returned
a full model, but the actual contract returns only a publication receipt. Retain
that receipt separately from display refresh and bind all refresh reads to the
original document/revision/session before syncing geometry. First full Vitest
also exposed a null prior-summary dereference in the new metadata adapter (six
failures; 8,155 passed and one skipped). Corrections and focused regressions are
in progress; no green integration result is claimed yet.

2026-10-15 — ISSUE-88: replaced lossy document-cache filename sanitization with
exact bounded identity admission. Unsupported IDs cannot alias valid files or
address the cache root/parent; strict HTTP refuses them before body acquisition.
Autosave reports unsupported IDs and continues valid documents. Baseline29failed/
9passed; final122 focused cases pass. Existing files and pruning are unchanged.

2026-10-15 — ISSUE-89 identified an admission/execution mismatch: dependency and
scoped replay exclude inert generator annotations, but ordinary strict native
builders still receive them. The isolated valid-gold cold-proof dossier failed
five cases with 11 controls passing in 3.68 seconds, including a real spawned
worker. The shared execution boundary now excludes only `_generator` after the
existing scope handoff, retaining recorded metadata and all input/identity
guards. Corrective validation passed all 16 annotation cases and 377 related
invalid-input, draft, source, scope and native-particle regressions (393 total).

2026-10-15 — ISSUE-87 fixed: committed and uncertain publication survive failed
display/transport, exact original-document revision/session checks guard refresh,
and default-document null maps only to the explicit server `__default__` sentinel.
Final86 focused tests and full8,181 passed/one skipped (708 files,309.16s).
No app/smoke/headset validation; MV-45 remains pending because Archive is absent.

2026-10-15 — ISSUE-91 API correction: physical input freshness is now explicit
in oxDNA/NAMD list/detail responses. A matching legacy partial fingerprint stays
unknown; known comparable differences are stale. No extra model/file work or job
mutation. 59 focused cases pass; obsolete legacy MD fixture repaired with paired
legacy/native assertions. Shared frontend labels subsequently passed 39 focused
and 8,192 full cases with one skipped (`6abb5dde`; API `764b413b`). Full receipts,
projection qualification and MV-46 app validation remain open; no app check is claimed.

2026-10-15 — ISSUE-90 pending NP deletion: the original global applied-version
sync erased an unrelated legacy direct-binding marker. The parent recorded the
49-case pending-native dossier red (31 failed/18 passed, 3.29 seconds), including
the actual deletion defect. Pending deletion now removes only its selected
version in native and compatibility paths. Native metadata inputs, owner checks,
atomic recording, nested ownership budgets and context/failure regressions passed
the parent's final 66-case run (4.20 seconds). Editing regressions passed 95 cases
(3.58 seconds), including seven identity-policy cases: 161 distinct green cases.
Thirty-repeat measurement passed all ten cells/five native cold proofs, with
cleanup; latency remains unqualified (native request/lock/light maxima
88.57/82.35/86.30 ms). Initial larger-fixture cold capture refusal remains in the
evidence. No app validation is claimed. Applied geometry is unchanged.

2026-10-15 — ISSUE-92 tests-first application ownership correction: root recorded
eight failures in 2.85 seconds across stale active constraints, unrelated legacy
binding preservation, surface-carrier identity and bound-handle selection. The
root cause is duplicated lifecycle state maintained separately from native
relocation: the geometry/domain moved, while the surface carrier and inactive
constraint fields did not; a global version-only sync also overwrote unrelated
owners. The narrow correction updates only affected ownership, clears inactive
constraints and explicitly excludes bound handles from free selection. Existing
register/relocation/restoration formulas and numerical pins are unchanged. Root
validation passed 181 distinct cases, after strengthening one stale status-only
assertion to the existing complete typed 422 diagnostic. No new native applied
contract or app check is claimed. No alternative geometry fix was attempted.

2026-10-15 — ISSUE-93 private DNA comparison cleanup: a shared-template disposal
regression exposed Three BufferGeometry's aliased userData on a geometry clone.
Detaching the private clone's metadata preserves the shared native template.
Added concurrent ordinary-scene identity/matrix/metadata survival assertions;
migrated obsolete constructor regex checks into actual buffer behavior. The
corrected 11-file run passed 195 cases in 3.97 seconds; real Python→Node packets
also passed. Full frontend passed 8,291 cases (one skipped) in 314.43 seconds; resource and
app qualification remain pending.

2026-10-15 — ISSUE-94 strict cold DNA decoding: the actual-byte benchmark found
that nested Design validation leaves Helix's forward-reference serializer deferred
until direct construction. A fresh-process minimal diagnostic reproduced the
MockValSer failure and confirmed schema initialization resolves it. The strict
boundary now resolves the existing schema once; pinned model/engine files remain
unchanged. Independent cold serialization, spawned DNA proof and controlled decode
cancellation pass within 115 distinct focused cases (one incomplete expected
proof fixture corrected). Actual HTTP measurements remain pending.

2026-10-15 — ISSUE-95 oxDNA copy input preservation: add the existing packaged
sequence-parameter filename to Copy Job's file set. Tests verify exact independent
bytes, stage rendering and honest legacy absence alongside the existing seed,
protocol and lineage contract. Initial present-file test failed as expected; both
copy cases plus 42 related physics/freshness cases now pass. Complete physical
input receipts and immutable preparation remain separate work.

2026-10-15 — ISSUE-99 focused grouping fix: ordinary and headless group creation
now always publishes one versioned `cluster_create` entry through the shared
pure builder and existing lock-owned replacement transaction. `log=False` is
accepted but cannot suppress recording. Historical cursor/sub-cursor input
refuses explicitly before allocation rather than silently truncating history.
Source, validation, undo, revision and failure checks stay inside one owning
lock; no nested `state.set_design`, full history proof or topology reconciliation
is added. Missing legacy roots remain unverified. The first green focused run passed
101 cases with 108 warnings in 5.57 s; the group file then passed 16 cases with
16 warnings in 2.88 s after adding the nicks→group→nick ordering regression.
There are 102 unique passes across these overlapping runs, not 117. Two old
tests requesting unlogged grouping were updated, retaining an explicit removed
receipt negative. `main.js` delta is 0. No app, broad-suite or latency
qualification; MV-48 remains open.

The same checkpoint reproduces ISSUE-100 rather than fixing it: ten bend/twist
tests include direct-edit controls and explicit assertions that the current
preview sequence removes the committed overlay before Apply, and that Cancel's
seek changes undo/redo. Apply refuses the resulting source correctly. The next
G1 increment must isolate preview state; do not weaken source proof to accept
the polluted document or preserve these characterization expectations as the
desired user contract.

2026-10-15 — ISSUE-101 forced-ligation recording: move source selection, endpoint
label/response scope and native building into one lock-owned minor transaction.
The shared builder preserves geometry and the recorder still snapshots,
reconciles and retries once. The red dossier reproduced three defects; all 107
related cases, including 14 new cases, now pass. The combined run's two preview-fixture
failures and corrected rerun remain in the
[continuation evidence](docs/audits/feature_history_20261014/validation_geometry_integrity_continuation.json).
No app, broad-suite or performance claim; MV-48 remains pending, `main.js` delta
is zero, and nick/resize/auto-crossover follow-ups remain open.

2026-10-16 — ISSUE-105 intake (open): historical bend/twist group controls do
not reliably update affected-helix membership. The private preview retains
native behavior and advertises group retargeting as unavailable. G2 must use
the existing prefix plane/scope resolvers and align preview, publication and
cold replay; this checkpoint does not change molecular calculations.

2026-10-16 — ISSUE-105 backend correction and gated history editor: actual group
selection changes now use existing selectors against the owned prefix. Unchanged
groups preserve historical explicit membership, and old commands replay unchanged.
The complete private control validator, plane editor, popup and viewport connect
through the real feature editor behind a default-false gate. Failures preserve
inputs, reversed inputs overwrite prior drafts, and explicit status/refresh
actions avoid a second publication. Native source tests exposed ISSUE-106's
pre-existing invalid all-members grouping; it remains separately open for a
compatibility-aware correction. See [checkpoint evidence](docs/audits/feature_history_20261014/validation_deformation_history_editor.json).
Both rollout gates remain closed and MV-48 remains open; no desktop or latency
result is claimed.

2026-10-16 — ISSUE-108 intake (open): native crossover growth reconstructs
`Helix` with an incomplete field list; batch growth can use original opposite
endpoints outside the final domain's range. Native controls reproduce the lost
metadata. U9's private organization adapter refuses the affected case before
native work; algorithms and legacy behavior are unchanged. This is containment,
not a fix or new milestone. The 752 focused U9 passes and remaining acceptance
are recorded in [U9 evidence](docs/audits/feature_history_20261014/validation_group_geometry_lineage.json).


2026-10-16 — ISSUE-110 Move Apply acknowledgement: extracted explicit-placement
commit retains refused/newer input and returns accepted legacy partial results.
Organized parts use one native batch publication with one undo/revision and
matching geometry, avoiding a second client transform. Current failures retain
the editor; reset retires old pending state. Actual factory/API/tool/native tests
and observed failures are retained in [U12 evidence](docs/audits/feature_history_20261014/validation_group_placement_ui.json).
The early InvalidURL factory mock failure is not a claimed behavior reproduction.
Public gates remain false; desktop/latency and earlier move editing stay open.


2026-10-16 — ISSUE-111 visibility queue review correction: bind rollback to each
save's dispatch revision and isolate pending counts/hydration by reset generation.
Regression cases cover successful earlier save followed by latest rejection and
same-ID reload while a prior save is held. No persisted schema or topology change.
See U12 evidence; this correction predates release and adds no milestone credit.

2026-10-16 — ISSUE-112 deformation opening lifecycle: reset during held Prepare
now retires the local opening immediately. The observed-open transition excludes
the controller's initial invalidation, and the generation rejects late old
responses/finalizers after a new tool opens. Meaningful failing regression and
passing focused correction are in [U13 evidence](docs/audits/feature_history_20261014/validation_deformation_creation.json).
This changes no geometry formula and earns no separate milestone credit.


2026-10-16 — U14 visibility integration: ISSUE-113 removes per-strand geometry
rescans by using the existing effective mask; ISSUE-114 applies endpoint masks to
cached saved Join lines without rebuilding them; ISSUE-115 settles visibility
before explicit Save/export and guards document ownership through asynchronous
reads/writes. The unused duplicate client exporter is pruned. ISSUE-111 reopened
once: two refused queued writes restored an unacknowledged intermediate state;
rollback now uses the last accepted checkpoint. Earlier one-success tests did not
cover this failure combination. Tests-first failures and final evidence are in
[U14 evidence](docs/audits/feature_history_20261014/validation_group_visibility.json).
No additional milestone credit or desktop qualification is claimed.


2026-10-16 — ISSUE-116 schema compatibility correction before U14: default model
serialization would add an empty presentation list to old sealed bytes. Preserve
the old canonical encoding with explicit empty-only field omission and the old
strict empty-state digest after validating the new field. Three observed red
canonical/stored/spawned recovery cases guard the fix; no relaxed decoder or
rewritten source evidence is used. This was discovered by tracing the actual
recovery equality check, beyond ordinary .nadoc roundtrip tests.


2026-10-16 — U16 / ISSUE-119: output-identity preservation also retained a derived
continuation source receipt after source input changes. Bind the edited receipt
to the proved prefix after identity preservation; never infer it from the latest
displayed geometry. Shared owned publication and typed reference failure keep
rejected edits atomic. The seven-family editor is one FH-21 milestone, not extra
credit for this fix or the shared-host extraction.

2026-10-16 — U17 / ISSUE-120–122: the gated Sweep history editor now distinguishes
native input replay from legacy snapshot rebasing. It identifies typed downstream
nick dependencies and preserves rejected drafts. Shared Apply rechecks its final
deadline after preservation. Private picker ownership blocks hidden legacy
authoring and prevents old cleanup from hiding a newer view; preparation can be
cancelled before the panel opens. Existing molecular algorithms and legacy
recovery contracts are retained. These corrections earn only the fixed FH-22
milestone when its full software acceptance passes; desktop remains FH-27/MV-51.

2026-10-16 — U18 / ISSUE-123–124: share strict placement/nucleotide/reset history
binding, correct the consumer-reference identity role and stale reset receipt,
and preserve exact typed failure attribution with atomic publication. Native
replay reuses its occupancy predicate without an added successful-target scan.
The standard regression command exposed an import-time randomized Sweep test ID;
replace it with a deterministic value. Archive-backed collection and FULL debt
remain explicit. FH-23 stays open; these fixes add no completed milestone.

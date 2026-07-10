---
name: project_simulate_panel_overhaul
description: "Simulate-panel UX overhaul — one collapsible Simulate section, static engine headers, context Run/Stop/Resume, master Job status card"
metadata: 
  node_type: memory
  type: project
  originSessionId: 68f44bf0-ff75-46c4-b4fc-6c7576403328
---

# Simulate panel UX overhaul (2026-07-08, in progress)

Direct user request (not the coverage loop). Consolidate the Dynamics-tab simulation UI
into one clean **Simulate** section with a **master Job status card** and context
Run/Stop/Resume buttons. Builds on the U-track (unified panel) work — the engine selector
(`engine_selector.js`, U4) already fronts the 5 engine panels.

## User's spec (verbatim intent)
- Make the **Simulate header collapsible**; **remove per-engine header collapse**.
- **Remove the Periodic MD** section from the frontend.
- **Unify** card styling, name, order across engines.
- Move all job status outputs, loading bars, and buttons into a **UX-reviewed master Job
  status card** (ONE global card reflecting the selected engine — user chose "one global").
- When a job starts, its outputs should be **visually clean**.
- **Every job-initiating button flips to Stop** the instant its job runs (press Relax →
  "Stop Relax"); selecting a **stopped** job flips it to **Resume**. Apply across all engines.
- User decisions (AskUserQuestion): one global master card · context buttons IN the card ·
  implement directly (no mockup) · structural changes first.

## Phase A2 — selector = dropdown, strip removed (SHIPPED 2026-07-08, uncommitted)
- Engine selector is now a **`<select>` dropdown** (`.engine-selector-dropdown`), not a
  segmented button control. `engine_selector.js` factory builds one `<option>` per
  `ENGINE_KEYS`; `select()` syncs `dropdown.value`. Old `.engine-selector-btn` / tablist
  removed. Tests rewritten (dropdown options + change-event).
- **Capability strip removed** — the `#engine-capability-strip` div, `renderStrip`,
  `stripMount` param, and `.capability-chip`/`.engine-capability-strip` CSS are gone.
  `selectedEngineCards()` (pure census) kept + still unit-tested, just no longer rendered.
- **oxDNA Advanced-card chevron bug fixed**: markup was `display:none;display:grid` (last
  wins → shown-on-load despite ▸), and the toggle opened with `style.display=''` which
  stripped the inline rule to `.ox-card__body`'s block, losing the 2-col grid permanently.
  Now markup is `display:none` + grid props, toggle opens to `display:'grid'`. Starts
  closed, toggles none↔grid cleanly (verified in-app).

## Phase A — structural (SHIPPED + verified, committed `73db970`)
- **Periodic MD panel removed**: DOM block + `periodic_md_panel.js` + `periodic_md_overlay.js`
  + `main.js` wiring + stale e2e spec. Client-only, no backend (see [[periodic_md]]).
- **Per-engine headers no longer collapse** — static labels. New `collapsible:false` option on
  `jobs_panel_base.js::initJobsPanelBase`: forces the section open (ignores persisted state,
  no heading listener), keeps the advanced-drawer + poll, and **defers `onOpen` to a
  microtask** (a permanently-open panel inits early in `main.js`, before late-declared deps
  like `_workspacePath` → firing onOpen synchronously was a TDZ; the microtask fires after the
  synchronous init body). All 5 panels pass `collapsible:false`; the 5 engine `<h2>`s keep a
  title `<span>` so `engine_activity_headers.js` can still hang its busy-spinner there.
- **Simulate section collapses as one**: `index.html` wraps the selector + capability strip +
  all engine panels in a collapsible `#simulate-body`, driven by `initJobsPanelBase` (wired in
  `main.js`, arrowStyle:'class'). `main.js` net **−8 LOC**.

## Phase B — naming (SHIPPED, committed `73db970`)
Unified divergent card titles to the U1 descriptor (`engine_capabilities.js` CARD_LABELS):
LAMMPS "Surface" → "Hard surface"; CanDo "Display" + others' "Visualizations & processing" →
"Visualizations". **Card ORDER + deeper styling deferred into Phase C** (which reorganizes the
same panels — reordering now would be redone). Canonical order = `CARD_KEYS`
(run, efield, anchors, surface, advanced, viz, metrics, joblist).

## Phase C — master Job status card + context Run/Stop/Resume (IN PROGRESS)
**Foundation (SHIPPED, committed `73db970`):** `frontend/src/ui/job_run_control.js` —
pure `runControlState(selectedJob, {verb, isActive, isResumable, busy}) → {action,label,disabled}`
with `RUN_ACTION={RUN,STOP,RESUME}`. The rule: nothing/completed selected → `▶ <verb>`;
selected job active → `■ Stop <verb>`; selected stopped/failed → `↻ Resume <verb>`. Active
wins over resumable. 9 unit tests. Each engine supplies its own predicates + verb.

**Engines wired (pattern = extract `_launchRelax`, add `_runControl`/`_stopSelected`/
`_resumeSelected`, dispatch the run btn's click on `_runControl().action`, paint label from
it, retire the redundant detail Start/Stop):**
- **oxDNA** (committed `73db970`): gated to the RELAXATION phase (`isActive:isRelaxRunning`) so
  a running PRODUCTION phase keeps "▶ Relax" (disabled) + a production-phase Stop stays in the
  detail. Detail Start retired. 99 panel tests (3 rewritten).
- **NAMD** (done, **uncommitted as of this file**): pure exported `mdRunControl(job,{busy})` —
  `isActive:mdJobIsActive`; **local** stopped/failed → Resume here, but an **Alpine** job's
  cluster-gated resume stays on its dedicated resume button (Alpine is never "Resume" here,
  though an in-flight Alpine job still shows Stop=scancel). Detail Start/Stop retired; Alpine
  submit/resume/ensemble keep their dedicated buttons. +9 `mdRunControl` tests.

**REMAINING:**
1. Wire the context button into **LAMMPS, mrDNA, CanDo** (lighter — no Alpine; mrDNA/CanDo have
   Coarse+Fine, so decide which action the context verb tracks — likely the primary/Coarse).
2. **Master Job status card consolidation**: fold the 5 bespoke `#*-jobs-progress` bars, status
   lines, Health cards, Metrics cards, and detail blocks into ONE global card in the Simulate
   section that reflects the selected engine's active/selected job; "visually clean when
   running"; apply the canonical CARD_KEYS order. Reuse the shared seams
   (`jobs_panel_render.js`, `metrics_card.js`, `job_tree.js`).

## Chain Simulations sidebar — replaced the "Plan Run" popup (2026-07-09)

Direct user request. Promoted the removed modal `md_plan_run.js` "Plan Run" overlay into a
persistent collapsible **"Chain Simulations"** section ABOVE Simulate (`#chain-sim-panel`,
Dynamics tab). Enable toggle → oxDNA/NAMD **Relax/Production buttons flip to "＋ Queue
Relax"/"＋ Queue Production"** and feed a scrollable, reorderable **queue** with per-stage
preflight (✓/⚠/✕), rough ETA, total ETA, and a **Launch** button. Named **projects** managed
like Animations (dropdown + `+`/⧉/× ; server-persisted on the design). `md_plan_run.js`
DELETED; `#md-jobs-plan-btn` removed.

**Architecture (module-first):**
- Backend model `ChainSimProject`/`ChainSimStage` on `Design.chain_sim_projects`
  ([backend/core/models.py]); CRUD in [routes_chain_sim.py](backend/api/routes_chain_sim.py)
  (`/design/chain-sim-projects` create/patch/delete + `PUT …/stages`), mirrors
  `routes_animations.py`. Client [chain_sim_endpoints.js](frontend/src/api/chain_sim_endpoints.js).
- **Backend chain extension (user chose "extend fully"):** the executor was NAMD-only +
  required a completed root. Now supports **rootless chains** (`CreateChainRequest.root_job_id`
  optional → stage 0 is a fresh relax that CREATES the structure; validated
  `_is_relax_protocol`) and **oxDNA execution** (`_chain_spawn` dispatches: parent=None →
  `_spawn_fresh_relax` (oxDNA `create_oxdna_job` / NAMD `create_md_job`); oxDNA+parent →
  `_spawn_oxdna_child` (`append_oxdna_run`); NAMD same-engine → `spawn_md_production`;
  cross-engine oxDNA→NAMD unchanged). Status adapter `_chain_job_status` resolves NAMD-then-oxDNA
  by id. The pure `md_chain_executor.py` was NOT touched (engine dispatch lives in the API
  adapters). oxDNA productions/field runs are separate CHILD jobs → fit the one-job-per-stage model.
- **Pure model** [chain_sim_model.js](frontend/src/ui/chain_sim_model.js): `stagePreflight`
  (production seeds from in-queue predecessor first, else `seed_job_id` of an existing completed
  job — stored `seed_job_name`/`seed_engine` so no live job list needed; `engineCanSeedFrom` =
  same-engine or NAMD←oxDNA/mrDNA), `estimate*Seconds`/`formatDuration` (rough: oxDNA by steps,
  NAMD by ns, size taper + optional benchmarked throughput), `groupIntoChains` (relax → new
  rootless chain; production continues the open chain or roots at a job). `stage_planner_model.js`
  kept ONLY for `chainStatusSummary`.
- **Panel** [chain_sim_panel.js](frontend/src/ui/chain_sim_panel.js) `initChainSimPanel({store,
  api, engines:{oxdna,namd:{getRunElements,applyRunConfig,getSelectedJob,getAdvanced}},
  selectEngine, getBaseCount, getCompletedJobs, getThroughput})` → `{isEnabled, enqueue}`.
  Enable persisted in localStorage; toggle dispatches `nadoc:chain-mode-change` (engine panels
  repaint labels). **Click a queue row → `selectEngine(engine)` + the engine's `applyRunConfig`
  with the stage's `{field, surface, anchors}` — the IDENTICAL call the real oxDNA job-select
  makes, so it produces the same visuals: purple anchor glow (`oxdnaAnchorsSetup.applyConfig` →
  `onChange` → `_refreshAnchorGlow`), the field arrow (forces_card `jobArrow:true` gizmo, dir +
  magnitude), and the hard-surface grid (`oxdnaFloorSetup.applyConfig`). The stored stage shapes
  (`field:{field_pN,dir}`, `surface:{dir,offset_nm,stiff}`, anchors list) MATCH `runConfigForJob`
  exactly, so the echo is byte-identical; a relax stage (no field/surface/anchors) clears them so
  a prior stage's visuals don't linger.** NAMD has no scene gizmo/glow (by existing design — real
  NAMD job-select doesn't echo either), so clicking a NAMD row only repopulates its inputs. Two
  vitest cases lock the row-click→applyRunConfig data + the relax-clears-echo behavior. Launch:
  warn/error popup, then one `createChain` per group.
- **Engine wiring:** oxDNA + NAMD panels gained `getChainMode`/`enqueueChainStage` deps; Relax
  verb → "Queue Relax", prod label → "Queue Production", click branches to enqueue; both buttons
  **always enabled in chain mode** (queuing authors a plan; engine need only be present at Launch).
  The NAMD panel now exposes `getRunElements/applyRunConfig/getAdvanced` on its return API (it owns
  its field/anchor cards). **Gotcha fixed:** oxDNA `_setBtnSpinner` only rewrites the label on a
  spinning-flag flip, so a chain-mode toggle left the prod label stale — now the idle prod label is
  set directly (mirrors the run button).
- `main.js`: `let chainSim` declared before the panels (bound lazily); +36 net LOC, ALL wiring
  (factory init + dep closures), no cohesive logic.

### Job-list integration + live per-stage status (2026-07-09, follow-up)
User request: launched chain jobs must appear in the Simulate engine job list with standard
status + health + trajectory viz (like a hand-launched run), and the queue rows must show each
stage's live run status.
- **`design_source_path` gap (the fix that makes chain jobs visible):** the engine lists filter
  on `design_source_path` (`filterJobsForPart` — a job with `null` path is dropped unless "show
  all"). The chain executor's **create** hops (`_spawn_fresh_relax` both engines + the
  cross-engine `_chain_spawn` branch) spawned jobs with **no** `design_source_path`, so chain
  roots were invisible. Fix: `MdPipeline.design_source_path` + `StagePlan.design_source_path`
  (via `build_pipeline_plan`) → the three create hops stamp it onto `CreateOxdnaJobRequest` /
  `CreateJobRequest`. `CreateChainRequest.design_source_path` carries it from the frontend
  (`getDesignSourcePath: () => _workspacePath`). **Parent-seeded children
  (`append_oxdna_run`/`spawn_md_production`) already inherit it** — only roots + cross-engine
  creates needed the stamp. Once listed, health + trajectory/RMSF viz work with zero extra code
  (regular-job machinery; the selection→viz path never gated on `design_source_path`).
- **Immediate job-list population on launch:** the engine panels only poll when they already
  know about an active job (`shouldPoll = open && hasActive`), so a chain launched from the
  *separate* Chain Simulations panel left the running stage-0 job invisible until the user
  toggled the panel. Fix: the chain panel calls `engines[eng].refreshJobs()` for each launched
  engine right after `createChain` resolves (the backend spawns stage 0 synchronously via
  `advance_chains` before returning, so the job already exists). `refreshJobs` → the panel's
  `refresh` (`_fetchJobs`) which populates the list AND re-arms the poll once the job reads
  active. oxDNA already exposed `refresh`; added `refresh: _fetchJobs` to the NAMD panel return.
- **Live per-stage status in the queue:** `chainGroups()` (pure) exposes the model stages (with
  ids) per lineage; `groupIntoChains()` is now its payload projection. Launch records
  `_launched=[{chainId, stageIds}]`; `_startPolling` polls each `getMdChain` → maps
  `chain.stages[i].{status,job_id,engine}` back onto rows by `stageIds[i]`, then fetches each
  realised job (`getOxdnaJob`/`getMdJob`) for `latestHealthSample`. A launched row shows the LIVE
  badge (`liveStageBadge`: ○ queued / ⟳ running / ✓ done / ✕ failed) + status label + a pass/fail
  **health dot** instead of the preflight glyph/ETA; project switch clears `_liveStatus` + stops
  polling. Tests: `chainGroups`/`liveStageBadge`/`latestHealthSample` (model) + a panel test
  driving launch→poll→row shows running badge + green health dot + `design_source_path` stamped.
- **Owed live validation (MV-33):** a REAL end-to-end chain run (actual oxDNA/NAMD execution) to
  confirm the spawned root lands in the engine list and its trajectory is viewable — not run here
  (heavy real sim). Verified by unit test + composition (create endpoints set `design_source_path`
  from the body, which the list filters on).
- **Chain-completion integration test (2026-07-09):** `tests/test_chain_completion_e2e.py` (3 tests)
  loads `workspace/6hbx100_1xT.nadoc`'s authored 3-stage oxDNA chain (relax→prod[field+surface]→
  prod[+anchors]), folds it into the `POST /md/chains` payload, and drives the REAL
  `advance_chains` supervisor (four job-creators stubbed) to `CHAIN_COMPLETED`. Asserts routing
  (fresh_relax→oxdna_child×2), predecessor-seeding (RED-guarded), forces carry-through,
  `design_source_path` stamp, and a mid-chain failure→`resume`→completion recovery path. This
  closes the "does a whole chain finish" gap at the INTEGRATION layer; **MV-33 (real binaries) is
  still owed** — the sim itself is stubbed.

## Chain failure diagnostics + the live-design root-cause fix (2026-07-09)

Real failure hit: a launched `6hbx100_1xT` chain halted at stage 1 (the first production)
with `409: A different design is loaded ('Bundle' … Open '6hbx100_1xT' to continue)`. Root
cause: the unattended supervisor's stage spawn ran the **interactive** live-design guard
(`_assert_job_current` / `_assert_md_job_current`), which compares the job against whatever
design is loaded in the app — the user had a *different* design open, so it 409'd 3× and the
chain halted. The chain needed nothing from the loaded design (it seeds from the parent
job's frozen snapshot + explicit stage forces).

- **Fix (user chose "chains use their own design"):** ambient flag
  `md_chain_executor.unattended_chain_spawn()` (a `ContextVar`, task-scoped) set by
  `advance_chains` around every `_chain_spawn`. Both guards call `in_unattended_chain_spawn()`
  and **stand down** when set. Default False → interactive behavior byte-unchanged. A chain
  now runs to completion regardless of what design is loaded / switched to mid-run. Tests:
  guard 409s interactively but stands down under the flag (oxDNA + NAMD), flag resets after
  the context, and the e2e asserts every stage spawns under the flag.
- **`diagnose_chain(chain)` (pure, in `md_chain_executor`):** turns a `ChainRun` into
  `{status, headline, failed_index, failed_job_id, error, cause, action}` — classifies the
  raw `chain.error` (design-mismatch / design-edited / missing-seed / generic) into a plain
  cause + next action, and tells a **spawn** failure (no job on the failed stage) from a
  **job** failure (stage has a job_id → point at its log). 6 unit tests.
- **`scripts/chain_doctor.py`** (matches the `lammps_doctor.py` convention): `chain_doctor.py`
  = summary of every chain + deep-dive the failed ones; `<id>` / `latest` / `--failed` /
  `--log-lines N`. Prints per-stage table, the classified why + action + the chain's source
  design, and tails a failed realised job's newest `*.log`. Reuses `diagnose_chain` so CLI
  and (future) UI never disagree.
- **In-app surfacing:** `chainStatusSummary` now returns `error` (the backend's own
  actionable message, only on failure); the Chain Simulations panel's status readout shows it
  in red on a halt instead of only the generic "Halted at stage N" headline. **NOT re-verified
  in a live app failure** (reproducing needs a real failed chain; the model change is
  unit-tested, the panel render is a two-branch textContent assignment).

## Field-needs-anchor relaxed to surface + full-chain automation (2026-07-09)

Second real failure on the same design: after the design-guard fix, a re-run halted at
stage 1 with `400: An electric field needs ≥1 anchor` — stage 1 is a downward field into a
hard surface (a **deposition** setup) with no strand anchor. The frontend preflight only
*warned* (Launch allowed) but the backend hard-rejects any field without a strand anchor.

- **Rule relaxed (user decision "surface anchors it"):** new pure `backend/core/field_anchor.py`
  — `surface_opposes_field(field_dir, surface_dir)` (field presses anti-parallel into the
  plane within ~25°, cos ≥ 0.906) + `field_needs_strand_anchor(...)`. A field with no strand
  anchor is now allowed **when a hard surface opposes it**. Wired into the ONE source of
  truth: `append_oxdna_run` + both `routes_oxdna_live` sites. The dedicated field-only
  E-field run (`write_field_forces`, no surface) is unchanged — still needs an anchor.
- **Frontend mirror:** `chain_sim_model.js` `_surfaceOpposesField`/`_fieldNeedsAnchor` mirror
  the backend (same 0.906); the preflight no longer flags a field-into-opposing-surface stage.
- **Up-front launch validation:** `create_md_chain` now validates the WHOLE plan against the
  field-anchor rule BEFORE spawning — a doomed production stage (field, no anchor, no opposing
  surface) returns a 400 naming the stage at Launch, instead of running the relax then dying.
- **The automation that catches this class (the ask):**
  - `tests/test_field_anchor.py` (11) — the pure geometry rule.
  - `test_chain_completion_e2e.py::test_launch_rejects_a_field_stage_with_nothing_to_hold_it`
    + `::test_launch_accepts_the_real_deposition_chain` — the real file's chain passes; a
    stripped-surface variant is refused at Launch.
  - **`test_full_chain_runs_end_to_end_with_a_mock_binary` (slow)** — drives the REAL
    create→relax→seed→append→append→completion orchestration on the real design with a MOCK
    oxDNA binary (fake runner carries the conf forward so seed/anchor/wall placement is real).
    This is the anti-false-confidence test: it exercises every spawn precondition the stubbed
    unit e2e skips, so it WOULD have caught "the second job failed" (stage 1's 400). ~0.8s.
- `diagnose_chain` + `chain_doctor` gained a field-without-anchor classification.

## Chain jobs → standard list: start-time population + row-click selection (2026-07-09)

User request: (1) a chain stage's job should appear in the standard engine job list **as
soon as it starts** (not only after it completes); (2) clicking a chain queue row should
**select that stage's real job in the standard list** (highlight the row + populate the
cards), like clicking the job's row there.

- **Bug behind the delete report first**: the oxDNA panel did `export { descendantIds } from
  './job_tree.js'` (a re-export, no local binding) → the delete handler's `descendantIds()`
  threw a silent ReferenceError. Fixed to a real `import` + separate `export`. See LESSONS H9.
- **Start-time population (Req 1):** the chain panel's poll tick now tracks realised stage
  job ids in `_seenJobIds`; when a stage's `job_id` first appears (the stage STARTED), it
  calls `engines[eng].refreshJobs()` so the running job lands in the standard list at once.
  Previously only the launch-time refresh fired (stage 0), so mid-chain stages surfaced only
  when the engine panel happened to still be polling — often not until completion.
- **Row-click selection (Req 2):** both panels now expose `selectJob(jobId)` (oxDNA +
  NAMD) — refetches if the job isn't listed yet, then runs the panel's real `_selectJob`
  (highlight + populate every card + follow the display), i.e. identical to a list-row click.
  Wired into `engines.{oxdna,namd}.selectJob` in `main.js` (+2 wiring lines). The chain
  panel's `_selectRow` calls `engines[eng].selectJob(live.jobId)` for a LAUNCHED stage (has a
  realised job in `_liveStatus`), falling back to the old `applyRunConfig` plan-echo for an
  un-launched stage. `_seenJobIds` resets on project switch + on each launch.
- **Verified in the running app** (Playwright, real launch on 6hbx100_1xT): oxDNA list went
  3→5 immediately on launch (Req 1); clicking the chain queue row selected the real job — the
  oxDNA detail showed the live `Running · 0/3 · 1_mc_relax · 14%` status (Req 2); zero console
  errors. Test jobs stopped+deleted, the file's chain project restored to its 3 stages.
- Tests: `chain_sim_panel.test.js` +2 (mid-chain start push via fake-timer 2nd poll tick;
  launched-row click → `selectJob(jobId)` not `applyRunConfig`). `oxdna_jobs_panel.test.js` +1
  (delete-handler regression, RED-verified). `just test-frontend` = **2453 passed**; `just
  smoke` 23/23.

## Per-stage "update to current settings" button (2026-07-09)

User need: after diagnosing a blown-up production (a field aimed OUT of the surface so its
single anchor bore the whole ~180 pN load → FENE explosion; not a chaining bug — the plan
carried the forces verbatim and the anchor trap `pos0` matched the seed conf exactly), the
user couldn't re-tune an already-queued stage. Added a **✎ button on each chain queue row**:
`_updateStageFromCurrent(i)` overwrites that stage's field/surface/anchors + advanced knobs
with the engine's CURRENT card config (reusing the same `_buildStage` the "Queue …" buttons
use), keeping the stage's engine/protocol/id/position. Fix a stage in place instead of
remove+re-queue. The revised plan is what the **next Launch** uses (Resume re-runs the
already-launched chain's frozen `chain.json` plan — re-Launch to apply changed settings).
Entirely in `chain_sim_panel.js` (no main.js change). Test: enqueue field A → reconfigure
cards to field B + anchor → click ✎ → persisted stage is field B, same id (unit). App-verified
on a throwaway project: ✎ renders, captured a changed prod-steps value (1234000) into the
persisted stage, re-persisted, zero console errors. `just test-frontend` **2454**; `just smoke` 23/23.

## Verification + debt
- Gates each slice: `just test-frontend` (vitest, **2439 passed** after Chain Simulations) +
  `just smoke` (23/23). Chain Simulations DID touch Python (new routes + chain-executor
  extension): full `just test` = **4461 passed** (1 pre-existing xdist-isolation flake,
  `test_md_list_includes_size`, passes in isolation — unrelated to chain-sim).
- New tests: backend `test_routes_chain_sim.py` (8, CRUD + .nadoc serialize round-trip),
  `test_chain_spawn_dispatch.py` (5, engine routing + `_is_relax_protocol`); frontend
  `chain_sim_model.test.js` (21), `chain_sim_panel.test.js` (4 jsdom — real factory drives
  enqueue→persist→preflight→launch grouping).
- **Live-verified (Playwright, temporary spec since deleted):** panel renders (zero console
  errors); enable → oxDNA Relax→"Queue Relax" + Production→"Queue Production"; disable reverts.
- **Doc-context-blocked (owes MV):** the create-project → queue-row round-trip through the app.
  `client.js` uses relative `/api` + `X-NADOC-Doc` doc headers; an API-`design/load`ed design
  isn't the frontend's active document, so the CRUD POST 404s in Playwright (same limit as
  MV-28/30/31). The route works (200 same-origin + backend tests) and the queue/preflight/launch
  logic is fully unit-verified — only the live doc round-trip is unproven → **MV-32** (enable →
  create project → Queue Relax + 2 Queue Production → verify ✓/⚠ glyphs, seed notes, ETAs,
  reorder/delete, click-to-repopulate, Launch popup). See [[manual_validation_debt]].
- **Live-gesture verification is blocked by the doc-context limit** (API `design/load` doesn't
  set the frontend workspace path → the per-design job filter drops mocked jobs → Playwright
  can't drive job selection; same as U4's MV-28). So the run/stop/resume + collapse *gestures*
  are unit-verified (real panel factory drives the button DOM) but owe manual rows:
  **MV-30** (Simulate collapse + static engine headers + Periodic-MD gone), **MV-31** (context
  Run/Stop/Resume on oxDNA + NAMD). See [[manual_validation_debt]].
- Related: [[project_md_job_system]], [[project_md_engines_panel]] (install gates prepend to
  `#oxdna-jobs-body`/`#md-panel-body` — still valid). U-track lives in `SIM_COVERAGE_PLAN.md`.

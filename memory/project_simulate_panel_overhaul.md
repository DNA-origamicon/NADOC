---
name: project_simulate_panel_overhaul
description: "Simulate-panel UX overhaul — one collapsible Simulate section, static engine headers, context Run/Stop/Resume, master Job status card"
metadata: 
  node_type: memory
  type: project
  originSessionId: 68f44bf0-ff75-46c4-b4fc-6c7576403328
---

# Simulate panel UX overhaul (2026-07-08, in progress)

## ⚡ "Use as NAMD seed" now creates a deferred-prep DRAFT (configure-then-Relax) — 2026-07-11
User ask: the seed button should NOT immediately solvate with defaults. Now it creates an **unstarted
NAMD `draft`** (new `MdStatus.draft`) that records the seed source + default advanced params but DEFERS
the expensive solvation. The user sets Advanced options, then presses **"Relax from oxDNA"** (the primary
launcher relabels for a selected draft) which solvates-from-seed + runs the STANDARD relax into the SAME
job id. Only the starting positions differ from a normal relax.
- **Backend** (`routes_md.py`): `CreateJobRequest.draft` → `_spawn_draft_job` (status=draft, no prep,
  `_seed_design_name` pulls a nice list label from the oxDNA/mrDNA job). New `POST /md/jobs/{id}/prepare`
  (`prepare_draft_job`) runs the standard pipeline into the existing draft via `_spawn_prep_job(existing_job=…)`
  (refactored to prep-in-place); the body carries the advanced settings, the draft owns the seed (body seed
  ids ignored). `reconcile_job_status` leaves a draft untouched (only repairs stale `running`).
- **Frontend**: oxDNA/mrDNA seed buttons post `{oxdna|mrdna_job_id, draft:true}` (was a full seed job).
  `md_jobs_panel.js`: pure `mdJobIsDraft` / `mdDraftRunLabel` ("▶ Relax from oxDNA/mrDNA"); `_runControl`
  draft branch; the run click routes a draft to `_launchRelax(draftId)` → `api.prepareMdDraft`; selecting a
  draft pre-fills the Advanced inputs from its `prep_params` + reveals the drawer (`_maybePrefillDraft`); a
  draft opens no status WS. `job_status_symbol.js`: `draft` badge = ✎ grey. Draft appears in the master
  list once scoped to its design.
- **Tests**: `test_md_draft.py` (draft persists, reconcile-inert, `_spawn_draft_job` defers prep);
  vitest for the pure fns; `e2e/md_draft_seed.spec.js` (running-app smoke: draft created unsolvated +
  surfaced in `/simulate/jobs` + app boots). NOTE: the button RELABEL click-through isn't e2e-asserted —
  the overhauled master list scopes to the browser workspace path the harness can't set; the relabel is
  the unit-tested pure `mdDraftRunLabel` wired through the same `_paintRunControl` as Relax→Resume.
## ⚡ Switching engine tabs left the previous engine's stages/status in the master card — FIXED 2026-07-11
User: select a NAMD relax job, then click the SNUPI tab → the NAMD stage timeline (and status
line/progress bar/detail/action buttons) kept showing. **Root cause:** the master card at the bottom
of the shared jobs list (`simulate_jobs.js`) reads everything from `_selectedNode()`, but selecting a
job auto-switches the tab (`_dispatchDetail → engineSelector.select(node.engine)`), so the only way to
mismatch is a *manual* tab click. `setActiveEngine(engine)` (fired by the selector's onSelect) only
re-rendered the LIST, never the master card — so a cross-engine selection lingered. **Fix:**
`setActiveEngine` now drops the selection when the selected run isn't in the newly-active tab's
`_visibleNodes()` and calls `_renderMaster()` (one call clears status + progress + stage timeline +
detail + run/archive buttons). In "show all job types" mode every run stays visible → selection
preserved (still highlighted in the list). Regressions in `simulate_jobs.test.js`: "switching to a
different engine tab clears the previous engine's stages + status" + the show-all preserve case.
`just test-frontend` **2685 pass**. NOT visually driven in the live app with two real coexisting jobs
(factory-drive jsdom test covers the exact `setActiveEngine` path the live selector calls).

## ⚡ Tabs reordered fast→accurate + "Use as NAMD seed" wiped oxDNA cards — FIXED 2026-07-11
Two user asks. (1) Engine tabs reordered to **CanDo · mrDNA · oxDNA · NAMD** (fast→accurate):
`ENGINE_KEYS = ['cando','mrdna','oxdna','namd']` in `engine_capabilities.js` drives tab order;
default selected engine stays **oxDNA** (main.js passes `initial:'oxdna'` — not ENGINE_KEYS[0]). A
small **fast→accurate axis** (`#engine-speed-axis`: "Fast" → green→blue→purple gradient bar w/
arrowhead → "Accurate") sits above the tabs in `#simulate-body`. Card *definitions* untouched — pure
reorder. (2) **BUG:** clicking oxDNA's "Use as NAMD seed" made **every oxDNA card disappear** until
reload. Root cause: the seed handler's obsolete `_revealMdPanel()` called `_base.applyCollapsed(true)`
→ set `#oxdna-jobs-body` to `display:none`. Under the tab model (panels are `collapsible:false`, no
header), re-selecting the oxDNA tab only re-shows the panel *wrapper* (`#oxdna-jobs-panel`), NOT the
collapsed *body* — so cards stayed hidden; it also clicked a removed `md-jobs-panel-heading` (no-op).
**Fix:** deleted `_revealMdPanel` (+ its now-unused `section_collapse_state` import); the seed handler
just dispatches `nadoc:md-job-created` (+ `sim-jobs-changed`), and **main.js listens → `engineSelector
.select('namd')`** to surface the new job. This also fixes mrDNA's seed (same event; it never switched
tabs before). Live-verified: oxDNA cards survive the seed, NAMD tab activates, cards intact on return.
Test `oxdna_jobs_panel.test.js` "on seed success" rewritten (was pinning the collapse bug) → asserts
body stays open + event fires with jobId. `just test-frontend` **2617 pass**.


## ⚡ Launch made while master list is IDLE didn't surface until refresh — FIXED 2026-07-11
User: a production run launched off a completed parent "fails to properly initiate an update to the job
list / progress bar unless I refresh" (hard to reproduce). **Root cause:** the master list+bar
(`simulate_jobs.js`) self-polls ONLY while it already holds an active node (`_schedulePoll`:
`_dynamicsActive && bodyVisible && _nodes.some(nodeIsActive)`). Launching off a *completed* parent means
nothing is active at launch → master poll NOT armed. The oxDNA panel's launch handlers refresh their OWN
(hidden) list via `_fetchJobs()` but never tell the master, and the master listened to no launch event →
the new running job never appeared until a manual refresh / tab-switch / design-changed re-fired `_fetch()`.
Intermittent because if ANY other job was active the master was already polling and caught it within
`POLL_MS` (1500 ms). Backend was fine (job `running` on disk, `/simulate/jobs` listed it) — purely a missing
frontend refresh trigger. **Fix:** `simulate_jobs.js` listens for `window` event `nadoc:sim-jobs-changed` →
`_fetch()` (picks up the job AND re-arms its poll from there). **ALL FOUR engine panels** dispatch it: a
`_notifyIfJobsChanged()` helper at the END of each panel's `_fetchJobs()` compares a signature of
`${job_id}:${status}` across the panel's jobs and fires the event only when the set/statuses CHANGE (first
fetch just seeds the baseline). This one choke-point covers every path — relax/production/coarse/fine launch,
stop, resume, autorefine, Alpine submit, VRAM-retry/refit, and completion — with no per-poll spam and no
chance of missing a launch site. mrDNA's "Use as NAMD seed" also dispatches directly (the new NAMD job isn't
in mrDNA's own list). No feedback loop: only the master listens, and its `_fetch` doesn't re-dispatch.
(oxDNA was first fixed with explicit per-site dispatches, then refactored to the same signature detector for
uniformity + autorefine coverage.) Regressions: `simulate_jobs.test.js` "a nadoc:sim-jobs-changed event wakes
the idle master list"; `oxdna_jobs_panel.test.js` "fires nadoc:sim-jobs-changed when the job set changes".
`just test-frontend` **2617 pass**. **NOT verified in the running app** (won't launch a real sim in the
user's live session; doc-context per-design-selection limit).

## ⚡ Master progress bar sat at 0 % for single-stage runs — FIXED 2026-07-10
**Regression from the "ONE master progress bar" slice.** `simulate_jobs.masterProgressPct`
computed an oxDNA job's progress as **completed-stage count / total stages**. An e-field /
surface / production *child* run is a SINGLE `1_production` stage, so while running it read
`0/1 = 0 %` and only jumped to 100 % on completion — the user reported it as "hung" (it wasn't;
the backend `/progress` correctly showed 77 %). The old per-panel bar (`oxdna_jobs_panel._renderProgress`)
used the live within-stage `stage_fraction` from `/progress`; the master bar dropped it.
- **Fix.** `oxdna_runner.job_overall_fraction(job, ws, specs)` — a lean `(done + running-stage
  energy-line fraction) / n` (mirrors `job_progress()['overall']`, no ETA/health work). The
  `/simulate/jobs` route stamps `progress_fraction` on every RUNNING oxDNA node; `masterProgressPct`
  prefers it and falls back to the stage-count for queued/older payloads. Verified against the
  LIVE server: the GT_corner_v2 e-field+surface run's node now carries `progress_fraction` (0.77→0.98
  as it ran) so the bar advances. Tests: backend `test_job_overall_fraction_{single_stage_run_advances,
  counts_done_stages}` (single-stage advances off 0, ==job_progress overall); frontend
  `simulate_jobs.test.js` masterProgressPct-uses-live-fraction.
- **NAMD note:** `masterProgressPct` still uses done-segment count for NAMD — coarse but non-zero for
  multi-segment relaxes; a single-segment NAMD production would show the same 0-until-done coarseness
  (not yet stamped with a live fraction). Left for when NAMD single-stage runs surface it.

## ⚡ Consolidated Archive/Delete above the jobs card · oxDNA autorefine button removed · dead-button audit — SHIPPED 2026-07-10
Three user asks:
- **ONE Archive + Delete pair** now sits in `#simulate-job-actions` (section-level, ABOVE the
  `#simulate-jobs` card) instead of a set buried in each engine's detail block. `simulate_jobs.js`
  owns it: `_renderActions(node)` shows the host only when a **deletable** run is selected (any
  engine except LAMMPS, `status !== 'running'`); Archive shows only for engines that support it
  (**oxDNA / NAMD**), label tracks `node.archived`. Click dispatches to the selected node's engine
  panel via `_panelFor(node)`. Each panel exposes `deleteSelected()` (→ bool) + oxDNA/NAMD also
  `archiveSelected({onProgress})`; these are the OLD inline listeners refactored into named fns that
  operate on the panel's already-synced `_selectedId` (the master's `_dispatchDetail`→`selectJob`
  keeps it in step). Archive byte-progress renders into the master `#simulate-jobs-archive-progress`
  (panels no longer own a progress el). Per-panel Archive/Delete buttons + their DOM removed.
- **oxDNA Autorefine button removed** (button + `#oxdna-autorefine-row` only, per user). The JS
  machinery (`_updateAutorefineButton`/`_startAutorefine`/deviation-map viz/`[AR]` tag/backend) is
  KEPT but now unreachable from the UI — all element reads are `?.`/`if (el) return` guarded, so
  removing the row throws nothing (verified: smoke 0 console errors). main.js dropped
  `'oxdna-autorefine-row'` from the run-control relocation.
- **Dead-button audit → removed 3 Phase-C-RETIRED buttons** that were permanently `display:none`
  with unreachable handlers: `oxdna-jobs-start-btn`, `md-jobs-start-btn`, `md-jobs-stop-btn` (the
  master run control owns relax start/stop/resume; oxDNA's `oxdna-jobs-stop-btn` was KEPT — it still
  serves the PRODUCTION phase). Everything else audited resolves to ACTIVE or a legitimately-reachable
  CONDITIONAL (per-run Stop-when-running, Resume, seed, Alpine submit/resume/ensemble, revert-prod,
  error-log). **Two flagged, NOT changed:** `simulate-jobs-run-btn` is LAMMPS-only (dormant unless the
  CPU fallback runs); `oxdna-jobs-deviation-toggle` label says "(autorefine)" but its enable gate is
  general sampling, not autorefine — a misleading label, left as-is.
- **Tests:** `simulate_jobs.test.js` +6 (host hidden w/o selection; oxDNA=Archive+Delete;
  mrDNA/CanDo=Delete-only; archived→Unarchive; LAMMPS/running→hidden; Delete+Archive dispatch to the
  panel). `oxdna_jobs_panel.test.js` delete-regression test rewired to `panel.deleteSelected()`; start-btn
  scaffold/assert dropped. `just test-frontend` **2595 pass**; smoke 23/23, 0 console errors. Served DOM
  verified (action host present + above jobs card; all removed ids absent). **Frontend-only → no Python.**
  **NOT live-gesture-exercised** (doc-context per-design selection limit, MV-28 family): an actual
  archive/delete on a real selected job in-app — covered by the unit dispatch tests + real panel APIs.

## ⚡ Uniform card widths + oxDNA Advanced expand fix — SHIPPED 2026-07-10
Follow-up to the header-removal below. **CRITICAL regression the header removal introduced:**
all 4 panel factories guard `if (!panel || !heading || !body) return` — removing the `<h2>`
headers made `heading` null → **every engine panel factory early-returned and wired NOTHING**
(dead buttons, no availability dispatch, no card toggles — the symptom the user hit was "the
oxDNA Advanced card won't expand", but the whole panel was inert). Fix: dropped `heading` from
the guard in all four (`oxdna/mrdna/cando/md_jobs_panel.js` → `if (!panel || !body) return`);
heading stays optional (the collapse base already guards a null heading). **Lesson: removing a
DOM element that a factory reads-then-guards-on silently kills the factory — exercise an actual
in-panel toggle, not just DOM presence.**
- **Uniform widths:** the 4 engine panels are nested `.panel-section` inside `#simulate-panel`
  (also `.panel-section`, padding `10px 14px`), so their own 14px H-padding made their cards
  narrower than the section-level jobs/shape/run-control cards. CSS `#simulate-body > .panel-section
  { padding-left/right:0; border-bottom:none }` zeroes it → every card shares the same edges
  (verified live: jobs/shape/run-controls/oxDNA-adv/viz/anchors/metrics all `left:14, right:16`).
- **Verified live:** oxDNA Advanced body expands to 243px (was stuck — panel was dead); all cards
  aligned; vitest 2583, smoke 23/23, 0 console errors.

## ⚡ ONE progress bar (below list) + status colour + tooltip + timeline at card bottom — SHIPPED 2026-07-10
User request. Consolidated every engine's progress bar into the single master bar
`#simulate-jobs-progress` (already below the list); the four panel bars (`#oxdna/mrdna/cando/
md-jobs-progress`) are `display:none` (still rendered into, harmless). Node-driven, self-contained
in `simulate_jobs.js` (no panel routing):
- `masterProgressPct(node)` extended: completed→100; NAMD from `segments` done/total; +existing
  LAMMPS steps / oxDNA stages. `masterProgressColor(node)` (NEW): green done · red failed · **orange
  = warning (out_of_date/stale)** · grey stopped/queued · blue active. `masterProgressTooltip(node)`
  (NEW): the detail that used to sit inline in `#md-jobs-progress` (NAMD stage/segments/%/current,
  oxDNA stages, +⚠ stale) → set as the bar's hover `title`. `_renderMaster` paints width+bg+title.
- **Stage timeline → LAST in the jobs card:** new `#simulate-jobs-timeline` (+ `-host`) block appended
  to `#simulate-jobs-body`; main.js relocates all four engine `#*-jobs-timeline` elements into the host
  (each panel still populates its element by id). Master `_renderTimeline(node)` shows the selected
  engine's timeline + hides the block when none. Removed the now-duplicate "Stage timeline" label from
  the NAMD detail.
- Tests: `masterProgressPct`(namd/completed), `masterProgressColor`, `masterProgressTooltip` + factory
  drive (bar width/colour/title on select; timeline show/hide). vitest 2587, smoke 23/23. Live: 4 engine
  bars hidden, timelines in host, timeline block is the card's last child, master bar below list, 0
  console errors. **mrDNA/CanDo have no granular % → bar sits at 0 while running (colour conveys state);
  fine (quick jobs).** Bar/tooltip live-render on real job selection covered by unit tests (doc-context
  limit blocks live per-design selection).

## ⚡ LAMMPS viz UNIFIED into the oxDNA viz card (reversed the removal) — SHIPPED 2026-07-10
User (correct on the physics): LAMMPS here runs the oxDNA2 FF → SAME CG bead model → same viz
applies. User chose "same card, dispatch loader" (route a LAMMPS run through the oxDNA panel's OWN
viz card). Implemented (invasive — the oxDNA viz handlers are deeply coupled to oxDNA job state):
- `oxdna_jobs_panel.js`: new `lammpsDisplay` dep + `_lammpsMode`/`_lammpsNode` state + exported
  `selectLammpsJob(node)`. The 4 viz radio listeners (display/flex/deviation/traj) + off + align
  early-return `if (_lammpsMode) { _lammpsViz(kind); return }`; `_lammpsViz` is a self-contained
  parallel path driving `lammpsDisplay` (which shares oxDNA's pure mappers via `initLammpsDisplay`).
  trajPlayer onSeek/onBeforePlay dispatch by mode (LAMMPS = CG, no field arrow/heavy-rep prebuild).
  `_updateButtons` early-returns before the viz gates in `_lammpsMode` (so a poll can't re-disable
  the LAMMPS-enabled radios); `selectLammpsJob` enables the radios by `node.viewable` + hides the
  oxDNA stage detail. `_selectJob` (oxDNA) clears `_lammpsMode` + stops the LAMMPS overlay.
- `simulate_jobs.js` `_dispatchDetail`: a lammps node → `engineSelector.select('oxdna');
  oxdnaPanel.selectLammpsJob(node)` (was: no-op after the prior removal). main.js: `initLammpsDisplay
  ({designRenderer})` → passed to the oxDNA panel. Backend `/lammps/jobs/{id}/{display,rmsf,deviation,
  trajectory}` already exist → works end-to-end.
- **No physics exclusions:** all 4 modes apply (deviation = trajectory-mean-vs-design, not autorefine-
  gated). Tests: oxdna_jobs_panel +2 (LAMMPS radios → loader; unviewable → radios disabled), simulate
  dispatch test updated. vitest 2589, smoke 23/23, live 0 console errors. **NOT live-driven:** an actual
  LAMMPS job's viz in-app (doc-context blocks per-design selection) — covered by unit tests + real
  backend endpoints. `lammps_display.js` un-orphaned; `oxdna_trajectory_player.js` still orphaned.

## ⚡ Removed the LAMMPS viz card + trimmed anchor text — SHIPPED 2026-07-10
- Removed the oxDNA Anchors sentence "Used by the field and surface, or on their own. A field
  needs at least one." (kept "Fixed strands held in place during the run (tethers / clamps).").
- **Removed the "Visualizations (LAMMPS run)" card** from the unified jobs card entirely — markup
  `#simulate-jobs-viz` + ALL its now-dead JS in `simulate_jobs.js` (the viz refs, `_display`/`_player`
  controllers, `_updateVizToggles`/`_viewsOff`/`_showView`, the radio listeners, `_VIEW_RADIOS`, the
  `designRenderer`/`getFlexScale` factory params, and the `initLammpsDisplay`/`initOxdnaTrajectoryPlayer`/
  `jobIsViewable`/`flexStatusText` imports). `_dispatchDetail` simplified: a node with no panel (LAMMPS)
  just returns — its Stop / re-Run still live on the master run button. Tests updated (viz DOM + 3
  assertions removed; the 2 LAMMPS/oxDNA-select tests kept sans-viz). main.js drops the 2 removed deps.
  **CONSEQUENCE:** a LAMMPS run (GPU-busy CPU fallback) now has NO visualization surface — acceptable
  since LAMMPS is the transparent fallback the user "shouldn't know about." `lammps_display.js` +
  `oxdna_trajectory_player.js` are now orphaned (like the other LAMMPS-fold leftovers). vitest 2587,
  smoke 23/23, live: viz card absent + 0 console errors.

## ⚡ Anchor scroll boxes + black scrollable boxes — SHIPPED 2026-07-10
- Removed the NAMD Anchors description ("Strands / bases held immobile…"). (oxDNA/CanDo anchor
  cards keep their own separate descriptions — only the NAMD one was asked for.)
- All 3 anchor lists (`#oxdna/cando/md-anchors-list`) are now scrollable boxes (max-height 110px,
  overflow-y auto, border, black bg).
- Every scrollable box in the Dynamics tab now has a **black** (`#010409`) bg to contrast the
  gradient-tinted cards: the job lists (`#simulate-jobs-list` + the 4 hidden engine lists),
  `#chain-sim-queue`, `#md-jobs-list`, `#md-jobs-timeline`, `#md-jobs-resume-history`, `#md-output-log`,
  the anchor lists. HTML/CSS only. Verified live: boxes = rgb(1,4,9), anchor list overflow-y auto,
  screenshot shows black boxes popping against the cards; smoke 23/23, 0 console errors.

## ⚡ Compact cards + gradient outline — SHIPPED 2026-07-10
`.ox-card` (components.css): `margin-bottom` 2px→1px (nearly flush); flat border replaced by a
subtle top→bottom **gradient outline** via the double-background trick (`border:1px solid
transparent` + `linear-gradient(fill,fill) padding-box, linear-gradient(to bottom,#3f464f,#20252b)
border-box`) — keeps the 6px rounded corners that `border-image` would square off, so cards still
pop while packed tight. Section-level inline gaps tightened too: `#simulate-run-controls` 6→2px,
`#simulate-jobs` 8→2px, shape-compare card 8→2px, all four `#*-jobs-body` margin-top 8→2px.
Verified: adjacent card gaps = 1px, two gradients in computed `background-image`, screenshot shows
compact stack with visible per-card outline; smoke 23/23, 0 console errors. **Known residual gap**
(not addressed — not a "card"): the empty progress/live-status/prod-status min-height spacers at the
oxDNA panel top leave ~35px before the Benchmark card; left as-is so a running job doesn't jump the
layout.

## ⚡ oxDNA: Production-steps + resource line → Advanced; "unlocks" line removed — SHIPPED 2026-07-10
- `oxdna-jobs-prod-steps` (wrapped `#oxdna-prod-params`) + the section-level auto-policy resource
  line `#simulate-status-line` ("GPU: free · N cores · Engine …") moved into `#oxdna-jobs-adv-body`
  at init (main.js), prepended in reverse (status line first, then prod-params). The oxDNA advanced
  body is itself a 2-col grid, so each moved block gets `gridColumn:'1 / -1'` to span a full row.
  `simulate_launch.js` still renders the status line by id (getElementById finds it post-move).
  **Consequence:** the resource line now shows only on the oxDNA tab with Advanced expanded (was a
  persistent section-level line) — per user request.
- Removed the "Production unlocks after relaxation completes." message (oxdna_jobs_panel.js
  `_updateProdControls` — the locked-state else branch now sets `''`). The "Ready to run production…"
  message when unlocked is unchanged. (The NAMD "Production unlocks after minimization…" text is a
  different message, untouched.)
- Verified live: prod-steps + status line inside `#oxdna-jobs-adv-body` (spanning rows), no "unlocks"
  text, Advanced expands; oxdna tests 91, smoke 23/23, 0 console errors (one assembly-exit smoke flake
  passed on isolated re-run).

## ⚡ NAMD launch CONFIG tucked into the Advanced card — SHIPPED 2026-07-10
User request: the NAMD Alpine-connect chip, Protocol select, Run-on radios, and the production
box (steps / total time / the child-job note) belong in the Advanced card, not loose at the panel
top. Gave the launch-form wrapper `id="md-launch-form"`; main.js (right after the run-control
extraction, so `md-launch-row` is already gone) `advBody.prepend(md-launch-form)` then
`prepend(md-cluster-connection-mount)` → order in `#md-jobs-adv-body` reads cluster → protocol →
run-on → production box → existing threads grid. Only the Relax/Production buttons stay in the
run-controls host above the jobs card. All by-ID wiring intact (init-time DOM move). Verified live:
all six items inside `#md-jobs-adv-body`, Relax NOT in advanced, Advanced still expands; md panel
tests 87, smoke 23/23, 0 console errors.

## ⚡ Headers removed · install-status → tab ⚠ · run buttons above the jobs card — SHIPPED 2026-07-10
Direct user request, three parts:
- **Per-engine `<h2>` headers removed** (oxdna/mrdna/cando/md). Panels pass their (now-null)
  heading to `initJobsPanelBase` — safe because all pass `collapsible:false` (guarded
  `collapsible && heading && body`). The old `md-jobs-panel-heading?.click()` in oxdna panel
  was already inert under the static-header model. `engine_activity_headers.js` **retargeted**:
  the busy spinner now hangs on the engine TAB (`.engine-selector-btn[data-engine]`, md→namd,
  no LAMMPS tab) instead of the removed header; its init moved AFTER `initEngineSelector` in
  main.js so the tabs exist. Test rewritten (builds tabs).
- **Install-status badges → ⚠ on the tab.** The 3 availability badges (`#oxdna-jobs-status`,
  `#mrdna-jobs-status`, `#md-jobs-namd-status`) are HIDDEN (`display:none`, kept so panel
  availability logic — incl. mrDNA's button-gating — is untouched). Each panel's
  `_checkAvailable`/`_checkEngines` now dispatches `window` event `nadoc:engine-availability
  {engine, ok, reason}`. `engine_selector.js`: each tab is `[label][⚠ warn]`; the factory
  listens for the event + `setEngineStatus(engine,{ok,reason})` shows the ⚠ with a tooltip
  `${reason}\nOpen Help ▸ MD Engines to install.` + `.is-uninstalled` class. CanDo has no
  availability gate → never warns. CSS `.engine-warn` (amber) added near `.engine-selector-btn`.
- **Run-control buttons moved above the jobs card.** New `#simulate-run-controls` host (4
  per-engine sub-divs) sits just above `#simulate-jobs`. main.js relocates each engine's launch
  cluster into it via `appendChild` (moves live nodes + listeners → IDs unchanged, zero rewiring):
  oxDNA `oxdna-launch-row`(Relax/Live/Full)+`oxdna-autorefine-row`; mrDNA `mrdna-launch-row`
  (Coarse/Fine); CanDo `cando-launch-row`+`cando-autorefine-row`; NAMD `md-launch-row`
  (Relax/Production). Selector gained `runControlEls` param → shows only the active engine's
  cluster (like panels). oxDNA/NAMD launch buttons already double as Stop/Resume (Phase C). **Left
  in the panels (not moved):** per-job Stop/Delete/Archive in the detail blocks; NAMD
  protocol/run-target/production-steps config; oxDNA prod-steps/live-status.
- **Tests:** `engine_selector.test.js` +4 (⚠ marker, availability event, runControlEls toggle),
  `engine_activity_headers.test.js` rewritten. vitest **2583** pass; smoke 23/23. **Live:** headers
  gone, badges display:none, all launch buttons inside `#*-run-controls` above the jobs card, active
  cluster shown / others hidden, ⚠ present-but-hidden on all tabs (all engines installed here),
  0 console errors. **NOT live-exercised:** the ⚠ SHOWING for an uninstalled engine (all installed
  on this box) — covered by the unit test.


## ⚡ ONE cross-engine job list per tab + engine filter + "Show all job types" — SHIPPED 2026-07-10
Direct user request: the unified `#simulate-jobs` list showed oxDNA+LAMMPS on every tab
(irrelevant on mrDNA/CanDo/NAMD, which also carried their OWN list → two lists per tab).
Now it is the ONE list for ALL FOUR engines, scoped to the active tab, in a collapsible card.
- **Backend:** `sim_jobs.py` gained `normalize_mrdna_job`/`normalize_cando_job`/`normalize_md_job`
  (mrDNA/CanDo flat roots; NAMD has parent/child like oxDNA, `engine:'namd'`). `GET /simulate/jobs`
  now also calls `routes_mrdna.list_mrdna_jobs`/`routes_cando.list_cando_jobs`/`routes_md.list_md_jobs`
  (each in its own try → one broken engine can't sink the others) and normalizes+merges. Design
  filter unchanged. Tests: `test_sim_jobs.py` +6 (16 total). **Live:** endpoint serves 66 nodes
  (30 ox/6 L/5 mr/2 cando/23 namd).
- **Frontend `simulate_jobs.js`:** engine dispatch in `_rowCtx` — each engine's own exported
  label fns render its rows (oxDNA `jobDisplayName`/`runRowLabel`; mrDNA/CanDo `jobDisplayName`;
  NAMD reuses `mdJobRowCtx` for its production/replica labels + seeded/remote badges + hourglass).
  `jobs_panel_model.js` gained `engineOf(job)` so `statusKeyFor` resolves per-row in a mixed list
  (back-compat: single-engine panels omit it). Client-side filter: `_visibleNodes()` = active
  engine (LAMMPS grouped under oxDNA via `engineGroup`) unless `_showAllTypes`. New "Show all job
  types" checkbox + engine badges ([ox]/[mr]/[CD]/[MD]) shown only in all-types mode. Collapsible
  "Jobs" ox-card (`getSectionCollapsed('dynamics','simulate-jobs')`). `setActiveEngine(key)` wired
  from `engineSelector.onSelect` (main.js). Selection routes to that engine's tab + `panel.selectJob`
  (added `selectJob` to mrDNA + CanDo panels; oxDNA/NAMD already had it). LAMMPS viz still owned here.
- **Per-engine lists HIDDEN not deleted** (mrDNA/CanDo/NAMD `#*-jobs-list` ox-cards → `display:none`,
  matching oxDNA's already-hidden list): each panel still renders into its hidden node + `selectJob`
  populates its (visible) detail/health/viz cards, so NO panel internals changed. One VISIBLE list/tab.
- **UI reorg (partial):** Shape-comparison card MOVED from the oxDNA panel to section level (below
  the Jobs card) — it's cross-engine. NAMD cards reordered Anchors→E-field→Advanced→Viz→Metrics
  (configure→results, matching oxDNA/CanDo; was Viz/Metrics-first). **DEFERRED (reported as recs):**
  chevron standardization (bespoke `▸` per toggle → `icon--rotates`), mrDNA display-toggles → a
  Visualizations ox-card, NAMD detail-block internal restructure.
- **Tests:** frontend `simulate_jobs.test.js` +6 (engine filter/switch, show-all toggle+badges,
  mrDNA/NAMD selection routing, collapse). vitest 2580 pass. Backend `test_sim_jobs` 16 pass.
- **Dropped:** the old per-engine "Show jobs for all designs" checkboxes are now in hidden cards
  (the unified list is design-scoped; "all designs" is no longer surfaced — re-add if wanted).


## ⚡ AUTO ENGINE-POLICY + resource status line + GPU-busy dialog — SHIPPED 2026-07-10
Novice-proof engine selection ("press one button → optimal speed"). Driven by a
benchmark: **oxDNA-GPU is 13× (small) to 47× (large) faster than LAMMPS-CPU at matched
dt**, so oxDNA-GPU is the default; LAMMPS-CPU is a *fallback* only when the GPU is busy or
a design is protein-free but the GPU is occupied. Proteins → oxDNA (LAMMPS can't). Also
fixed the LAMMPS timestep (`1e-5→5e-3`, ~500× faster — see [[project_lammps_oxdna]]).
- **Backend:** `backend/core/engine_policy.py` (PURE — `cpu_slowdown_factor`,
  `recommend_engine`); `backend/api/routes_simulate.py` → `GET /simulate/recommendation`
  (reuses `has_proteins`, `md_vram.detect_gpu_activity`/`gpu_contention_summary`,
  `lammps_runner.free_cpu_cores`, `/jobs/active` ETA). **Busy semantics differ from
  `/md/gpu-status`:** our own running NAMD/oxDNA-CUDA job DOES count as busy (a new run
  would contend) and its ETA is shown; external hogs are named but can't be timed.
- **Frontend:** `client.simulateRecommendation`; `ui/simulate_policy.js` (PURE —
  `statusLineText`, `recommendationDialogCopy`, `dialogChoices`, `translateOxdnaToLammps`);
  `job_activity.confirmSimEngineLaunch` (cross-engine 3-way — **CPU = switch to LAMMPS**, not
  oxDNA-CPU); `ui/simulate_launch.js` factory (`refresh` renders `#simulate-status-line`,
  `guardOxdnaLaunch` shows the dialog + on "CPU" launches LAMMPS via `lammpsPanel.launch()`).
  oxDNA panel gained `simGuard` dep (falls back to `confirmGpuLaunch`); LAMMPS panel exposes
  `launch(overrides)`. **main.js Δ = +25, pure wiring.**
- **GOTCHA fixed:** `runBtn.addEventListener('click', _launch)` passed the click Event as
  `_launch`'s new `overrides` arg → wrap as `() => _launch()`.
- **Scoped out (not needed for correctness):** auto-*switching* the engine tab on a poll
  (the existing `runningEngineForPath` handler + the status line + the launch dialog already
  route correctly regardless of the selected tab). Reconsider if the UX wants it.
- **Tests:** backend `test_engine_policy` (7) + `test_routes_simulate` (3); frontend
  `simulate_policy.test` (11) + `simulate_launch.test` (6). Backend 4598 pass, frontend 2583
  pass, smoke 23/23. Live: endpoint serves oxDNA/CUDA when GPU free; status line renders
  "GPU: free · 13 cores free · Engine: oxDNA (GPU) — fastest here", 0 console errors.
  **NOT live-exercised:** the actual GPU-busy dialog (hard to force a busy GPU live; covered
  by the unit tests + the route's busy-branch test).


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

## Phase A2 — selector = dropdown, strip removed (SHIPPED 2026-07-08) → REVERTED 2026-07-10
A2 briefly turned the selector into a `<select>` dropdown and deleted the capability strip.
**Reverted 2026-07-10 at user request** ("we want the engine tabs back as well as the tags
listing what each is capable of") — the segmented-tab selector + capability strip are the
current shipped state again (identical to the U4/db4895f version; see next block). The
oxDNA Advanced-card chevron fix from A2 was in a different file and is unaffected.
- **RESTORED (current):** `engine_selector.js` + its test restored wholesale from db4895f —
  segmented control (`.engine-selector-btn`, `role=tablist`, `is-active`), `stripMount` param,
  `renderStrip` (one `.capability-chip` per `CARD_KEYS`; unsupported → `is-greyed` + reason
  tooltip). `index.html`: `#engine-capability-strip` div back under `#engine-selector-mount`;
  tab + strip + chip CSS restored (dropdown CSS removed). `main.js` passes `stripMount` again.
- **oxDNA Advanced-card chevron bug fixed** (unchanged by the revert): markup was
  `display:none;display:grid` (last wins → shown-on-load despite ▸), and the toggle opened with
  `style.display=''` which stripped the inline rule to `.ox-card__body`'s block, losing the
  2-col grid permanently. Now markup is `display:none` + grid props, toggle opens to
  `display:'grid'`. Starts closed, toggles none↔grid cleanly (verified in-app).
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
1. Wire the context button into **mrDNA, CanDo** (lighter — no Alpine; both have Coarse+Fine, so
   decide which action the context verb tracks — likely the primary/Coarse). *(LAMMPS is DONE —
   folded into the master card below; it's no longer a tab.)*
2. **Master card — full consolidation** of mrDNA/CanDo/NAMD: fold their bespoke `#*-jobs-progress`
   bars, status lines, Health/Metrics/detail blocks into the ONE global card built below. oxDNA +
   LAMMPS already feed it (substrate shipped); oxDNA delegates its rich detail/viz via `selectJob`.

## ⚡ LAMMPS folded into the unified job list + master card (SHIPPED 2026-07-10)
The auto engine-policy runs oxDNA-GPU when free, CPU-LAMMPS (same oxDNA2 FF) when the GPU is busy —
the user shouldn't know which. So **LAMMPS is no longer an engine tab**; every Simulate run appears
in ONE hierarchical list with a subtle **[L]** badge on LAMMPS rows, feeding the Phase-C master card.
- **Backend:** `backend/core/sim_jobs.py` (PURE — `normalize_oxdna_job`/`normalize_lammps_job`/
  `filter_nodes`; a node = the full job dict + `{engine,kind,production_state,is_child,viewable,n_units}`
  overlay so the frontend label fns work on it verbatim). `GET /simulate/jobs?design_source_path=&show_all=`
  in `routes_simulate.py` reuses `routes_oxdna.list_oxdna_jobs`'s enrichment (reconcile + out_of_date +
  `dir_size_bytes_cached`) + LAMMPS reconcile, then normalize+merge+filter. Never raises. Path filter
  mirrors `normalizeWorkspacePath`. Tests: `tests/test_sim_jobs.py` (10). Backend 4608 pass.
- **Frontend master card** `ui/simulate_jobs.js` (`initSimulateJobs({api,getWorkspacePath,designRenderer,
  oxdnaPanel,engineSelector,getFlexScale})→{refresh,selectJob,getSelected}`): unified list (job_tree +
  jobs_panel_model/render; `[L]` tag; `{engine,id}` selection) + master status/progress + a context
  Run/Stop/Resume button (`runControlState`) that is **LAMMPS-only** (hidden for oxDNA / no selection —
  an oxDNA job's Relax/Stop/Resume already lives in the oxDNA panel below the title, so showing one here
  too duplicated it; an `[L]` node has no other control so the master card owns its Stop / re-Run) + viz.
  **Viz dispatch:** an oxDNA node
  → `oxdnaPanel.selectJob(id)` (its rich viz stays in the oxDNA panel); an **[L]** node → this card OWNS
  `initLammpsDisplay` + a viz sub-card (relocated from the deleted LAMMPS panel). Markup = new `#simulate-jobs`
  block in `#simulate-body`. Pure helpers (`verbForNode`/`nodeIsActive`/`nodeIsResumable`/`masterProgressPct`/
  `masterStatusText`/`nodeDetailText`) unit-tested; jsdom factory drive in `ui/simulate_jobs.test.js`.
- **oxDNA panel:** its in-panel Jobs card is hidden (`#simulate-jobs` is the one list); added
  `launchRelax`/`autorefineJobIds` to its return API (the master RUN action + the `[AR]` tag). No internals removed.
- **Removed:** `lammps_jobs_panel.js` + its markup + test; `lammps` dropped from `engine_capabilities`
  ENGINE_KEYS/LABELS/CAPABILITIES + selector `panelEls`. **KEPT:** `lammps_jobs_logic.js`, `lammps_display.js`,
  `lammps_forces_setup.js` (orphaned now — the LAMMPS launch/forces UI is unreachable by design; LAMMPS is
  born only from the CPU fallback).
- **CPU fallback decoupled:** `simulate_launch.js::guardOxdnaLaunch` no longer `select('lammps')`; on CPU it
  calls `launchLammps(params)` which main.js wires to `api.createLammpsJob(buildLammpsPayload(...))` +
  `simulateJobs.refresh()`. Test updated.
- **main.js Δ:** ≈ pure wiring — removed `initLammpsJobsPanel`/`initLammpsForcesSetup` + anchor-glow/gizmo
  (net **−12 LOC**), added `initSimulateJobs` + the direct-create fallback helper.
- **Tests/verify:** frontend `vitest` 2576 pass; `just smoke` 23/23. Backend `just test` 4608 pass.
  **Live:** engine tabs = oxDNA/mrDNA/CanDo/NAMD (no LAMMPS); `#simulate-jobs` list + master card + viz DOM
  present; `#lammps-jobs-panel` gone; `GET /simulate/jobs` serves 36 merged nodes (30 ox + 6 [L]) in-browser;
  0 console errors. **NOT live-exercised (doc-context limit, MV-28 family):** the POPULATED per-design list
  rendering an actual [L] row + master card + [L] viz — API `design/load` doesn't set the frontend
  `_workspacePath` so the per-design filter returns [] in Playwright. Covered by the vitest factory drive
  (real factory → mock nodes → asserts the [L] badge, viz-show, run-control + selection dispatch). → owes an
  MV row for the live populated [L] path.
- **Interim asymmetry (documented):** oxDNA viz still in the oxDNA panel; only LAMMPS viz is in the master
  card. Full oxDNA-viz + mrDNA/CanDo/NAMD consolidation is the Phase-C follow-up above.

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

## Simulate dropdown defaults to the running engine (2026-07-09)

User request: opening a design that is already simulating should default the Simulate
engine dropdown to that engine (open a file running a NAMD job → dropdown = NAMD).
Tie-break: the most recent job when several are busy on the same design.
- **Backend:** `/api/jobs/active` (`routes_jobs._collect_active`) now carries `created_at`
  (epoch seconds) on every entry — all 5 job models already have it. Needed for the
  most-recent tie-break; nothing else consumed a timestamp before.
- **Pure decision** `runningEngineForPath(activeJobs, path)` in
  [job_activity.js](frontend/src/ui/job_activity.js): filters busy (running/preparing)
  jobs matching the normalized `design_source_path`, sorts by `created_at` desc, returns
  the winner's engine key, **mapping the backend `'md'` → the selector's `'namd'`** (the
  other four keys already match). 5 unit tests.
- **Wiring** (`main.js`, thin): a `nadoc:workspace-path-change` listener (fires on every
  real workspace file-open via `_setWorkspacePath`) fetches active jobs and, when the
  loaded design has a busy job, calls `engineSelector.select(eng)`. No-op when nothing is
  busy (leaves the selector as-is). +import +listener, no cohesive logic.
- **Live-verified** on the running dev servers: opened `6hbx100_noT.nadoc` (real active
  NAMD job) via the library row → dropdown defaulted to `namd`, zero console errors.

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

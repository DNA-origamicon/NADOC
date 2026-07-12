# MD Sidebar UX Audit (2026-06-11)

## Cluster card promoted + connect chip moved + early-stop de-experimentalized — SHIPPED 2026-07-11
- Dropped the "(experimental)" tag from the early-stop toggle label + tooltip (well-tested now).
- **Cluster (Alpine) card pulled OUT of `#md-jobs-detail` to a top-level, always-visible card**
  (parity with the Viz card; verified in-app). It now leads with the **connect chip**
  (`#md-cluster-connection-mount` relocated from the Advanced card into `#md-jobs-cluster-body`
  at init, `main.js`) so connecting is reachable BEFORE any Alpine job exists (fixed audit
  friction #1/#12). The per-job controls (submit/resume/ensemble/rollup/status/resume-history)
  still show/hide with the selection; `_clearSelectedJob` resets those parts but keeps the card.
  `_applyJobState` no longer toggles the card's own visibility. vitest 2659; smoke 21 pass.
- **Alpine vs local protocol AUDIT (2026-07-11):**
  - **#2 FIXED** — run-target radios (Local/Alpine) moved from the collapsed Advanced card into
    the Cluster card (after the connect chip), so run-location controls sit together + are
    visible. HTML move; ids unchanged; verified in-app.
  - **#3 FIXED** — `mdRunControl` now takes `runTarget`; a fresh launch with target=Alpine
    relabels the primary button **"▶ Prepare for Alpine"** (it only preps+queues; a separate
    Submit follows). Run-target radio `change` repaints it; stop/resume labels unchanged. Test
    added.
  - **#8 FIXED** — `MdJob.pending_scancel` (load-setdefault). Stop on a disconnected remote job
    marks it stopped locally AND sets `pending_scancel` (`routes_md.stop_md_job`); the next
    connected `poll_remote_jobs` pass drains it (issues scancel, clears flag) even though the job
    is no longer "active" — so the SLURM job doesn't keep burning SU. Frontend toasts the deferred
    message. Tests: `test_poll_remote_jobs_drains_pending_scancel`,
    `test_stop_disconnected_defers_scancel`.
  - **#6 FIXED** — two parts. (a) A successful `POST /cluster/connect` now kicks
    `poll_remote_jobs` immediately (`routes_cluster.py`), so a run that FINISHED while the
    session was down gets its results fetched on reconnect (not up to ~30 s later) — this also
    drains #8's deferred scancels. (b) Frontend nudge: pure `mdRemoteReconnectPrompt(jobs,
    clusterState)` → an amber `#md-jobs-cluster-reconnect-note` in the Cluster card ("N Alpine
    runs in flight — reconnect to monitor and fetch results") shown when submitted Alpine jobs
    are queued/running/preparing AND the session isn't connected. Wired to
    `nadoc:cluster-state-change` + every `_fetchJobs`. Tests: `test_cluster_connect_kicks_remote_poll`
    (backend), `mdRemoteReconnectPrompt` (frontend).
  - #5 by design — no live metrics/health for remote runs (SLURM has no local WS).
  - #11 minor — ensemble button gated on connection though `ensemble-production` staging works
    offline (only submit needs the session).

## NAMD detail declutter — SHIPPED 2026-07-11 (the loose stack below Health)
Audited the loose items under the Health card; user directed the cleanup. Done in
`index.html` + `md_jobs_panel.js`:
- **Removed (derelict/redundant):** the duplicate detail status line (`#md-jobs-detail-status`,
  redundant with the master job card); the invisible progress bar (`#md-jobs-progress`,
  `display:none`, superseded by the master bar) + its ~150 lines of dead render code
  (`_showPreparingProgress`/`_renderPrepProgress`/`_fmtEta`/`_renderProgress`/
  `_productionRunSummary`/`_productionAdvisoryText`/`_productionFailureText`, + orphaned
  `_statusLabel`/`_latestHealthForSegments`); the "Load Frames" button (`#md-jobs-frame-controls`,
  duplicated the Display-MD radio → `_startMdDisplay`); the separate mid-run early-stop toggle.
- **New "Cluster (Alpine)" card** (`#md-jobs-cluster-card`, collapsible, shown only when the
  selected job has cluster content): Submit-to-Alpine + Resume buttons, Ensemble replicas,
  ensemble roll-up, resume history, and an Alpine-only status line (`#md-jobs-cluster-status`,
  the awaiting-submit / SLURM-queued states rescued from the deleted status line). Visibility =
  OR of its parts, computed in `_applyJobState`.
- **Early-stop unified:** the ONE Advanced toggle (`#md-jobs-early-stop`) is now BOTH the launch
  default AND the live mid-relax control — for a running local relaxation a change POSTs the
  override (`setMdEarlyStop`) with the `#md-jobs-early-stop-pending` badge; otherwise it's the
  create default. Gated by `_isLiveRelax(job)`. The old `#md-jobs-early-stop-live*` removed.
- **Error box moved into the Health card body** (`#md-jobs-detail-error`).
- Timeline unchanged (already relocated to the master jobs card by main.js).
- vitest **2659**; smoke 21 pass (2 pre-existing unrelated); **DOM restructure verified in the
  running app** (throwaway Playwright: cluster card present, error in Health body, all removed
  ids absent, submit/resume/ensemble/rollup/resume-history inside the cluster card).

## Production-job button mislabeling — FIXED 2026-07-11 (follow-up to Phase 2)
User: selecting a RUNNING production job showed the primary control as "■ Stop Relax" +
grayed "Start Production". Backend was CORRECT (job `7456d0130168` `run_kind='production'`,
seeded from parent) — purely a frontend labeling bug: `mdRunControl` hardcoded verb 'Relax'
+ keyed off `mdJobIsActive` regardless of `run_kind`, and `_renderProductionControls` only
enabled its button for a `completed` job. **Fix (`md_jobs_panel.js`):** the primary control
governs the RELAXATION lifecycle only — `mdRunControl` returns "▶ Relax" DISABLED when a
production child is selected (`mdIsProductionChild`). The Production button becomes that
child's Stop/Resume control via pure `mdProductionAction(job)` → stop (running) / resume
(stopped-failed) / start (relax root or completed→chain); its click branches to
`_stopSelected(prodBtn)`/`_resumeSelected(prodBtn)` (both now take a btn arg). Resume states
get a tooltip "Stopped jobs can be resumed from their last checkpoint." (both the Production
button AND the primary Relax control's Resume). `_paintRunControl` now honours `rc.disabled`.
Tests: `mdRunControl` production-child (disabled) + `mdProductionAction` (4). vitest 2659;
smoke 21 pass (2 pre-existing unrelated). **NOT auto-verified in-app** (per-design job select
is the MV-28 doc-context limit) — user has the live repro to confirm by re-clicking.

## Re-audit 2026-07-11 (post Simulate-panel overhaul) — phased fix in progress
The sidebar is now three pieces: master job card (`simulate_jobs.js`), NAMD panel
detail (`md_jobs_panel.js`), Display-MD overlay (`md_panel.js`). Fresh audit found the
biggest live-update hole is a **local running job freezing permanently on a dropped
detail WebSocket** (no reconnect; the documented `_pollTimer` REST fallback was DEAD
CODE, never armed; the one "backend not responding" warning wrote to a `display:none`
element `#md-jobs-namd-status`). The timeline spinner kept animating → card *looked*
live while frozen.

**Phase 1 — SHIPPED 2026-07-11 (`md_jobs_panel.js`).** Added a detail-WS **watchdog**
(`_startWsWatchdog`/`_wsWatchdogTick`, 5 s tick, `_WS_STALE_MS`=12 s): reconnects a
dropped socket, force-reopens a silent-but-open (wedged) one, and on a failed backend
probe surfaces a now-VISIBLE "backend not responding" banner (`_setBackendStale`
un-hides `#md-jobs-namd-status`). Decision is pure+unit-tested (`mdWatchdogDecision`:
disarm/reconnect/refresh/idle — local live job only; terminal/remote → disarm). Armed
in `_openDetailForJob`'s local branch, torn down on terminal/remote select + panel
`onClose`. Dead `_pollTimer` removed. Tests: `md_jobs_panel.test.js` mdWatchdogDecision
(4). Full vitest **2654** green. **NOT exercised with a real dropped WS on a live NAMD
job** (can't force it); pure logic pinned, smoke gate passed except two PRE-EXISTING
`helices`-teardown console errors from concurrent uncommitted work (unrelated).

**Phase 2 — SHIPPED 2026-07-11 (`simulate_jobs.js` + backend `namd_metrics.py`/`routes_md.py`).**
Master-card correctness: (a) `engineLabel(node)` — `masterStatusText`/tooltip no longer
mislabel NAMD/mrDNA/CanDo as "oxDNA · running" (regression-tested). (b) Backend stamps a
live within-segment `progress_fraction` on RUNNING NAMD nodes (`namd_metrics.overall_fraction`
pure + `_namd_running_fraction` reads the running segment's log in `list_md_jobs`; flows to
`/simulate/jobs` via `normalize_md_job`'s `**d`); `masterProgressPct` NAMD branch prefers it
so a single-segment production advances instead of sitting at 0 %. (c) The NAMD panel's WS
state handler now calls `_notifyIfJobsChanged()` so a selected job's status transition (e.g.
completing + spawning children) wakes the idle master. Tests: `overall_fraction` (4, backend),
`masterStatusText`/`masterProgressPct` NAMD (frontend). `just test-smart` → **FULL 4682 pass**
(foundational MD change); vitest 2655.

**Phase 3 — SHIPPED 2026-07-11 (`md_jobs_panel.js` + `md_panel.js`).** Display-MD robustness:
(a) design↔job guard in `_refreshMdDisplay` — refuses to stream a job whose
`design_source_path` ≠ the open design (was: paint one structure's trajectory onto another,
possible in show-all / mid-switch). (b) re-check `displayToggle.checked` + tab visibility
AFTER the `_fetchDisplayMeta` await (toggle-off no longer clobbered back on). (c) `md_panel.js`
unexpected-close emits `md-display-state:error` so the readiness dot doesn't stay green over a
dead socket. (d) `_setDisplayIndicator` warming→error timeout (`_MD_WARMING_TIMEOUT_MS`=30 s)
so a hung load can't sit amber forever. The **early-stop toggle stuck-disabled** finding is
resolved transitively by Phase 1 (watchdog reconnects → next push clears pending). The **amp
slider inert in beads/ballstick** finding is MOOT — `#md-amp` lives in the hidden `#md-panel`,
unreachable (derelict, see P5). vitest 2655; smoke 21 pass (2 pre-existing unrelated
`helices`-teardown failures from concurrent work).

**Phase 4 — SHIPPED 2026-07-11 (`md_jobs_panel.js`).** (4b) `_maybePollRemote` edge-triggers
one final `_fetchJobs`+`_fetchJobMetrics` on the active→idle transition (`_hadActiveRemote`),
so a just-completed Alpine replica's cluster health_samples fill the ensemble grid instead of
staying on the remote note. (4a) The ≤30 s supervisor auto-resume window is ACCEPTED as-is:
it self-heals, and Phase 1's watchdog keeps the local status fresh; a distinct backend
"awaiting-auto-resume" flag would need another full-suite cycle for marginal value — deferred.

**Phase 5 — DOCUMENTED (no risky deletions).** The derelict/hidden inventory is INTENTIONAL,
not accidental cruft: `appendMdProduction` client method + `/md/jobs/{id}/production` are
retained-but-app-dead legacy (kept + doc-header-tested on purpose); `/md/jobs/{id}/health` +
`/md/browse` are orphaned-by-design; the whole `#md-panel` manual UI (scrubber/play/live/load/
amp) is `display:none` with its controller reused programmatically — **do NOT delete the markup:
`md_panel.js:136,160` read `body`/`heading` UNGUARDED, so removing `#md-panel` throws at factory
init.** The `#md-jobs-panel-heading`/`-arrow` reads (`md_jobs_panel.js:510-511`) are harmless
guarded null-reads. Left in place; recorded here so they're not re-investigated as bugs.



Audit of every MD sidebar feature: failure modes, whether the error reaches the
user, whether it can leave the UI stale/frozen, and test coverage. Ranked
highest-risk first. Items marked **[FIXED 2026-06-11]** were addressed in the
Display-MD streaming pass (see code refs); the rest are open findings.

Data flow recap: `md_jobs_panel.js` (the sidebar) drives launch/stop/resume/delete
and the Display-MD toggle. Display routes through `md_panel.js` (`mdDisplayController`)
→ `/ws/md-run` (`backend/api/ws.py`) for trajectory frames, and `/ws/md-jobs/{id}`
for status. Resolver: `routes_md._latest_display_segment` (display endpoint) and
`md_import.resolve_md_config`/`_latest_existing_dcd` (the WS load).

---

## R1 — Live Display MD never renders + NS_BINDING_ABORTED  **[FIXED 2026-06-11]**
**Risk: highest** — the headline bug. While the toggle is on, MD positions never
appear and Firefox logs aborted requests.
Root causes (all three confirmed by reproduction):
1. `ws._refresh_latest_sync` rebuilt the entire `mda.Universe(psf, dcd)` every 5 s
   poll (signature cache never hits on a growing DCD). Measured 1.7 s for a 0.5 M-atom
   system and worse for multi-GB trajectories → polls back up, frames lag forever.
   → **Fixed:** reuse the Universe, re-read only the trajectory via
   `Universe.load_new` (0.003 s; verified it *does* discover appended frames — the
   broken-`_reopen` lesson does not apply to `load_new`).
2. Seeking the mid-write final frame could surface a torn frame as `{type:error}`,
   which `md_panel._restoreDesign` turns into a blank scene. → **Fixed:** safe-back
   fallback (try last frame, fall back one) on top of MDAnalysis flooring n_frames
   by file size.
3. `displayLatest`/`prewarmLatest` tore down an in-flight WS (`_openWebSocket` closes
   `_ws` mid-handshake) → NS_BINDING_ABORTED. → **Fixed:** `decideReload` returns
   `wait-in-flight` when a load for the same config+mode is pending; in-flight tracked
   by `_loadInFlight`/`_loadConfigPath`.
Tests: `test_ws_helpers.py::test_md_run_ws_get_latest_follows_growing_trajectory` +
`…_tolerates_torn_final_frame`; `md_display_state.test.js` (decideReload table).

## R2 — Display resolver mismatch: WS streams the stale pre-checkpoint DCD  **[FIXED 2026-06-11]**
**Risk: high** — silent wrong-data, not a crash. The `/display` endpoint resolves the
newest `<seg>.contN.dcd` continuation, but the frontend only forwards `config_path`;
the WS then re-resolves via `md_import._latest_existing_dcd`, which ignored `.contN.dcd`
and streamed the stale base `<seg>.dcd`. After a Resume Production, Display MD showed
pre-resume frames. → **Fixed:** `_latest_existing_dcd` now prefers the newest
`<seg>.cont*.dcd`, matching `_latest_display_segment`. Tests in `test_md_import.py`.
Residual: the two resolvers are still independent code paths that must be kept in
sync by hand — a future cleanup could have the WS accept the explicit
`trajectory_path` the `/display` endpoint already returns.

## R3 — `get_latest` "No trajectory loaded" race during a slow load
**Risk: medium** — error spam + a transient blank. If the 15 s display refresh (or a
representation-change) pokes the controller while `_load_sync` is still running for a
large system, the old code could `_sendPoll()` before `ready`, and the backend replies
`{type:error,"No trajectory loaded"}`. The `wait-in-flight` guard (R1.3) removes the
*premature reopen*, but a `get_latest` arriving between WS-open and `ready` is still
answered with an error rather than being queued until ready. Mitigated, not fully
closed. No test. Suggest: backend buffers/ignores `get_latest` until the first load
completes, or replies `{type:log}` instead of `{type:error}`.

## R4 — Relax launch ("▶ Relax"): long prep with only a toast on failure
**Risk: medium.** `_runRelax` POSTs solvation/prep; failures surface as
`showToast('Prep failed' / 'Error')`. Prep is long-running and there is no determinate
progress in the sidebar during package build (op_progress exists but isn't wired here).
A mid-prep navigation away or backend exception can leave the preset controls in a
disabled/ambiguous state. No automated test of the prep→queued→running transition.

## R5 — Start/Stop are fire-and-forget; status only via WS reconcile
**Risk: medium.** `_startSelected`/`_stopSelected` POST `/start`,`/stop` and toast
"requested". Actual state change depends on the `/ws/md-jobs/{id}` reconcile loop. If
the WS is down (`onclose` → single REST refresh, no auto-reconnect backoff loop), a
stopped/started job can display a stale status chip until the next manual action or
`_ensureSelectedSubscription` tick. Stop has no confirmation and no "stopping…" state.
Covered indirectly by `test_md_milestone1.py`/`test_md_runner_proceeds.py` at the API
layer; the *UI* stale-state path is untested.

## R6 — Auto-resume supervisor invisibility
**Risk: medium.** `reconcile_job_status` (namd_runner) can move an interrupted job back
through `running`. The sidebar reflects this only if subscribed. A job that auto-resumes
while the panel shows a different selection won't update its chip until `_fetchJobs`
(no periodic full refresh while a detail WS is open). User can believe a run is dead
when it has resumed. `resumeKindForJob` is unit-tested; the supervisor→UI propagation
is not.

## R7 — Resume / Resume Production button-state correctness
**Risk: medium-low.** `resumeKindForJob` only returns non-null for `status==='stopped'`
with a pending segment; `failed` jobs get no resume affordance even when the failure was
transient (e.g. a torn-frame health-gate trip). `_prodMode` ('append' vs 'resume') is
derived in `_renderProductionControls` from the tag substring `'prod'` — brittle if a
segment is ever named with "prod" in an unexpected place. `resumeKindForJob`/
`resumeKindForJob`-driven relabel are unit-tested; `_prodMode` selection is not.

## R8 — Delete: guarded server-side, weakly guarded client-side
**Risk: low-medium.** `DELETE /md/jobs/{id}` refuses while running (good), but the
sidebar Delete button shows only a toast on rejection and no confirm dialog before
`rmtree` of a multi-GB job dir. Accidental deletes are unrecoverable. No "are you sure".
Server refusal-while-running is covered; the irreversible-delete UX is not.

## R9 — Display mode switching (nadoc / ballstick / beads) reload churn
**Risk: low-medium.** Changing the scene representation while Display MD is live fires
`nadoc:representation-change` → `_openWebSocket()` (full reload) when the stream mode
flips nadoc↔ballstick. That reload is legitimate, but it still closes the prior socket
(an expected abort) and re-runs the heavy `_load_sync`. `canReapplyFrame` now gates
stale cached-frame reuse (unit-tested), but the reload cost on representation toggling
is unmitigated. `beads` mode shares the `nadoc` stream and only differs in overlay
sizing — correct, but bead-size changes don't re-render until the next frame.

## R10 — Live vs scrub playback / frame seek  **[FIXED 2026-07-01]**
**Risk: low.** Scrub `seek` is robust (clamped server-side; now also lazily reloads the
Universe when a seek lands beyond its stale frame count — see md-panel-status). The
"Fetching…" pulse could previously sit forever if a poll never returned. → **Fixed:**
per-interval pacing via `nextLivePollAction` (md_display_state.js) — never stacks a poll
on an outstanding one, and after `_LIVE_POLL_TIMEOUT` (15 s) surfaces a warn + re-polls
instead of pulsing indefinitely. Pure fn unit-tested (`md_display_state.test.js`); the
live-bar DOM wiring itself is not exercised in a live-app session.

## R11 — PBC/Kabsch alignment quality  **[PARTIAL 2026-07-01]**
**Risk: low (correctness, not crash).** `_seek_sync` does sequential unwrap + dynamic-T
+ hybrid nearest-image + Kabsch with a gimbal-lock inlier re-fit. Heuristic-heavy; a
late-frame >60° drift can still mis-align. → **Numerical pin added:**
`test_md_run_ws_dcd_alignment_matches_design_eq` feeds a frame == design geometry and
asserts rigid-atom RMSD < 0.5 Å (catches scale/axis/broken-Kabsch regressions). Does NOT
pin the hard late-frame >60°-drift case (would need a real drifted trajectory). The
`view_whole.xtc`-missing warnings are still Output-log only.

## R12 — Displacement-amplitude slider / prewarm / health-gate display
**Risk: low.** Amp slider only affects `nadoc` mode (`applyFemPositions(updates, _amp)`);
silently inert in ballstick/beads — no UI hint. Prewarm (`prewarmLatest`) opens a
hidden WS to warm the cache; `stopPrewarm` is guarded by `_displayVisible` and could
leak a socket if toggled rapidly (now also clears `_loadInFlight`). Health-gate dots
render from job state; a gate trip shows as a failed segment but the human-readable
reason lives in the Output log, not the chip.

## R13 — Crossover extra-base beads frozen under Display MD  **[FIXED 2026-06-11]**
**Risk: low-medium (wrong-data display).** In `nadoc` mode the helix renderer's
`applyFemPositions` (helix_renderer.js) moves beads/cones/slabs but never the
extra-base crossover beads — those live in the `crossoverConnections` group and are
arc-interpolated between endpoint nucleotides only at build/cluster/unfold/deform time.
So with Display MD on, crossover endpoints tracked the trajectory while the extra bases
stayed at their geometry-build positions. → **Fixed (Option A, geometric arc tracking):**
`design_renderer.applyFemPositions` now calls `applyClusterCrossoverUpdate([])` after the
helix overlay, re-interpolating every arc from the live (MD-moved, or reverted) endpoint
positions. Display-only; reuses the tested cluster-update path. **Note (Option B not done):**
true per-base MD positions are blocked by key collision — `atomistic.py` stamps every
extra base in a crossover with the *source* nucleotide's `(helix_id, bp_index, direction)`,
so they can't be routed to distinct beads without unique keys end-to-end.

---

### Coverage summary
- **Now tested:** live-grow + torn-frame WS path, `.contN.dcd` resolver, the
  open/reuse/wait reload decision, frame-apply gating, mode selection.
- **Still untested (ranked):** R3 load-race, R5 stop/start stale-state, R6 supervisor→UI,
  R4 prep progress, R8 delete confirm, R10 live-bar hang, R11 alignment numerics.
- **Highest remaining product risk:** R3 (transient blank during slow loads) and R6
  (auto-resume invisibility) — both are "UI says one thing, backend is doing another"
  classes, the same family as the original bug.

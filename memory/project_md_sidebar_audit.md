# MD Sidebar UX Audit (2026-06-11)

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

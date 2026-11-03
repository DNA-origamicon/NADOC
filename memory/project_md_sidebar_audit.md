
# MD Sidebar UX Audit (2026-06-11) — topic guide

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

<a id="md-sidebar-ux-audit-2026-06-11"></a>
- [MD Sidebar UX Audit (2026-06-11)](details/project_md_sidebar_audit/01-md-sidebar-ux-audit-2026-06-11.md#md-sidebar-ux-audit-2026-06-11)

<a id="early-stop-card-moved-under-the-jobs-card--shipped-2026-08-07"></a>
- [Early-stop card moved under the Jobs card — SHIPPED 2026-08-07](details/project_md_sidebar_audit/01-md-sidebar-ux-audit-2026-06-11.md#early-stop-card-moved-under-the-jobs-card--shipped-2026-08-07)

<a id="cluster-card-promoted--connect-chip-moved--early-stop-de-experimentalized--shipped-2026-07-11"></a>
- [Cluster card promoted + connect chip moved + early-stop de-experimentalized — SHIPPED 2026-07-11](details/project_md_sidebar_audit/01-md-sidebar-ux-audit-2026-06-11.md#cluster-card-promoted--connect-chip-moved--early-stop-de-experimentalized--shipped-2026-07-11)

## Health card: a spinner may ONLY mean "in flight" — SHIPPED 2026-07-31

The card decided "show a spinner" from the *rendered* value: `jobActive && value === '—'`. That
conflated three different situations, and the two that were not in flight spun forever — which is
how a run whose health probe was dead (see `project_md_job_system.md`, orphan adoption) looked
identical to one about to report.

**New pure module `frontend/src/ui/md_health_tiles.js`** — `mdHealthTileStates(...)` maps job +
sample + probe to `TILE_STATE.VALUE | PENDING | UNAVAILABLE | FAILED` per tile. It imports
**nothing** (importing `md_jobs_panel.js` would drag the whole DOM surface into every consumer), so
`active` is passed in by the panel, which owns `mdJobIsActive`. `_renderMetrics` draws
`makeSpinner` for **PENDING only**; every other absence is `—` plus a `title` saying why.

Rules, in order: a present value always wins (`0` is a reading, not an absence) → job not active =
UNAVAILABLE → `health_probe.enabled === false` = UNAVAILABLE with its reason → `last_error` =
FAILED → Broken bp / Shell charge consult the sample's `diagnostics` (`null` = predates the field,
so **old jobs on disk never spin**; `"ok"` + null value = "measured as none"; anything else =
FAILED with that text) → **watchdog**: no sample in `2 × interval_s` = FAILED, which bounds every
remaining spinner in time → otherwise PENDING. The log-derived tiles (Temp / Pressure / Speed) do
not consult the probe at all — they come from the WS log parse, which is why they kept working.

`mdLatestStageLabel` gained a last-resort fallback to `job.segments[current_segment_idx].stage`, so
"Latest" is never unknown mid-run.

Pins: `md_health_tiles.test.js` (16), 6 DOM tests in `md_jobs_panel.test.js` driving the real panel
and counting `.nadoc-spinner` nodes, 2 in `md_stage_timeline.test.js`. Verified in a real browser
against the reported fixture: 0 spinners, four tiles `—` with reasons, Latest correct.

<a id="namd-detail-declutter--shipped-2026-07-11-the-loose-stack-below-health"></a>
- [NAMD detail declutter — SHIPPED 2026-07-11 (the loose stack below Health)](details/project_md_sidebar_audit/02-namd-detail-declutter--shipped-2026-07-11-the-loose-stack-below-h.md#namd-detail-declutter--shipped-2026-07-11-the-loose-stack-below-health)

<a id="production-job-button-mislabeling--fixed-2026-07-11-follow-up-to-phase-2"></a>
- [Production-job button mislabeling — FIXED 2026-07-11 (follow-up to Phase 2)](details/project_md_sidebar_audit/02-namd-detail-declutter--shipped-2026-07-11-the-loose-stack-below-h.md#production-job-button-mislabeling--fixed-2026-07-11-follow-up-to-phase-2)

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

<a id="r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint-dcd--fixed-2026-06-11"></a>
- [R2 — Display resolver mismatch: WS streams the stale pre-checkpoint DCD  **[FIXED 2026-06-11]**](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint-dcd--fixed-2026-06-11)

<a id="r3--get_latest-no-trajectory-loaded-race-during-a-slow-load"></a>
- [R3 — `get_latest` "No trajectory loaded" race during a slow load](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r3--get_latest-no-trajectory-loaded-race-during-a-slow-load)

<a id="r4--relax-launch--relax-long-prep-with-only-a-toast-on-failure"></a>
- [R4 — Relax launch ("▶ Relax"): long prep with only a toast on failure](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r4--relax-launch--relax-long-prep-with-only-a-toast-on-failure)

<a id="r5--startstop-are-fire-and-forget-status-only-via-ws-reconcile"></a>
- [R5 — Start/Stop are fire-and-forget; status only via WS reconcile](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r5--startstop-are-fire-and-forget-status-only-via-ws-reconcile)

<a id="r6--auto-resume-supervisor-invisibility"></a>
- [R6 — Auto-resume supervisor invisibility](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r6--auto-resume-supervisor-invisibility)

<a id="r7--resume--resume-production-button-state-correctness"></a>
- [R7 — Resume / Resume Production button-state correctness](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r7--resume--resume-production-button-state-correctness)

<a id="r8--delete-guarded-server-side-weakly-guarded-client-side"></a>
- [R8 — Delete: guarded server-side, weakly guarded client-side](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r8--delete-guarded-server-side-weakly-guarded-client-side)

<a id="r9--display-mode-switching-nadoc--ballstick--beads-reload-churn"></a>
- [R9 — Display mode switching (nadoc / ballstick / beads) reload churn](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r9--display-mode-switching-nadoc--ballstick--beads-reload-churn)

<a id="r10--live-vs-scrub-playback--frame-seek--fixed-2026-07-01"></a>
- [R10 — Live vs scrub playback / frame seek  **[FIXED 2026-07-01]**](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r10--live-vs-scrub-playback--frame-seek--fixed-2026-07-01)

<a id="r11--pbckabsch-alignment-quality--partial-2026-07-01"></a>
- [R11 — PBC/Kabsch alignment quality  **[PARTIAL 2026-07-01]**](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r11--pbckabsch-alignment-quality--partial-2026-07-01)

<a id="r12--displacement-amplitude-slider--prewarm--health-gate-display"></a>
- [R12 — Displacement-amplitude slider / prewarm / health-gate display](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r12--displacement-amplitude-slider--prewarm--health-gate-display)

<a id="r13--crossover-extra-base-beads-frozen-under-display-md--fixed-2026-06-11"></a>
- [R13 — Crossover extra-base beads frozen under Display MD  **[FIXED 2026-06-11]**](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#r13--crossover-extra-base-beads-frozen-under-display-md--fixed-2026-06-11)

<a id="coverage-summary"></a>
- [Coverage summary](details/project_md_sidebar_audit/03-r2--display-resolver-mismatch-ws-streams-the-stale-pre-checkpoint.md#coverage-summary)

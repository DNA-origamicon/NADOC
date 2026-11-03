# Live reconfigure — toggle floor / E-field / anchors mid-session (2026-06-23) — supporting detail

[Topic head](../../project_oxdna_efield.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Live reconfigure — toggle floor / E-field / anchors mid-session (2026-06-23)
Before this, a live session composed its element set ONCE at start and only the field's
magnitude/direction could be re-aimed in place; toggling the floor or E-field ON after starting did
nothing (the floor card's `onChange` wasn't even wired to the live controller, and the field card's
re-aim path no-ops when the session started fieldless — the engine has no `string` force to mutate).
Now any composition change recomposes the running engine **seamlessly from the current pose** (user
chose seamless over restart-from-relaxed).
- **Backend.** `LiveSession.reconfigure(rebuild_fn, field_oxdna, field_dir)` queues a recomposition;
  the worker loop (`_apply_pending_reconfig`, now using **manual `__enter__`/`__exit__`** instead of
  `with self._session:` so it can swap engines mid-loop) snapshots the current pose
  (`_OxpyStepper.snapshot_seed()` → `reconfig_seed.dat`), tears down the old engine, calls the
  route-supplied `rebuild_fn()` → `(new_session, new_frame_builder)` seeded from that pose, enters the
  new engine, sets the field, and keeps stepping. `POST /oxdna/live/{id}/reconfigure`
  (`LiveReconfigureRequest`, same field/surface/anchors/anchor_stiff as start) resolves elements via the
  shared `_resolve_live_elements` + `_build_live_engine` helpers (extracted from `start_oxdna_live`, so
  start and reconfigure run identical setup), pre-validates field-needs-≥1-anchor on the request thread
  (`resolve_anchor_particles` needs only the design, not the conf), and queues the rebuild. `LiveSession`
  gained `design`/`design_ref` attrs + `rundir`/`burst_steps` properties so the route can rebuild.
- **Frontend.** `oxdna_live_controller` replaced `onFieldChanged` with **`onElementsChanged`** (kept as
  an alias) driven by a pure **`reconfigSig(el)`** = a composition signature that EXCLUDES field
  magnitude/dir (those stay the in-place re-aim) but includes field on/off, surface on/off+params, and
  anchors. Same sig → field re-aim (`updateOxdnaLiveField`); changed sig → debounced (350 ms, engine
  rebuild is heavy) `reconfigureOxdnaLive` POST, gated on field-needs-anchor. `main.js` wires the floor
  card's `onChange` (was unwired) and the anchors card's `onChange` to `onElementsChanged` too. `client.js`
  `reconfigureOxdnaLive`.
- **Verified.** Backend `test_oxdna_live_session.py` +3 (GPU-free worker engine-swap: old snapshotted+closed,
  new entered+field-set, keeps stepping; reconfigure 404 + field-needs-anchor 400). Frontend
  `oxdna_live_controller.test.js` +8 (`reconfigSig` stability/sensitivity; floor-toggle→reconfigure,
  field-enable-after-fieldless-start→reconfigure, magnitude-change→re-aim-not-reconfigure,
  field-without-anchor→warn-no-POST). Backend 3074 / frontend 1666 / smoke 23 green. **REAL oxpy
  end-to-end probe on this box:** start free-dynamics from a relaxed seed → reconfigure adds a hard floor
  → stays `running`, keeps stepping, new forces file has `repulsion_plane`, structure moved only 0.27 nm
  median between pre/post frames (SEAMLESS, no teleport). The in-browser toggle-floor/field-mid-Live
  gesture is human-eye → folded into **MV-OXLIVE-CUDA**.

## Out-of-date job guard — design edited after a relax (2026-06-23)
Editing the design after running a job then starting live/production resolved the CURRENT design's
anchor selections against the job's FROZEN snapshot topology → particle indices out of range →
internal-server-error (the rundir prep runs synchronously in the request handler). Now guarded:
- **Fingerprint.** `backend/core/oxdna_staleness.py`: `oxdna_design_fingerprint(design)` = sha256 of the
  oxDNA-build-relevant fields (`helices, strands, crossovers, deformations, extensions, overhangs,
  overhang_connections, forced_ligations, photoproduct_junctions`) — topology + sequence + geometry
  SOURCES. EXCLUDES display layers (cluster transforms/joints — Three-Layer display, never in
  `_geometry_for_design`; camera, metadata, feature log, proteins). So a cluster drag / camera move does
  NOT mark jobs stale; only a structural/sequence/geometry edit does. `OxdnaJob` gained
  `design_fingerprint` + `feature_log_position` (set at creation; children inherit the parent's). Survives
  the design.json round-trip (verified).
- **out_of_date flag.** `GET /oxdna/jobs` (+ `/{id}`) compute the current design's fingerprint once and
  tag each job `out_of_date` (= job fp ≠ current fp; old jobs derive their fp from the frozen snapshot,
  cached by job_id). Frontend shows a ⚠ on stale rows (`oxdna_jobs_panel.jobOutOfDate`); `main.js`
  refetches the list on every `currentDesign` change so the markers appear immediately.
- **Guard (the crash fix).** `routes_oxdna._assert_job_current(job)` raises **409** when the active design
  fingerprint ≠ the job's, called in `append_oxdna_production` / `_field` / `_run` + `start_oxdna_live`
  (before any rundir prep). The frontend turns the 409 into the popup; it's also the backend safety net.
- **Roll = SEEK the feature-log cursor to the job's position (FINAL, 2026-06-23).** Evolution:
  (1) first cut = `_seek_feature_log` — but the ⚠ never cleared because sequence assignment wasn't logged
  (it was `set_design_silent_reconciled`, undo-only), so seeking back dropped the sequences (64/64 → 0/64);
  (2) second cut = restore the job's exact `design.json` snapshot byte-for-byte — cleared the ⚠ but did NOT
  move the feature-log cursor (the Feature Log tab showed the snapshot's own short log, and a post-job
  overhang stayed visible). User wanted a REAL seek visible in the tab. **Final fix has two parts:**
  - **Sequence assignment is now a feature-log op.** `/design/assign-scaffold-sequence` +
    `/design/assign-staple-sequences` (`routes_assign_sequences.py`) switched from `snapshot()` +
    `set_design_silent_reconciled` → `mutate_with_feature_log(op_kind='assign-scaffold-sequence' /
    'assign-staple-sequences', ...)`. Added both kinds to `SnapshotOpKind` (models.py). Now a seek
    reproduces the sequenced state, so the seek-based roll clears the ⚠. (Full suite green — no test asserted
    the old no-log behavior.)
  - **`crud.roll_active_to_job_state(snapshot, feature_log_position, return_name)`** seeks the cursor to the
    job's `feature_log_position` via `_seek_feature_log` (FULL log kept, later entries inactive/forward, the
    model reverts — a post-job overhang disappears, exactly like sliding the Feature Log rail; the cursor is
    visible in the tab). If the seeked fingerprint == the job's it's used directly (new jobs); else (OLD
    jobs with no recorded position / pre-logging) it falls back to overlaying the job's exact snapshot
    topology onto the seeked log+cursor so it still runs. The roll endpoints pass `job.feature_log_position`.
  - Non-destructive return path unchanged: saves the pre-roll work as a **loadout** branch
    (`return_loadout_id`); "↩ Return to latest" = `selectLoadout(id, {saveCurrent:false})` (the
    `save_current=false` query stops `select_loadout` clobbering the branch). The user can ALSO seek forward
    via the Feature Log tab (the full log is preserved). The duplicate `/design/feature-log/seek` route was
    removed (pre-existing `routes_feature_log.py /design/features/seek` already exists). Per the user's
    choice: Display / View-trajectory / Flexibility stay usable on stale jobs; only Production + Live are gated.
  - **CLIENT-SYNC BUG (the "nothing rolls back / seeker doesn't move" report) — fixed.**
    `client.rollOxdnaJobDesign` / `rollMdJobDesign` used `_request(...)` directly, but **`_request` does NOT
    auto-sync the design response** (it just `return json`) — so the server seeked the design (the ⚠ cleared
    via the job-list refetch) but the CLIENT never applied it: no scene rebuild, no feature-log cursor move.
    This silently affected even the earlier snapshot-restore version. Fix: both roll calls now
    `await _syncFromDesignResponse(json)` (like `selectLoadout`) → `currentDesign` (seeked cursor) +
    `currentGeometry` (reverted topology) update → the scene rebuilds AND `feature_log_panel`'s
    `subscribeSlice('design')` moves the rail thumb. Verified on `workspace/6hb_sim_tests.nadoc` (7-entry log,
    cursor -1 → eff-pos 6): real job→edit→roll returns `feature_log_cursor 6`, full 8-entry log kept, ⚠
    cleared. Regression test `roll_design_sync.test.js` (stubs fetch, asserts the store's
    `currentDesign.feature_log_cursor` actually moves).
  - **MANUAL-seek doesn't clear the ⚠ (the inverse report) — fixed (2026-06-24).** When the user manually
    seeks the Feature Log back to a job's run position, the job's ⚠ should clear (the backend DOES clear it —
    a manual seek to the job's `feature_log_position` re-matches the fingerprint, verified on
    `6hb_sim_tests`). The gap was the in-page refetch trigger: the oxDNA panel relied on main.js's
    `store.subscribe(currentDesign)` calling `oxdnaPanel.refresh()`, but the panels' 1.5 s poll is PAUSED off
    the Dynamics tab (`nadoc:left-tab-change`), and a manual seek happens on the Feature Log tab — so the
    only signal was that store subscription, which was an indirect/fragile chain. **Fix:** the client now
    emits a single reliable `nadoc:design-changed` window event on EVERY design sync (`_signalDesignChanged()`
    replaces the 4 `nadocBroadcast.emit('design-changed')` sites in `_syncFromDesignResponse` /
    `_syncPositionsOnlyDiff` / `_syncClusterOnlyDiff` — `currentDesign` content only ever changes via the
    client, verified). BOTH job panels now self-listen (`window.addEventListener('nadoc:design-changed', _fetchJobs)`
    — the MD panel already did) and refetch regardless of tab/poll state; main.js's `store.subscribe` for this
    was removed (the client is now the single source). Regression: `roll_design_sync.test.js` asserts
    `seekFeatures` dispatches `nadoc:design-changed`.
- **Shared oxDNA+MD guard + MD parity (2026-06-23).** The fingerprint module gained
  `design_build_fingerprint` (neutral alias of `oxdna_design_fingerprint`) + `current_active_design_fingerprint()`
  (catches ALL exceptions → None; staleness is advisory and must never 500 the job list). **MD jobs now mirror
  oxDNA:** `MdJob` gained `design_fingerprint` + `feature_log_position`; `_prepare_job_bg` writes
  `design.json` + the fingerprint from the design it prepared (covers seeded + non-seeded); `routes_md`
  list/get add `out_of_date`, `append_md_production` gets `_assert_md_job_current` (409), and
  `/md/jobs/{id}/roll-design` restores the snapshot. Frontend: shared **`ui/job_staleness.js`**
  (`jobOutOfDate` + `ensureJobCurrent({job, rollFn, refetch, isStale, actionLabel})`) drives BOTH panels;
  the oxDNA panel + live controller + MD panel all delegate to it. `main.js` dispatches `nadoc:design-changed`
  on each `currentDesign` change → both panels refetch so ⚠ appears immediately. The fingerprint EXCLUDES
  display layers (cluster transforms/joints, camera) so a cluster drag doesn't false-flag.
- **Headless gotcha (regression fixed).** The guard reads the active design; the headless oxDNA wrappers
  (`headless_oxdna_build.append_field` / `append_production`) drove the routes against the DEFAULT doc, so
  in the shared-process test suite (randomized order) a prior test's leftover design tripped the guard →
  39 spurious 409s. Fix: `_scratch_job_design(job_id, workspace)` scopes the job's OWN snapshot as the
  active design for the call (mirrors how `create` is scoped) — the field/production run logically operates
  on the job's design, so the fingerprint matches and the guard passes. `test_oxdna_staleness.py` also
  drops the default doc after each test (it sets it for the TestClient routes).
- **Tests.** `test_oxdna_staleness.py`: fingerprint sensitivity/insensitivity, guard 409, list flag,
  `test_assign_sequences_are_feature_log_steps` (the new logged entries), **`test_roll_seeks_feature_log_cursor_and_keeps_full_log`**
  (the reported fix — roll seeks the cursor to the job position, FULL log kept, model reverts, ⚠ clears,
  forward-seek returns to latest), + the old-job snapshot-overlay fallback. `test_md_staleness.py` (MD parity).
  Both fixtures reset the doc-context contextvar to the default doc; both import the app at MODULE level so
  `test_md_milestone1`'s fake-fastapi `sys.modules` swap can't poison `include_router`. Frontend
  `job_staleness.test.js` + panel/controller pins. The in-app ⚠ + roll-seeks-the-tab + return-to-latest
  gesture is human-eye → **MV-OXSTALE** (covers oxDNA + MD).

### Roll/return re-audit (2026-08-08)

- The historical synchronization failure is now covered end-to-end by
  `tests.automation_harness.assert_roll_return_lifecycle`: edit present + stale → unsafe follow-on
  refused 409 → roll keeps the complete Feature Log and restores the job fingerprint/cursor → stale
  clears → `save_current=false` return restores the exact latest fingerprint/cursor/log → stale
  correctly reappears. `test_md_staleness.py` drives the same return endpoint for NAMD parity.
- One live-workflow edge was reproducible and fixed: `showPersistentToast` reused a single global slot
  but retained its previous action. A pre-existing loading/status toast could therefore consume the
  roll-complete message while omitting (or miswiring) **Return to latest**. Reuse now replaces severity,
  loading state, and controls; `ui/toast.test.js` is the can-go-red pin.
- Identity root cause resolved: cross-design roll is intentionally allowed but now carries the job
  snapshot's own Feature Log; it never grafts the active file's history onto another `Design.id`.
  Workspace identity follows professional move/copy semantics: rename/move retains UUID and remaps job
  provenance; Save As/copy forks UUID. `DesignMetadata.identity_last_known_path` is the durable location
  signoff. Legacy files acquire it lazily without changing their ID, while duplicate legacy IDs are split
  during the library audit. See `backend/core/design_identity.py` + `tests/test_design_identity*.py`.
- ISSUE-22 is therefore **REVALIDATION REQUIRED**, not confirmed broken: hand-drive oxDNA + MD
  roll/follow/return once; close as stale if both pass.
- Feature Log seek performance follow-up (2026-08-08): removed the obstructing global `Loading F…`
  toast and suppressed the generic request popup for slider seeks; progress is now local via
  `aria-busy`. The backend no longer deep-copies the complete design before copy-on-write replay.
  MD/oxDNA stale-job badge refreshes are 150 ms coalesced background work, and roll-design returns an
  authoritative `matches_job` flag so the action path never waits for a full job-list refresh.

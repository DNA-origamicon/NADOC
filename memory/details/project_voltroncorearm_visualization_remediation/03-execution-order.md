# Execution order — supporting detail

[Topic head](../../project_voltroncorearm_visualization_remediation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Execution order

1. V1 and V2: make remote state truthful and actionable.
2. V3: make cached/visible readiness impossible to misreport.
3. V4: remove avoidable request contention.
4. V5: instrument, then optimize the measured dominant load phases.
5. V6: make the full verification loop bounded and repeatable.
6. Reconnect Alpine and run the complete welcome -> refreshed-frame matrix.

## Completion record

Append dated entries here after each implementation/test loop. Include commands, measured
timings, failures, and the next action. Do not mark this project complete while any V-item
is pending or while the final remote refresh remains unverified without a documented
external blocker.

### 2026-08-15 — Loop 1: remote refresh truthfulness

- Added `mdRemoteRefreshGate`, a structured state/reason/label/title/enabled decision for
  disconnected, fetching, warming, job-not-running, and ready states.
- Refresh now exposes `data-gate-reason` and `aria-disabled`, and paints a persistent
  actionable status instead of relying on color and tooltip alone.
- Cluster-state broadcasts repaint Refresh using the event's state directly, avoiding a
  one-event lag in the connection-state getter.
- Alpine Refresh reconciles `/api/cluster/status` immediately before starting remote work;
  an expired session retains the local frame and asks the user to reconnect.
- Verification: `cd frontend && npx vitest run src/ui/md_jobs_panel.test.js` — **236 passed**.
- Remaining for V1/V2: reconnect Alpine and capture disconnected -> connected -> warming ->
  ready -> fetching -> applied through Playwright.

### 2026-08-15 — Loop 2: honest readiness, contention, and bounded verification

- Renamed the parser-only display event to `topology-ready`. The readiness dot remains
  warming until `prewarmed`/`frame-cached`; only `frame`/`frame-applied` represents visible
  coordinates. Focused display tests cover topology-ready before cached-frame readiness.
- Coalesced identical in-flight job JSON GETs, active-job probes, same-device resource
  probes, library lists, and unified simulation lists. AbortSignal-bearing requests remain
  independent. The Playwright timeline records coalesced followers.
- Fixed the operation-idle boundary: importing populated topology with no geometry no
  longer completes at the empty intermediate rebuild. Background polls now remain deferred
  until separately fetched geometry has built and presented its final frame.
- Added `nadoc:operation-timing` and captured phase deltas in the Playwright timeline,
  including response, parse, geometry fetch, mesh construction, crossovers, post-build,
  and final render.
- Made scene screenshots explicit (`NADOC_AUDIT_SCENE_SCREENSHOTS=1`). Default headless
  runs retain UI screenshots and geometry assertions without entering an unbounded
  SwiftShader readback.
- Verification: six focused Vitest files — **330 passed**.
- Bounded geometry Playwright: **passed in 1.1 minutes**, preserving all 14,179-position,
  overhang, rod, and hidden-reference invariants.
- Bounded Display-MD Playwright: **passed in 40.7 seconds**. Welcome -> design loaded fell
  from 38.35 s to **19.82 s**; warm-up -> cached frame fell from 12.45 s to **8.60 s**;
  cached-frame apply remained **111 ms**.
- The operation trace now attributes the import's 16.44 s: ~1.13 s response+parse, ~8.03 s
  geometry fetch, repeated scene builds, and final presentation. Follow-up: explain/remove
  the post-geometry rebuild fan-out rather than merely accepting it.
- Job `82a3cd08ed4f` is now `completed`, so Refresh correctly gates as `job-not-running`.
  Playwright verified the retained final frame stays visible and the reason is explicit.
  A true remote fetching -> applied check requires a running Alpine job; do not mutate this
  completed fixture merely to satisfy the test.

### 2026-08-15 — Loop 3: eliminate rebuild fan-out and broad regression

- Operation marks identified two post-geometry full rebuilds as empty surface-capture
  overlay highlight transitions (`count=0`, highlight true then false).
- `setExtraNucleotides` now updates empty-overlay metadata/glow state without rebuilding
  the 14,179-position scene. The final trace contains one real geometry build and no
  extra-nucleotide rebuild.
- Welcome -> design loaded improved again to **17.02 s**, a **55.6% reduction** from the
  38.35 s audit baseline. The complete retained-frame diagnostic passed in **31.6 s**.
- The remaining geometry request is intentionally expensive and fully attributed by
  `Server-Timing`: measured/deformed placement of 29,418 active+reference positions took
  3.87 s and the required straight reference placement took 4.28 s; axes, overhang
  rotations, and JSON parse together took ~0.20 s. Both coordinate sets are consumed by
  deformation/unfold visualization, so removing either would trade away correctness.
- Post-fix request audit found **zero overlapping identical GETs**. Coalesced followers
  remained visible in the diagnostic log.
- Broad verification: `npm test -- --reporter=dot` — **322 files, 5,609 tests passed**.
- Production verification: `npm run build` — **passed**.
- Real Playwright verification: Display-MD retained-frame workflow **passed**; geometry
  invariants **passed**. Current external limit remains a live remote-refresh transition:
  the VoltronCoreArm fixture is completed and therefore has no running Alpine restart
  frame to fetch.

### 2026-08-15 — Loop 4: complete remote state matrix without mutating the run

- Added `NADOC_AUDIT_MOCK_REMOTE_TRANSFER=1` to the Voltron diagnostic. It changes only
  the browser-visible lifecycle flag and intercepts the Alpine start/progress control
  endpoints. It does **not** change the completed job, its files, or backend state.
- The data path remains real: VoltronCoreArm design import, 413 MB topology attach,
  WebSocket topology/model preparation, 14,179-position cached frame, forced refresh
  reload, scene application, and final geometry are all exercised normally.
- With UI screenshots enabled and scene readback safely disabled, all **17/17** predicted
  initial/intermediate/final states passed in **41.8 s**: welcome, design load, Dynamics,
  selection, warming, frame cached, instant display, remote refresh request, transfer
  completion, refreshed socket frame applied, final 100% UI, plus both forbidden-work
  assertions.
- Refreshed-frame reconstruction took 6.25 s and final scene application completed before
  the 100% UI state by 206 ms. No generic Working popup or unintended Alpine poll occurred.
- This closes V1/V2's running-job frontend verification while preserving the completed
  simulation fixture. Real SSH/SFTP transport remains covered by its backend tests and is
  intentionally not fabricated or restarted for a visualization regression.

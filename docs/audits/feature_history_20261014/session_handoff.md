# Feature-history stopping-point handoff

Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Updated October19,2026. User requested finishing the current batch, a local commit, then stopping.
**Tools done: 2/4 (Extrude, Sweep). CAD ledger: 20/34 complete, 14 remaining (7 core, 7 parked).**
**Sessions since last gate flip or milestone close: 1.** No milestone credit for this commit.
Persistent goal is paused; do not mark the overall overhaul complete. No push requested.

## Scope and next work

Stop after the current commit. On an explicit continuation, retain the existing plan and review
progress every30minutes using `.development-artifacts/feature-history-focus/review.json`.
Bend/Twist gates are ON, but their large-part preview p95 remains1208.8ms (median1113ms).
User explicitly deferred that performance gap while completing Sweep/Extrude and history editing.
No legacy-file compatibility, numerical-manifest regeneration, geometry-golden updates or new host.
Preserve Fine Routing parameter-edit semantics: remove a child only when every target is
unoccupied; partial applicability and other failures refuse atomically and identify the child.
Move/suppression never delete routing children automatically. Molecular constants remain locked.
If a major unresolved decision would take over2hours, defer it for the user's return as requested.
Next bounded task after resumption: qualify the remaining Bend/Twist C8 gap against the existing
500ms preview/3s small Apply/10s large Apply/200ms Cancel budgets (2× allowance).
Do not reopen completed Sweep performance or grow legacy/sealed-path qualification matrices.

## Completed user-facing behavior

- Bend/Twist: isolated creation/history editing, downstream error attribution and dependency view.
  Desktop mutating-preview fallback and destructive history peeling removed; other consumers of
  legacy creation helpers are not claimed removed. C8 remains open, so tools are not counted done.
- Sweep: production gates ON; ordinary-part C1–C9 complete. Interactive preview displays axes,
  nodes and cross-sections over static prefix context. Backend now calls guide planning without
  building or validating full candidate DNA on every update. Apply retains complete native rebuild.
  Latest measured p95: small36ms/large88ms, excluding GPU raster; Apply163/2530ms, Cancel47/35ms.
  Attached/independent/detached source lifecycles, later topology changes, routing removal/refusal,
  rollback refusal, exact Cancel, undo/redo/save/reopen and independent cold replay passed in app.
- Extrude: all seven native family lifecycles and five creation workflows covered; ordinary-part
  C1–C9 complete. Legacy length-only editor removed. Existing modal form remains the editor;
  live preview is separate follow-on scope. Nicked posed continuation uses the existing straight
  continuation terminus eligibility rule. Bundle creation is failure-atomic with one Undo.
- History dependencies: revision-bound parent/child viewer uses existing native resource contracts.
  Error/blocked badges describe a refused draft; canonical geometry stays unchanged on failure.
- Whole-row Move: existing evaluation jobs/commit/undo; native replay resolves references at the
  proposed stage. Shared resources alone are not ordering barriers; valid moves may change geometry.
  Initial bundle stays first. Missing producers refuse with feature/child attribution. Source proof,
  final cold replay and per-stage structure checks run; Fine Routing IDs/child order are preserved.
- Suppress/Unsuppress: saved definitions and IDs remain in place as fingerprinted no-op steps.
  Capture, replay, rollback, repair drafts and persistence retain suppression. Unsuppress regenerates
  the saved operation and suffix. Missing producers refuse atomically without cascading deletion.
- Source repair: existing saved-proposal panel supports Sweep source helix; continuation/frame source
  frame; deformed continuation reference helix; overhang extrusion anchor helix. Choices come from
  the actual feature prefix. Existing native binding refreshes derived continuation receipts; full
  replay validates geometry and downstream features. Repair preserves explicit suppression state.
  Tracking repair callbacks cannot be skipped by the outer replay cache on repeated proposals.
- ISSUE-146: repair launcher was hidden inside assembly's configuration-only toolbar. It now has
  a sibling host with the existing part-context visibility guard; no additional panel or lifecycle.

## Verification

Evidence logs: `.development-artifacts/feature-history-focus/` (not committed disposable output).
- Sweep guide backend43/session16 and app3 passed; scratch ydmfjcfe independently absent.
- Move backend26/UI5 and app4 passed; scratch uizkyodf independently absent.
- Suppression backend20/repair-capture11/UI7 and app6 passed (four tools, Move, refusal);
  scratch6ehu2rrw independently absent. Earlier full frontend9367 pass/1skip and smoke23 passed.
- Final source repair12, existing selection62/repair58, archive capture45, extension routes23 passed.
  The earlier extension capture-budget setup error did not recur in the complete file.
- Source repair browser2 passed: selection/evaluation/Apply/undo/redo/save/reopen/cold proof.
  Scratch `/tmp/__e2e__history-w_0rosal` independently absent. Failed diagnostic runs cleaned too.
- Final full frontend:779 files,9367passed/1skipped (337.61s). Final smoke:23passed (2.3min);
  scratch `/tmp/__e2e__smoke-zkgbb4ne` independently absent.
- Final backend FAST:19078passed/83failed/19skipped (348.88s;379s aggregate), zero per-test
  timing violations. Failure-set comparison: all64 baseline failures plus19 schema expectations.
- `just lint` passed; main.js LOC delta0. No formulas/constants, manifests or goldens changed.

Final backend log: `stop-backend-final.log`. The64 baseline failures comprise11 sealed-path
HTTP/registration,2 junction-balance tolerance, and51 historical numerical-manifest compatibility
expectations. Suppression metadata adds19 obsolete schema-compatibility expectations. Old pins
remain fail-closed; user explicitly declined legacy compatibility, so no manifests were regenerated.
The previous124failures/1error reduced to83failures/no errors after archive-schema and exact capture
accounting fixes; focused archive routes28/capture45/accounting31 pass. No new current repair/runtime
failure remains. Broad suite is not green. Aggregate timing remains above90s; per-test violators=[];
slowest4.62s is a real native-worker test. No arbitrary reclassification or guard changes.
Selector output:
```
decision: FAST  (fast suite only)
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```
No test session requested; focused development checks are authorized. Keep guards and serialization.

## Commit and shared-worktree boundaries

Commit explicit feature-history paths and selected hunks only. Include the preview adapter and
its existing host dependencies that earlier commits already import but left untracked. This is
capturing existing overhaul work, not implementing another sealed-path successor.
Leave unrelated VR, simulation/activity/readiness, scientific-selection policy, memory hygiene and
other project edits untouched. Mixed files: stage only dependency API in `frontend/src/api/client.js`,
history timing classifications in `tests/conftest.py`, and ISSUE-146/147 ledger/fix-log additions.
Earlier sealed activity/display tests and related modules remain outside this commit; their changes
are coupled to the separate activity/readiness backlog. No stash/reset/restore, no push or amend.

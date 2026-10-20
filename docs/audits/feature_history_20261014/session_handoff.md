# Feature-history stopping-point handoff

Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Updated October20,2026 after the bounded Bend/Twist C8 qualification task.
**Tools done: 2/4 (Extrude, Sweep). CAD ledger: 20/34 complete, 14 remaining (7 core, 7 parked).**
**Sessions since last gate flip or milestone close: 2.** Delta0 completed/0 scope; no gate flip.
The overall overhaul remains open. Commit locally under the operating contract; no push.

## Scope and next work

Next bounded task: reduce the measured large-part native Full display construction cost within
the existing Bend/Twist preview lifecycle, then rerun the same C8 cases against1000ms preview,
6000/20000ms small/large Apply and400ms Cancel ceilings (the existing2× allowance).
Server display568–586ms and client layer369–392ms dominate; JSON encoding is only4–5ms.
Do not expand matrices or add a host. Preserve native coordinate/inventory checks, molecular
constants, manifests and goldens. If optimization needs a scientific change, present the concrete
review required by CLAUDE.md. Existing rendering patches refuse changed axes; do not reuse them
for Bend/Twist while leaving stale axes. Review focus every30minutes using the existing review.json.
At the next session end N becomes3 unless a production gate flips; obey the subsequent stop-loss.
Old files remain excluded. Fine Routing removes a child only when every target is unoccupied;
partial applicability and other failures refuse atomically. Move/suppression never auto-delete children.

## Current qualification evidence

- The strict harness now measures both tools at6×84 and18×504, with one successful sequenced
  evaluation per sample, valid layers, adopted Apply, exact Cancel and no canonical Cancel reads/writes.
- Four-case browser run:2passed/2failed (2.5min), failures only large preview p95.
  Small Bend/Twist: preview118/112ms, Apply950/425ms, Cancel72/67ms.
  Large Bend/Twist: preview1315/1136ms, Apply4664/4417ms, Cancel162/157ms. GPU raster excluded.
- Native recipes and file sizes are recorded in the existing Bend/Twist plan; no existing user files changed.
- Final reporting-only soft assertions keep all budget/console checks reachable on timing failures;
  syntax checked, browser repeat cancelled while queued behind another session's full suite.
- Focused Ruff and JS syntax checks pass. No production change, broad-suite rerun or completion credit.
- Browser root `/tmp/__e2e__history-w9btjio7` and profiler root `/tmp/__e2e__bend-profile-_66eaqqe`
  independently absent. Earlier own baseline root1w_e5dal was also verified absent. Queued interrupted
  checks never started a browser or allocated scratch. Other sessions' artifacts were left alone.
- Logs: `bend-twist-c8-resume.log`, `bend-c8-server-profile.log`, `bend-c8-resume-baseline.log` in
  `.development-artifacts/feature-history-focus/`. The final log records the cancelled queued repeat.
- Snap `just` failed after the environment restart; direct `scripts/validation_guard.sh` preserved
  serialization/worker caps. No user systemd was available, so its memory scope was unavailable.

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

## Previous commit verification (not rerun in this task)

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

This task owns the latency spec, its opt-in fixture startup helper, three additional native latency
fixtures, this handoff and the appended C8 plan evidence. The plan also has earlier uncommitted
feature-history evidence; it is eligible under the operating contract's same-subsystem rule.
Leave unrelated VR, simulation/activity/readiness, scientific-selection, memory hygiene and other
project edits untouched. No stash/reset/restore, push, amend or broad staging.

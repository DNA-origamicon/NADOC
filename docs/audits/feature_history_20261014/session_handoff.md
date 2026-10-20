# Feature-history stopping-point handoff

Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Updated October20,2026: user resumed sustained six-tool milestone work.
**Tools done: 2/6 (Extrude, Sweep). CAD ledger: 20/34 complete, 14 remaining (7 core, 7 parked).**
**Sessions since last gate flip or milestone close: 2.** Delta0 completed/0 scope; no gate flip.
The overall overhaul remains open. Commit locally under the operating contract; no push.

## Scope and next work

Next task: qualify geometric Move/Rotate history editing in the isolated running app,
using its existing native preview host and panel. The test-only transform gate is opt-in;
production gates remain OFF. Finish ordinary owner translation/rotation, downstream replay,
Cancel, undo/redo and save/reopen before extending to linked/named movement semantics.
User authorized sustained six-tool milestones and fresh reviewers every30minutes; this
supersedes the prior one-task/session stop-loss. watchdog.json owns the active timer.
Do not repeat unchanged C8 benchmarks. Retain scientific authorization, constants,
manifests/goldens and native placement/inventory checks. History-row Move is reorder,
not geometric Move. Old files remain excluded.

## Current qualification evidence

- Detached candidate/spare layers reuse exact native inventories and coordinate arrays;
  fresh native axes are rebuilt, with preview-only guide tessellation reduced. Native
  bead/slab/connector placements remain unchanged; canonical rendering defaults unchanged.
- Focused65 pass, including fresh-build parity with rotated poses, periodic visibility,
  malformed compact floats, exact reuse and untouched spare on inventory mismatch.
- Final fixed12-sample C8 run:3pass/1fail. Small Bend/Twist preview107/111ms,
  Apply939/429ms, Cancel72/70ms. Large Bend/Twist preview994/1149ms,
  Apply4436/4333ms, Cancel211/161ms. Only large Twist p95 exceeds1000ms.
  Thresholds unchanged; GPU raster excluded (SwiftShader). Both tools remain unqualified
  as a gate pair. Logs: static-preview-reuse.log and static-preview-reuse-c8.log under
  .development-artifacts/feature-history-focus/; root /tmp/__e2e__history-llcbiwr6 absent.
- Final full frontend regression:779files/9377pass/1skip (342.94s), including compact
  buffer reuse. Log: static-preview-final-frontend.log. Move/Rotate harness work ongoing.
- Direct scripts/validation_guard.sh preserves serialization/worker caps because Snap
  just fails here. User systemd unavailable; memory scope unavailable.

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

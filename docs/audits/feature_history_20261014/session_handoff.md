# Feature-history stopping-point handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 7. User explicitly selected FH-18 on October 27, 2026.

**Tools done: 4/4 (Bend, Twist, Extrude, Sweep); Move/Rotate and Fine Routing also qualified.**
CAD ledger: **22/34 complete, 12 remaining (5 core, 7 parked)**.
This session closes one FH-18 membership-recovery defect; FH-18 remains open. No gate or milestone change.

## Delivered task — cluster membership during history scrubbing
Reproduction: create a cluster from the default owner, dissolve it, create another
cluster from the remaining helix, then scrub backward. The default owner incorrectly
stayed empty. Forward recovery also failed to reapply the creation transfer once
membership was restored. The same implicit-setter problem affects histories without dissolution.

Recovery now restores default helix membership from the selected topology snapshot,
then reapplies creations after that snapshot, even when their group records survived
from the current display. Later explicit membership and later snapshots retain authority.
No native placement formula, topology operation, molecular constant, schema pin,
dissolution admission policy or production gate changed.

The new regression covers with/without dissolution, both seek modes, repeated
backward/forward recovery, later membership edits and nick snapshots, one-step
undo/redo, JSON reopen and independent proof with poisoned recovery payloads.
The app test uses the real visible history thumb, ordinary client operations,
save/reopen and native proof. Its reusable spec is `frontend/e2e/cluster_history.spec.js`.
See [bounded evidence](group_placement_migration_plan.md#fh-18-membership-recovery--october-27-2026).

## Validation and limits
- Focused recovery file: 40 pass. The initial two new cases failed before the fix.
- App: 1 pass, clean console; create/dissolve/undo/redo/save/reopen and four rail seeks.
  Initial harness attempts used an unadmitted document ID and clicked an inert notch;
  corrected to the existing admitted fixture and actual thumb dragging, without production changes.
- Ruff, JavaScript syntax and diff checks pass. No frontend production code changed.
- `just test-smart`: decision **FAST (fast suite only)**; **19505 pass/19 skip/84 fail/1 setup error**.
  83 failures match the prior baseline. The extra deformation-prefix failure and repair-draft
  setup error hit capture budgets before this recovery path; both exact nodes pass isolated reruns.
  The prior exact-float TTL failure did not recur. Broad suite remains red.
- DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
- Required slow-test triage: 384s aggregate, zero per-test violators; existing real-worker
  preview/publication/cleanup fixtures and relaxation totals dominate. No marker/budget changes.
- Evidence retained in `.development-artifacts/feature-history-focus/fh18-*` (compact logs/triage only).
  All three owned browser scratch roots independently confirmed absent; no original workspace edits.

## Single next FH-18 task
Qualify ordinary cluster dissolution's live incoming-owner diagnostics in the sidebar:
frame, child, joint and deformation references must explain refusal and leave canonical
state/history unchanged. Reuse the existing typed reference inventory and recording path.
Do not restart PartGroup migration or widen to FH-25/26/27/28 in the same task.
Posed-cluster dissolution remains explicitly refused; this recovery fix does not qualify
posed regrouping or establish a new placement-preservation contract.

## Retained completed work and scope
Move/Rotate functional and nominal-preview work is complete, production transform gates ON.
`be9fe4aa` and reconciliation `0c5f7494` close the prior task; see the
[transform plan](transform_history_editor_plan.md#completion-audit-and-corrective-measures--october-27-2026).
Final preview p95 small Move/Rotate 48/55ms; ordinary large 452/444ms; posed large 469/459ms.
40 samples per direction, first included; no remaining Move/Rotate performance task.

Clusters own geometry among grouping constructs; Staple Groups organize strands.
Experimental PartGroup / Groups and Placements migration, named-group motion/compiler
and geometry-consumer rollout remain retired. Both organization gates stay OFF.
Old-file conversion and simulation/agent provenance remain outside scope.
ISSUE-126 collision-free publication/repair/undo policy remains complete; ISSUE-143 is
separate unequal-direct connection work. Remaining core milestones are FH-18/25/26/27/28;
seven asset/import/connection milestones remain parked.

## Shared-worktree boundaries
Incoming HEAD: `cd54e113`. Commit only the seven explicit task paths: two recovery modules,
one backend regression file, browser spec/config, existing group plan and this handoff.
Pre-existing API/VR/simulation/test/memory/audit edits remain untouched. No push, reset,
stash, restore, dependency download or original workspace mutation. `main.js` unchanged.

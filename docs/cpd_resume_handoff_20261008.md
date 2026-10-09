# CPD resume handoff — 8 October 2026

**Explicitly paused by user. Await explicit resume.**
Stopped `cpd-anti-cube-validation-control-2-v6-watch.service`, then
`cpd-anti-cube-validation-control-2-v6.service`. Both inactive/dead; no NAMD
process remains. An old completion message does not authorize restarting.

## Restart state

Root: `/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/cpd-anti-gpu-cube-context-v5`.
Repo alias: `.development-artifacts/cpd-anti-gpu-cube-context-v5`.

Current case: control replica2. Segments01–09 completed worker checks (9ns);
full independent replica audit is pending. Segment10 was interrupted by user.
Latest verified checkpoint prefix relative to root:
`control/replica-2/validation/segment-10/checkpoint.5100000`.
Use its `.coor`, `.vel`, and full `.xsc` together. Step5100000 equals9.14ns
validation time (preparation ended530000). All265477 atom coordinates and
velocities finite; saved cell/coordinates match DCD; geometry/water/image checks
pass with image clearance48.6246A. Last log step5101000 is not a restart point.

`campaign_pause_20261008.json` pins the files and records verification. Copy at
`cpd-anti-cube-validation-control-2-service-v6/user_pause_20261008.json`.
The supervisor's original `status.json` may still say running after termination;
actual systemd state and this user pause supersede it. Watch token:
`08cadadb-8f2d-456f-9774-955353229c88`.

## On explicit resume

1. Verify no competing NAMD or stale watcher,archive availability and checkpoint
   hashes. Preserve pause receipts,original sources and deadlines.
2. Audit nine completed segments and interrupted segment10 only through5100000:
   native energy,method,full cell,restarts,chemistry,water,image and observables.
   Interrupted log lacks normal completion; do not use terminal-log parser blindly.
3. Prepare a new uniquely named continuation from step5100000 for430000steps
   (0.86ns) to5530000. Keep2fs ordinary masses,p4,PME144cubed,NPT force-switch,
   full velocities/XSC,100ps restart triples and10ps DCD. Declare restart RNG seed;
   do not promise bitwise Langevin trajectory continuity. Verify CPU/native initial
   energy against the checkpoint step's recorded energy,not the log's last row.
4. Choose a fresh bounded job clock strictly below16h using measured~50–55min/ns
   plus audit margin; a2h cap should comfortably fit this remainder but recheck.
   Existing v6launcher refuses an existing validation folder; do not delete it,
   overwrite segment10,or reset its historical deadline. Re-arm a watcher only
   for the newly admitted continuation and current thread.
5. Aggregate control2 time series without duplicate endpoints/uncheckpointed tail.
   Independently audit native/cells/checkpoints and sampled chemistry. Review
   physical/structural/performance evidence and matched28contacts with anti2.
   Original validation/completion_review.json needs approved_for_next_run and
   pinned aggregate assessment,audit,performance_report before anti3 admission.
6. Finish anti3/control3 sequentially with audits,then final matched interpretation,
   provenance errata and portable restartable package. No automatic promotion.

## Retained scientific status

All six preparations audited. Anti1,control1,anti2 have audited10ns validation;
control2 is incomplete. Anti1 shared-contact retention is lower than anti2 and
control1,with materially different prepared baselines. Preserve all replicas;
no equilibrium,causal lesion effect,minimum or full NAMD readiness claim.
Anti2's startup bad_any_cast failed run remains archived. Its100ps diagnostic
and subsequent8.9ns completed without recurrence; root cause unresolved. Another
such exception requires review,not a retry loop.

Relevant tools: `audit_cube_replica_v9.py` for uninterrupted replicas;
`audit_cube_anti2_v12.py` for its split trajectory; `resume_cube_v7.py` demonstrates
checkpoint-specific energy handling but is hardcoded to anti1 and cannot be run
unchanged for this control2 pause. Frozen engine can review arbitrary aligned
step lengths; add a new bounded continuation wrapper with appropriate case/steps.

Simulation data remain in the archive. Uncommitted CPD code/docs and unrelated
VR/extrusion work are preserved. No commit was requested for this pause.

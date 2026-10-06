# CPD pause and resume handoff — 6 October 2026

**Paused explicitly by the user. Do not resume from an old completion wake.**
Both the active validation service and its independent completion watcher were
stopped. No other CPD computation was launched. Earlier compute authorization
remains subject to this later pause; await explicit user resume.

## Retained state

Archive root:
`/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/cpd-anti-gpu-cube-context-v5`
(accessible through `.development-artifacts/cpd-anti-gpu-cube-context-v5`).

- All six fresh matched preparations were independently audited. Three anti and
  three controls use paired seeds41017/52027/63037. Final system265477 atoms,
  87289 waters,237 added salt pairs. `startup_admission_v6.json` records evidence
  and runtime budget; `startup_endpoints_lock_v6.json` freezes starting states.
- Anti1 validation `segment-01` completed1ns and passed worker chemistry/water/
  image/restart/CPU endpoint energy checks. Native independent audit and physical/
  structural interpretation remain pending. Minimum image37.1846 A.
- `segment-02` was interrupted at user request. Last logged step1328000 is not a
  restart point. Latest complete retained triple is
  `anti/replica-1/validation/segment-02/checkpoint.1300000.{coor,vel,xsc}`.
- Step1300000 corresponds to1.54ns validation time after step530000 preparation.
  Verified finite coordinates/velocities, full XSC step identity and geometry/
  water/image checks. Cubic edge137.93626449 A; image clearance41.0346 A.
  There may be up to56ps of logged work beyond this checkpoint; do not credit it
  as resumed trajectory or append overlapping frames blindly.
- `campaign_pause_v6.json` pins the checkpoint and records checks and pause.
  Service evidence at `cpd-anti-cube-validation-anti-1-service-v6/user_pause.json`
  records shutdown. Original `status.json` can remain stale (`running`); both
  systemd units are inactive/dead. Watch token was
  `d3a438fa-8758-40ae-b563-af73f903fecd`; a delayed wake does not revoke this pause.

## On explicit resume

1. Read the current user instruction and campaign head, then verify no other
   NAMD process or CPD watcher is active. Check archive availability and all
   restart/input hashes. Preserve the existing pause receipt as history.
2. Independently audit completed segment01 and segment02 through step1300000.
   Check trajectory cells/chemistry, restart energies, native method, physical
   blocks, voids and registered observables. The interrupted native log has no
   terminal marker, so the completed-log parser must not be used blindly.
3. Prepare a new continuation plan and worker/output location. Existing v6
   launchers intentionally reject existing validation folders; do not delete
   or overwrite them or reset old deadlines. Resume with binCoordinates and
   binVelocities from the same checkpoint plus full extendedSystem XSC and
   firsttimestep1300000. Preserve ordinary masses,2fs,NPT force-switch10–12A,
   p4,PME144cubed and all scientific gates/observables.
4. The original segment02 endpoint is1530000. Continuing230000 steps reaches
   that endpoint (0.46ns); then eight1ns segments reach step5530000, completing
   the original10ns target. Ensure the new runner correctly supports partial
   segment lengths,10ps DCD cadence,100ps checkpoints and nonduplicated times.
   Record stochastic restart seed policy; do not claim bitwise trajectory
   identity across restarted Langevin segments.
5. Re-estimate remaining runtime, including input verification and audits, and
   admit only one job below16h. Previous full10ns estimate was~11h nominal,
   13.93h with conservative margin/reserve and15h hard cap. Preserve1ns review
   boundaries and stop on failures/material slowdown. Re-arm a completion
   watcher only for the newly admitted job and current thread.
6. Review the completed anti1 trajectory scientifically before control1, then
   anti2/control2/anti3/control3. Each successor needs pinned independent audit,
   assessment and performance report with explicit completion review. Finish
   structural interpretation, provenance errata and portable restartable package.

## Code and validation

New files: `gpu_cube_preparation_v6.py`, `audit_cube_preparation_v6.py`,
`launch_cube_preparation_v6.py`, `gpu_cube_validation_v6.py`, and
`launch_cube_validation_v6.py` under `experiments/cpd_anti_additive/`.
The preparation and validation workers use pinned archived engine copies;
changing current repo code can invalidate historical input pins. Preserve
source versions and distinguish historical audit from new admission.

19 focused tests passed before validation launch (cube validation, preparation
review/admission, GPU NPT context and native logs). They cover restart chaining,
input integrity, deadline margin, overwrite prevention, and stopping on failure
or slowdown. Pause checkpoint was checked against native energy step and
physical gates. `docs/cpd_namd_methods_si_draft.md` is an existing draft retained
with this work; it has not been newly source-audited as part of the pause.

Large trajectories, restart binaries and logs remain in the archive, not Git.
Current scientific scope is preliminary cis-anti-I and matched control context;
no equilibrium, global-minimum or general CPD/full NAMD production-readiness
claim is made.

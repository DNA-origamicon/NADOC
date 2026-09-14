# Alpine restart recovery

NADOC now distinguishes a Slurm allocation restart from a new sampling trajectory.
The backend reads `scontrol Restarts/StartTime` and a compute-node execution journal.
A same-segment step regression is supporting evidence, never sufficient proof of
independent sampling or of surviving output. Repeated polls reconcile one incident
per Slurm allocation/restart count.

## Recovery on the compute node

New submissions and manual resumes stage `remote_alpine_restart.py` as
`nadoc_alpine_restart.py`, alongside the existing resume configuration helper.
Before any stage can overwrite output, the batch script journals the execution and
preserves previous logs. Completed stages are skipped. Interrupted dynamics stages:

1. Validate coordinate/velocity binary lengths and atom counts against the PSF,
   finite positive-volume XSC, checkpoint step, and NAMD's XSC → coordinates →
   velocities write ordering. Prefer the newest valid generation; `.old` can be
   selected when the newest generation is incomplete.
2. Copy the selected input triplet into the attempt directory before NAMD can rotate
   its rolling restart files.
3. Continue at `firsttimestep`, running only the requested remaining steps with the
   same physical configuration. A checkpoint exactly at the target uses `run 0`
   to produce the final output set.
4. Write a fresh `.contN.dcd/.xst`; retain prior pieces. If checkpoint rollback leaves
   overlapping/partial DCD output, preserve the original bytes in the attempt folder
   and repair the canonical prefix to the checkpoint boundary. Only such damaged or
   overlapping pieces need copying; ordinary aligned continuation is inexpensive.
5. Keep early-stop health evaluation on the latest continuation. Subsequent cell-grid
   recovery also preserves the pre-outage pieces.

No valid checkpoint means a recorded blocked incident and a failed allocation,
not silent production from the original seed. Interrupted minimization requires
review; automatic checkpoint continuation here is for dynamics. No new allocation
is submitted by this recovery mechanism: Slurm must restart/requeue the allocation.
Neither NADOC nor an authenticated browser needs to be running at the time.

Validation is structural and conservative, not a proof of filesystem durability or
physical stability. The resumed trajectory is a checkpoint continuation, not a
bitwise reproduction of the uninterrupted stochastic trajectory.

## Entries and acknowledgment

A verified legacy `.dcd.BAK` is protected by a hard link in a unique attempt directory,
which survives replacement of the `.BAK` name. Its DCD frame count, file length and
final frame record markers are checked. NADOC creates a deterministic, linked,
terminal job entry with independent local package files and no Slurm control handle.
It exposes the preserved trajectory through ordinary remote download. Downloading
that entry does not complete or stop its active parent; preserved entries stay
terminal and cannot start/resume/submit. They have no ensemble replica index.

The original running entry retains its identity and its live allocation. Its alert
opens a popup explaining the restart, continuation checkpoint or reset, preserved
paths, and sampling caveat. **I understand** acknowledges exactly the displayed
incident revision. Acknowledgments are written atomically outside `job.json`, so
stale polling writes cannot erase them. Closing the popup does not acknowledge it.
The warning becomes a history icon; subsequent restarts or materially changed
findings require acknowledgment again. Normal progress into later stages does not.
The preserved child has an informational history icon, without pretending the user
has acknowledged the parent's warning.

Same-seed restarts are explicitly marked **independence unverified**. Their output is
not concatenated with the running attempt, and they should not automatically be
counted as independent replicas for uncertainty estimates. Checkpoint continuations
remain chronological pieces of one run.

## Existing 24hb_0xT allocation (2026-09-13)

- Active NADOC job: `2f281ba1a83a`; Slurm: `32090992`, still RUNNING with `Restarts=1`.
- Preserved prior attempt: NADOC `594917c0d119`, **6032 frames / 120.64 ns / 95,559,957,652 bytes**.
- Remote preserved directory:
  `/scratch/alpine/jojo6687/nadoc_jobs/2f281ba1a83a/output/attempts/legacy-32090992-r1`.
- The 95.56 GB trajectory remains on Alpine; this change does not download it.
- Because Slurm spools the submitted script, changing `nadoc_job.sbatch` alone would
  not protect the current allocation. Its production config was atomically replaced
  with a small Tcl wrapper that invokes the same recovery helper on its next launch.
  The original is retained as `.before_restart_guard.conf`. Atomic replacement leaves
  the running process's already-open config inode intact. No cancel/requeue occurred.
- The legacy shell redirects its NAMD log before the Tcl wrapper starts. The log at
  installation was copied to `output/*.before_restart_guard.log`; an exact log tail
  immediately before a future outage is not guaranteed by this retrofit. Trajectory
  and checkpoint protection still happen before NAMD initializes the next simulation.

## Verification

Node tests execute emitted Bash and the retrofit Tcl wrapper using real binary test
checkpoints and a recording stand-in for NAMD. They cover repeated restarts,
truncated/mixed checkpoints, `.old` fallback, exact-end checkpoints, preservation and
nonoverlapping DCD repair, and the existing cell-grid recovery. Backend tests cover
incident deduplication, acknowledgment revisions/races, routing, and independent
snapshot ownership. Frontend tests cover popup dismissal, acknowledgment success and
failure, rerender signatures, and disabled controls for preserved entries.

Browser spec: `frontend/e2e/alpine_restart_notice.spec.js`. It creates no saved jobs or
designs and mocks the acknowledgment API. Browser execution and `just smoke` were
blocked by the repository's simulation guard because another local NAMD simulation
was running. Do not override the guard or interrupt that simulation to test this UI.

Validation results (2026-09-13): `just test-smart` selected **FULL** with a user-opened
test session: **8367 passed, 618 skipped, 1 xfailed, 9 failed**. All nine failures are
missing `workspace/BigO.nadoc` or `workspace/smallO-poly.nass` fixtures, outside these
changes. The final focused restart suite passed **19 tests**; existing cell-recovery
suite passed **12**. `just test-frontend`: **6406 passed**. Ruff and `git diff --check`
passed. No Playwright artifacts were created; cleanup paths were checked empty.
This task's `main.js` LOC delta is **0**.

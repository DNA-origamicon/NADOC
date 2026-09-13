# Atomistic PEG visualization

The persistent `NAMD_PEG8_wall_review.nadoc` and managed PEG qualification/fast-relax
jobs use their saved atom indices, PSF bonds and real DCD coordinates. Visualization
never writes positions into the design, changes force parameters or launches NAMD.

## Controls

| Option | PEG behavior |
|---|---|
| Off (native positions) | Restores saved initial PEG coordinates; stops playback and live polling. |
| Display MD | Latest complete frame, including the active stage; checks every 5 seconds while running/queued. Camera position is preserved on refresh. |
| Flexibility map | Per-atom population RMSF about the selected dynamics stage's mean, in Å. Chains are made whole across periodic faces, with roots registered to the saved graft sites. No rigid-body fit removes wall-relative motion. Minimization is excluded. |
| View trajectory | Shared play/pause, previous/next and slider controls use the same frames as the PEG review card. Stage selector chooses the recorded chunk. |
| Water | Oxygen-only representation, with periodic hydration-shell distance from PEG atoms or the whole box. Water is hidden for the RMSF mean. |
| Periodic box | The package's fixed orthorhombic cell, aligned with the atom coordinates and wall planes. |
| Beads / VDW / Ball & Stick / Stick | PEG atom/bond representations follow the shared View menu; atomistic radii come from the existing atom catalogue. |
| Full | Lightweight PEG atom points and actual PSF bonds. |

The repulsive planes and harmonic-graft annotations remain visible across modes.
Plane dimensions respect the declared normal axis, including non-cubic cells.
Changing documents or selecting a DNA job clears the PEG overlay and its timers;
DNA visualization controls resume their normal routing.

## Sampling and continuation evidence

`GET /api/md/peg-qualifications/{job_id}` accepts `segment` and `max_frames` (1–200,
default 100). A one-frame request returns the latest frame. Larger requests sample
uniformly and include the first and last available frames; `raw_frames` reports the
unsampled count. RMSF labels identify the selected stage and sampled/raw counts.
The general DNA frame-interval row is hidden for this bounded PEG reader.

The reader assembles continuation fragments in numeric restart order. A restart
at step S discards the old future after S, even before its first new frame has been
written. Frame headers and complete-record byte counts determine what can be read;
an in-progress tail is excluded. Mismatched atom counts and nonfinite coordinates
fail explicitly. The reader does not depend on DNA/base mapping or energy parsing.

## Remaining applicability limits

- These short qualification/relaxation trajectories are not equilibrium samples.
  Production-only occupancy clouds and density/cluster controls stay unavailable
  with an explicit explanation. A validated PEG production path remains necessary.
- PEG-only systems contain no thymine; T–T photoproduct analysis is inapplicable.
- The current qualification package contains PEG and water, with no ions. The ion
  option explains this rather than invoking DNA solvent analysis.
- DNA helix hulls, cylinders, molecular surfaces and external coarse models do not
  define a PEG representation. PEG remains visible as atoms/bonds in those modes,
  with an explicit fallback label. A PEG molecular-surface implementation and
  validated coarse PEG mapping remain separate work.
- Water is explicitly oxygen-only in this review renderer, including atomistic
  representation modes; water hydrogen/bond rendering is not yet implemented.
- The fixed-surface RMSF estimate is a sampled per-stage descriptive statistic,
  not pooled production RMSF or an equilibration certificate. The native safety
  and skip metrics continue to use their independent paired evidence pipeline.

## Validation

Focused regression coverage checks restart rollback, active-stage visibility,
latest-frame sampling, fixed-frame RMSF with an analytic displacement oracle,
periodic chain reconstruction/water selection, shared sidebar routing, atomistic
representations, wall-axis dimensions, Off/exit cleanup and cancellation of live
polling. The read-only Playwright test opens the persistent document and exercises
shared controls against the recorded native qualification trajectory.

### Recorded checks — 2026-09-12

- `just test-frontend`: **6,275 passed**, 403 files. A pre-existing surface-test
  debounce outlived jsdom; test teardown now drains it before restoring real timers.
- PEG Playwright review/control tests: **2 passed**. Real F7/F6/F4 representation
  switching, latest step 1000, RMSF scale, shared scrub/step controls, all 2,944
  water oxygens, periodic box, Off and zero DNA display/parser requests verified.
  RMSF and initial-configuration screenshots were visually inspected, then removed.
- Fast-relax creation/recorded-stage regression: **1 passed**. Its one queued child
  was deleted by `afterEach`; no engine was launched by the browser tests.
- New backend frame-reader tests: **3 passed**.
- `just test-smart`: `decision: FULL  (FULL suite)  [test-dedicated session OPEN]`;
  **8,295 passed, 554 skipped, 1 xfailed, 11 failed**. All failures require absent
  BigO/smallO workspace fixtures. No `DEFERRED` groups were printed.
- Changed Python files pass Ruff and `git diff --check` passes. Repository-wide
  `just lint` reports existing F841 in `routes_oxdna.py` and F401 in
  `test_oxdna_peg.py`.
- `just smoke` was refused by `scripts/sim_guard.py` because the real NAMD job was
  running. This broader smoke gate remains outstanding; its guard was preserved.
- Read-only dev API checks returned p10's 30 frames through step 120000 and the
  actively written p100 stage, including step 140000 at the time of inspection.
- Browser setup exposed a separate mrDNA job-reconciliation race:
  concurrent saves in one backend process share `job.json.<pid>.tmp`, and
  `os.replace` can report that temporary file missing. This is outside the PEG
  viewer; PEG interactions passed, but the workspace-wide mrDNA race remains open.

No test-created workspace/session files remain. The original eight MD job
folders and persistent review document are retained. `main.js` LOC delta for
this visualization task: **0**.

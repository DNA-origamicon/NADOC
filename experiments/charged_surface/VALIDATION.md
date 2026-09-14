# Surface profile validation — 2026-09-13

Persistent document: `workspace/NAMD_charged_wall_control.nadoc`.
Job: `6ed2945c805e`, running through the normal NAMD runner.
The test session was opened by the user; launch used the slow-test guard.

## Software checks

- Six focused backend tests pass: normalization, two-face volume, charge balance,
  finite-slit analytic oracle, periodic wrapping, restart rollback/torn tail,
  API validation and persistent POST/GET results.
- 6,280 frontend tests pass. Dedicated blank-document browser workflow passes,
  including the three surface plots (fixture response for plotting).
- `just smoke`: 23 passed. Backend logs still expose the existing mrDNA temporary
  file rename race; it did not fail this run's browser assertions.
- `just test-smart`: FULL, 8,712 passed, 15 failed, 143 skipped, 1 xfailed.
  Failures are in assembly/cando missing fixtures, PEG Live workers and SNUPI
  dynamics. No deferred group: the full suite ran in the open test session.
- Ruff passes for the changed analysis modules/tests. Repository lint still has
  two pre-existing errors in routes_oxdna.py and test_oxdna_peg.py.
- main.js LOC delta: 0. Browser-created document/draft/output artifacts cleaned.

## Native checks and initial observations

The GPU compatibility probe completed, followed by all 7,000 minimization steps
and entry into NVT dynamics. No NAMD job error was recorded at this snapshot.
Initial dynamics use 2 fs before the inherited 4 fs stages; 298.15 K thermostat.
No topology, coordinates or run parameters were changed after native launch.

An independent MDAnalysis reader reproduced every Na+/Cl- concentration bin in
`surface_profiles_0000002.json` exactly (maximum difference 0 mM). Each native
snapshot so far conserves the -26e wall + explicit-ion total at 0e.

At 2026-09-13T08:52:23.888922+00:00, 19 complete frames were available;
10 frames from the latter half were analyzed. Reservoir-region Na+
was 304.92 mM and Cl- was 234.63 mM. These are finite-cell
measurements, not the requested added-salt value. The corresponding reference
Debye length at εr=78.4 was 0.585 nm.

The pooled charge compensation inside ~1 nm rose from 23.1% (first recorded
snapshot) to 53.2% in the snapshot covering 88 ps. At the snapshot above it is
76.9%. This shows developing ionic compensation;
it does not establish a Debye law. The fit is still rejected (poor fit or an
upper-bound length), and no converged screening length is claimed.

## Ongoing observation

The running monitor saves the latest result every 60 seconds in
`workspace/md_jobs/6ed2945c805e/surface_profiles.json`, plus numbered snapshots,
`surface_profile_monitor.jsonl` and `surface_monitor.log`. It exits at a terminal
job state. Refresh the Surface ions and screening card or reselect the job to
read current results. These files supersede this time-stamped initial report.

Remaining qualification: stable separate-face profiles and bulk plateaus,
independent seeds, fit/bin/window sensitivity, longer trajectories, dielectric
calibration and finite-cell scaling. Do not infer equilibrium from neutrality,
a good single fit, or completion of this relaxation ladder.

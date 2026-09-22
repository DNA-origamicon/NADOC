# Alpine submission: periodic-image clearance

The Alpine review shows a separate **Periodic-image clearance** check before upload or SLURM submission. A low or unverified gap disables Submit until the user checks **Submit anyway — I accept the periodic self-interaction risk**. Reopening the review or changing the partition resets that acknowledgment. The submission endpoint recomputes the check; hiding the UI or using an API client does not skip it.

This check measures **fixed-pose envelope gaps**, independently of the existing rotational-diffusion guard. It applies to short runs, restrained runs, and production runs. `allow_undersized_cell` and an orientation restraint do not bypass it.

For each axis, the gap is the cell length minus the solute heavy-atom extent along that axis. It is a conservative lower bound on atom-to-image separation. A negative envelope gap indicates overlapping bounding envelopes, not necessarily colliding atoms. Translation of an intact solute does not change this measurement. Solvent and ions, including hydrated magnesium, are excluded using the prepared PSF; remaining solute heavy atoms are included.

The recommendation is **max(2.4 nm, twice the largest configured short-range cutoff)**. This is an engineering reserve for internal fluctuations and cell contraction, not the onset distance for direct interactions. Direct short-range interactions can occur below one cutoff; PME also includes long-range interactions. Passing this initial-pose check does not establish box-size convergence or predict future bending, swelling, or rotational diffusion. The existing rotational check remains separate.

The check reads the starting stage's real NAMD inputs. Production reseeds therefore use `equilibrated.coor` and its matching `equilibrated.xsc`, rather than the original design PDB or pre-equilibration box. Missing, inconsistent, dynamic, or unsupported inputs report **unverified**, requiring acknowledgment instead of silently passing. Nonorthorhombic cells are not currently evaluated. Implicit-solvent inputs have no periodic solvent-cell check.

Remote resumes choose their current checkpoint on Alpine. This check cannot certify that pose from stale local files, so resume reports unverified and requires explicit acknowledgment. No remote coordinate download is performed by the review.

API:

- `GET /api/md/jobs/{id}/remote-recommendation` includes `image_clearance`. Resume review sends `resume=true` (independent of the resource-selection `current` flag). Ensemble review sends `ensemble=true` and displays the worst result across every eligible replica.
- `POST .../submit-remote`, `POST .../resume-remote`, and `POST .../ensemble-submit` accept `allow_small_image_gap`, default false.
- A failed check returns HTTP 409 with the gap/recommendation or reason, and the override field name.
- All ensemble members are checked before any member is submitted.
- An accepted submission attempt appends its verdict and explicit override to `image_clearance_reviews.jsonl` in the job directory. The override is not inherited from prior runs.

This guard covers user-triggered Alpine submissions. It does not add runtime monitoring, resize the solvent cell, or change local/RunPod launch behavior.

## Regression motivating this check

`3x6SQ_norm_skips`, production job `9b1151dfca21`, had production-start envelope gaps X/Y/Z of **0.571 / 0.469 / 0.637 nm**. The original unrelaxed package had **2.4 / 2.4 / 2.482 nm**, illustrating why a production check must use the relaxed checkpoint. The new guard rejects that production start unless separately acknowledged, even though the old rotation override was already enabled.

Reference: [NAMD nonbonded interactions](https://www.ks.uiuc.edu/Research/namd/3.0.2/ug/node25.html) distinguishes the short-range cutoff from full electrostatics. The 2.4 nm recommendation above is NADOC's conservative default, not a NAMD guarantee.

## Verification (2026-09-21)

- Final focused backend run: **123 passed** (clearance, rotation guard, remote executor).
- Full frontend suite: **6,747 passed**; final affected frontend rerun: **31 passed**.
- Browser UI plus smoke/teardown: **24 passed**. Cluster calls in the clearance exercise were stubbed; no production submission was made. Workspace cleanup verified with no remaining `__e2e__` files.
- Whole-repository Ruff and diff whitespace checks passed. `main.js` LOC delta: **0**.
- `test-smart` decision: **FAST (fast suite only)**. Result: **8,801 passed, 8 failed, 7 skipped**. Seven failures require absent external photoproduct archive fixtures. One source-inspection failure occurred while the source file was being reformatted; it passed both earlier and in the final stable-source focused rerun. The broad run is not claimed green.
- Aggregate run time was 188 seconds, with **zero per-test budget violators**. Required read-only slow-test triage found no justification for marker or budget changes; 8,816 tests, six workers, and concurrent frontend/browser work account for the broad workload.
- The snap-installed `just` executable could not create `/run/user/1000` in this environment. Verification used the recipes' exact guard/command equivalents, retaining all suite guards.

Selection output:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

# Architecture (build → relax → produce → measure → adjust → repeat) — supporting detail

[Topic head](../../project_skip_twist_selfconsistency.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Architecture (build → relax → produce → measure → adjust → repeat)

- **Measures** (pure, in `backend/core/oxdna_health.py`):
  - `measure_geometry_rmsd(positions, reference)` — Kabsch-superpose the mean structure
    onto the analytic reference over shared keys → RMSD (nm). The STOP gate (target 0).
  - `measure_bundle_twist(positions)` — SIGNED global twist (deg, right-handed) the
    skips control. The STEER signal.
- **Constraint layer** (same file): `geometry_match` + `bundle_twist` registered in
  `_CONSTRAINT_MEASURES` (0 landmarks, in `_REFERENCE_MEASURES`). `check_relaxed_constraint`
  gained `reference_positions=`; `_dispatch_measure` filters the mean to the reference
  core (`_filter_to_reference_core`). For `geometry_match` the verdict also carries
  `steering={bundle_twist_residual_deg}` (RMSD is unsigned → can't pick direction).
- **Loop**: `iterate_to_constraint(..., reference_fn=)` recomputes the analytic reference
  per build (skips change the nucleotide set each iteration) and threads it to the verdict.
- **Skip tuning module** `backend/api/skip_twist_tuning.py`:
  `build_sq_skip_design(cells, length, skip_period)` (seamless route + full_autostaple +
  periodic skips + full_sequence), `core_reference_geometry(design)`, `PeriodAdjuster`
  (secant on signed twist residual), `iterate_sq_skips(...)` convenience wrapper.
- **Knob** = square-lattice skip PERIOD. `sq_lattice_periodic_skips(design, skip_period=48)`
  (loop_skip_calculator.py) is now parameterized; canonical default 48 unchanged. Smaller
  period = more deletions = more de-twist. Seed 48 (`SQ_SKIP_PERIOD_DEFAULT`).

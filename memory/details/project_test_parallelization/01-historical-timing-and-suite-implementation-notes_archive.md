# Historical timing and suite implementation notes — historical evidence

[Topic head](../../project_test_parallelization.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Historical timing and suite implementation notes

**2026-09-20 portable-fixture follow-up:** the user opened a test
session and requested full/slow validation, excluding CPD work running on another
computer. BigO/smallO and cube regressions now build their routed inputs headlessly;
assembly/history checks passed (54). Scaffold extension preserves existing assigned
bases while adding unknown bases only at new sites (8 focused checks). Tcl native
oracles now execute with the installed interpreter; native PEG tests use the built
Chudoba engine. MD reader, solvent, restart and display fixtures generate isolated
inputs rather than requiring archived jobs. The current full non-CPD run uses one
xdist worker to serialize GROMACS, with BLAS/OpenMP threads capped at one. FULL
completed: 8,946 passed, 17 skipped, 4 failed in 6 h 19 min; no unmarked timing
violators. The full-scale skip/twist campaign alone took nearly four hours and
passed. The mock-chain capability and two linker manifests are repaired pending
focused slow reruns; PEG Live bindings now build. Legacy mrDNA zero-step accuracy
and two bulk-insertion retention assertions remain active scientific failures. See `docs/portable_test_fixtures.md` and the maintenance report.

**2026-09-19 maintenance triage:** the native hybrid smoke test was renamed from
`test_prepared_hybrid_job_runs_on_fork` to `..._upstream` without updating `_SLOW_TESTS`.
The registry now matches; slow-only collection confirms it remains in the oxDNA group.
The loop-copy connected-component regression uses an 84 bp routed bundle with three
insertion sites per selected helix instead of 168 bp; its connectivity assertions are intact.
Final `test-smart`: FAST, 8,713 passed / 52 skipped / one cube-rerouting sequence failure,
107.74 s pytest / 116 s guard, zero per-test violators. The aggregate backstop still fired;
no tests were relegated for cumulative suite size. Seven review-packet and four Tcl skips
are explicit missing dependencies, not validation passes. See `docs/maintenance_2026_09.md`.

Backend tests run in parallel via pytest-xdist. The 2026-09-06 inventory contains
8,166 cases, including real MD and finite-element solves; full-suite wall time is
not a measure of the fast development loop.

**2026-09-10 fast-gate triage:** the two `test_bigo_periodic_flatten_*` cases in
`tests/test_assembly_flatten.py` load the full live BigO polymer, flatten thousands
of strands, and export its topology / reconstruct nucleotide geometry and FEM mesh.
They took 9.77 s / 16.87 s (5 s per-test limit), so they now live in `_SLOW_TESTS`,
area `cando`; `assembly_flatten` source changes select that same slow area. The
smaller flatten/periodic tests stay fast. **Historical fixture drift (resolved by the September 19 headless recipes):** the then-current
workspace polymer yields 5,366 strands and 1,624 seam distances, while these tests
hardcode 587 and 112 for an older three-repeat artifact. Both failed before their
classification changed; moving them to slow does not resolve those assertions.
The September 19 replacement constructs a deterministic three-copy assembly; its
conservation, seam-family and FEM-connectivity assertions pass.
The subsequent `just test-smart` run passed 7,721 tests (35 skipped), with zero
per-test violators (slowest 3.47 s). It still printed the aggregate 99 s / 90 s
backstop notice; the 7,755-case fast suite has broad cumulative cost, so no
additional tests were relegated merely to suppress that notice.

**2026-09-06 audit outcome:** across the full and final focused runs, all current
cases are accounted for: 8,076 passed, 89 test skips, one expected failure, plus
one collection skip. Frontend: 6,191 passed. The full command was intentionally
interrupted to cut the obsolete two-duplex OpenMM case at the user's request;
its watermark was not advanced. The queued tests and changed metric controls
then passed (40 focused checks in 3.85 s). No full-command pass is claimed.

The legacy OpenMM smoke assertions share one real simulation. Its unconnected-
duplex `<0.5 nm` separation gate was removed after audit: it asserts a model
behavior, not a software invariant, and the newer paired-reference campaign
already documents GBn2 separation limitations. Exact positive/negative drift
controls replace it; real smoke and single-duplex MD checks remain and passed.
See [[project_openmm_implicit]]. Timed `faulthandler_timeout` diagnostics crashed
this local Python 3.12.3 in `PyCode_Addr2Line`; use verbose case progress here
instead of interpreting that diagnostic crash as a dynamics failure.

**Fixture drift audit (2026-09-06).** Regression tests must construct the state they
assert rather than rely on the user's current workspace contents. Voltron's
empty-cluster regression failed after the live file was repaired; BigO-poly's
simulation parity fixture grew from one instance to three. The former now builds
explicit empty auto-cluster shells plus reference strands, and the latter uses a
temporary two-instance 6hb assembly across all six engine preparation/lifecycle
routes. Failure-safe document finalizers run even when fixture setup fails.

The same audit found seven molecular-placement cases whose original workspace
fixtures are absent (`6hb_2xT`, `2x3SQx32_2xT`, `24hb_1xT`). Like the existing
Voltron surface panel, these now explicitly skip with the missing path; absence
is not a geometry pass. Restore the original inputs to exercise their unchanged
clash, piercing, bond and displacement assertions.

The July surface-envelope baselines used legacy 1ZEW templates. Their test now
requests those templates explicitly: Voltron area is 18152.6 nm² versus the frozen
18077.7 nm² baseline; the native measured-template build is 19045.7 nm². Native
surface determinism and vectorized/exact equivalence remain covered separately.
All 14 surface tests passed; no golden, tolerance or production geometry changed.

The real NAMD benchmark uses an 8 bp 6hb in a temporary workspace, retaining its
full minimization/warmup/MD protocol. Preparation is capped at four threads and
the trial at two, with cancellation/join cleanup even on failure. It passed in
the full audit after the old 32 bp fixture exceeded its 600 s deadline.

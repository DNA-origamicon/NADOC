# September maintenance follow-up

Current test policy (2026-09-20): normal commands validate software only. Production,
equilibrium sampling and physical convergence campaigns require explicit
`just test-scientific TARGET`; see [inventory](scientific_validation.md).
Historical full-run commands/results below predate this split; the legacy
`NADOC_RUN_OXDNA_SLOW` flag no longer enables campaigns.

Scope: the six findings from the September 1–19 commit review, plus nearby defects exposed
while fixing and validating them. Scientific phase constants, saved user designs, and native
simulation protocols were not changed.

## Implemented

1. **Response ordering.** `frontend/src/api/design_revisions.js` separates full-design
   revisions from per-field authoring acknowledgements. Annotation, view-volume, and camera
   responses cannot discard a required older geometry response. Newer acknowledged fields
   are merged into that response. Independent metadata fields do not suppress one another;
   stale acknowledgements after closing a design are ignored. Optimistic-concurrency requests
   still use the latest observed server revision. Unit and API-client ordering regressions added.
2. **Trajectory memory.** JSON fallback frames become float64 typed arrays (no precision
   reduction). Both transports now count toward the coordinate budget, and eviction/reloading
   retains exact requested frames. Accounting inspects every frame rather than assuming the
   first is largest. Tests cover JSON, binary, limits, eviction, exact seeks, and double precision.
   The existing policy retains one foreground page even if that page alone exceeds the budget;
   this is a coordinate-cache target, not a hard cap on the browser's total heap or GPU memory.
3. **Lint.** Cleared the six failures in the configured backend/tests lint command. The unused
   nanoparticle response in a test now has an explicit HTTP-success assertion.
4. **Shared numerical code.** `backend/core/md_frame_alignment.py` owns rigid alignment and
   the sequential inlier guard for live coarse display and trajectory extraction. The existing
   periodic unwrap/reassembly functions were already shared; reader-specific inputs remain
   with their readers. Portable tests cover rigid transforms, nonrigid exclusion, isolated reader
   histories, missing references, sequential outliers, and random seeks. A one-time comparison
   against commit `9aec578d` produced exactly equal rotations and zero coordinate difference
   across 500 frames; see `validation/maintenance_alignment_equivalence.json`.
5. **Module boundaries.** MD creation/production/summary models moved to
   `backend/api/md_request_models.py` (over 500 lines removed from the route file), with
   compatibility exports. Pure trajectory sizing/timing/progress presentation moved to
   `frontend/src/ui/md_trajectory_presentation.js`; revision policy moved out of the API client.
   The large modules still have further extraction opportunities; this is incremental maintenance.
6. **Generated evidence.** Thirty exp59/exp60 summaries are retained as deterministic gzip,
   indexed by original-byte SHA-256 and sizes. All archives were checked against their original
   committed bytes. 20,065,088 bytes became 1,800,762 bytes. Campaign readers/cached-run checks
   accept both formats, writers emit gzip, and original CSV/Markdown reports remain readable.
   See `experiment_artifacts.md`. Existing Git history is unchanged; no external artifact service
   has been selected or falsely implied to hold the results.

## Additional repairs

- `state.load_design(None)` again clears a document without crashing in nanoparticle prewarming.
  This restores the empty-session contract used by aptamer import/history tests.
- Headless orchestration mocks advertise the current physics signature. They simulate lifecycle
  and display recovery, **not native physics**, whose capability and scientific tests stay separate.
- Toolchain tests now exercise an explicit fake GNOME Orca and missing executables instead of
  assuming this workstation has NAMD/psfgen installed.
- Tcl native-oracle tests now locate the interpreter and SDK in flat conda installations
  as well as system layouts, and compare an executed native extension against Python forces.
  CPD/photoproduct edits from the subsequent test-repair pass were withdrawn at the user's
  request; CPD validation is running on the other computer.
- The renamed native oxDNA hybrid smoke case is again registered as slow. Its old `fork` registry
  name no longer matched the `upstream` test. This closes an accidental real-binary fast-suite leak.
- The loop-copy connectivity regression uses an 84 bp bundle instead of 168 bp, retaining multiple
  insertion sites and all component/bond assertions. It remains in the fast suite.
- Browser teardown now also removes hidden project-revision stores for test parts, but only
  after every stored snapshot proves test ownership. Mixed user/test or corrupt history is
  preserved. Four orphan stores from this session were removed through that same guard.
  Unit coverage checks deletion, deduplication, path traversal, mixed history, and corruption.
  Final disk checks found no test-prefixed parts, scratch outputs, or recent test project stores.
- Graphene setup tooltips and their browser test now point to **Box and solvent**, where the
  fields moved. The test no longer demands duplicate preparation fields in the wizard.

## Validation

- Configured `ruff check backend/ tests/`: passes.
- Frontend full suite: 460 files / 6,639 tests passed. The subsequently added client integration
  regressions also passed (13 focused checks including the earlier revision/stream tests).
- Production frontend build passed; it still warns about large chunks.
- Focused backend extraction/artifact/reader checks: 40 passed.
- Updated headless orchestration, loop-copy, and alignment checks: 298 passed / 39 deselected,
  37.04 seconds pytest / 40 seconds guard; zero per-test budget violators.
- Annotation browser suite: 3 passed (editing, dragging, protein/nanoparticle targets, file
  persistence, global toggle, and import round-trip). Test parts removed by global teardown.
- Updated graphene setup browser checks: 2 passed.
- Cleanup/revision/stream final focused frontend run: **16 passed**.
- Browser ordering regression passed against the real backend with a delayed full
  design/geometry response and a newer annotation acknowledgement.
- Initial broad backend run, before the test session: **8,713 passed, 52 skipped, 1 failed**
  (cube rerouting, subsequently repaired),
  107.74 seconds pytest / 116 seconds guard. No individual test exceeded five seconds.
  The aggregate 90-second backstop still fired. Triage found broad suite cost (8,766
  outcomes), not another native-test leak; no additional tests were relegated just to
  silence the warning. Headless orchestration and geometry fixtures remain the largest
  cumulative costs. Profile fixture reuse before changing test selection or budgets.

That pre-session `just test-smart` selected **FAST (fast suite only)**. Its deferred message was:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

No session marker, budgets, guards, CI configuration, or golden geometry was changed.

## Open validation and separate findings

- **Full non-CPD validation completed:** `just test-smart` selected FULL and returned
  **8,946 passed, 17 skipped, 4 failed** in 22,734.919 s (6 h 19 min pytest time).
  CPD/photoproduct work was explicitly excluded. One worker serialized native simulations.
  The full-scale skip/twist campaign passed, but dominated runtime; test-count progress near
  99% concealed hours of remaining work. See `validation/maintenance_non_cpd_backend_2026_09_20.json`.
  There were no unmarked per-test budget violations. No all-green full pass is claimed.
- **Post-run repairs pending slow validation:** the mock chain now advertises current physics
  capabilities, and mrDNA linker fixtures emit the required nucleotide manifest instead of
  swallowing decoder errors as skips. PEG Live bindings built successfully and report available. The initial
  user-opened session expired during the full run; five focused slow reruns require a new window.
- **Bulk extra-base retention:** 6HB and 18HB bulk-insertion relaxation retained 84.33% and
  84.92% of designed pairs versus the unchanged 85% threshold. Both failed before production.
  Their precise-insertion counterparts passed. Two native tests also passed topology.top where
  the reader requires the initial conf.dat; corrected. Re-reading the saved bulk results with
  conf.dat leaves both retention values unchanged. Neither tolerance nor physics was changed.
- **Legacy mrDNA decoder:** fixing ignored fixture arguments exposed a real zero-step position
  mismatch: mean 0.691 nm versus the unchanged 0.10 nm limit. This per-helix decoder is still
  used by MD seed preparation. Its assertion remains active; no geometry, tolerance or locked
  phase change has been made to conceal it. Scientific clarification is pending.
- **Historical native-reference inputs:** the two SNUPI census comparisons and two manual
  hinge regressions need the original small designs (`6hbx100_noT`, `3x4SQ`, and
  `3x6_hinge_bound_end_to_root`), plus `Hinge3`, `6hb_2xT`, `2x3SQx32_2xT`, and
  `24hb_1xT` for protected-anchor and approved molecular-placement regressions.
  Arbitrary generated replacements would not preserve those
  independent reference results. The requested archive path is pending; runtime tests should
  use portable pinned inputs, never that machine's archive mount.
- **Browser memory/GPU:** JSON budget behavior is unit-tested; real large-trajectory playback,
  representation switching near the budget, and GPU allocations still need an in-app memory run.
- **CI gaps:** frontend CI runs Vitest but not a production build or browser smoke. The build
  currently succeeds with chunk-size warnings. Consider adding a build and a bounded isolated
  browser test gate; this change does not alter CI policy.
- **Obsolete assumptions:** source-text-only rendering checks cannot establish visual behavior;
  historical suite totals are not current validation; workstation executable availability is not
  a unit-test invariant. The old hybrid smoke registry name and moved wizard-field assertions
  were corrected rather than used as evidence that those paths had been tested.

## Portable-fixture and native-test follow-up

See `portable_test_fixtures.md` for generated inputs and their limits. Completed focused checks:

- Assembly flattening/history: 54 passed. Headless periodic recipes replace mutable BigO/smallO
  workspace assemblies, retaining seam/FEM/atomistic checks and conservation assertions.
- Scaffold extension sequence bookkeeping: 8 passed. Existing assigned bases stay at their
  correct offsets; only newly introduced sites receive unknown bases, with loop/skip accounting.
  The cube rerouting/idempotence check now builds and reloads its own routed/stapled input.
- Real solvent extraction: 18 passed. Native solvation/ionization prepares the package, then
  controlled whole-water motion tests affine transforms, imaging, selection and charge census.
- Large display readiness: passed on generated 18HB × 200 bp / 7,200 nucleotide input
  (8.11 s initial load, 366 ms warm response, 0.2 Å aligned RMSD). This is controlled motion,
  not an equilibrium claim or a browser heap/GPU measurement.
- Native GROMACS round-trip and binary XTC checks passed using fresh temporary preparation
  and minimization. The roughly 11 s shared native fixture belongs in the slow registry.
- Installed Chudoba CPU/CUDA cases run rather than skip. Their script failures exposed a stage
  schema bug: Langevin friction may be explicit `gamma_trans` or `diff_coeff`, exclusively.
  The schema and scripts now support that existing native-engine contract; parameter values
  are unchanged. Focused native recheck: 144 passed; its two remaining fixture failures then
  passed in a 5-case rerun (fine-resolution mrDNA tail plus overhang azimuth cases).
- mrDNA native fixtures now write/bind the required nucleotide manifest and propagate native
  failures. Coarse output without orientation particles uses the existing translation-only
  decoder path instead of incorrectly requiring one fine nucleotide frame per coarse bead.
- Nick/ligation sequence preservation was also repaired while constructing many-strand inputs.
  Fourteen regressions cover both directions, insertions/skips, unassigned sequences and partial
  ligation. Together with generated CanDo parity and startup isolation: 67 passed. The updated
  sequence-dependent trajectory and large-display fixtures then passed all 9 checks (34.09 s).
- Test startup now uses the isolated workspace for audit logs, session caching and job supervision;
  the previous fixture only patched the assembly module, leaving startup's imported path stale.
  A real startup/shutdown regression checks the audit file and job directory in temporary storage.
  The interrupted first non-CPD run had 3,055 passed / 3 missing-input skips and no failures;
  it was stopped to apply this isolation fix before more startup tests ran.
- Memory lint: zero errors after repairing five missing index entries and a broken workspace-report
  link. Fifty-nine long-file warnings remain; no mass rewrite of historical notes was attempted.

Obsolete tests removed: an always-skipped XTC placeholder (replaced by a real generated binary
round trip), a missing uncommitted early-stop log bank replay (portable parser/parity controls
remain), and the permanently xfailed >50% mrDNA minimization speedup assertion whose reference
already converged in approximately 15 steps. Their removal is not evidence of physical speedup.

### Further validation improvements identified

- Separate reported runtime estimates for short native integration checks and multi-hour physical
  convergence campaigns. The latter should remain explicit, visible validation obligations;
  do not silently skip them or weaken their convergence criteria. No selection/guard policy changed.
- The bulk-insertion oracle gates one stochastic final frame. Investigate retention histories and
  replicate variability before treating the narrow misses as either a software defect or acceptable
  sampling noise; a rerun-until-green policy would conceal this uncertainty.
- A generic headless 3×6 hinge is not equivalent to Hinge3's manual-anchor preservation case: it
  intentionally takes the specialized hinge routing path. Its replacement attempt was withdrawn;
  the original assertion remains pending its original input.
- Completion detection now has an independent process watcher and an atomic completion marker.
  Its notification fired when pytest exited. The conversational waiter alone does not survive an
  interrupted turn, and this interface exposes no independent scheduler to wake a closed conversation.

Native failure inputs, seeds, logs and final configurations are retained in
`experiments/maintenance_20260920/bulk_extra_base_failures.zip` with per-file and
archive SHA-256 in its manifest. No user workspace artifacts were created for this evidence.

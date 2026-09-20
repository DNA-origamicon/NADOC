# CPD strand-builder integration — 2026-09-20

Implemented preliminary additive cis-syn v6 support for adjacent internal TT on
one strand. Full scientific-release gates remain pending. Formation preflight,
proper-rotation placement, exact psfgen patch delta, frozen force-field packaging,
CUFIX aliases, and continuation timestep/HMR restrictions are connected.
The ordinary design view retains its product-intent marker; actual product
coordinates and topology are generated for NAMD.

## Delivered and checked

- Example: `docs/examples/cpd_preliminary_duplex.nadoc` (12 bp).
- Self-contained ZIP: `.development-artifacts/cpd-builder-integration-v1/CPD_preliminary_demo.zip`.
- Native NAMD: 40,061 atoms, 1,000 minimization steps, then 1,000 steps at 2 fs.
  Finite energy output; all four CPD stereocenters and both crosslinks pass in
  every one of 10 saved dynamics frames. Maximum heavy-atom bond: 1.679884 Å.
- Actual minimized structure: `.development-artifacts/cpd-builder-integration-v1/native_duplex.png`.
- Live Chromium formation/import/atomistic-view check passed. CPD progress browser
  check passed separately. Final screenshot inspected; test workspace files removed.
- CPD backend regression subset: **61 passed**.
- `just test-frontend`: **455 files, 6,573 tests passed**.
- Changed backend/test files pass Ruff. `git diff --check` passes.
- Task-specific `main.js` LOC delta: **0**. Existing unrelated edits preserved.
- No cloud resources or money used. No long simulation campaign launched.

## Repository-wide checks are not green

`just test-smart` selected **FAST (fast suite only)** and finished with
**8,619 passed, 27 failed, 116 skipped, 9 errors**. No CPD/photoproduct tests failed.
Remaining failures are in other workflows, including missing fixture/data paths
and assembly, oxDNA, CanDo and aptamer tests. They have not been repaired by this task.
Exact deferred notice:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

`just smoke`: **22 passed, 1 failed**. The assembly-exit console gate caught an
HTTP 500 from the mrDNA job listing/persistence path (`FileNotFoundError` renaming
`job.json.<pid>.tmp`). The CPD browser tests pass independently.
`just lint` reports three findings outside this task: unused variables/imports in
`backend/api/routes_oxdna.py`, `tests/test_oxdna_peg.py`, `tests/test_streptavidin.py`.

Logs, native outputs, plots and failed smoke diagnostics are retained under
`.development-artifacts/cpd-builder-integration-v1/`. Disposable Playwright output
folders and `__e2e__` workspace files are absent after teardown. These checks qualify
integration/startup; they do not add an ensemble-convergence claim to the prior
34-ns benchmark or validate Drude or additional stereoisomers.

`just lint-memory` also remains red: five unrelated topic heads lack index entries
(Amber GB ion, crossover catenation, nucleotide transform, protein conjugation,
VoltronCoreArm visualization remediation). The new CPD topic is indexed.
Final ZIP audit verified all 11 packaged asset hashes and the preliminary-use notice.

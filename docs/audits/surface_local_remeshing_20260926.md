# Figure quality promotion and local remeshing

## Display behavior

Figure quality permanently uses the continuous closed-occupancy field, sampled
on the shared 0.05 nm world lattice with 0.0425 nm Gaussian sigma, followed by
four Taubin iterations. The legacy `chimerax` API name is retained; `continuous`
is now an alias for the same surface. The new display default probe is 0.10 nm.
The user can still change it, and Figure quality / Local remeshing share the
remembered probe. No saved design files or molecular coordinates were modified.

The former temporary Continuous field control is now **Local remeshing
(temporary)** (`detail=remeshed`). Both native design and simulation display
paths apply the same remeshing operation. Native strand shells remain independent;
simulation shells retain their previous fused grouping.

## Local algorithm and limits

`backend/core/surface_remesh.py` detects adjacent-face normal turns >=60 degrees.
It splits the incident triangles and the matching edges of neighboring triangles
(conforming red/green refinement). Only sharp-edge endpoints and newly inserted
vertices can move. A fixed surrounding face ring makes the objective account for
normal turns across the patch boundary. Up to eight local relaxation steps are
accepted only when length-weighted squared excess turn above 60 degrees decreases.

Each vertex stays within 0.01 nm of its baseline position (new vertices start on
baseline triangle edges). Candidate steps reject face collapse below 10% of its
reference area or orientation changes beyond the normal-dot guard of 0.2. Other
regions remain exactly unchanged. Original molecular atoms are never moved.
New/moved display vertices inherit nearest-reference strand/nucleotide ownership.

This is bounded mesh regularization, not projection onto an analytical or implicit
solvent surface. Subdivision preserves connectivity; the orientation checks are
local and do not prove the absence of self-intersections. The experiment is not a
physical solvent-accessibility calculation. Global area alone is not a guarantee
of preserved pore detail. Use the displacement bound and visual comparison too.

Integer edge keys avoid expensive structured row sorting; relaxation uses a sparse
adjacency matrix on local patches. Sharp-edge detection still scans the whole mesh,
so there is overhead even when refinement is sparse. Existing CUDA closing remains
in use; no extra CPU/GPU transfers were added for the local mesh operation.

## Verification and evidence

- Surface-focused tests cover default/radius routing, permanent-mode alias parity,
  native/simulation selection, dense/tiled field agreement, conforming refinement,
  ownership, displacement bounds, smooth-sphere no-op, and an unchanged separate shell.
- `.development-artifacts/surface-remesh/mini_rect.json` contains the final comparison
  on the read-only `workspace/mini_rect.nadoc` input at 0.10, 0.14, and 0.24 nm.
- `.development-artifacts/surface-remesh-comparison/` holds purposeful browser A/B
  screenshots of an isolated six-helix, 12-bp fixture. The test switches Figure quality
  → Local remeshing → Figure quality and checks exact restoration.
- `main.js` LOC delta: 0.

Playwright pre-run inventory found no owned test session, revision store, fixture,
report directory, or isolated-port credentials. The fixture uses
`__e2e__surface-continuous` as its document/name, with exact afterEach cleanup for
`.session`, `.nadoc-projects`, and `playwright_tests` paths. Global teardown removes
prefixed workspace files/revision stores and viewer credentials; the reporter removes
Playwright outputs. The screenshots are intentionally retained outside the workspace.

Backend verification: `just test-smart` selected **FAST**. First run: 9,278 passed,
15 skipped, eight previously recorded photoproduct-review/CPD-preview failures;
99 s guard wall time while the diagnostic benchmark was also running. The required
`triage-slow-tests` skill was read and the report inspected: no per-test violators.
An isolated rerun took 93 s (91.06 s pytest), still over the 90 s aggregate backstop:
9,278 passed, 15 skipped, those eight failures plus the newly added separate-shell
test. That fixture accidentally extracted exactly through lattice vertices,
producing degenerate triangles; moving the analytic test isovalue off the lattice
and disabling degenerate triangles corrected the fixture. All four remeshing tests
then passed in 2.58 s. The other 26 surface checks had passed in the preceding
focused run. No production remeshing change was needed for that test correction.

No tests were reclassified and no guard/budget was changed. The isolated aggregate
overrun remains recorded; the report showed broad 1–4 s tests, with no identified
shared accidental slowness warranting changes outside this task. Full-suite debt
remains, as reported by the selector:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

Frontend: 543 files passed, 7,077 tests passed / one skipped. After the final toggle
identifier change, all 44 surface-controller tests passed again. Lint and whitespace
checks passed. No `main.js` change.

## Final mini_rect comparison

Figure quality → local remeshing, with otherwise matched settings:

| Probe (nm) | >60° edges | >90° edges | Maximum turn | >60° edge length reduction | Warm generation seconds |
|---|---:|---:|---:|---:|---:|
| 0.10 | 107 → 19 | 0 → 0 | 88.6° → 70.6° | 86.4% | 5.78 → 8.48 |
| 0.14 | 19 → 0 | 2 → 0 | 105.4° → 59.5° | 100.0% | 6.69 → 8.42 |
| 0.24 | 158 → 58 | 24 → 8 | 152.6° → 102.9° | 80.8% | 13.56 → 16.63 |

All three outputs have zero boundary edges, nonmanifold edges, and degenerate
faces. Global area changes remain below 0.002%; added triangles remain below
0.06%. These are diagnostics on one design, not a guarantee about all pores or
self-intersections. The final run includes the integer-key optimization and the
fixed face ring. Each mode was warmed once and measured once; these are advisory
timings, not statistically robust speed benchmarks. Browser smoke ran during the
later 0.24 nm measurements. Quality analysis and serialization are excluded.

Large-design browser limitation: the initial mini_rect A/B attempt exceeded
Chromium's inspector response-body cache. Capturing and forwarding the response
fixed that test-tool issue, but the 2.6-million-triangle scene then stalled the
headless SwiftShader renderer (a previously documented limitation in
`memory/project_voltroncorearm_visualization_remediation.md`). The isolated test
browser was stopped and teardown verified. Final browser verification therefore
uses the six-helix fixture (276,224 → 276,264 faces; >60° edges 4 → 0), while the
complete mini_rect meshes are validated by the numerical audit. This is not a
hardware-GPU render-performance benchmark. Browser fixtures are never saved over
the original mini_rect design.

Final app result: 23 smoke/assembly checks passed, followed by a passing focused
A/B run (56 s test time). The new 0.10 nm default and both controls were exercised.
Figure quality restored exactly in both mesh bytes and rendered pixel hash after
switching back. The remeshed surface had distinct mesh bytes and pixels; no page
or shader errors were recorded. Both saved screenshots were inspected. Post-run
queries confirmed absence of all inventoried fixture/session/revision/report and
isolated credential paths, including after failed attempts. Only the documented
comparison evidence remains.

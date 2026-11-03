# NADOC desktop benchmark map

As of **2026-10-22**, the desktop survey covers **54 major operation families** across authoring, documents, history, assemblies, chemistry, rendering, playback, simulation, jobs, sharing and application controls. The strongest fresh optimization candidate is native display-geometry generation. The largest measurement gap is user-input-to-visible-result latency in the browser.

Track the ongoing three-operation optimization rounds in [rounds.md](rounds.md). The survey baseline below predates those optimizations.

Start with the [workflow matrix](workflows.md), [current findings](findings.md), and [benchmark protocol](protocol.md). The machine-readable registry is [workflows.tsv](workflows.tsv); the exhaustive source inventory is [inventory.csv](inventory.csv).

## What percentage is mapped?

“Operation” has several meanings. We report separate denominators rather than combine unrelated counts into a misleading percentage:

| Coverage measure | Result | Meaning |
|---|---:|---|
| Backend route declarations assigned to a functional area | **832/832 = 100%** | Structural ownership map; not a claim that every route is active or measured |
| Eligible frontend JavaScript modules assigned to an area | **759/759 = 100%** | Structural map including shared viewer code; not individual UI actions |
| Backend core modules assigned to an area | **453/453 = 100%** | Includes supporting algorithms, cache and transport code |
| Curated major operation families with owner and benchmark contract | **54/54 = 100%** | Our estimate of broad product-operation mapping; not exhaustive combinations |
| Families with current CPU component measurements | **20/54 = 37.0%** | Fresh runs on this worktree |
| Additional families with linked historical component results | **6/54 = 11.1%** | Older fixtures/revisions; not refreshed or comparable across hosts |
| Families with either current or historical measured component evidence | **26/54 = 48.1%** | At least one component measured; not complete family coverage |
| Additional families with a linked harness only | **7/54 = 13.0%** | Reusable starting points, not counted as measured here |
| Families with no linked performance evidence | **21/54 = 38.9%** | Explicit backlog; not a claim that no test exists anywhere |
| Families fully measured from input through backend to visible completion | **0/54 certified here** | CPU results must not be substituted for desktop UX measurements |

The practical estimate is that **most major desktop operation areas are now mapped**, while only **about 48% have linked timing evidence for even one component**. There is no defensible percentage of *all possible user actions* or *total runtime consumed*: neither production usage frequencies nor the full cross-product of modes, sizes and states is available. “100%” above is strictly completeness against the named structural or curated denominators, not a whole-application performance claim. All families have equal weight; a small menu action counts as one family just as a simulation workflow does.

The source census and component evidence were refreshed during round 4 and includes concurrent worktree additions: 832 route declarations, 759 frontend modules and 453 core modules. Historical initial-pass counts below describe the earlier snapshot.

See [generated coverage](coverage.md) and [counts/source hashes](coverage.json) for exact denominators. Initial classification mapped 734/830 routes (88.43%), 680/760 frontend modules (89.47%) and 392/449 core modules (87.31%). A second pass identified generation, MD, atomistic, navigation and resource-management owners and explicitly excluded four scene-debug helpers. The final pass added parameterization, checkers and library modules to the census and linked concrete workflow contracts/evidence.

## Scope and limitations

The census scans `backend/api`, `backend/core`, `backend/physics`, `backend/parameterization`, `backend/checkers`, `backend/library`, and `frontend/src`. Parameterization and experimental screening are mapped but no scientific campaign was launched. Native VR code, VR-named modules/routes, test files/helpers, archived frontend code and debug helpers have explicit exclusion reasons in the CSV. `backend/ml`, offline experiments, scripts used only for research, static data and third-party/native simulation internals are outside this desktop runtime census. Dormant ML propagator code is not treated as an active desktop operation. Mixed desktop/VR modules remain included unless their filenames trigger the explicit exclusion rule; shared functionality in VR-named files is therefore a possible undercount.

Source classification uses **ordered filename/path rules**, not measured call graphs or a proof of reachability. A file can serve several areas but is counted once under its first matching owner. Broad `ui`, `physics` and parameterization directory rules supply coarse ownership only. Route rows are AST decorator declarations: router prefixes, mounting, dynamic registration and multiple methods inside `api_route` are not expanded. CSV paths/line numbers identify their definitions; the route text is not necessarily a callable URL. Frontend modules are not action counts. These limitations are why structural percentages and measurement coverage remain separate.

Current results come from the existing dirty worktree. Existing edits were preserved; the base commit alone does not reproduce it. The report records dirty paths, host, interpreter, commands and harness hashes; the census records inspected source hashes. Source hashes identify bytes but do not archive another session's uncommitted changes. Synthetic straight bundles, empty assembly part sources, small PDBs and generated atom buffers expose scaling, not representative scientific completeness. Browser, real GPU, network, disk persistence, fresh-process startup and remote execution were not measured in this batch.

## Reproduce and maintain

From the repository root:

```sh
python scripts/desktop_benchmark_inventory.py
scripts/validation_guard.sh .venv/bin/python scripts/benchmark_desktop_baseline.py
# Optional diagnostic profile (overwrites the compact profile report):
scripts/validation_guard.sh env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m scripts.benchmark_desktop_core --profile \
  > docs/benchmarks/desktop/geometry_profile.json
```

The optional profile CLI was added after the recorded timing sweep; the timing path is unchanged, but its recorded harness hash therefore predates that CLI addition.

The first command is a static scan and validates all workflow source/evidence links. The second runs eight sequential cases/harness invocations and retains compact results in `current_baseline.json`. It requires the mounted Archive scratch filesystem and the repository environment, Node dependencies, and existing inert A/B fixture sources. It does not launch the app, a browser, a simulation or remote jobs. Failures/timeouts are retained and return a failing exit status. Do not interpret a partially written result as a completed baseline; inspect all exit codes and `finished_utc`.

The baseline command overwrites the current report. Before an optimization comparison, retain a dated compact copy and compare identical fixtures, source revisions, machine and settings. After adding a workflow or evidence link, update `workflows.tsv`, rerun the census, and update this summary if the denominator changes. Keep unmeasured rows visible. Do not promote a harness to measured coverage merely because its file exists.

## Validation and retained artifacts

- Eight baseline invocations completed successfully, including output-equivalence checks in existing harnesses and new geometry nonmutation/round-trip invariants.
- The new core harness measured six pipeline stages at three sizes, with 15 warm samples per stage plus a first-call measurement.
- A separate one-call warm CPU profile was collected for the largest native geometry fixture; see [geometry_profile.json](geometry_profile.json).
- Static census regeneration, linked-path checks and focused Python lint were used to validate the documentation tooling. No application behavior changed; full backend/frontend suites and browser acceptance were not run.
- Scratch was placed under the verified Archive-backed `.development-artifacts/desktop-benchmark/tmp`, found empty, and removed along with its task directory. Compact JSON/CSV/TSV/Markdown evidence is retained here. No user designs/jobs or preexisting artifacts were deleted.

## Local raw evidence

Raw test logs (`*.txt`) and the diagnostic PNG are retained under `.development-artifacts/worktree-cleanup-20261029/desktop-benchmark-logs/`, with local compatibility symlinks. They are excluded from Git; the JSON measurements, inventories, reports and reproduction scripts remain tracked. Archive `inventory.json` records their sizes and SHA-256 checksums.

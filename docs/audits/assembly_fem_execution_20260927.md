# Assembly CanDo / SNUPI execution — 2026-09-27

Scope: launch and display FEM predictions for assemblies, including the local
30-instance `BigO-poly.nass` (424,144 flattened nucleotides, 1,680 helices).
Companion audit: `assembly_simulations_20260927.md` covers passive tab browsing.

## Contract and fixes

- Shared CanDo/SNUPI request models, material laws, coarse/fine controls, RMSF,
  thermal sampling, anchors/field and SNUPI dynamics/hydrodynamics are retained.
  No topology, geometry constants, material parameters or sampling counts changed.
- Canonical flattening retains all copies and reconstructs stitched crossovers.
  Explicit FEM launches use a compact acknowledgement, avoiding a full browser
  Design replacement, redundant part geometry generation and hidden part rendering.
  Other engines retain their existing full projection; the cache distinguishes them.
- Job snapshots own FEM results. Result reads/restarts/stops/deletes do not prepare
  the current assembly. Assembly visualization cannot reuse an unrelated live part
  scene just because the backend fingerprint matches the flattened simulation Design.
- Counting, fingerprinting, project revision recording, hydrodynamic preflight and
  snapshot preparation run in FastAPI's worker pool, preserving document context.
  Single-job fingerprint polling, large display/RMSF/trajectory JSON reads and full
  snapshot geometry loading also run in workers.
- Both engines share the existing per-document/revision fingerprint cache instead
  of reserializing the complete assembly on every poll. No-RMSF node summaries use
  actual axis-node counts rather than dividing terminal-inclusive nucleotide counts.
- CanDo uses the CPU contention policy. Both launch panels catch preparation errors;
  temporary rows are removed after success or failure, and failed launches can retry.
- Existing provenance, lifecycle endpoints, progress, persisted options and job
  filtering are shared with parts. Physical results remain display-only.
- `frontend/src/main.js`: this task's net LOC delta **0**.

## Native evidence

Read-only direct full-BigO coarse solves, one BLAS thread, RMSF disabled:

| Engine | Solve + reconstruction | Peak process RSS | FEM nodes | Returned nucleotide records |
|---|---:|---:|---:|---:|
| CanDo | 96.96 s | 5,204 MiB | 211,680 | 424,144 |
| SNUPI | 93.74 s | 5,467 MiB | 211,680 | 424,144 |

The mesh has one connected component and 211,624 elements; canonical flattening
reconstructs 22,740 crossovers. Both the flattened strand-order count and returned geometry include terminal
bases beyond the lightweight source-count estimate of 423,360. Linear solve itself took about 28–31 s; native
nucleotide reconstruction took about 52 s. Those costs are not browser preparation.

## Validation and cleanup

Focused preparation/API regressions: **7 passed**, including concurrent capability
requests during blocked preparation and document-context preservation for both engines.

Native browser test is opt-in: `uv run python scripts/verify_assembly_fem.py`.
Artifact inventory: engine job directories (snapshots/results/progress/logs), project
revision stores, operation logs, and `__e2e__` autosaves all live in a unique disposable
workspace. The wrapper removes it in `finally`, after Playwright shuts down its API,
Vite and browser; remaining detached SNUPI workers are identified by PID, command and
workspace before termination. The isolated Vite bridge credential in `/tmp` is also
removed. Session caching is disabled. Screenshots/traces are managed by Playwright's
cleanup reporter. Original BigO assembly/source files are read-only.

Initial browser attempt failed on a test-harness omission: the RMSF checkbox was in
its collapsed Advanced card. No jobs launched; disposable workspace and credentials
were removed. The test now opens the card before using the control.

Full-size NMA/thermal sampling and SNUPI Langevin dynamics are separate expensive
workloads; the BigO execution check explicitly selects static coarse prediction with
RMSF unchecked. No advanced option is silently disabled or approximated for assemblies.

A subsequent browser attempt caught a mistaken oracle (423,360 advisory source
count versus 424,144 actual flattened nucleotides), corrected without changing
production counts. Another attempt encountered an HTTP keep-alive connection reset
during native computation. Polling now retries ECONNRESET using Playwright's
`maxRetries` (matching production's protected transport); production fingerprint
polling and result loading were also moved off the event loop. Disposable artifacts
were removed after each attempt.

The fourth browser attempt completed CanDo but exposed the no-RMSF node-count bug
(212,072 reported versus 211,680 actual mesh nodes). This is now fixed in both
cache writers and pinned with unpaired-terminal regression cases. The same run
exposed repeated full-topology fingerprint work; the shared revision cache is now
used by both FEM panels and is regression-tested across engines and revisions.

BigO full-nucleotide scene experiment: CanDo completed in 224.05 s while the
software-rendered browser was active, loaded snapshot geometry, and reached
“Showing predicted shape.” Headless SwiftShader then took ~80 s per frame,
making subsequent browser interactions impractical. This attempt was interrupted;
all tagged test processes and its disposable workspace were removed. The final
browser spec exercises the regular cylinder result view on all 30 copies and the
full snapshot/nucleotide deformation path on a two-copy assembly. Solver inputs
and product representation defaults are unchanged. Real-GPU full-scene interaction
is recorded as MV-ASSEMBLY-FEM-LARGE-GPU, not claimed verified.

The unified list also polls mrDNA and BLADE while a FEM tab is active. Their
identical uncached fingerprint helpers now use the same revision cache; the cache
regression covers all four engines. Capability probes during reconstruction after
caching responded in 59 ms (CanDo) and 33 ms (SNUPI), versus an observed 1.7 s
CanDo probe before caching. These are observations, not a guaranteed latency bound.

Additional native advanced-mode check: the canonical three-copy `smallO` polymer
(1,134 FEM nodes, 2,394 nucleotide records) completed nonlinear prediction with
2 explicit load steps and RMSF enabled in both materials. CanDo generated all 48
thermal frames in 15.70 s; SNUPI completed its nonlinear/RMSF path in 3.93 s.
Coordinates and RMSF were finite, RMSF was positive, and serialized topology was
identical before/after. The isolated temporary workspace was removed. This checks
execution/plumbing, not convergence of BigO's fine/thermal/dynamic workloads.

Frontend full gate: 7,109 passed, 1 skipped, 1 failed (109.72 s). The failure was the
existing oxDNA idle-polling timing test at `oxdna_jobs_panel.test.js:1495` (3 reads
observed versus 2). An isolated full-file rerun passed all 131 tests in 3.13 s;
no oxDNA panel or test code was changed. Ruff and diff hygiene pass. Snapshot route
regressions additionally passed (2 passed, 13 deselected, 4.03 s).

Playwright two-copy BigO check: **1 passed (3.6 min)**. CanDo completed in
10.46 s and SNUPI in 9.14 s, each with 14,112 nodes. Both full nucleotide
predictions displayed through the assembly host. The check also verifies a single
compact preparation across both launches, no part-geometry fetch, retained editor
Design identity and unchanged original assembly input. Temporary artifacts removed.
Production frontend build passed (13.63 s; existing large-chunk advisory).

Playwright full 30-copy BigO check: **1 passed (14.4 min)**. CanDo completed
in 163.05 s and SNUPI in 161.52 s, both with 211,680 FEM nodes. Both cylinder
results displayed successfully, and switching Off returned to the assembly. The
same preparation/editor-preservation assertions passed at full scale. Most browser
overhead beyond native runtime was SwiftShader rendering/input latency. The wrapper
removed its disposable workspace and bridge credentials after the successful run.

Backend gate: `just test-smart` chose **FAST**; **9,299 passed, 15 skipped,
8 failed** in 100.21 s. Seven photoproduct review tests require the unavailable
external `tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`;
one CPD preview test has an existing coordinate-golden mismatch. These are the
same failures recorded in the preceding simulation-browsing audit. No associated
photoproduct code, user test edits or geometry goldens changed in this task.

Selector deferral (verbatim):
```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

Slow-test triage: aggregate guard reported 106 s versus the 90 s backstop.
`.nadoc-slow-candidates.json` has zero per-test violators across 9,322 tests;
the slowest is existing streptavidin adsorption packing/clash checking (4.61 s).
The top files distribute time across many tests (headless oxDNA 23.5 s/45 tests,
oxDNA relaxation 23.0 s/246 tests). No new assembly test appears in the slowest
25. Inspection found no shared accidental host probe attributable to this change;
the report supports aggregate suite-size drift, not an individual heavy-test leak.
Per the triage skill, no tests were arbitrarily reclassified and no budgets raised.

Clean sequential frontend rerun: **550 files passed; 7,110 tests passed,
1 skipped** (103.23 s). This supersedes the earlier aggregate result and confirms
the oxDNA timing failure did not recur without concurrent browser work.

Smoke artifact inventory: `__e2e__` workspace parts/assemblies and their project
revision histories are removed by global teardown; session cache is disabled;
the isolated port-5174 bridge credential is removed by teardown; Playwright reports,
screenshots and traces are removed by its cleanup reporter. Smoke creates no FEM jobs.

Final smoke gate: **23 passed (2.2 min)**. Teardown removed six test designs
and one project revision store. Final filesystem/process audit found no disposable
native workspace, tagged process, prefixed workspace design, test report or
port-5174/5175 bridge credential remaining. Lint and `git diff --check` passed.

# CanDo thermal reconstruction and progress

The user authorized stopping BigO job `29da658d7294` and implementing the
improvements identified in `bigo_cando_thermal_diagnosis_20260927.md`.
The stop route initially returned `stopping`: the old worker checked cancellation
only after the whole prediction. Reload after adding cancellation at progress
boundaries terminated that worker; the API subsequently confirmed `stopped`.
No other job was running. Its snapshot/history remain available; it was not restarted.

## Implementation

- Job-local `ThermalReconstruction` prepares strand coverage, reference geometry,
  node registration, interpolation indices, winding offsets, Kabsch targets and
  passive terminal offsets once. No cache spans jobs or mutable editor state.
- Thermal frames emit only aligned XYZ arrays. Vectorized bead interpolation and
  winding retain the existing rotation-minimizing frame, twist and alignment
  algorithms. The unchanged full reconstruction produces static and selected
  representative geometry, including slab orientations and FEM axes.
- The ensemble uses a preallocated float64 array. Fluctuation statistics use
  bounded coordinate chunks and per-node accumulation with the existing fallback
  for skipped nodes and unchanged representative-selection formula.
- Trajectory JSON retains its schema, streamed one numeric frame at a time to an
  atomic temporary file. Cancellation removes the temporary and preserves any
  previous complete file. No whole-ensemble conversion to boxed float lists.
- Progress reports preparation, every `N/48` reconstructed frame, ensemble
  statistics, representative reconstruction, each saved trajectory frame and
  final saving. Thermal work has a larger phase weight. The old size-only ETA
  is suppressed when actual phase progress exists; phase weights are not a
  claim about elapsed time. Stopped/completed status overrides stale progress.
- The existing unified job bar consumes the frame/phase labels from the backend;
  no new rendering or composition-root wiring is needed.
- Cancellation is checked at phase/frame/cache boundaries. A native eigensolve
  remains non-interruptible until its next boundary.

Modes (200), thermal draws (48), temperature, physical parameters, topology,
geometry constants and locked helical phases are unchanged. No geometry golden
was modified. `frontend/src/main.js` net change for this task: zero lines.

## Full-size bounded benchmark

Read-only stopped BigO snapshot: 211,680 nodes, 424,144 nucleotide records.
One BLAS thread, no NMA rerun or job launch. Two seeded displacement fields were
reconstructed by both the unchanged full path and the new coordinate-only path.

| Draw | Full reconstruction | Thermal XYZ | Speedup | Maximum absolute coordinate difference |
|---|---:|---:|---:|---:|
| 1 | 51.057 s | 9.246 s | 5.52× | 9.095e-13 nm |
| 2 | 50.434 s | 9.864 s | 5.11× | 4.547e-13 nm |

All nucleotide identities/order matched. Shared-context preparation: 15.890 s.
The benchmark's initial static reference took 50.996 s. Peak process RSS was
2,047 MiB (this bounded test retains only one comparison frame, not all 48).
These are reconstruction measurements, not an end-to-end job speedup or a
full-size NMA/convergence validation. Reproduce with the read-only
`scripts/benchmark_fem_thermal.py SNAPSHOT` module documented in its header.

## Validation

Focused fast-path tests: **11 passed** (final run: 3.76 s). Cases include nonzero rotations and
translations, loop/skip copies, terminal extensions, polymer assembly ends,
authored deformation, cluster transforms, single-node fallback, reference
reuse, chunked RMSF/representative parity, 48 native frame updates, atomic
serialization, cancellation and the no-drawable-column modal fallback. Existing thermal cache tests: **3 passed**.

Playwright artifact inventory: `scripts/verify_assembly_fem.py --thermal`
creates a unique disposable workspace containing only test sources/assembly,
job snapshots/results, revisions, logs and autosaves. Design filenames use
`__e2e__`. The wrapper finally block stops only processes tagged with that
workspace and removes it, plus the test-port bridge credential. Session cache
is disabled. Playwright's reporter removes screenshots, traces and reports.

Native nonlinear/RMSF/48-frame regression: **1 passed, 18 deselected** (5.27 s).
Playwright: **1 passed (31.8 s)**. The actual assembly panel showed thermal
frame counts, the job saved 48 frames and finished at 100%, the representative
thermal conformation displayed, and Off returned to the assembly. Initial test
attempts used obsolete detail/status selectors/text; the production pipeline
completed and the test was corrected to inspect the current visible status bar.
All disposable artifacts were removed after each attempt.

`just test-smart`: **FAST**, **9,310 passed, 15 skipped, 8 failed** (final rerun: 91.01 s).
The failures match the preceding audits: seven photoproduct tests need an absent
external review packet; one CPD preview test has an existing coordinate mismatch.
No photoproduct code, user test edits or geometry goldens were modified.

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

Slow-test triage: final aggregate guard measured 99 s versus 90 s. The report has zero
per-test violators over 9,333 tests; slowest existing test is streptavidin adsorption
packing (4.12 s). This is the same aggregate suite-size drift diagnosed in the
preceding assembly audit, with no new thermal test among the leading offenders.
No test classifications or budgets changed.

Full focused CanDo lifecycle file: **15 passed** (29.06 s), including native
completion, cache/progress reconciliation, snapshot isolation and autorefine
compatibility with the new numeric ensemble representation.

Frontend gate: **550 files passed; 7,110 tests passed, 1 skipped** (89.93 s).
Smoke artifact inventory: prefixed workspace designs/assemblies and their project
history are removed by global teardown; session cache is disabled; port-5174
bridge credential is removed by teardown; reporter removes screenshots/traces.
No simulation jobs are created by smoke.

Smoke: **23 passed (2.0 min)**; production build passed (9.61 s, existing
large-chunk advisory). Teardown removed six prefixed designs and one project
history store. Filesystem checks found no disposable FEM workspace, prefixed
workspace design, test report or port-5174/5175 credential remaining. BigO is
still stopped. Lint and diff hygiene pass.

Final API check confirms BigO remains stopped. No tagged disposable worker
processes remain. Temporary benchmark/test logs and scratch scripts were removed;
reproducible checks and summarized evidence are retained in the repository.

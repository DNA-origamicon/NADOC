# ITER-4 — SNUPI predicted shape / static visualization — 2026-08-24 — supporting detail

[Topic head](../../project_simulate_panel_overhaul.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

#### ITER-4 — SNUPI predicted shape / static visualization — 2026-08-24

**State:** verified; retained-slow-with-progress; action expectation missed, transport expectation
met; advance after reassessment.

**Fixture + scale:** archived completed static job `6f32b88f5a06` for `3x6x400_test`:
14,686 design nucleotides, 14,972 cached FEM display rows and 7,200 axis nodes. This is a distinct
SNUPI-material job/cache, not the CanDo fixture.

**Full code path read:** all SNUPI visualization modes and the trajectory player in
`snupi_display.js` → selection/retarget/status/error handling in `snupi_jobs_panel.js` → client
transport → `routes_snupi.py` snapshot/display/RMSF/trajectory/deviation/cylinders/shape-source
routes → `snupi_runner.py` cache creation, legacy cache reads, detached solve and progress. The
shared CanDo mappers plus the complete renderer instance-update path read in ITER-3 were rechecked
at the call boundary; SNUPI's material law affects the cached coordinates, not their renderer
addressing contract.

**Research:** Three.js' official
[`InstancedMesh` documentation](https://threejs.org/docs/pages/InstancedMesh.html) and
[resource lifecycle guide](https://threejs.org/manual/en/how-to-dispose-of-objects.html) support
retaining an exact already-instanced scene rather than disposing/recreating its GPU resources.
NumPy's official [`tobytes()` contract](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.tobytes.html)
supports reusing the tested static FEM column wire without coupling the SNUPI scientific solve to
CanDo. Fingerprint equality remains the safety gate; only the material-agnostic display protocol
is shared.

**Benchmark/test + expectation:** direct warm endpoint samples plus exact Playwright gestures on
the real design/job. A new live regression records request choice, status mutations and elapsed
time; unit tests pin historical snapshot behavior, current-scene reuse, all named phases and
legacy binary-sidecar derivation. Expected: remove the entire snapshot request/rebuild, reduce the
remaining display wire by at least 75%, and improve the complete gesture by at least 25%. The
wire expectation passed; the complete-action expectation did not.

**Before:** display `4,462,206 B` at `0.062837, 0.063766, 0.066724 s`; snapshot
`7,921,383 B` at `0.221663, 0.223215, 0.274477 s`; RMSF `486,963 B` at
`0.008642, 0.005342, 0.006079 s`; deviation `4,919,128 B` at
`0.357373, 0.224918, 0.352289 s`; cylinders `644,987 B` at
`0.059752, 0.192895, 0.054929 s`. Predicted shape took `12,625 ms`, fetched JSON display plus
snapshot, rebuilt the scene and exposed only the final `Showing predicted shape` text.

**Change + loop:** first, all five modes gained retained download/compute/transform/snapshot-or-
reuse/apply progress, explicit failure state, request cancellation continuity, and fingerprint-
gated live-scene reuse. Historical/unknown jobs still render their snapshot. That first pass
removed the snapshot but measured `14,695 ms`; its visible phase interval was `5.316 s`, dominated
by `3.463 s` display JSON transfer/parse. Reassessment kept the candidate: the second pass added a
SNUPI-owned `display.bin` sidecar/route using the tested `CFRM` integer-identity + float32 column
contract, streaming byte progress, a 23 ms decode, and JSON fallback. New solves write both caches;
legacy jobs derive binary once.

**After:** `922,808 B`, **79.319% smaller** than display JSON. First legacy derive/pack/delivery
was `0.055398 s`; warm direct samples `0.001382, 0.000932 s`. The progress-enabled visible phase
interval fell from `5.316 s` to `4.366 s` (**17.9% faster**). The whole gesture was `13,049 ms`,
which is **3.4% slower** than the original no-progress `12,625 ms` and misses the 25% expectation.
The apparent contradiction is measured rather than hidden: on this 14.7k structure every required
progress paint waits for an approximately `0.85 s` headless WebGL frame, offsetting the removed
network/scene work; pre-event selection/render scheduling also varies by seconds. Removing those
paints would violate this goal's UX contract. Further packing would tune a 23 ms decoder and ~1 ms
warm server route, so it is not an efficient next change.

**Correctness/equivalence + UX:** all 14,972 helix/bp/copy/direction identities are exact; observed
float32 maximum absolute error is `7.623e-6 nm`. Current jobs make no JSON display or snapshot
request; stale jobs preserve both fallbacks. Retained rows now name display download/decode,
RMSF/deviation/cylinders/trajectory fetches, transform, snapshot build or scene reuse, application,
and failures. Focused gates pass (`4` backend including shared CanDo checks; `38` frontend),
repository FAST is `7,204 passed / 117 skipped`, complete frontend is `352 files / 5,867 tests`,
and the real-fixture Playwright proof passes. FULL backend remains deferred until a user-opened
test-dedicated session exists.

**Decision + next candidate:** retain the visible phases and stop optimizing this 23 ms decoder.
Proceed to mrDNA's predicted-shape display, which still needs its own end-to-end audit; do not
assume its external simulation frame/schema or snapshot-current semantics match the FEM siblings.

#### Fixture audit — mrDNA predicted-shape display — 2026-08-24

Every archived mrDNA job, including the 14,774-nucleotide Voltron job, predates the required
`nucleotide_map.json`. The display, snapshot, and bead routes correctly reject them with HTTP 409
in 11–17 ms and instruct the user to rerun. The full frontend/controller/router/runner/decode path
was read, but this is not counted as an optimization iteration: manufacturing a tiny fixture or
bypassing the manifest guard would not measure the real process. Queue a representative completed
rerun; meanwhile advance to the next real, valid >1 s fixture.

#### ITER-5 — LAMMPS final-structure display — 2026-08-24

**State:** verified; optimized below one second at the backend, complete browser action still over
one second with per-subprocess progress; advance after reassessment.

**Fixture + full path:** completed CPU-fallback job `3bb1b170da66` on `6hbx100_noT`, 1,328
nucleotides and 101 trajectory frames. Read the complete display controller and oxDNA-panel LAMMPS
dispatch/status path, client request, `routes_lammps.py` dump-to-oxDNA cache/input resolution,
`composite_trajectory`, downsampling/alignment/flattening core, and both the full and bounded-tail
oxDNA readers through final `applyFemPositions` rendering. The final-structure route was paying for
the whole composite trajectory and then retaining only `frames[-1]`.

**Research + expectation:** Python's official
[`IOBase.seek`](https://docs.python.org/3/library/io.html#io.IOBase.seek) contract permits a negative
offset relative to end-of-stream, supporting a bounded suffix read proportional to one terminal
frame. NumPy's official [`linalg.svd`](https://numpy.org/doc/stable/reference/generated/numpy.linalg.svd.html)
documents the SVD primitive already used by NADOC's Kabsch alignment, so the safe optimization is
to preserve that math and reduce the number of frames passed through it. Expected cold route at
least 4× faster and below 250 ms, with no complete-gesture regression; because the baseline gesture
exceeded one second, show determinate read/align, transform, and apply phases.

**Measurement + baseline:** a read-only Playwright gesture opened the real library design, selected
the unified LAMMPS row, chose Final structure, waited for the usable scene, counted requests and
timed the whole action. Baseline was `2,012 ms`, one `294,073 B` display response, and only the final
status. Direct warm route samples were `0.075192, 0.077918, 0.076882 s`; uncached sibling/full-scan
samples were `1.055633 s` and `0.524497 s`, and a new `align=false` cache key on the main fixture
was `0.426303 s`.

**Change:** `latest_aligned_trajectory_frame` reuses the production bounded-tail parser to seek and
parse only the latest complete frame, then runs the same PBC unwrap, topology plan, Kabsch SVD and
vectorized display flattening with the same loop-copy key order. The LAMMPS display route calls that
specialized core; the scrub trajectory remains unchanged. The controller/panel now retain one
labelled determinate bar each for `Read and align final frame`, `Transform final coordinates`, and
`Apply final structure` while work is active.

**After + comparison:** main aligned route samples `0.031573, 0.032075, 0.028884 s` (**2.5× warm
speedup**); main unaligned samples `0.030069, 0.029434, 0.026832 s` versus the cold-key baseline
`0.426303 s` (**14.7× by medians**). The two previously cold sibling jobs now return in
`0.053694 s` and `0.150651 s`, respectively (**19.7×** and **3.48×** against their recorded
full-scan calls); all are below 250 ms. The exact live browser gesture is `1,592 ms`, **20.9%
faster** than `2,012 ms`, despite deliberately yielding two render frames to expose client phases.
The under-250-ms and no-regression expectations pass; one sibling misses the aspirational 4× ratio
but the representative main cold-key result exceeds it substantially.

**Correctness + verification:** a parametrized regression compares every key and coordinate against
the legacy composite's final frame at `1e-12` for both `align=true` and `align=false`; both pass.
Focused frontend tests are `122 passed`. Repository FAST is `7,206 passed / 117 skipped`; complete
frontend is `352 files / 5,869 tests`. The real-fixture Playwright proof passes, observes exactly
one display request, all three progress phases, and the terminal final-structure status. FULL
backend is deferred until the user opens a test-dedicated session, per the gate output below.

**Decision + next candidate:** the backend is now tens of milliseconds and further tail/parser work
is not the dominant end-to-end cost. Retain the progress because the measured WebGL/browser action
is still 1.592 s. Advance to the cross-tab inventory with a real completed fixture; keep mrDNA at
the head of the queue once a manifest-current job exists.

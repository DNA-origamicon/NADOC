# Feature-log evaluation optimization

The feature log remains complete. Evaluation is local to a requested cursor;
an entry superseded at the end can still supply an animation frame or undo state.
Native file loading already restores the saved Design rather than replaying the
log, so these changes target seeking, fine-routing boundary reconstruction, and
animation geometry. They make no claim of accelerating native file parsing.

## Implemented stages

1. **Read-only evaluation plan.** `GET /api/design/features/evaluation-plan`
   accepts `position` (default `-1`) and optional `sub_position`. It reports
   resource reads/writes, conservative command-overwrite decisions, the selected
   recorded topology source, and child-prefix decisions. The plan is not part of
   the hot path and never writes to the design. Full snapshots are not decoded;
   child patches are decoded only when explaining an explicitly selected prefix.
2. **Absolute-state evaluation and deferred geometry.** Long logs use a combined
   overlay scan and a targeted snapshot search. Cluster pose includes translation,
   rotation, and pivot. Whole-overhang orientation and sub-domain angles are
   distinct resources. Every bend/twist remains in its original order. Geometry
   is generated only for requested states. Compact, atomistic, and surface batch
   routes share output for exact end-cursor aliases (`-1`, last index, overshoot),
   while retaining every requested response key and every distinct frame.
3. **Recorded-patch composition.** Mid-routing seeks and sub-step boundary
   reconstruction compose runs of at least eight recorded patches. Ordered maps
   retain creation/deletion and remove/re-add order, then materialize only the
   surviving POST objects. This avoids repeated collection scans, intermediate
   model construction, and Design copies. Relative resize commands are never
   summed or replaced by their final delta.
4. **Extensible effect contracts.** `Effects` and `analyze_overwrites` implement
   backward overwrite analysis with intervening reads, partial batch writes, and
   unknown barriers. Audited contracts cover cluster poses, overhang/sub-domain
   setters, and recorded whole-object modifications. Recorded patches support
   every minor subtype with a payload, including crossover and resize effects;
   command types without complete contracts remain conservative. Legacy builders
   are replay boundaries: pending state is materialized before calling them.

The production implementation lives in `backend/core/feature_evaluation.py` and
`backend/core/design_diff.py`, integrated through `backend/api/crud.py` and
`backend/api/routes_feature_log.py`. The planner distinguishes a semantic command
dependency from the ability to restore that command's already-recorded result.
A snapshot can therefore bypass a builder even when that builder has no effect
contract.

## Invariants and scope

- No log rows, IDs, snapshots, or animation frames are removed or rewritten.
- No plan or decoded state is cached across requests. In-place edits, undo,
  imports, and sub-cursor changes cannot reuse stale plans. Batch alias reuse
  lasts only for the current request; it does not hash the whole design.
- Small logs (under 32 entries) keep the existing overlay/search path. Short
  patch runs keep sequential application because planning overhead can outweigh
  the savings.
- Patch composition reproduces **non-defensive forward apply** on valid recorded
  history. Duplicate object IDs fall back to reference list semantics. Defensive
  reapplication of a tail after surgical deletion is unchanged.
- The composer neither reruns reconciliation nor guesses missing effects. It
  retains every recorded field change, including another object's deletion.
- Diff coverage is deliberately identical to the existing `_DIFF_FIELDS`:
  helices, strands, crossovers, forced ligations, extensions, overhang connections,
  photoproduct junctions, and cluster joints. This is not all of `Design`:
  overhang metadata, cluster membership, and duplex collections are examples
  outside this diff format. Existing snapshot substitution/reconstruction rules
  still apply. Expanding persistence coverage requires a separate versioned
  migration and correctness audit, not an optimizer assumption.
- Missing/evicted snapshots and unsupported legacy commands retain existing
  fallback behavior. Optimizations do not claim to repair an unreconstructable
  historical state or validate corrupt intermediate patch payloads.

## A/B checks and rollback

Production defaults to optimization. Set `NADOC_FEATURE_EVALUATION=baseline` to
disable it for seeks, child boundaries, and all geometry batches. A request runs
only one evaluator; there is no hidden double calculation or production timing
probe. Internal seek calls can also pass `optimized=False` explicitly.

The benchmark compares against `scripts/feature_evaluation_reference.py`, a frozen
copy of the original evaluator and geometry batch routes, rather than
only comparing two branches of newly shared code. Keep this oracle fixed when
extending the optimizer.

```bash
uv run python -m scripts.benchmark_feature_evaluation \
  --design tests/fixtures/corner_miter_test.nadoc \
  --design tests/fixtures/relax_2x2_closebond.nadoc \
  --repeats 21 --iterations 60 --output /tmp/feature-evaluation-ab.json
```

The harness first checks full model equality and input immutability. It then
alternates warmed A/B timing batches, with cyclic GC disabled during timing to
reduce collection noise. It records raw samples, median, and p95 of batch means.
The gate fails if the optimized median increases by **both >5% and >0.05 ms**.
These tolerances distinguish material regressions from timing noise; they are
not a guarantee that every individual invocation is faster. Run timing in
isolation from the test suite or other heavy work.

Initial short runs produced timing flags even for paths using the same code.
Small-path fallbacks, longer paired samples, and the frozen reference were used
before accepting the final run. All 23 final cases passed the gate. The checked-in
raw results are in [benchmarks/feature_evaluation_ab.json](benchmarks/feature_evaluation_ab.json).

| Case | Original median | Optimized median |
|---|---:|---:|
| 1,000 cluster poses, final state | 0.735 ms | 0.246 ms |
| 1,000 cluster poses, middle state | 0.697 ms | 0.186 ms |
| 100 recorded patches | 5.657 ms | 2.741 ms |
| Corner fixture, second routing prefix | 1.400 ms | 1.038 ms |
| Closebond fixture, routing prefix | 0.736 ms | 0.589 ms |
| Four distinct compact geometry frames | 3.424 ms | 3.431 ms |
| Compact geometry with repeated end aliases | 3.454 ms | 1.711 ms |

A separate six-case run covers the actual atomistic and surface routes, including
single frames and four distinct frames as no-benefit controls. All six passed the
same gate. End-alias batches took 57.559 → 28.588 ms for atomistic rendering and
93.665 → 47.428 ms for surfaces. The surface fixture uses `grid_spacing=0.6` and
`smooth=1`; these results do not measure every surface resolution. Raw samples:
[benchmarks/feature_evaluation_renderers_ab.json](benchmarks/feature_evaluation_renderers_ab.json).

```bash
uv run python -m scripts.benchmark_feature_evaluation --only-renderers \
  --renderers atomistic surface --repeats 11 --iterations 5 \
  --output /tmp/feature-renderers-ab.json
```

`tests/test_feature_evaluation.py` compares every cursor/sub-cursor against the
frozen evaluator, including saved designs and randomized object lifecycles. It
also covers mixed orientation batches, relative grow/shrink before a crossover,
intervening readers, unknown operations, evicted snapshots, edits without a cache
reset, and materialization counts. Existing routing/revert/delete and animation
tests remain regression coverage. Performance thresholds live in the benchmark,
not flaky per-test wall-clock assertions.

Final focused validation: **226 passed, 3 skipped** (feature evaluation, animation,
fine routing, snapshots, edits/dependencies, resizing, crossover placement, and
assembly feature-log actions). The broader fast suite passed 8,678 tests but had
29 existing failures and nine existing setup errors, plus an invalid angle in a
new test fixture that was corrected before the focused rerun. All 38 existing
failures/errors were reproduced with the three changed production modules loaded
from their original HEAD sources. They involve simulation/toolchain availability,
missing archived evidence, and existing fixture/state assumptions. Counts and
node IDs are recorded in
[benchmarks/feature_evaluation_regressions.json](benchmarks/feature_evaluation_regressions.json).
The fast-suite timing report had zero individual over-budget tests; its aggregate
119-second guard runtime used four workers for 8,757 tests. No tests were
reclassified and no time budgets were raised.

## Adding another contract

1. List all resources read and written, including object existence and incidental
   topology changes. Use full overwrites only; relative updates read their old
   resource and therefore do not kill earlier writes.
2. Add the contract to `feature_effects`. Unknown remains the default. A partial
   overwrite of a batch must retain that batch unless partial execution is
   separately implemented and validated.
3. Add A/B histories that consume the intermediate state, undo it, edit it, and
   request it as an animation frame. Compare topology/IDs/order as well as geometry.
4. Add the relevant workload to the paired benchmark. Enable a faster path only
   after equivalence and timing pass, including short/no-benefit cases.

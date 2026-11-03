# Desktop benchmark protocol and next iterations

The [workflow registry](workflows.md) defines owner, workload and measurement for each major operation. A row becomes measured only when it links a successful run with fixture identity, revision/worktree identity, environment, samples and correctness evidence. A unit test passing is not a performance measurement; a kernel benchmark is not an end-to-end benchmark.

## Measurement boundary

For user-visible operations, record the same transaction through:

1. User input/command dispatch.
2. Request start, backend admission/queue, compute, serialization and response bytes.
3. Response receipt/decode and store application.
4. Geometry/overlay/DOM update and GPU upload where observable.
5. First rendered frame containing the intended result; separately record persistence/job completion when relevant.

Use the existing [`operation_timing.js`](../../../frontend/src/perf/operation_timing.js) traces and [`viewer_performance.js`](../../../frontend/src/perf/viewer_performance.js) capture facilities. The 50-entry timing ring is bounded: export samples after each batch before they are overwritten. Inspect trace status and completion marker. Fallback completion is not proof of a useful visible frame. Correlate overlapping responses by their owning transaction, not one global active request. Report client total wall time directly; backend phases are attribution and must not be added to overlapping client intervals.

Record browser/GPU/driver, viewport, pixel ratio, representation, detail level, camera, visible atom/triangle counts, network mode, server workers and cache state. Keep camera/visibility fixed for A/B. Headless/software rendering results are not workstation GPU acceptance. Validate the intended visible result with pixel/selection/geometry checks; a fast blank frame is invalid.

## Fixtures and statistics

Use small, medium and large fixtures for each family, with both part and assembly hosts where supported. Minimum dimensions to vary:

| Dimension | Initial sweep |
|---|---|
| DNA topology | 6/24/96 helices; short/long strands; routed, edited and attached-assets variants |
| History | 0/100/1000 entries; near/end/middle cursor and repair/recovery branches |
| Atomistic display | 30k/150k atoms; sparse serials; bonds on/off; fixed viewport |
| Assemblies | 100/500/1500 instances; chain/star/closed-loop, shared/unique source parts |
| UI collections | 100/1000/10000 rows; open/search/scroll and selection |
| Jobs/peers | 0/10/100 fake jobs; 2/10 controlled peers; offline/reconnect |
| Memory lifecycle | At least 20 open/edit/close cycles; retained heap/RSS plateau and listeners |

Synthetic sizes are reproducible stress inputs, not claims about typical user documents. Supplement with read-only copies of representative real designs and record content hashes. Separate fresh-process cold start, cold file/cache, warmed operation and repeated cache-hit measurements; never label a warmed first sample “cold startup.”

The current core/assembly screening baseline uses 15 warm samples. For latency-tail acceptance, use at least 100 interactions across multiple independent sessions, retain raw samples, and report median, p95, p99, count and failures. Use nearest-rank percentiles and publish the estimator; at small sample sizes p95/p99 can equal the maximum. Alternate A/B order when feasible. Report memory before/peak/after separately, and report timeouts/cancelled/invalid results rather than silently dropping them. GC observations indicate correlation, not causation, and must not be subtracted from end-user latency.

A provisional triage budget is 16.7 ms for a 60 Hz frame and 100 ms for immediate interaction feedback. These are investigation targets, not existing product guarantees or hard CI gates. Long operations need prompt progress/cancellation and separate completion metrics. Establish host-specific noise and a statistically credible paired baseline before adding regression thresholds.

## Iteration queue and completion criteria

| Pass | Concrete deliverable | Completion criterion |
|---|---|---|
| Completed: census | Route/module ownership and explicit exclusions | Every inventoried eligible source classified; new unmatched sources remain visible on regeneration |
| Completed: evidence consolidation | 54-family registry with historical/current/harness/gap states | Every row has an existing source owner and a concrete benchmark contract |
| Completed: current CPU screening | Core pipeline, renderer loading, FK, connector enforcement and input replay | Eight successful invocations with correctness results, plus diagnostic geometry profile |
| Next: desktop E2E | Open/save/close, edit/undo/scrub, picking/drag, representation switches, panels | Successful input-to-visible measurements for small/medium/large copied designs and verified cleanup |
| Next: retention/tails | Long histories, repeated open/close, many instances and queued fake jobs | Stable tail statistics and retained-memory trends across independent sessions |
| Next: remaining backend boundaries | Export preparation, metrics, filesystem, job orchestration and sharing | Stage timings plus payload/memory metrics; engine runtime isolated from frontend orchestration |
| Then: paired optimization | Highest measured user-visible cost | Same-fixture improvement, identical intended output and no material regressions in affected hosts |

No operation family is marked E2E-complete solely because its source is mapped. The useful stopping point for this survey is a broad navigable map, current screening measurements, linked historical evidence and explicit gaps; proving performance across the full behavior space is a subsequent benchmark campaign.

## Safe execution and output ownership

Use `scripts/validation_guard.sh` for heavy checks so they serialize with other work. Archive must be mounted and `.development-artifacts` must resolve there before creating scratch/captures. Never benchmark against mutable user designs, active production jobs or running simulation directories. Current CPU harnesses operate in memory and do not start workers or servers.

Before a browser run, inventory every persisted artifact, use `__e2e__` names for workspace parts/assemblies, verify failure-safe teardown and check the paths afterward. The existing [real-design viewer benchmark](../../../frontend/e2e/viewer_performance_benchmark.spec.js) already copies its source, requires an isolated API base, hashes the original and supplies cleanup; audit its current configuration before use. It strips history, so it cannot stand in for a long-history benchmark. Optional metrics output is a deliberately retained artifact. Keep compact result/provenance JSON; discard task-owned bulk captures only after analysis and dependency checks.

No remote job or physical sampling is needed to benchmark queue admission, status polling or package preparation. Use fake workers/replayed transport for those boundaries. Engine throughput needs a separately scoped, approved fixture run and must keep scientific correctness/convergence separate from software wall-time improvements.

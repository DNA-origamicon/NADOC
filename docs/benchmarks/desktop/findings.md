# Desktop baseline findings — 2026-10-22

Native geometry generation is the largest CPU cost in the newly measured design pipeline. This ranking is restricted to sampled workloads; it does not identify the largest consumer of users' total time.

Host: AMD Ryzen 9 9950X, Python 3.12.3, Node v22.22.2. Exact environment, dirty paths, commands, raw samples and correctness results are in [current_baseline.json](current_baseline.json). Older Ryzen 5 3600 results elsewhere in the repository must not be compared to these as an optimization speedup.

## Fresh backend measurements

Synthetic honeycomb bundles, 84 base pairs per helix; each helix has both strand directions. Times are median milliseconds for 15 warm calls. Correctness comparisons occur outside the timing interval; GC remains enabled. The first-call number in the raw report is not a fresh-process cold start: fixture preparation has already exercised some paths.

| Pipeline stage | 6 helices / 1,008 nt | 24 helices / 4,032 nt | 96 helices / 16,128 nt |
|---|---:|---:|---:|
| Construct bundle | 0.138 | 0.358 | 1.551 |
| Native display geometry | **5.270** | **25.323** | **189.037** |
| Serialize JSON | 0.019 | 0.069 | 0.273 |
| Parse/validate JSON | 0.065 | 0.267 | 1.183 |
| Encode history snapshot | 0.037 | 0.115 | 0.403 |
| Decode history snapshot | 0.073 | 0.291 | 1.220 |

The 96-helix design serializes to 114,730 bytes; its base64 compressed snapshot is 7,220 bytes. These empty-history fixtures do not establish save/undo costs for deep history or attached atomistic assets. Geometry p95 is 31.8, 63.7 and 268.1 ms respectively. With only 15 samples, the nearest-rank p95 is the maximum; these tails are screening signals, not stable production percentiles.

A [warm diagnostic profile](geometry_profile.json) of the 96-helix case places approximately 79 ms cumulative in `_emit_arrs`, 36 ms in `native_full_arrays_for_helix`, and 43 ms in `attach_native_slab_poses`. These are instrumented timings, not baseline timings; parent/child cumulative rows overlap and must not be summed. The trace suggests investigating Python per-nucleotide output allocation and repeated coordinate/pose work. It does not justify changing native molecular placement, phase constants, topology or physical semantics.

| Assembly/history component | Median ms | p95 ms / limitation |
|---|---:|---|
| FK, 100-instance chain | 0.034 | 0.059 |
| FK, 500-instance chain | 0.129 | 0.179 |
| FK, 1,500-instance chain | 0.574 | 1.927 |
| FK, 500-instance star | 5.147 | 5.836 |
| Connector postpass, 1,500-instance chain | 0.606 | **24.563**; isolated tail, cause unknown |
| Connector enforcement, 500 independent mates | 12.156 | 12.870 |
| Input capture, 128 tiny PDB imports | 5.208 | Maximum 5.422; nine repetitions |
| Input proof replay, same imports | 10.826 | Median only supplied by existing harness |

FK uses `rigidEvery=4`, revolute/rigid mixed graphs and empty part designs. Chain and star traversal/moved scopes differ, so their ratio is not a controlled algorithmic regression or proof of a complexity class. Connector legacy comparison is 146.375 → 12.156 ms with equal aggregate checksums, confirming an existing improvement on this fixture; it is not a new optimization in this change. The checksum is weaker than complete transform equality and should be strengthened before accepting a future FK implementation change. All input-replay samples reported `reproduced_import`.

## Fresh frontend CPU measurements

Node/Three.js generated buffers, not browser/WebGL rendering. The existing loading harness alternates historical/current implementations, warms up, and verifies exact instance buffers.

| Component | Fixture | Current median ms |
|---|---|---:|
| First-open renderer construction | 30k atoms, object format | 6.227 |
| First-open renderer construction | 30k atoms, columnar format | 6.545 |
| First-open renderer construction | 150k atoms, object format | **53.797** |
| First-open renderer construction | 150k atoms, columnar format | **40.383** |
| Cached compact-frame expansion + application | 30k atoms | 0.849 |
| Cached compact-frame expansion + application | 150k atoms | 4.134 |

The rapid-scrub control performs two reads (`0,48`) compared with seven in the inert historical implementation. This is an I/O request-count observation, not measured disk latency. The existing decoder reports eliminating 28.8 MB of sparse scratch at 150k atoms; this is computed avoided buffer capacity, not measured whole-process RSS. No end-to-end FPS or GPU improvement is claimed.

## Ordered investigation backlog

| Priority | Investigation | Evidence and next decision |
|---|---|---|
| 1 | Native geometry construction/allocation | Current 189 ms median at 16k nt plus profile. Instrument allocation/repeated transforms, then paired A/B with identical geometry and placement validation. |
| 2 | Desktop edit/open phase attribution | Existing operation timing and viewer hooks can separate request, store, geometry and render completion. Measure real copied designs before deciding which stage to optimize. |
| 3 | Large renderer first-open construction | Current 40–54 ms CPU at 150k atoms. Measure main-thread long tasks, GPU upload and first useful frame in a real browser; investigate buffer reuse or staged construction only after that split. |
| 4 | Tail latency and long-history retention | Geometry and connector outliers; deep-history evidence is historical. Correlate GC/allocations and scheduler activity over longer runs without subtracting pauses from UX latency. |
| 5 | Assembly fanout and shared-source rendering | Star FK and independent mates are measured, whole-assembly geometry/draw costs are not. Add varied graph shapes and shared/unique part fixtures with complete transform checks. |
| 6 | Picking, panels, autosave, jobs and collaboration | Large gaps in the workflow matrix. Add action-to-visible traces and memory-cycle measurements; no current timing basis to rank them by cost. |

The older [performance audit](../../audits/performance_20260925/README.md), [active visualization audit](../../audits/active_visualization_20260925/README.md), [loading audit](../../audits/loading_open_20260926/README.md) and [feature-history audit](../../audits/feature_history_20261014/README.md) remain valuable component baselines. Their existing speedups must not be counted as new gains, and source-only hypotheses in those reports remain hypotheses.

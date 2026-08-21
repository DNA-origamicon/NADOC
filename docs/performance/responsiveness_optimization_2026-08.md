# NADOC responsiveness optimization campaign — August 2026

Status: thirty optimizations complete; awaiting approval for the fourth batch.

This campaign has measured thirty changes to editing and visualization responsiveness.
All figures below are wall-clock milliseconds on this workstation. Browser
results use Chromium through Playwright's isolated backend (`:8002`) and Vite
server (`:5175`), never the live development session.

## Measurement protocol

- Pure kernels retain every sample, run a JIT warm-up first, and report median
  and p95. Legacy and optimized implementations run in the same Node process.
- The pathview benchmark imports `workspace/VoltronCore.nadoc`, then expands it
  in browser memory to 2,460 strands, 10,920 domains, and 7,992 crossovers.
  It records 31 synchronous wheel/redraw samples per mode.
- Browser checks fail on page/console errors. Canvas states retain a full-pixel
  FNV-32 digest and transition count. All five original states, plus the selected
  state, were byte-identical across the viewport, indicator, and selection changes.
- Assembly fixtures contain 1,000 instances and 999 joints. The benchmark
  asserts the expected propagated positions after every run.
- Percentage is median latency reduction. Speedup is `before / after`.

## First batch — completed optimizations 1–10

| # | Process and change | Before median / p95 | After median / p95 | Result |
|---:|---|---:|---:|---:|
| 1 | Atomistic selection recoloring: compile selection arrays into sets and keyed domain intervals | 61.259 / 63.159 ms | 8.277 / 10.129 ms | 86.5% lower; 7.40× |
| 2 | Nucleotide-to-cluster resolution: compile cluster membership predicates once per immutable design | 1,248.934 / 1,271.875 ms | 2.862 / 3.032 ms | 99.77% lower; 436.4× |
| 3 | Cluster extension-key expansion: index host strands instead of `find` per extension | alpha: 46.305 / 46.533 ms; selected: 33.847 / 34.128 ms | alpha: 2.586 / 4.246 ms; selected: 2.213 / 2.481 ms | 94.4% / 93.5% lower; 17.91× / 15.29× |
| 4 | Assembly forward kinematics: build rigid/child joint adjacency once instead of scanning every joint at every BFS node | revolute: 28.597 / 29.061 ms; rigid: 37.380 / 38.203 ms | revolute: 11.073 / 21.854 ms; rigid: 6.255 / 14.695 ms | 61.3% / 83.3% lower; 2.58× / 5.98× |
| 5 | Connector-coincidence postpass: index eligible joints by child instance | 9.313 / 9.564 ms | 0.136 / 0.175 ms | 98.54% lower; 68.45× |
| 6 | Undefined-base/sequence rendering: cache skip-aware sequence columns and overhang lookup per design | 38.900 / 45.900 ms | 26.400 / 33.100 ms | 32.1% lower; 1.47× |
| 7 | Periodic pathview domain rendering: horizontally cull transformed off-screen domains before cap/crossover/selection work | 31.700 / 32.700 ms | 28.600 / 30.400 ms | 9.8% lower; 1.11× |
| 8 | Registered crossover rendering: cull off-screen arc bounds before strand lookup, styling, and Bézier drawing | zoomed: 7.800 / 8.300 ms | 4.200 / 4.900 ms | 46.2% lower; 1.86× |
| 9 | Crossover indicator overlay: cache occupied slots, coverage ranges, junctions, and per-helix minima per design | zoomed: 4.200 / 4.900 ms | 1.700 / 2.200 ms | 59.5% lower; 2.47× |
| 10 | Selected-strand redraw: cache the selected strand-id expansion using design/filter/selection signatures | 3.900 / 5.100 ms | 1.800 / 2.400 ms | 53.8% lower; 2.17× |

The combined ordinary zoomed redraw moved from 8.3 ms in the original baseline
to 1.8 ms in the final audit (78.3% lower, 4.61×). The final browser run kept
all canvas digests equal and reported no browser errors.

## Second batch — completed optimizations 11–20

The second batch concentrated on high-rate pointer work and repeated linear
searches in visualization preparation. Kernel rows use 15 paired samples in one
Node process. Browser rows use 31 hover samples or five 20-event pan bursts in
isolated Chromium. Every paired kernel retained an identical checksum.

| # | Process and change | Before median / p95 | After median / p95 | Result |
|---:|---|---:|---:|---:|
| 11 | Pathview disconnected-layout grouping: replace quadratic all-cell flood fill and `shift` queue with coordinate adjacency and head-index BFS | 11.057 / 14.524 ms | 1.623 / 2.538 ms | 85.3% lower; 6.81× |
| 12 | Pathview hover hit testing: reuse the design-keyed helix/track interval index instead of scanning every strand/domain per pointer event | 3.900 / 4.300 ms | 0.400 / 0.500 ms | 89.7% lower; 9.75× |
| 13 | Pointer-drag painting: coalesce high-rate move redraws into one animation-frame render while preserving immediate pointer-up rendering | 672.400 / 698.300 ms end-to-paint | 37.000 / 61.900 ms | 94.5% lower; 18.17× |
| 14 | Overhang spec-to-domain mapping: index design strands by id once | 2.230 / 5.291 ms | 0.284 / 0.637 ms | 87.3% lower; 7.86× |
| 15 | Geometry-to-overhang-domain mapping: reuse one strand-id index for backbone entries | 2.008 / 2.163 ms | 0.274 / 0.646 ms | 86.4% lower; 7.34× |
| 16 | Overhang junction resolution: index the first crossover by unordered helix pair instead of scanning crossovers per overhang | 34.089 / 63.071 ms | 0.973 / 1.808 ms | 97.1% lower; 35.03× |
| 17 | Extension visibility expansion: precompute synthetic extension-helix ids instead of rebuilding and scanning an array per nucleotide | 58.614 / 61.818 ms | 2.586 / 2.874 ms | 95.6% lower; 22.67× |
| 18 | 3D staple visibility/isolation: retain strand type by id instead of searching backbone entries per cone | 37.914 / 47.846 ms | 0.101 / 0.138 ms | 99.7% lower; 374.2× |
| 19 | Expanded-spacing extension arcs: index extension host strands once per map build | 4.743 / 5.148 ms | 0.672 / 1.488 ms | 85.8% lower; 7.06× |
| 20 | Cluster visibility/opacity expansion: share one weakly cached strand-id index across every cluster for an immutable design | 99.134 / 107.372 ms | 0.240 / 0.270 ms | 99.8% lower; 412.7× |

The final browser audit reproduced all six established canvas hashes and the pan
completion hash, reported no browser errors, and left the hovered strand empty at
the benchmark's known empty coordinate. Pointer dispatch itself fell from 659.1
ms to 0.1 ms per 20-event burst because rendering no longer blocks every event.

## Third batch — completed optimizations 21–30

Batch three moved more design-derived work to immutable-snapshot indexes. The
frontend fixture contains 6,000 strands / 24,000 domains, with feature-specific
large crossover, geometry, extension, and selection sets. Each kernel uses 15
paired legacy/current samples and asserts identical checksums. Assembly uses 500
independent connector mates (1,000 instances), also with matching final transforms.

| # | Process and change | Before median / p95 | After median / p95 | Result |
|---:|---|---:|---:|---:|
| 21 | Coaxial arc preparation: cache descriptors, index forced-ligation transitions, and viewport-cull arcs | 27.729 / 28.422 ms | 1.502 / 1.685 ms | 94.6% lower; 18.46× |
| 22 | Pathview extensions: cache host-strand entries per design and horizontally cull arms | 0.386 / 0.805 ms | 0.0040 / 0.0059 ms | 99.0% lower; 95.7× |
| 23 | End/domain drag setup: index selected element resolution and track-local crossover/domain blockers | resolution: 27.131 / 27.229 ms; blockers: 28.539 / 55.965 ms | resolution: 0.043 / 0.102 ms; blockers: 0.032 / 0.034 ms | 99.8% / 99.9% lower; 624× / 901× |
| 24 | 3D renderer lookups: reuse nucleotide-identity, slab-copy, and cylinder-domain maps | 129.734 / 131.966 ms | 0.487 / 0.724 ms | 99.6% lower; 266.5× |
| 25 | Heatmap preparation: retain the prepared map per design instead of recomputing each redraw | browser: 31.700 / 34.200 ms | browser: 30.700 / 32.300 ms | 3.2% median and 5.6% p95 lower; preparation removed in paired kernel |
| 26 | Assembly connector snaps: share one FK joint adjacency through all residual subtree propagations | 127.488 / 135.458 ms | 11.177 / 11.623 ms | 91.2% lower; 11.41× |
| 27 | Visibility queries: index base keys by strand when geometry changes | 71.305 / 141.138 ms | 0.034 / 0.085 ms | 99.95% lower; 2,117× |
| 28 | Pathview lasso: visit only intersecting helix/track domain buckets | 0.141 / 0.464 ms | 0.0083 / 0.0128 ms | 94.1% lower; 17.07× |
| 29 | Crossover arc hit-testing: precompute geometry and bin candidates horizontally | 12.916 / 13.693 ms | 0.102 / 0.107 ms | 99.2% lower; 127.0× |
| 30 | Pathview design comparison/paint lookup: use helix-id maps instead of repeated `find` calls | 72.560 / 73.026 ms | 0.147 / 0.156 ms | 99.8% lower; 493.3× |

The integrated large-design browser audit improved ordinary zoomed redraw from
1.8 / 2.0 ms to 0.8 / 1.4 ms (median / p95), while selected zoomed redraw moved
from 1.9 / 2.3 ms to 0.8 / 1.9 ms. Design update stayed flat-to-better at 53.3 /
65.2 ms to 53.0 / 63.6 ms, so the indexes did not shift redraw cost onto editing.
All established canvas and pan hashes remained identical and browser errors were empty.

## Evidence map

- Optimizations 1–3: [paired frontend kernel log](raw/frontend_kernels_paired_final.json)
- Optimization 4: [revolute baseline](raw/assembly_fk_revolute_baseline.json),
  [revolute after](raw/assembly_fk_revolute_after_04_adjacency.json),
  [rigid baseline](raw/assembly_fk_rigid_baseline.json), and
  [rigid after](raw/assembly_fk_rigid_after_04_adjacency.json)
- Optimization 5: [connector baseline](raw/assembly_connector_postpass_baseline.json)
  and [connector after](raw/assembly_connector_postpass_after_05_index.json)
- Optimization 6: [pathview baseline](raw/pathview_baseline_with_zoom.json) and
  [sequence-cache result](raw/pathview_after_07_sequence_cache.json)
- Optimizations 7–9, including exact pixel evidence:
  [pre-cull baseline](raw/pathview_precull_visual_baseline.json),
  [domain culling](raw/pathview_after_07_domain_culling.json),
  [arc culling](raw/pathview_after_08_crossover_culling.json), and
  [indicator index](raw/pathview_after_09_indicator_index_cache.json)
- Optimization 10: [selected baseline](raw/pathview_selected_baseline.json) and
  [selected-cache result](raw/pathview_after_10_selection_cache.json)
- Final production-state audit: [pathview final](raw/pathview_final_10.json)
- Optimizations 11 and 14–20: [final paired batch-two kernel log](raw/batch2_10_cluster_shared_strand_index.json)
- Optimization 12: [hover baseline](raw/batch2_02_hover_baseline.json) and
  [final browser audit](raw/batch2_final_pathview_playwright.json)
- Optimization 13: [pan baseline](raw/batch2_03_pan_baseline.json),
  [first coalesced result](raw/batch2_03_pan_raf.json), and
  [final browser audit](raw/batch2_final_pathview_playwright.json)
- Optimizations 21–25 and 27–30:
  [paired batch-three frontend log](raw/batch3_frontend_indexes.json)
- Optimization 26: [paired assembly adjacency log](raw/batch3_assembly_shared_fk_index.json)
- Integrated third-batch audit: [pathview Playwright log](raw/batch3_final_pathview_playwright.json)

The reproducible harnesses are
`frontend/scripts/responsiveness-kernel-bench.mjs`,
`frontend/scripts/responsiveness-batch2-kernel-bench.mjs`,
`frontend/scripts/responsiveness-batch3-kernel-bench.mjs`,
`scripts/benchmark_assembly_fk.py`, and
`scripts/benchmark_assembly_shared_index.py`, plus
`frontend/e2e/responsiveness_pathview_bench.spec.js`.

## Functional verification

- `just test-smart`: 7,187 passed, 116 skipped (fast suite; 19 seconds).
- `npm test`: 5,806 passed across 341 frontend test files.
- `npm run build`: production Vite build passed.
- Playwright responsiveness spec: passed against the isolated servers, with no
  browser errors and identical pixel hashes for plain, overhang, periodic,
  zoomed, and selected views.
- The focused pathview end-lasso/forced-ligation Playwright case passed. An
  unrelated background mrDNA reconciliation request logged a job-file race, but
  did not fail the browser case or touch these optimization paths.
- Focused development checks also passed: 20 atomistic color-resolver tests, 49
  cluster-entry tests, and 65 assembly connector/FK/kinematics tests.
- The repository's slow simulation groups remain deferred by policy because no
  user-opened test session was active; none of the ten changes touches a simulator.

## Rejected experiments

These are deliberately not counted and their production edits were removed:

- Replacing FK array queues with `deque` did not improve the star topology
  (58.896 ms list versus 59.019 ms deque for revolute); raw logs are retained.
- An earlier per-frame pathview heatmap experiment changed the median only from
  30.9 to 30.5 ms while worsening p95 from 32.4 to 34.5 ms. The refined
  immutable-design preparation cache in optimization 25 was retained only after
  both browser median and p95 improved.
- An overhang-label cache changed 20.5 to 20.3 ms, inside run noise.

## Next ten candidates — approval required

1. Index crossover-sprite hit circles, which still scan every visible sprite on
   each pointer movement.
2. Map selected element keys directly to owning strands so selection broadcasts
   do not rescan all strand domains after every click/lasso.
3. Index consecutive domain transitions for `_findXoverDomains` and crossover
   drag setup.
4. Reuse track-domain indexes while validating candidate crossover positions,
   eliminating the remaining full-design range scans in `_getValidXoverBps`.
5. Cache reference-only helix membership and active-strand extents per immutable
   design for periodic and reference rendering passes.
6. Index loop/skip markers by helix and bp for pointer and lasso hit-testing.
7. Replace remaining overhang-cylinder instance `find` getters with direct
   instance-id maps in the 3D renderer.
8. Build interface-point label maps for repeated assembly connector resolution,
   especially manual connectors shared across FK and highlight refreshes.
9. Measure and cache pathview selection-key expansion for large multi-domain
   strands and component selections.
10. Profile crossover-indicator generation by visible bp window and skip lattice
    candidate enumeration outside the viewport before neighbor/occupancy checks.

No work on the fourth batch should begin until it is approved.

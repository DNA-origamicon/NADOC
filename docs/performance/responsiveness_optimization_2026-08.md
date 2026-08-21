# NADOC responsiveness optimization campaign — August 2026

Status: fifty optimizations complete; awaiting approval for the sixth batch.

This campaign has measured fifty changes to editing and visualization responsiveness.
All figures below are wall-clock milliseconds on this workstation. Browser
results use Chromium through Playwright's isolated backend (`:8002`) and Vite
server (`:5175`), never the live development session.

## Measurement protocol

- Pure kernels retain every sample, run a JIT warm-up first, and report median
  and p95. Legacy and optimized implementations run in the same process. Batch
  five additionally records cold build+query totals, candidate visits, index
  cardinality, query fingerprints, and independently compared result vectors.
- The pathview benchmark imports `workspace/VoltronCore.nadoc`, then expands it
  in browser memory to 2,460 strands, 10,920 domains, and 7,992 crossovers.
  The fourth-batch audit records 25 synchronous wheel/redraw samples per mode.
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

## Fourth batch — completed optimizations 31–40

Batch four removes the remaining full-design scans from selection, crossover
editing, loop/skip interaction, and several 3D/assembly lookup paths. The
frontend paired fixture contains 6,000 strands / 24,000 domains, 12,000
crossover sprites, 19,200 loop/skip markers, and 20,000 cylinder records. Each
kernel uses 15 paired legacy/current samples and asserts identical nonzero
checksums. The assembly fixture performs 1,000 queries over 2,000 real
`InterfacePoint` models.

| # | Process and change | Before median / p95 | After median / p95 | Result |
|---:|---|---:|---:|---:|
| 31 | Crossover indicator hit-testing: bin sprite hit circles in world space while retaining legacy first-hit priority | 25.515 / 34.213 ms | 0.771 / 5.887 ms | 97.0% lower; 33.09× |
| 32 | Selection broadcasts: lazily map element keys to all owning strands instead of rescanning every domain | 7.786 / 10.122 ms | 0.097 / 0.182 ms | 98.8% lower; 80.37× |
| 33 | Crossover drag resolution: lazily index consecutive domain-transition signatures | 240.503 / 247.238 ms | 0.051 / 0.053 ms | 99.98% lower; 4,756× |
| 34 | Crossover position validation: reuse the two relevant track indexes for occupied slots and overlap blockers | 55.681 / 57.759 ms | 0.121 / 0.147 ms | 99.8% lower; 461.12× |
| 35 | Periodic/reference queries: cache active-strand extent and reference-only helix membership with the immutable design index | 11.552 / 11.929 ms | 0.0015 / 0.0015 ms | 99.99% lower; 7,738× |
| 36 | Loop/skip interaction: lazily index markers by helix/bp and restrict lasso work to intersecting sorted rows | 4.925 / 4.947 ms | 0.047 / 0.080 ms | 99.1% lower; 105.43× |
| 37 | 3D overhang-cylinder picking: replace instance-array `find` calls with half/full instance-id maps | 62.300 / 64.531 ms | 0.056 / 0.233 ms | 99.91% lower; 1,118.64× |
| 38 | Assembly manual connector resolution: build an interface-point label map once per touched instance and pass resolved models through frame/position fallbacks | 11.887 / 11.969 ms | 0.070 / 0.109 ms | 99.4% lower; 170.19× |
| 39 | Whole-strand/component selection: lazily cache each strand's domain element-key expansion | 1.124 / 1.904 ms | 0.395 / 1.447 ms | 64.8% lower; 2.84× |
| 40 | Visible crossover indicators: enumerate only valid lattice residues, cache neighbor destinations, merge coverage ranges, and binary-search occupancy | 1.076 / 1.796 ms | 0.155 / 0.175 ms | 85.6% lower; 6.93× |

The exact pre-batch commit (`a8f447e3`) was rerun in an isolated worktree rather
than compared with an older fixture. Against that baseline, design update stayed
flat-to-better at 56.2 / 69.9 ms to 55.7 / 66.9 ms, ordinary zoomed redraw moved
from 0.9 / 1.2 ms to 0.7 / 1.0 ms, zoomed periodic redraw moved from 0.8 / 0.9
ms to 0.7 / 0.8 ms, and full periodic redraw moved from 25.9 / 30.8 ms to 23.9 /
27.1 ms. Selected redraw remained 0.8 ms median; its p95 moved from 1.9 to 2.1
ms. All six canvas hashes, transition counts, and the pan-final hash were exactly
equal, and the browser error log was empty. Selection, crossover-drag, and
loop/skip indexes are lazy so ordinary design replacement does not pay their
construction cost.

## Fifth batch — completed optimizations 41–50

Batch five targets pointer/lasso interaction, arc selection, nick editing, 3D
cylinder visibility, and live assembly connector frames. The frontend fixture
contains 6,000 strands / 24,000 domains, 12,000 arcs, 16,000 crossovers, 60,000
assigned nucleotides, and 24,000 cylinder entries. Each row uses 15 paired
samples. “Before” and “after” consume the same fixture and query objects, and
the harness compares complete result vectors outside the timed regions.

| # | Process and change | Before median / p95 | After median / p95 | Result |
|---:|---|---:|---:|---:|
| 41 | Pointer row resolution: binary-search immutable row bands for `_helixAtWY` and `_hitTest` | 3.748 / 4.672 ms | 0.408 / 0.592 ms | 89.1% lower; 9.19× |
| 42 | Lasso track ranges: lazily sort domain intervals and use prefix-max rejection for narrow horizontal windows | 2.135 / 2.633 ms | 1.144 / 2.006 ms | 46.4% lower; 1.87× steady-state |
| 43 | Strand/element lasso: share row-band + track-range candidate enumeration instead of traversing every domain | 22.102 / 23.168 ms | 0.351 / 1.176 ms | 98.4% lower; 62.89× |
| 44 | Forced-ligation point hits: add bounded curve descriptors to the shared horizontal arc bins | 78.352 / 79.856 ms | 3.381 / 3.460 ms | 95.7% lower; 23.17× |
| 45 | Arc lasso: reuse cached crossover/forced-ligation descriptors and bins | 181.616 / 184.631 ms | 11.657 / 11.862 ms | 93.6% lower; 15.58× |
| 46 | Grouped crossover drag: map selected keys directly to all matching crossover records | 28.969 / 29.225 ms | 0.072 / 1.461 ms | 99.75% lower; 403.21× |
| 47 | Nick tools: reuse track, domain-owner, and strand-terminal indexes for hover/nick/ligation resolution | 907.542 / 912.381 ms | 0.831 / 1.750 ms | 99.91% lower; 1,092× |
| 48 | Cylinder hidden alpha: index assigned nucleotides by `(strand, domain)` instead of filtering all geometry per cylinder | 94.503 / 95.401 ms | 0.019 / 0.043 ms | 99.98% lower; 5,101× |
| 49 | Selected cylinder glow: resolve domain refs directly to indexed straight/half/full entries | 0.435 / 1.529 ms | 0.095 / 0.247 ms | 78.2% lower; 4.59× steady-state |
| 50 | Live blunt connector frames: share helix, deformed-axis, and bp-position resolution per immutable design | 19.503 / 19.716 ms | 9.896 / 9.992 ms | 49.3% lower; 1.97× |

Cold totals were measured rather than inferred. Rows 41, 43–48 all remain
faster with index construction charged to the first query batch. Row 42 costs
2.962 ms cold versus 2.074 ms before and crosses break-even on its second
equivalent lasso batch. Row 49 costs 0.744 ms cold versus 0.408 ms before and
crosses break-even by the third selection refresh; it also reuses the
cylinder-domain index already needed by picking and representation checks.
These two amortization boundaries are retained here instead of hiding build
cost outside the benchmark.

The real connector benchmark uses 12 actual `Helix` models and 48 live blunt
labels. It resolves frames through production `_build_world_connector_frames`
with the real deformation functions. The complete 4×4 frame fingerprint is
identical, maximum element delta is 0.0, whole-design axis solves fall from 24
to 1, and per-helix nucleotide solves fall from 24 to 12.

### Anti-gaming and semantic audit

- Every paired frontend row records a query fingerprint, result-vector
  fingerprint, result count, index cardinality, and before/after candidate
  visits. A timing result is rejected if any result vector differs.
- Cold measurements construct the index inside every timed invocation. Steady
  measurements use the same production-equivalent immutable indexes and make
  their amortization boundary explicit.
- Candidate visits fall in all nine frontend rows (for example, lasso 8,400,000
  → 11,963; arc point hits 24,000,000 → 634,306; nick tools 144,000,000 →
  247,829). Thus the lower time accompanies less equivalent work, not fewer
  queries or weaker output checks.
- An initially implemented binary point-hit search was removed after measurement:
  on short real-style track buckets it regressed 1.249 ms to 1.982 ms steady and
  1.208 ms to 3.283 ms cold. Point hits retain the faster legacy-order bucket
  walk; the interval index is used only for range queries where it wins.
- The production Playwright fixture is identical before/after: 59 helices,
  2,460 strands, 10,920 domains, and 7,992 crossovers. All six state hashes and
  the final pan hash match exactly (`33504fd8`, `92d1d9b6`, `0412e322`,
  `773d024c`, `37c4e71d`, `c7ed93e4`, pan `70ff283f`), transition counts match,
  the known empty hover remains empty, and browser errors are empty.
- Integrated browser timings did not show a hidden broad regression: zoomed
  plain stayed 0.7 ms median (p95 1.0 → 0.9), selected zoomed improved 0.8 →
  0.7 ms (p95 1.9 → 1.8), and hover stayed 0.4 ms (p95 0.6 → 0.5). The noisier
  design-update sample moved 54.6 → 56.2 ms median and 64.7 → 72.7 ms p95; that
  variance is reported, not presented as a batch-five improvement.
- Production-source regression tests prevent reintroducing full-array scans in
  path hit/lasso, arc hit/lasso, cylinder alpha, and cylinder glow. The assembly
  unit test additionally asserts physical positions for all four resolved labels
  while proving one axis solve and one per-helix nucleotide solve.

## Campaign-wide summary — optimizations 1–50

All fifty accepted rows have paired output-equivalence evidence in the tables
above. The campaign progressed from render preparation and assembly FK (1–10),
through high-rate pointer and shared 3D indexes (11–20), immutable design caches
and viewport work restriction (21–30), selection/editing lookup removal (31–40),
to the interaction/visibility/live-frame paths in this fifth batch (41–50).
Experiments that failed to improve the measured workload are not counted; they
remain listed under “Rejected experiments.” Because fixtures and units differ,
individual row times are deliberately not summed into a misleading aggregate.
The stable end-to-end facts are: production builds pass, all fast backend and
frontend regressions pass, browser errors remain empty, and established pixel
digests are unchanged across every integrated audit.

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
- Optimizations 31–37 and 39–40:
  [paired batch-four frontend log](raw/batch4_frontend_indexes.json)
- Optimization 38: [paired interface-point log](raw/batch4_interface_point_index.json)
- Integrated fourth-batch audit: [exact pre-change baseline](raw/batch4_pathview_baseline_a8f447e3.json)
  and [optimized Playwright log](raw/batch4_pathview_playwright.json)
- Optimizations 41–49, including cold costs and anti-gaming fingerprints:
  [paired batch-five frontend log](raw/batch5_frontend_indexes.json)
- Optimization 50: [real-geometry blunt resolution log](raw/batch5_blunt_resolution_cache.json)
- Integrated fifth-batch audit: [exact pre-change production baseline](raw/batch5_pathview_baseline.json)
  and [optimized Playwright log](raw/batch5_pathview_playwright.json)

The reproducible harnesses are
`frontend/scripts/responsiveness-kernel-bench.mjs`,
`frontend/scripts/responsiveness-batch2-kernel-bench.mjs`,
`frontend/scripts/responsiveness-batch3-kernel-bench.mjs`,
`frontend/scripts/responsiveness-batch4-kernel-bench.mjs`,
`frontend/scripts/responsiveness-batch5-kernel-bench.mjs`,
`scripts/benchmark_assembly_fk.py`, and
`scripts/benchmark_assembly_shared_index.py`,
`scripts/benchmark_interface_point_index.py`,
`scripts/benchmark_blunt_resolution_cache.py`, plus
`frontend/e2e/responsiveness_pathview_bench.spec.js`.

## Functional verification

- Merged-`master` `just test-smart`: 7,190 passed, 117 skipped. The additional
  skip is the incoming optional `workspace/VoltronCoreArm.nadoc` regression
  fixture, which is not versioned or present on this machine.
- Merged-`master` `npm test`: 5,836 passed across 346 frontend test files.
- `npm run build`: production Vite build passed.
- Playwright responsiveness spec: passed against the isolated servers, with no
  browser errors and identical pixel hashes for plain, overhang, periodic,
  zoomed, and selected views.
- Production-browser indexed-interaction spec: passed real pointer strand-lasso
  and arc-lasso gestures against `VoltronCore.nadoc`, selected more than ten
  strands and more than five crossover owners, and verified every emitted owner
  id exists in the loaded design.
- Focused development checks also passed: 30 helix-renderer/pathview tests and
  27 assembly connector tests. Source contracts forbid the optimized frontend
  paths from falling back to whole-array scans; the connector tests pin both
  physical frame positions and expensive solver call counts.
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
- Binary-searching every point hit on a sorted/prefix-max track index regressed
  the representative short-bucket workload from 1.249 to 1.982 ms steady and
  from 1.208 to 3.283 ms cold. The edit was removed; only range lasso queries
  use the structure retained in optimization 42.

## Next ten candidates — approval required

1. Restrict loop/skip element-lasso traversal to `_rowBands` intersecting the
   lasso rather than scanning every displayed helix.
2. Upgrade arc hit bins from horizontal-only buckets to sparse 2D buckets so
   tall designs reject unrelated Y rows before Bézier distance tests.
3. Reuse row bands for gutter-circle hit testing, gutter lasso, and helix reorder
   insertion instead of repeatedly materializing/scanning all rows.
4. Index ds-linker bridge geometry by helix and bp during renderer construction;
   bridge cylinder setup currently filters the full geometry array, then filters
   each bridge again at both endpoint bps.
5. Reuse the `(strand, domain)` nucleotide map for MD overhang-rod updates, which
   still filters all assigned geometry once per overhang cylinder per frame.
6. Compile representation overrides into per-domain visible ranges so
   `_isDomainCyl` and `_cylRepVis` do not perform a map lookup for every bp column.
7. Make alpha refresh dirty-domain-aware, updating only strand/domain entries
   changed by reference, cluster, hidden-nucleotide, or representation state
   instead of sweeping all bead/slab/cylinder arrays.
8. Index scalar/flex recolor targets by nucleotide and domain so interactive
   color-map changes avoid repeated full backbone/slab traversal.
9. Cache `principal_seam_connectors(design)` in the same per-design live-frame
   resolution cache used for blunt labels; multiple seam labels currently
   recompute the complete seam geometry independently.
10. Retain interface-point label maps in assembly connector caches across
    cache-miss refreshes and position fallbacks instead of rebuilding them for
    each touched instance refresh.

No work on the sixth batch should begin until it is approved.

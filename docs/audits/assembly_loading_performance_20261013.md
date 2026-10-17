# Assembly loading and first Full display — 2026-10-13

**2026-10-14 merge provenance.** Pushing this work required integration with
upstream `76451452`. The upstream exact scaffold-length readiness step is retained
and shares the same per-projection loop/skip map as sequence checks. All 150
focused backend readiness/length/sequence tests and 52 frontend API,
representation-save and VR Join integration tests pass. The hardware measurements,
8,075-test frontend run and smoke results below describe the pre-merge implementation;
they were not repeated after integration. Local issue IDs 75/76 became 79/80 to
preserve upstream issue IDs. No scientific placement rules were changed by the
conflict resolution.

Post-merge `just test-smart` selected **FAST**: **11,019 passed, 23 failed,
21 skipped, eight errors**, in 192.73 s pytest / 212 s guard. FULL remains deferred
under the notice recorded below. The retained `merge-test-smart.log` shows three
newly imported VR failures rejected by the existing WSL platform guard, and four
CPD preview setup errors from the upstream corrected cis-anti-I chemistry; those
VR/preview implementations and tests are unchanged from `origin/master`. This is
not a green aggregate run. The slow-test triage report has zero individual
violators; the 212 s aggregate exceeds 90 s without a single heavy culprit, so no
budgets or test classifications were changed. Focused integration checks above
are green. Logs remain under `.development-artifacts/benchy-load-performance/`.

**Status: PARTIAL (ISSUE-80): implementation and validation complete; cold loading and Full GPU performance remain below target.** Final release measurements on unchanged application/test source are:

| Workload | Navigation → paint | Import → paint | First Full choice → frame | Steady Full FPS, first/restored |
| --- | ---: | ---: | ---: | ---: |
| Benchy: seven sources, 462,002 nucleotides | 34.203 s | **29.669 s** | **33.0 ms** | 21.07 / 21.60 |
| Hinge500: 500 copies of one source | 10.481 s | **6.119 s** | **485.2 ms** | 2.36 / 1.85 |

These are single document/browser/source-geometry-cold runs, not repeated-run medians. Choice→frame starts at the trusted representation option click, excludes menu navigation, and measures an actual renderer frame/next-rAF opportunity rather than compositor presentation or input-to-photon latency. The hinge screenshot anomaly and separate zero-mismatch control diagnostic are retained below. Fast switches do not establish the sub-five-second cold-load target or the historical 2,000/5,000-instance frame-rate targets.

Final frontend: **8,075 passed, one skipped across 697 files**. Post-fix smoke: **23 passed**. Final FAST: **10,603 passed, 22 failed, 21 skipped, four collection errors**, with identical baseline failure/error IDs and zero individual timing violators; the 203 s aggregate guard still exceeds 90 s. Exact geometry/transport parity, native-placement gate and cleanup are documented below. No acceptance run remains pending; the issue stays partial for the measured performance limitations and unresolved screenshot observation.

This follows the preserved [earlier Full interaction audit](benchy_full_performance_20261013.md), which fixed passive selection/recoloring but measured 69.71 s opening and 22.60 s first Full. Those older browser boundaries include overlapping application work and differ from this protocol.

## Workload and historical comparison

The current Benchy is `workspace/benchy/independent_20261013/Benchy-assembly.nass`: seven distinct source parts, 2,249 helices, and **462,002 nucleotides**. This session's geometry is the only Benchy modeling attempt used. Benchmarks copy the assembly and its parts into a unique `__e2e__` directory and use a fresh document; originals are checked by SHA-256.

| Source | Nucleotides |
| --- | ---: |
| Hull | 162,908 |
| Cabin sides | 55,902 |
| Cabin ends | 57,028 |
| Deck/roof | 122,956 |
| Rims/arches | 48,250 |
| Smokestack | 12,498 |
| Stack collar | 2,460 |

The historical comparator is `workspace/bench_fixtures/bench_hinge_500.nass`: **500 copies of one source**, `workspace/Ultimate Polymer Hinge.nadoc`. Its current source has 71 helices and 230 strands; SHA-256 is `e706c0bc3d323ef633a59c22d1d05a42472138369f7e772e2b88c027266b9f9b`. The separate `hinge_test.nass` presently references `Ultimate Polymer Hinge2.nadoc` and is not this sweep fixture. Unique-source construction cost must be separated from instance-copy cost.

The [historical inventory](../../.development-artifacts/benchy-load-performance/historical_assembly_metrics.md) links retained data, commits, fixtures, and harness limitations. The original target was approximately 2,000 instances at 60 FPS and 5,000 at 30 FPS, assuming 5–20 unique parts copied many times. It was not a demonstrated multisource result. In May, commit `907f2a00` reduced the N=500 source Design GET count from 500 to one and cold rebuild from 43.5 to 2.2 seconds. The retained pre-fix GPU sweep records 0.4 Full p5 FPS and 18.8 Cylinders p5 FPS at N=500, but lacks GPU/browser/viewport identity and predates indicator gating and later LOD changes. These are historical observations, not a controlled comparison to today's machine.

The old `scripts/bench_assembly.py` still counts/truncates only v1 `instances`, while the retained fixtures use v2 `instances_v2`; repair this before reusing its N labels. Missing-source fast-fail results and software-GL FPS are explicitly invalid historical comparisons.

## What changed

**Native geometry production and transport.** Ordinary occupied helical DNA can now emit compact columns directly from the existing `native_full_arrays_for_helix` authority and the shared slab-pose arithmetic. The fast path preserves site order, loop copies, skips, last-domain-wins ownership, and terminal flags. Authored chemical residues, extensions, overhangs/bridges, per-nucleotide transforms, photoproducts, duplicate helix IDs, and domains outside physical helix spans retain the general record pipeline. Coordinates and model constants are unchanged.

The assembly geometry endpoints negotiate `?format=ndgb1`; default clients still receive JSON. NDGB carries JSON metadata and aligned numeric arrays, with native coordinates in Float64. It reconstructs the same ordinary array/object shape for the existing placement validator and renderer. Constant rows decode into independent copies; dictionary metadata, nulls, booleans, signed zero, and object keys are preserved. The binary response opts out of gzip, trading a modest increase over compressed JSON bytes for removal of synchronous compression cost. Cache keys retain live file revision and cluster-override identity; a binary-created cache entry can still serve subsequent default JSON.

**Background work waits for source readiness.** Hidden cluster/overhang panels await the renderer's matching source versions and membership, then consume its already-decoded display Designs. A base Design fallback is only considered afterward for unresolved entries and remains deduplicated by source. Replaced source/document waits abort; failed/disposed renderer generations reject waiters. Backend design readiness waits for that load boundary, remains unknown while waiting, and still performs its authoritative backend assessment. No timeout is used to pretend a load has completed.

Selected-part authoring continues to read the immediate, base-only `getInstanceDesign` path. Overridden renderer Designs never seed that authoring cache. The earlier protections against passive selection PATCHes, stale selection callbacks, and writes during forced refresh remain in place.

Browser review also found repeated 4.4–6.2-second backend readiness jobs on representation changes. Assembly readiness now keys its expensive assessment and scientific fingerprint by every persisted assembly/instance input except the live instance representation, together with source-file revision stamps. Identical revision/object/stamp polls avoid recomputing the semantic hash. Source content, pose, names, visibility, owned DNA, and other authored changes still invalidate the result; current simulation-job status is refreshed on every read. The part-only readiness path retains its behavior. The retained browser traces keep the first cold assessment cost while avoiding repeated completed assessments during later representation changes. The cold hinge500 assessment remains expensive, as measured below.

The readiness controller now also retains its pending request across semantically identical representation snapshots instead of aborting and replacing it. Authored input/source-version/document changes still invalidate, and explicit refresh/job polling remains available. Backend sequence assessment builds the same loop/skip map once per Design projection instead of once per strand; the validator returns its exact flattened Design so readiness avoids a second flatten while retaining the canonical JSON round-trip. The projection is serialized and released before parsing the canonical Design, avoiding simultaneous retention of both large Designs; a weak-reference regression verifies that lifetime. Independent source review found no correctness issue. These changes do **not** cancel an assessment already running on the server. Final review also caught an early-switch wait: choosing Full before initial Cylinders geometry completed could retain an obsolete representation signature indefinitely. Source readiness now compares membership and mode independently of representation, while retaining live source-version, dirty-source and unversioned-snapshot authority. Fresh inline/legacy snapshots restart their wait conservatively; versioned representation-only snapshots retain the pending request. Real deferred-renderer and controller regressions are included in the 80-case focused batch.

Direct-open tabs hide welcome before library initialization. Those hidden tabs now defer only the initial library listing/disk enrichment until welcome becomes visible. Initial visible welcome and explicit refresh calls remain immediate. The backend listing itself is an `os.walk`/stat operation; the separate identity-audit thread can still contend for the GIL when it parses changed or unstamped files. This change does not claim to remove all backend startup contention.

**Prepare Full once; defer unused indexes.** Supported coarse representations prepare native Full primitives during source construction, while the requested Cylinders/Beads/Full representation still controls actual LOD caps and visible primitives. Full-only slabs/connectors use per-instance visibility masks; prepared-view export honors the same mask. Full→Beads→Cylinders→Full can reuse the prepared resources instead of rebuilding nucleotide geometry. Protein attachments, linker/binder auxiliary sources, and unsupported representations retain their existing guarded paths.

This is upfront Full resource preparation with **lazy interaction/simulation indexes**, not a claim that the initial Full GPU paint is free. String-key maps used by per-base edits and simulation overlays are built on first use; entry order and loop-copy identity remain stable. The first Full draw can still compile shaders/upload resources and must be measured in the browser. Merely finding retained Full buffers is not proof that Full was drawn.

**Display prepared CG choices while saving.** `ui/assembly_representation_actions.js` lets Full, Beads, Cylinders, and Hull Prism choices update the displayed assembly immediately, preserving each row's non-enumerable live source version. The controller serializes the ordinary batch PATCH requests and coalesces only unsent intermediate choices. It suppresses the global busy overlay for those coarse-grained display saves; it does not suppress errors or bypass backend persistence. Accepted responses still pass through normal revision synchronization, with a newer local choice reapplied. A failed latest save restores the last confirmed representation and shows an error. Document reset or membership replacement retires pending choices and late callbacks. Atomistic/surface choices stay in the same ordered queue with their existing confirmation and acknowledgement-before-display behavior. All 65 focused controller/switcher/busy/v2 tests pass. The Benchy actual-click browser run passed; timing requires actual rendered geometry, not the local state update alone.

Final lifecycle corrections retain a failed source build for later poll/Show waiters until an explicit rebuild starts; reset/disposal stay isolated and no automatic geometry retry is introduced. A WeakMap marks accepted API responses and immutable snapshot representation values before publication. Equal-value authoritative snapshots can advance confirmed state through synchronous store-clone subscribers, while unmarked delayed clones cannot override it. Independent source review is clean, and the final 122-case correctness scope plus full frontend cover these paths.

Joint and connector indicators also retain their meshes and pending frame request across representation-only snapshots. The input gate excludes only the live representation while preserving every authored field and explicitly capturing the non-enumerable live source version; unversioned file sources do not qualify for reuse. Source, pose, interface, joint, membership, or document changes retire stale callbacks. Forced refresh and live-drag invalidation remain available, and failed frame requests permit retry. The background connector GET suppresses its delayed global busy overlay. All 27 focused cases pass; an independent source-only review found no concrete stale-version, document-reset, volume-cache, or hidden-panel correctness issue.

Hull construction reuses lattice-cell edge identities and common sweep-spine centroids within a single immutable build. It avoids straight-only work for curved hulls and lazily constructs scan/marker inputs only when those branches need them. The frame evaluator, centroid addition order, sample spacing, curve tolerance, and final mesh data are retained. No cache crosses an authored design/axis change.

## Isolated phase measurements

All artifacts in this section live in `.development-artifacts/benchy-load-performance/`. These are serial local CPU profiles, not repeated browser medians. Subphase timers can be nested; do not add independent harness totals or compare them directly to navigation-to-paint.

The [backend optimization audit](../../.development-artifacts/benchy-load-performance/backend_optimization_audit.json) records:

| Backend phase, seven sources | Previous | Optimized |
| --- | ---: | ---: |
| Source read | 0.031 s | 0.030 s |
| Parse/validate source Designs | 1.706 s | 1.591 s |
| Native nucleotide/compact production | 11.404 s | 4.486 s |
| Helical axes | 1.883 s | 1.369 s |
| Overhang-axis overlay | 0.168 s | Not needed for this bounded fast path |
| Design metadata conversion | 0.126 s | 0.237 s |
| Compact packing + JSON encoding + gzip / binary encoding | 5.240 s | 1.542 s |
| Production total | **20.560 s** | **9.255 s** |

The total is a 2.22× improvement in this profile, excluding frontend decode/render and concurrent application startup. The prior assembled JSON was 242,706,372 bytes; prior gzip was 85,656,308 bytes; the seven binary packets total 96,840,871 bytes. Binary is about 60% smaller than uncompressed JSON and about 13% larger than the former gzip payload. Packet-vs-assembled metadata accounts for small byte-total differences between artifact tables.

The [staged renderer result](../../.development-artifacts/benchy-load-performance/staged-renderer-final.json) uses real shared-renderer construction over retained geometry payloads, with no GPU draw:

| Stage | CPU time |
| --- | ---: |
| Read/parse retained JSON inputs | 1,497.02 ms |
| Expand compact nucleotide columns | 379.43 ms |
| Initial source build, requested Cylinders with supported Full prepared | **7,817.72 ms** |
| First Full representation update | **0.615 ms** |
| Beads update | 0.126 ms |
| Cylinders update | 0.075 ms |
| Full restore | 0.069 ms |

Within the initial build, source timers sum to approximately 3,181 ms hull construction, 3,657 ms helix objects, 549 ms LOD geometry, 289 ms colors, 95 ms shared textures, 28 ms bounds, and 15 ms crossovers. The earlier staged checkpoint paid 8,457 ms initially and another 14,324 ms for the first Full rebuild. These checkpoints describe changed work allocation, not GPU latency.

Independent primitive profiling recorded hull work 11,241→3,603 ms and Full helix construction 6,175→3,617 ms. These sum different calls from the staged harness and must not be added to its total. The final initial renderer build alone remains above five seconds.

**Cold background readiness remains a separate bottleneck.** The [readiness reuse profile](../../.development-artifacts/benchy-load-performance/readiness-reuse-profile.json) measures the actual 500-copy source assessment at **39.604 s after map/flatten reuse, before the final projection-lifetime cleanup**: one flatten 6.507 s, standard readiness 5.812 s, fingerprint 0.326 s, and approximately 27 s remaining route/projection/canonical-round-trip work. It is not a foreground load timer. A bounded 20-copy comparison is 1.515→1.343 s (1.13×), with exact complete report SHA-256 and scientific fingerprint equality; loop/skip-map calls fall from 504 to two. The old 500-copy implementation was not rerun, so no full-scale speedup ratio is claimed. Source bytes remained unchanged. This is an intermediate profile; the lifetime cleanup has not been assigned an unmeasured speedup. Server-side cancellation is still absent: browser abort or document closure can leave this work contending with the next foreground load.

## Exactness and malformed-input review

The following are exact comparisons, not visual similarity scores:

- [Compact source parity](../../.development-artifacts/benchy-load-performance/compact-profile.json): all seven actual part responses, totaling 462,002 nucleotides, match the previous complete serialized JSON SHA-256 after binary round-trip. Source hashes are retained per part. Unit cases cover straight, bend, twist, sweep, partial/overlapping domains, loop copies/skips, and general-path fallback.
- [Frontend transport and occupancy-hull parity](../../.development-artifacts/benchy-load-performance/frontend-exact-parity.json): decoded binary is `isDeepStrictEqual` to the original JSON for every part. Old/current hull groups have equal hashes over object types, world matrices, every geometry attribute's bytes, and index bytes. The measured old/current hull work in this separate pass totals 11,627/3,708 ms.
- [Lazy assembly-hull parity](../../.development-artifacts/benchy-load-performance/assembly-hull-lazy-exact-parity.json): old/current merged solid and marker presence, geometry attributes, and index bytes match for all seven sources. This verifies the final lazy scan-input change separately from the earlier sweep/edge changes.

The transport review found that byte-read bounds alone did not bound decoded allocations: a tiny repeat descriptor or an array shaped `[4294967295, 0]` could request billions of containers while using zero data bytes. Both decoders now apply a default **64×1024×1024 decoded-entry budget**, including container entries/repeated copies, and bound nesting to 256. The frontend rejects malformed descriptors before oversized reconstruction; the Python oracle preflights expansion. Dictionary indices, dtypes, aligned offsets, shapes, finite numbers, prefix/version, and truncation remain validated. The latest frontend decoder regression and expanded 20-case Python binary regression passed.

These checks establish unchanged transport values and constructed mesh data for the exercised sources. They do not replace the native-placement review gate, GPU drawing checks, or broad feature regression tests.

## Browser protocol and final results

Final measured artifacts are the Benchy [summary](../../.development-artifacts/benchy-load-performance/release_benchy_766e00d2745c_summary.json), [trace](../../.development-artifacts/benchy-load-performance/release_benchy_766e00d2745c_audit.json), [hashes/cleanup](../../.development-artifacts/benchy-load-performance/release_benchy_766e00d2745c_source_hashes.json), and hinge500 [summary](../../.development-artifacts/benchy-load-performance/release_hinge500_4ea9e7c55fdd_summary.json), [trace](../../.development-artifacts/benchy-load-performance/release_hinge500_4ea9e7c55fdd_audit.json), [hashes/cleanup](../../.development-artifacts/benchy-load-performance/release_hinge500_4ea9e7c55fdd_source_hashes.json). Application/test files did not change between the final 8,075-test suite and these runs.

| Final boundary / operation | Benchy | Hinge500 |
| --- | ---: | ---: |
| Navigation → source ready | 32.168 s | 7.167 s |
| Navigation → initial Cylinders frame | **34.203 s** | **10.481 s** |
| Import request start → source ready | 27.634 s | 2.805 s |
| Import request start → initial Cylinders frame | **29.669 s** | **6.119 s** |
| Actual first Full choice click → Full frame | **33.0 ms** | **485.2 ms** |
| Beads choice click → Beads frame | 93.8 ms | 1,058.8 ms |
| Cylinders choice click → Cylinders frame | 76.4 ms | 689.0 ms |
| Restore Full choice click → Full frame | 35.4 ms | 205.8 ms |

| Workload / representation | Submitted triangles | Draw calls | Steady FPS |
| --- | ---: | ---: | ---: |
| Benchy Full, first/restored | 91,752,688 | 35 | **21.075 / 21.597** |
| Benchy Beads | 71,424,600 | 21 | 29.981 |
| Benchy Cylinders | 473,152 | 12 | 59.460 |
| Hinge500 Full, first/restored | 1,517,472,000 | 5 | **2.363 / 1.855** |
| Hinge500 Beads | 1,183,248,000 | 3 | 2.855 |
| Hinge500 Cylinders | 192,000 | 1 | 59.210 |

Both Full checks retain all seven Benchy sources / all 500 hinge copies at close LOD with unchanged native camera and LOD policy. Benchy retains 462,002 unique-source nucleotides. Full-only visible primitives, current requested representations, frame advances and submitted triangles prove actual Full submission; retained buffers alone are insufficient. Cylinders includes the curved-collar mesh `sharedLodCurvedCyl` as well as straight/hull slots.

Neither run reports errors, Design PATCHes or context loss. Hinge has no busy overlay; Benchy's only busy event is its initial geometry GET (17.545 s overall, 96,874,917 encoded bytes). Original/copy hashes and each run's exact cleanup pass. One hinge readiness GET remains pending at browser close. Server-side cancellation is absent, so this result does not establish that expensive background assessment or cross-document CPU contention is solved. In the live lazy-connector check after clocks/screenshots, closed sections contain zero connector rows; opening creates four delete controls, and the section closes normally.

**Screenshot limitation, retained rather than explained away.** The release hinge [first-Full screenshot](../../.development-artifacts/benchy-load-performance/release_hinge500_4ea9e7c55fdd_first_full.png) shows Cylinders in row selectors despite the measured frame's recorded store/renderer Full state; the restored-Full screenshot shows Full. Bounded source review found no confirmed defect: visible-panel updates synchronously write registered select values, and no hidden/collapsed transition was evidenced. The old screenshot has no simultaneous DOM-value probe, so its cause remains unresolved. A separate current-source [controls diagnostic](../../.development-artifacts/benchy-load-performance/controls_hinge500_a993d498ff87_summary.json) and `controls-hinge500.log` explicitly inspect all 500 DOM row controls after every timed Full/Beads/Cylinders/Full phase: zero mismatches in requested value, shown value and selected text, and its [first-Full screenshot](../../.development-artifacts/benchy-load-performance/controls_hinge500_a993d498ff87_first_full.png) shows Full. That repeat measures 5.964 s import→paint and 233.8 ms first Full, with clean errors/hashes/cleanup, but is diagnostic rather than a replacement for the primary 6.119 s / 485.2 ms run. The release values certify renderer submission timing; they do not certify simultaneous compositor/DOM pixels or total menu-navigation latency. No code change was made without a reproduced cause.

The [runner](../../.development-artifacts/benchy-load-performance/startup_first_full.mjs) uses a fresh visible browser/context, disabled HTTP cache, a new document, unique copied source paths and a 1440×1000 viewport at DPR 1. Chromium 145 reports `ANGLE (Microsoft Corporation, D3D12 (NVIDIA GeForce RTX 2080 SUPER), OpenGL 4.6)`. The checkout is `6a8328c2d8e451c0fc804b27a4150b57fe9acaa7` plus each run's recorded uncommitted changes. OS file cache, backend module initialization and library identity stamps are not reset: these are document/browser/source-geometry cold, not machine cold-start measurements. Native fit framing is retained; no harness camera adjustment forces the close-LOD workload.

There is no startup screenshot or steady sample before first Full. Public ArrowRight navigation holds the representation submenu open, then the trusted option click starts the timer. Menu opening is excluded; subsequent four-second steady samples, screenshots, connector checks and DOM-control probes are outside the transition timer. Static GL metadata is queried once. Frame completion requires matching membership/representation, actual close/mid/hull counts, visible primitives, a renderer frame advance and positive triangles, observed at the next rAF. Screenshot completion is a separate visual observation, not a compositor-present timestamp.

**Earlier results are checkpoints, not final acceptance substitutes.** They remain in the artifact directory:

| Checkpoint | Import → paint | First Full | Why retained |
| --- | ---: | ---: | --- |
| `optimized_benchy_9845954f7eba` | 29.270 s | 521 ms | Before later UI gates/static GL-probe correction; Full 28.35/30.61 FPS, outer View menu partly obscures screenshots |
| `optimized_hinge500_07ae74e6d692` | 17.462 s | 13.713 s | Inactive view-volume points and hidden overhang DOM dominated the tail |
| `corrected_hinge500_d21a6f9e3c33` | 6.088 s | 1.621 s | Still had empty-warning layout reads, row rebuilds and an autosave popup |
| `final_hinge500_98ab4b0efd4c` | 5.670 s | 294 ms | Before final readiness/failure/acknowledgement fixes |
| `verified_hinge500_e77a3c5e0f0c` | 6.280 s | 275 ms | Before final failure/acknowledgement fixes; Full 2.05/1.81 FPS |
| `verified_benchy_cf119ef707da` | 29.925 s | 36.4 ms | Before final failure/acknowledgement fixes; Full 31.74/31.37 FPS |
| `final_benchy_eb73e3a9f67e` | 51.190 s | 35.2 ms | Contention checkpoint: geometry header wait ~38.8 s versus earlier ~16.7 s; source build ~8.82 versus ~8.56 s |
| `idle_benchy_b639ac399636` | 28.519 s | 40.2 ms | Idle checkpoint, Full 30.86/32.75 FPS; demonstrates sensitivity, not eliminated contention |

The final release Benchy Full FPS is lower than the preceding verified checkpoint; no controlled repeated-run study attributes that difference to a specific cause. The invalid first runner omitted curved cylinders and never met startup completion; its partial artifact is excluded. `verified_hinge500_63a2d1e0b52f` lost submenu visibility before the Full option click, so has no valid Full transition; its 6.349 s startup import→paint is diagnostic only, with clean cleanup.

The [first hinge tail profile](../../.development-artifacts/benchy-load-performance/hinge500-live-tail.cpuprofile) sampled 3,631 ms in `withSkippedColumnPoints`, 1,841 ms prefix creation, 1,562 ms assembly-point materialization, 923 ms its caller and 5,820 ms garbage collection. Hidden overhang sorting/list/dropdown costs were 576/172/436 ms. The [follow-up profile](../../.development-artifacts/benchy-load-performance/profile_hinge500_87acf6a406d5.cpuprofile) separately found 3,583 ms in the benchmark's repeated GL probes, 2,501 ms empty warning sync, 406/483 ms row/connector builders and 677 ms accessibility processing. These are sampled interval self times, not a decomposition to subtract from a transition. The final implementation gates inactive volumes and hidden panels, reuses semantic rows and source sorting, avoids empty/hidden warning layout, builds connector sections on open, and keeps autosave quiet while manual Save retains progress.

The intermediate readiness traces also retain the early 6.20/4.71 s Full/Beads requests and later ~66/62/79 ms cached headers. They motivate semantic reuse but do not erase the cold 39.604 s assessment profiled above. The old 69.71 s opening and 22.60 s first-Full workflow has different timer boundaries; no controlled cold-load speedup is claimed.

The [final cleanup verification](../../.development-artifacts/benchy-load-performance/final-cleanup-verification.json) proves exact preservation of **205 project-store paths, five document IDs and nine original source/assembly hashes**, zero artifacts across all recorded test prefixes, and no bridge credentials. All **109 frozen app/test file hashes** match, with no added/removed files in that scope. The two source-error/accepted-snapshot correctness fixes, final frontend, post-fix smoke, release runs and controls diagnostic therefore share the frozen implementation.

## Validation record and remaining limitations

Commands below are reproduction/validation entry points; results are attributed to the retained runs, not to a new run performed while drafting this audit. All heavy commands use the serialized validation slot.

| Check | Recorded status |
| --- | --- |
| `just test-focused tests/test_native_compact_geometry.py` | 12 passed |
| `just test-focused tests/test_native_slab_placement.py` | 17 passed |
| `just test-focused tests/test_native_geometry_binary.py` | 20 passed, including allocation-budget and nesting-depth review |
| `just test-focused tests/test_assembly_geometry_cache.py` | 5 passed; includes cold NDGB→same-cache default JSON parity for both routes |
| `just test-focused tests/test_design_readiness_api.py` | 17 passed, including 9 new semantic-cache cases |
| Focused frontend batch, `focused-frontend.log` | 10 files, 73 tests passed; renderer reuse/representation, prepared instances, lazy maps, sweep, panel/readiness gates, and initial decoder |
| Final decoder/library batch, `final-decoder-library.log` | 2 files, 29 tests passed; includes decoded-allocation budget and hidden library startup |
| Renderer owner's two serialized focused batches | 53 tests/10 files and 46 tests/7 files passed; 99 executions include 12 repeated reuse cases, or 87 unique tests across these two batches |
| Actual-source binary/compact and both hull parity scripts | All seven parts passed exact comparisons |
| Final scoped Ruff | Passed on all 23 changed backend/test files |
| `just lint` | Same two pre-existing unused imports: `parse_event` in `vr_prompts.py`, `Path` in `test_cpd_cube_validation_v6.py`; retained `lint.log` |
| Final `just lint-memory` after documentation | Same four pre-existing errors/60 warnings, no new issues; `lint-memory-completed.log`, details below |
| `uv run python -m tools.native_placement_audit check` | Clear |
| `git diff --check` / `main.js` size | Clean; 10 added / 12 removed, net −2 lines of thin wiring |
| `node --check .development-artifacts/benchy-load-performance/startup_first_full.mjs` | Passed before browser execution |
| `just test-smart`, before timing shrink | FAST: 10,585 passed, 22 failed, 21 skipped, 4 collection errors; 196.57 s pytest / 212 s guard; two individual timing violators |
| `just test-smart`, preceding backend checkpoint | FAST: 10,585 passed, 22 failed, 21 skipped, 4 collection errors; 195.83 s pytest / 217 s guard; same 22/4 baseline signatures, zero individual timing violators, aggregate 90 s backstop exceeded |
| Overhang lifecycle/sidebar/cache focused batch | 5 files, 35 passed, including 7 new lifecycle regressions; 3.19 s Vitest |
| Final FAST after readiness changes | 10,603 passed, 22 failed, 21 skipped, 4 collection errors; 191.09 s pytest / 203 s guard; identical failure/error IDs, zero individual timing violators, aggregate 90 s backstop exceeded |
| Full frontend before early-switch readiness edge fix | 696 files, 8,060 passed, 1 skipped; 316.79 s |
| Frontend checkpoint after early-switch fix | 696 files, 8,066 passed, 1 skipped; 327.96 s; `test-frontend-acceptance.log` |
| Final failure/retry and acknowledgement regressions | 122 unique cases across 10 files; initial 121 pass plus corrected v2 fixture/affected 20-case rerun pass; source review clean |
| Post-correctness-fix full frontend | 697 files, 8,075 passed, 1 skipped; 314.18 s; `test-frontend-verified.log` |
| Post-correctness-fix smoke | 23 passed in 2.6 minutes; `smoke-verified.log`, exact preserved stores/documents/hashes and zero bridge credentials |
| Release hardware / selector-display verification | Final measured runs retained; diagnostic checks all 500 controls with zero mismatches each phase; unreproduced release screenshot anomaly documented, 109-file source manifest unchanged |
| Early-switch readiness focused regressions | 8 files, 80 passed; version/membership/mode and conservative unversioned restart retained |
| Optimistic CG representation controller focused checks | 4 files, 65 passed: 14 controller, 41 switcher, 3 busy, 7 v2 cases |
| View-volume performance follow-up focused checks | 7 files, 25 passed |
| Joint/connector representation reuse focused checks | 3 files, 27 passed: 20 real-mesh renderer, 6 input-gate, 1 background-busy case; 2.00 s Vitest |
| Quiet autosave/manual-save lifecycle checks | 2 files, 32 passed; `src/api/assembly_autosave_busy.test.js` and `src/app/lifecycle.test.js`, retained `autosave-busy-focused.log` |
| Sweep-warning idle/hidden lifecycle checks | 5 passed, 764 ms; active placement, hover/undo, live geometry, camera scale/orientation retained; `sweep_warning_idle_validation.json` |
| Assembly-panel semantic row reuse focused checks | 4 files, 31 passed; includes same-object nested mutation, selection, draft retention, live versions and document reset; independent source review clean |
| Backend FULL | Deferred as quoted below; no broad FULL pass claimed |
| Intermediate hardware Benchy browser, source integrity and cleanup | Passed, `optimized_benchy_9845954f7eba_*`; seven close-LOD sources, real Full triangles, no Design PATCH or CG busy overlay, unchanged hashes and exact cleanup |
| Verified Benchy checkpoint before final correctness fixes | Passed `verified_benchy_cf119ef707da_*`: 29.925 s import→paint / 36.4 ms first Full; all seven close, 462,002 nucleotides, unchanged hashes/exact cleanup |
| Intermediate hardware hinge500 comparator | Geometry/hash/cleanup passed, performance failed; `optimized_hinge500_07ae74e6d692_*`, inactive point construction and hidden overhang DOM work identified |
| Second intermediate hardware hinge500 comparator | `corrected_hinge500_d21a6f9e3c33_*`: import→paint 6.088 s / first Full 1.621 s, clean geometry/hashes/cleanup; still over load target, with one background-autosave popup |
| Hardware hinge500 checkpoint before final readiness fixes | Passed geometry, all representations, no busy/errors/Design PATCH/context loss, hashes and exact cleanup: `final_hinge500_98ab4b0efd4c_*`; 5.670 s import→paint / 294 ms first Full; load and Full-FPS targets unmet |
| Verified hinge500 checkpoint before final correctness fixes | Passed `verified_hinge500_e77a3c5e0f0c_*`: 6.280 s import→paint / 275.1 ms first Full, same Full geometry, no busy/errors/mutations/context loss, clean hashes/cleanup; one readiness GET pending at close |
| Final hardware measurements and cleanup | Release Benchy/hinge and controls diagnostic complete; exact stores/documents/source hashes preserved, all test prefixes/bridge credentials absent |
| Backend readiness reuse focused batch | 131 unique passed: 18 reuse, 40 standard readiness, 17 readiness API, 8 assembly validator, 48 sequences; changed-file Ruff clean |
| Latest frontend readiness/lazy-connector/panel batch | 61 passed across 8 files: controller 20, host 7, comparator 6, lazy connector 3, panel 17, selection/context 8; independent readiness source review clean |

The [final frontend log](../../.development-artifacts/benchy-load-performance/test-frontend-verified.log) passes **8,075 tests with one skipped across 697 files in 314.18 s**, including both final correctness fixes. The [post-fix smoke log](../../.development-artifacts/benchy-load-performance/smoke-verified.log) passes all **23 tests in 2.6 minutes**. Its [cleanup comparison](../../.development-artifacts/benchy-load-performance/release-smoke-cleanup-comparison.json) proves exact preservation of 205 project-store paths, five document IDs and nine source/assembly hashes, with zero prefixed artifacts and bridge credentials. Release hardware and the separate controls diagnostic are complete; the unreproduced screenshot anomaly is retained above as a limitation.

The [preceding frontend log](../../.development-artifacts/benchy-load-performance/test-frontend-acceptance.log) reports **8,066 passed and one skipped across 696 files in 327.96 s**, including the early-switch readiness fix. The earlier 8,060-case run is retained only as a checkpoint.

The earlier five backend focused files contain 71 passing cases; the later 131-case readiness batch overlaps existing coverage and is separate. Frontend batches overlap and must not be added as unique-test totals. The renderer owner's 53-case batch covered `assembly_renderer_shared.reuse`, `assembly_representation`, `prepared_assembly_instances`, `lazy_map`, `helix_renderer.interaction_indexes`, `helix_renderer.simulation_visibility`, `assembly_source_colors`, `assembly_renderer_shared.colors`, `assembly_source_readiness`, and `polymerization_preview`. Its 46-case batch covered `assembly_hull_geometry`, `assembly_hull_geometry.lazy`, `hull_lattice_edges`, `hull_sweep`, `hull_occupancy`, `hull_volume_cutouts`, and repeated `assembly_renderer_shared.reuse`. Both used `just validate-safe npm --prefix frontend test -- src/scene/<name>.test.js ...`; their tool-session outputs were 3529 and 72465, without retained log files.

The [initial FAST log](../../.development-artifacts/benchy-load-performance/test-smart.log) and [preceding rerun](../../.development-artifacts/benchy-load-performance/test-smart-final.log) are not green aggregate runs. Their 22 failures and four collection errors have the same signatures as the earlier audit: missing native VR viewer/unsupported WSL prerequisites, absent archived CPD fixtures, and the four original-HEAD-reproduced trajectory/junction/preview failures documented there. These runs add no claim that those pre-existing failures are fixed. The initial guard flagged `tests/test_cluster_join_api.py::test_repeated_join_uses_remaining_host_route_without_moving_previous_donor` at **5.19 s** and `tests/test_cluster_join_free.py::test_batch_apply_token_history_and_stale_rejection` at **5.06 s** against the unchanged five-second per-test budget. The [retained timing report](../../.development-artifacts/benchy-load-performance/backend_slow_candidates_final_snapshot.json) and [triage](../../.development-artifacts/benchy-load-performance/backend_slow_triage_source_only.json) identify unused deformed/straight geometry HTTP response work. The test-only use of existing `X-NADOC-Skip-Geometry` headers preserves real join/routing/history and explicit native-position assertions. Both focused nodes pass: repeated join 2.29 s setup + 1.16 s call, batch join 2.44 s setup + 1.54 s call. Logs are `slow-shrink-repeated-join.log` and `slow-shrink-batch-join.log`; Ruff passed. The preceding FAST run has zero individual timing violators in `backend_slow_candidates_after_shrink.json`. The [final acceptance log](../../.development-artifacts/benchy-load-performance/test-smart-acceptance.log) reports **10,603 passed, 22 failed, 21 skipped, four collection errors**, in **191.09 s pytest / 203 s guard**. The [failure identity comparison](../../.development-artifacts/benchy-load-performance/backend-acceptance-failure-comparison.json) has no added or removed failure/error IDs. Its [retained timing report](../../.development-artifacts/benchy-load-performance/backend_slow_candidates_acceptance.json) again has **zero individual timing violators**, while the aggregate remains **203 s > 90 s**. Markers and budgets are unchanged; the broad backend run is not green.

The overhang lifecycle validation command was `just validate-safe npm --prefix frontend test -- src/ui/assembly_overhang_panels.test.js src/ui/assembly_overhang_list_panel.test.js src/ui/assembly_overhang_connections_panel.test.js src/ui/assembly_instance_designs.test.js src/ui/right_sidebar_tabs.test.js`; all five files / 35 cases passed. This includes source readiness and existing sidebar host behavior, not only the new semantic helper.

The final correctness-focused command was `just validate-safe npm --prefix frontend test -- --silent=true src/scene/assembly_source_readiness.test.js src/scene/assembly_renderer_shared.reuse.test.js src/ui/design_readiness_host.test.js src/ui/design_readiness_controller.test.js src/ui/design_readiness_controller.assembly.test.js src/api/assembly_response_authority.test.js src/api/assembly_v2_expand.test.js src/api/assembly_batch_busy.test.js src/ui/assembly_representation_actions.test.js src/ui/representation_switcher.test.js`. Session 77066 passed 121 cases with one new fixture missing its required `t12`; after supplying the identity transform, the guarded `assembly_response_authority`/`assembly_representation_actions` rerun passed 20/20 in session 10908. That is 122 unique focused cases, not 141 distinct tests.

The [connector reuse validation](../../.development-artifacts/benchy-load-performance/connector_reuse_validation.json) records `just validate-safe npm --prefix frontend test -- src/scene/assembly_joint_inputs.test.js src/scene/assembly_joint_renderer.reuse.test.js src/api/client_connector_frames.test.js`: all three files / 27 cases passed. The renderer cases use real Three.js indicator meshes/materials in jsdom; only the unrelated Canvas2D hover preview is stubbed. They cover pending-request reuse, authored-input and live-version invalidation, same-ID document resets, stale results, failures, empty inputs, disposal, forced refresh, and live-drag cancellation.

[Final memory lint](../../.development-artifacts/benchy-load-performance/lint-memory-completed.log) retains four errors in unchanged files: `project_cpd_strand_builder.md` has 1,557 lines, `project_native_vr.md` has 1,291, `project_exp_predictor.md` lacks an index entry, and `project_md_job_system.md` links to missing `.development-artifacts/gold_validation_20260914/RESULTS.md`. It also reports 60 warnings, including the existing over-200-line path-to-thousands head. The post-documentation rerun retains the same four errors/60 warnings with no new memory-lint issues. These unrelated repairs were not added to this performance change.

The selector's deferred notice, verbatim:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

Retained reproduction commands include:

```bash
just validate-safe .venv/bin/python .development-artifacts/benchy-load-performance/profile_geometry.py --label baseline --save-payloads
just validate-safe .venv/bin/python .development-artifacts/benchy-load-performance/profile_compact.py
just validate-safe node --expose-gc --max-old-space-size=4096 .development-artifacts/benchy-load-performance/profile_frontend.mjs baseline
just validate-safe node frontend/scripts/bench_assembly_renderer.mjs .development-artifacts/benchy-load-performance/baseline-payloads .development-artifacts/benchy-load-performance/staged-renderer-final.json
just validate-safe node .development-artifacts/benchy-load-performance/verify_frontend_transport_hulls.mjs
just validate-safe node .development-artifacts/benchy-load-performance/verify_assembly_hull_lazy.mjs
node .development-artifacts/benchy-load-performance/startup_first_full.mjs --fixture benchy --tag release
node .development-artifacts/benchy-load-performance/startup_first_full.mjs --fixture hinge500 --tag release
```

The profiling commands overwrite the named output artifacts; use a new label/output path for a fresh comparison. Do not run these concurrently with the browser, backend tests, or another profiler. Recorded final counts, hardware results, source hashes and cleanup above bind the frozen implementation; earlier artifacts remain labeled checkpoints.

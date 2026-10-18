# Benchy Full assembly performance — 2026-10-13

Reproducer: `workspace/benchy/independent_20261013/Benchy-assembly.nass`, seven
native source parts, 2,249 helices and 462,002 nucleotides. Tests open isolated
`__e2e__benchy_full_perf_*` copies; original assembly and parts are preserved.
Raw operation traces, screenshots, test logs and the operation runner are retained
in `.development-artifacts/benchy-full-performance/`.

## Confirmed causes

1. Selecting a part called `animation_defaults.ensure()` through the animation
   panel, even when that panel was hidden. Empty animation lists caused a PATCH
   of the entire source Design. Geometry invalidation then started a full assembly
   rebuild. This explains a rebuild completing later during apparent idle time.
2. Multiple panels independently fetched the same large source Designs. The cold
   baseline made 21 Design GETs for seven parts. Selecting parts added more GETs
   and unsolicited Design PATCHes. The busy popup was reporting real redundant
   work, rather than causing the delay itself.
3. The shared renderer refetched all assembly coordinates and discarded every
   source mesh on rebuild, including representation-only changes. Invalidation
   also launched unawaited rebuilds, multiplying some explicit refreshes.
4. Curved indexed sweep axes repeatedly rebuilt the same interpolation table at
   every sample. Backend cache hits also repacked compact geometry, and editing
   one source evicted unrelated sources. Feature seeking prewarmed a different
   cache key from the geometry read path.
5. Changing color modes rebuilt the complete molecular geometry into a temporary
   group just to copy its colors. On this Benchy, that took 10.39 seconds and
   included a 7.95-second main-thread task. The same redundant work ran when a
   source was first built.

## Changes

Passive part selection is read-only. Base Design requests share a document- and
source-version-aware cache; stale selection responses cannot retarget panels.
Selection changes repaint existing assembly rows. Explicit animation creation
remains available through the New animation action.
During a forced refresh, retained authoring callbacks cannot write an old Design;
repeated selection shares that refresh and null results permit a clean retry.

The shared renderer retains unaffected meshes and decoded coordinates, rebuilds
changed representations locally, refetches changed sources, and serializes and
coalesces refreshes. Exiting assembly mode invalidates pending builds. Runtime
source versions stay out of saved assembly data.

Color changes now repaint retained nucleotide color textures, cylinder interval
colors, and recorded curved-tube vertex spans. They preserve mesh identities,
coordinates, selection alpha, crossover endpoint ownership, and the existing
strand/base/cluster/overhang palettes. No temporary molecular geometry is built.

Native indexed sweep axis samples use the existing frame evaluator in a batch;
other deformation stacks retain their previous path. Cached compact wire payloads
are reused, source invalidation is targeted, and seek/read cache keys agree.
Molecular placement constants and authored geometry are unchanged.

## Native coordinate parity and axis timing

The actual hull and deck/roof files were evaluated using both the previous scalar
frame loop and the batched evaluator. Every output coordinate and the complete
JSON structure matched exactly; the maximum coordinate difference was 0 nm.

| Source | Helices | Axis points | Previous loop | Batched | Speedup |
|---|---:|---:|---:|---:|---:|
| Hull | 289 | 11,817 | 20.54 s | 0.402 s | 51.0× |
| Deck/roof | 893 | 6,650 | 5.04 s | 0.687 s | 7.3× |

Source hashes were unchanged. Evidence: `indexed_axes_benchmark.json` and the
reproducible `benchmark_indexed_axes.py` in the artifact directory.

## Measurement method and limits

The initial baseline opened in Cylinders because NADOC's assembly load policy
forces that representation. Its network trace proves the selection mutation and
rebuild chain independently of representation. Cold open took 123.98 seconds;
selection eventually produced another full geometry request and a rebuild during
the 70-second idle interval. Its browser used SwiftShader, so baseline frame and
click timings are **not** a hardware performance comparison.

The final live run explicitly switches the seven parts to Full through the real
representation menu. Chromium uses Mesa D3D12 on the NVIDIA RTX 2080 SUPER at a
1440 × 1000 browser viewport. The audit records per-source close-LOD mesh counts,
Full representation state, rendered primitive counts, frame intervals, actual
mouse interactions, API traffic, busy popups, and rebuild completions. The orbit
test uses the actual scene canvas and asserts that the camera moved. Render FPS
uses the renderer's frame counter, independently of the rAF interval observer.

## Final live results

All seven sources remained at Full close LOD: **462,002 nucleotides,
91,752,688 triangles**, 35 draw calls before selection overlays (37 afterward).
The browser reported no page errors or failed requests. All native source-file
hash assertions passed.

| Operation | Action completion | Two-frame paint | Geometry rebuilds | Busy overlay |
|---|---:|---:|---:|---|
| Select/reselect/deselect in part list (5 actions) | 79–449 ms | 183–496 ms | 0 | None |
| Select through actual canvas pick | 64 ms | 274 ms | 0 | None |
| Hide / show smokestack | 73 / 74 ms | 158 / 142 ms | 0 | None |
| Change color mode to Cluster | 290 ms | 412 ms | 0 | None |
| Request Full when already Full | 4 ms | 64 ms | 0 | None |
| Three sidebar changes | 1,095 ms total¹ | 1,140 ms | 0 | None |
| Actual orbit and zoom gesture | 746 ms total² | 802 ms | 0 | None |
| Idle for at least 70 seconds | 32.0 rendered fps | 33.4 ms frame interval p95 | 0 | None |

¹ Includes three intentional 300 ms waits. ² Includes a ten-step mouse drag,
wheel input, and an intentional 250 ms wait; it is a gesture duration, not input
latency. Idle had two long tasks, maximum 355 ms. Ordinary actions still have
occasional subsecond main-thread work; the final run does not claim zero jank.

The color action previously took **10.39 seconds** in the intermediate Full GPU
run on the same device. Direct repaint reduced it to **0.29 seconds**. The maximum
color-change long task fell from 7,948 ms to 288 ms.

The complete run made **seven base Design GETs**, down from 21 in the initial
trace, and **one nucleotide assembly geometry GET**, during startup only. There
were **zero part-Design PATCHes** and no nucleotide geometry requests during
selection, visibility, color changes, representation switches or idle. Visibility
and representation updates used their intended assembly-instance PATCH routes.

## Remaining performance limits

Cold opening to the default Cylinders representation still took **69.71 seconds**;
the subsequent first Full build took **22.60 seconds**. Full → Cylinders took
**14.24 seconds**, and Cylinders → Full **21.95 seconds**. These explicit changes
each rebuilt meshes once using retained nucleotide coordinates. The largest
main-thread task during the latter was 6.43 seconds. This patch fixes unexpected
work on basic actions; it does **not** make cold opening or mesh construction
instantaneous. Existing protein-accessory queries still run on actual source
rebuilds, including empty results for this Benchy.

The cold geometry request took about 48 seconds including connection scheduling
and transfer. Read-only inspection found one native nucleotide generation per
unique source; the recorded request overlaps source Design reads, readiness and
library listing. That timing is not an isolated geometry CPU profile. Further
work should profile source parsing, native generation, packing, compression and
mesh construction separately; see `cold_geometry_readonly_audit.json`.

Evidence: `final_gpu_events.json`, `final_gpu_audit.json`,
`final_gpu_summary.json`, `final_gpu_source_hashes.json`,
`final_gpu_full.png`, and `final_gpu_after.png`. The operation runner closes its
document/browser and deletes its exact temporary workspace copy in `finally`.

## Automated validation

The full frontend suite passed: **676 files, 7,917 tests passed, 1 skipped**
(310.86 seconds). A subsequent review caught the forced-refresh authoring race;
after fixing it and adding three regressions, the six affected context/cache/
renderer test files passed again: **33 tests passed**. This final focused run is
recorded separately from the full-suite count.

`just smoke` passed **23 tests** in 2.5 minutes, including console-error,
assembly-exit and loaded-design close-session teardown gates. The native Full
placement review gate is clear, and `git diff --check` passes. Ruff passes on all
changed Python files. Repository-wide `just lint` still reports two existing
unused imports in `backend/api/vr_prompts.py` and
`tests/test_cpd_cube_validation_v6.py`; both files match git HEAD exactly, so the
lint delta is zero.

Final cleanup verified no test-prefixed workspace/session artifacts, no retained
benchmark document, and no isolated smoke servers. All nine original Benchy
assembly/part/monolithic files have their pre-test hashes. Useful evidence stays
under `.development-artifacts/benchy-full-performance/`; see
`final_cleanup_and_source_integrity.json` and `lint_baseline_identity.json`.

## Backend validation and existing suite failures

The 48 focused backend tests passed: compact cache reuse, targeted invalidation,
seek/read cache parity, scalar/batched sweep axis parity, sweep orientation and
native display placement. The native placement review gate remains required for
these changes; scientific constants and placement formulas were not changed.

`just test-smart` selected **FAST**. Result: **10,542 passed, 22 failed,
21 skipped, 4 collection errors**, 186.87 seconds of pytest time (204 seconds
including the guard). The broad suite is not green in this checkout:

- Ten failures require the missing native VR viewer binary; one requires a
  supported VR host rather than WSL.
- Seven failures require an absent archived CPD review packet. Four collection
  errors are the same missing CPD assembly fixture on four workers.
- The remaining four failures concern a trajectory header expectation, two
  junction-balance tolerances, and a CPD preview snapshot. A separate process
  imported all four edited backend modules from the original git HEAD and
  reproduced all four failures with the same signatures. No checkout or app
  files were changed for that replay.

The aggregate timing warning was triaged using
`.claude/skills/triage-slow-tests/SKILL.md`: zero tests exceeded the 5-second
per-test budget (slowest 4.57 seconds). The report contained 639.8 seconds of
summed work across 10,585 tests, about 60 ms/test, run on four workers. No test
reclassification or budget change was justified. Detailed evidence is in
`backend_failure_triage.json`, `backend_slow_candidates_snapshot.json`,
`backend_unchanged_failure_sources.json`, and `head_failure_replay.log`.

The test selector's deferred notice was:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

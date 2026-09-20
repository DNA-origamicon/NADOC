# Production viewer A/B — 2026-09-20

**Current static Voltron checkpoint passes the initial performance gates.** There is no material
regression in typical FPS, p95 frame interval, file-open workflow time, or sampled heap.
This covers the first decoder extraction plus diagnostics, not a completed standalone viewer.
It is a bounded engineering comparison, not a statistical proof of equivalence or a Zoom benchmark.

## Controlled workload

- Real visible Windows Chrome 153, NVIDIA RTX 2080 SUPER; production builds, canvas 1272 × 833, DPR 1.
- Full representation (detail 0), strand coloring; atomistic and surface off. Same saved camera and multiscale orbit.
- One browser renderer at a time, isolated backend/workspace per build. ABBAABBAAB order;
  fresh page and native file open each visit, 5-second settle, then 20-second warmup and
  20-second measured repeatable orbit. Five measured runs per build, 100 seconds each.
- Warm browser/filesystem caches preflighted on both builds. Screenshots taken outside timing.
- Frozen baseline commit: `cce80858ff528a2648cba3f18351685f75dc673c`, with equivalent diagnostics added.
  Baseline API decoder remains original; candidate uses extracted decoder. Both builds are marked dirty
  because diagnostics are uncommitted. Frontend source hashes distinguish the actual builds:
  A `8c0c3afabaecec6db378f99c34804209cd397c3e0227e76d0ae469ccee2fbfa5`;
  B `9c963f70da5253440c0a80d7729b440f90a9831704d21dd1593f85c2c7f8bddd`.
- Native source `workspace/VoltronCoreArmV2.nadoc`, SHA-256
  `f0c03351c3962b6a50ae96e7e8cfb5e6722701572be36d9aca3b85df066148f6`.
  Runtime document hash matches across every capture:
  `7afd7103269830f4bf25a5ccd93551b664c6e4e123b3f250e215ce30d7f46561`.
  This hash does not cover simulation content.

## Primary results

Medians across the five measured runs, except explicitly labeled maxima/totals:

| Metric | Baseline A | Candidate B | Change |
|---|---:|---:|---:|
| Mean FPS | 42.34 | 42.78 | +1.03% |
| p95 frame interval | 26.0 ms | 26.6 ms | +2.31% |
| p99 frame interval | 29.2 ms | 29.3 ms | +0.34% |
| File-open workflow | 5574.5 ms | 5641.8 ms | +1.21% |
| Sampled peak JS heap | 792.3 MB | 772.4 MB | -2.52% |
| Maximum sampled heap across runs | 1097.2 MB | 1203.6 MB | +9.69% |
| Frames >33 ms / all frames | 26 / 4210 | 61 / 4243 | tail observation |
| Frames >50 ms | 2 | 3 | tail observation |
| Worst frame interval | 64.4 ms | 75.7 ms | tail observation |

Frame intervals measure the render loop, not GPU time or input-to-photon latency.
Heap is approximate `performance.memory` sampling, sensitive to garbage collection and browser-process
lifetime; it is neither retained-memory/leak analysis nor GPU memory. File-open time ends at normal
application workflow completion; auxiliary assets can continue settling. It is not cold startup or
complete-scene readiness. Resource counts were checked after settling.

Initial gates investigate repeatable p95 regression exceeding both 10% and 1 ms,
load regression exceeding both 10% and 100 ms, and sampled peak heap regression over 10%.
Primary medians pass; the maximum sampled heap comparison also remains below 10%, but is noisy.
No invalid run, context-loss flag, or camera/control restoration failure occurred. This does not close
unmeasured picking, trajectory, load-readiness, or long-session memory gates.

## Tail behavior and confirmation

Candidate had more >33 ms intervals, concentrated in visit 6; that run is retained below.
No measured frame reached 100 ms. After observing the tail, a separate reverse-order BA pair
was run under the same conditions; it does not replace or selectively alter the primary results.

Confirmation: B 42.78 FPS, p95 26.1 ms;
A 44.02 FPS, p95 25.6 ms.
B had one 51.2 ms frame and p99 38.1 ms;
A worst was 42.5 ms and p99 30.1 ms.
The sustained p95 spike did not repeat; rare candidate tails remain an observation, not a proven
absence of jitter. Continue to track them at subsequent extraction checkpoints.

| Visit | Build | FPS | p95 ms | p99 ms | Worst ms | Frames >50 ms |
|---|---|---:|---:|---:|---:|---:|
| 1 | A | 41.62 | 28.1 | 38.1 | 60.9 | 1 |
| 2 | B | 42.78 | 26.6 | 29.3 | 34.1 | 0 |
| 3 | B | 43.04 | 27.3 | 37.7 | 75.7 | 1 |
| 4 | A | 40.43 | 28.5 | 33.2 | 46.6 | 0 |
| 5 | A | 42.34 | 26.0 | 29.2 | 31.0 | 0 |
| 6 | B | 40.52 | 34.1 | 42.4 | 70.7 | 2 |
| 7 | B | 43.37 | 25.3 | 27.4 | 30.1 | 0 |
| 8 | A | 43.15 | 25.4 | 27.6 | 64.4 | 1 |
| 9 | A | 42.90 | 25.8 | 27.9 | 31.1 | 0 |
| 10 | B | 42.34 | 26.3 | 29.3 | 33.7 | 0 |

## Visual and lifecycle evidence

All 20 primary and four confirmation before/after canvas PNGs are byte-identical:
`08904acfd9eb78eeb90176d0db405b1363f843456e2fd0b7912485fe565c2355`.
The captured overview was visually inspected and includes the attached particle and protein structure.
Pixel identity proves equivalence at this restored overview pose; it does not prove correctness of
all intermediate orbit frames, close-up molecular content, picking, or other representations.
Every measured last frame reports 2,677 calls, 6,069,870 triangles, 30,503 lines,
1,711 geometries and 195 textures. Camera and controls restore after each capture.
Both batches successfully return to the original editor and reopen Voltron.

## Reproduction, evidence, and limits

Use [the performance manual](../../viewer_performance_manual.md) and `scripts/viewer_ab.mjs`.
[Raw primary records](comparison.json), [machine-readable summary](summary.json),
[baseline records](A.json), [candidate records](B.json), and
[separate confirmation](../viewer_ab_production_20260920_confirmation/comparison.json) are retained.
The confirmation raw scope string inherited “ABBA”; its authoritative visits show the actual BA order.

Validation after the testing-tool changes: 6,672 frontend tests across 471 files, 23 smoke checks,
both production builds, and repository lint passed. Existing build chunk-size warning remains.
No renderer/scientific geometry changes or new `main.js` lines were introduced in this comparison step.

Still required before sharing a production experience: prepared standalone package parity;
large assemblies; cube_pore recorded Full/atomistic trajectories and graphene/ion content;
selection/highlight latency; long-session memory; guest hardware/browser matrix; four-client
meeting traffic, follow/jump behavior, loading and reconnection. No meeting room or Zoom stream
was exercised. These results authorize continuing extraction, not releasing the presentation feature.

Isolated benchmark listeners on 8020/8021/5180/5181 are stopped after testing; the user's
8000/5173 editor is preserved. Disposable candidate workspace is removed. The frozen baseline
worktree and fixture copies are retained outside the user's workspace for future comparisons.
Cleanup verification found no prefixed workspace test artifacts and no project stores modified
since before this smoke run. Older test-named project histories were left untouched. The original
Voltron source checksum is unchanged, and a final browser inspection confirms the original editor
document, visible Voltron, enabled controls, and closed Process Log.

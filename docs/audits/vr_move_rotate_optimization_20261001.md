# Selected-part Move/Rotate optimization — 2026-10-01

The native selected-part preview now caches packed instances and endpoint weights
when selection/style changes. During a drag it transforms indexed instances,
updates bounds, and streams affected instance buffers without rebuilding semantic
ownership, colors, object IDs or highlight membership. Full, Stick, Ball & Stick
and VDW use this path. Other representations and visualized slab frames retain
the existing rebuild path.

## Budget results

Same 24-helix/76-strand snapshots and RTX 3080 Ti as the
[baseline investigation](vr_move_rotate_performance_20261001.md). Values below
use the worse of translation and rotation. Each case has five warmup frames and
40 measured frames. Selection remains highlighted throughout stationary and
moving comparisons.

| Representation | One base: median update ms | One base: p95 update + draw ms | Cluster: median update ms | Cluster: p95 update + draw ms |
| --- | ---: | ---: | ---: | ---: |
| Full | 0.19 | 2.21 | 0.49 | 2.40 |
| Stick | 0.72 | 8.62 | 2.42 | 14.09 |
| Ball & Stick | 1.08 | 9.59 | 3.92 | 16.49 |
| VDW | 0.35 | 2.43 | 1.00 | 3.43 |

Full's baseline updates were 19 ms for one base and 37–38 ms for the cluster.
Ball & Stick was 294–295 ms for one base and 630–632 ms for the cluster.

**Full has substantial headroom below 11.1 ms in the controlled rendering test.**
VDW and small Stick/Ball & Stick selections also fit. Large Stick/Ball & Stick
selections do not yet meet that budget with the current draw workload.

The complete timing columns serialize update plus the production shadow pass and
two 1852×2056 eye-sized draws, waiting for the GPU only in this diagnostic. They
exclude XR/UI/event work and are not a promise of physical headset FPS. The
projection is fixed, broadside, and identical between runs. Capture happens
outside the timed interval. No shadow, lighting, radii, detail or controller-speed
settings were reduced.

## Remaining atomistic cost

Cluster GPU-draw p95 is 10.98 ms for Stick and 11.93 ms for Ball & Stick in this
view, before preview update or other application work. Highlighting a large
selection adds a second set of enlarged translucent primitives. The residual
cluster bottleneck therefore includes rendering itself, not just CPU transforms.

The current optimization still uploads a complete affected channel; unchanged
instances in that channel retain their packed bytes. Orphaning GL storage avoids
waiting on the previous draw. A future GPU preview transform/weight path could
remove most of the 2–5 ms atomistic cluster CPU/upload cost. Ball & Stick's draw
cost alone can exceed 11.1 ms, so equivalent-output GPU work on shadow/highlight
passes would also be needed for a dependable large-selection budget. These
measurements establish feasibility for small selections and VDW, not a universal
90 Hz guarantee for all atomistic views or model sizes.

Selection/style changes and commit still build a fresh cache once and can hitch;
this change targets continuously changing preview transforms. Peak cache storage
is bounded to the displayed representation and one owner. It stores original and
current packed instances plus affected indices. Representation/scene replacement,
color/highlight changes, commit and undo invalidate or rebuild it. Coordinate-only
trajectory playback falls back to the general style path while a preview cache
is active, avoiding stale cached positions. This is not a trajectory optimization.

## Correctness and reproduction

`native/vr_viewer/src/rigid_preview.hpp` owns the packed cache; `GlScene` retains
source-space semantic transforms for picking and handles. Boundary bonds keep
independent start/end weights. Every frame starts from committed-pose instances,
so repeated drags do not accumulate floating-point motion. Exact bounds are
recomputed without identity/ownership lookups. Cancel restores committed poses.

`nadoc-vr-rigid-preview-test` compares the new renderer against the unchanged
rebuild algorithm, including partial endpoint weights, a 180° turn, highlights,
depth, picking, invalid owners, Cancel, commit, subsequent edits, VDW switching,
owner changes, Undo and scene replacement. The old path is selectable only by
this test build. CTest passes, as do the move-panel and staged-representation
checks; the coordinate-playback executable passes. The tour-catalog suite passes
31 tests.

All **32 real-scene rendered frames are byte-for-byte identical** to the baseline.
Evidence: `.development-artifacts/vr-move-optimized-20261001/`, including
`timing.json`, `baseline-pixel-comparison.json`, complete PNG frames and per-case
logs. Baseline evidence remains in `vr-move-performance-20261001/`.

The reusable correctness check is registered at **Debug → VR Tours & Tests →
Tools · Authoring → Move / Rotate · renderer regression**. Saved-scene profiling:

```sh
uv run python -m tools.vr_workflows.move_preview_check \
  --scene-dir .development-artifacts/vr-split-20260930 \
  --output .development-artifacts/vr-move-preview/new-run
```

The existing live Move/Rotate tour initially failed before editing because it
sent menu input during the early startup screen, where controller processing is
intentionally suspended. Three retained failures distinguish the original missing
poses, the insufficient pose-only fix, and the explicit invalid-pose assertion.
The harness now waits for startup completion and sets owned simulated poses before
opening menus. The unchanged `steady_fast` base edit/commit/Undo/save/reopen tour
then passed in `vr-move-optimized-live-ready/`. It uses a generated private design,
not the user's document. Test cleanup removed the temporary workspace artifacts.
The failed runs remain available under `vr-move-optimized-live-{smoke,retry,poses}/`.

Four-profile validation and compositor evidence are recorded separately under
`.development-artifacts/vr-move-optimized-validation/`.

## Final live validation

The first matrix passed `steady_fast`, then `steady_deliberate` exceeded the
unchanged 150 ms input-replay deadline at 162 ms. That failure remains in
`vr-move-optimized-validation/profiles/`. Validation had been running Chromium
headless with Playwright's forced focus, keeping the competing desktop renderer
active. The physical Move/Rotate tour now runs headed and disables focus emulation,
matching the established native representation-motion harness. Production browser
rendering policy, input sampling, seeds, motion profiles and deadlines are unchanged.

The corrected matrix in `vr-move-optimized-live-focused/profiles/` passes all four
profiles for a **Full single-base edit on the generated small test part**:
trigger translation/rotation, exact edit scope, stereo moved-target/unchanged-neighbor
pixels, commit, desktop feature log, Undo, save and reopen. This is separate from
the 24-helix renderer benchmark and does not claim live atomistic validation.

| Profile | Compositor samples during edit | GPU p95 ms | Repeated / dropped |
| --- | ---: | ---: | ---: |
| steady_fast | 72 | 1.73 | 0 / 0 |
| steady_deliberate | 188 | 1.96 | 0 / 0 |
| variable_fast | 72 | 2.51 | 0 / 0 |
| variable_deliberate | 188 | 1.90 | 0 / 0 |

All 520 interval samples were fresh, with GPU maximum 6.93 ms. SteamVR sampling
uses polling wall timestamps with approximately 100 ms boundary uncertainty;
`compositor-summary.json` retains exact intervals and counts. Captures are outside
these motion intervals. The actual submitted mirror contains the visible part;
both-eye geometry checks show the selected base moving 11–13 cm while over 1,100
other visible primitives remain fixed. Physical through-lens comfort is not measured.

All owned viewers, browser contexts and private test workspaces were cleaned up.
SteamVR remains running; no runtime settings or user documents were modified.

## Full-sized live follow-up

[The 24HB versus 6HB live comparison](vr_move_rotate_24hb_live_20261001.md)
confirms 24HB Full single-base drag GPU p95 of 3.27–4.26 ms, with occasional
frame-delivery hitches on both model sizes. It also records an unresolved
24HB Undo-after-save failure and the observation/setup differences. The original
atomistic benchmark above already used this 24HB model.

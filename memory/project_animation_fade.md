---
name: Animation fade ("this is how I made this")
description: Per-bp-range fade granularity for beads/slabs/cones/cylinders/axis sticks during keyframe playback; lessons from teeth.nadoc debugging
type: project
originSessionId: 9f1bf930-958e-498b-bcf5-3b65f7fbdd52
---
## What

Animations now fade in/out elements (strands, helices, axis sticks, helix shaft cylinders, beads, slabs, cones, axis arrow segments) when keyframes reference different `feature_log` indices. Implemented in `frontend/src/scene/helix_renderer.js` `applyPositionLerp(fromBaked, toBaked, t, excludeHelixIds, fadeOpts)`. Fade is **scale-based** (collapse instances to a point when invisible) — InstancedMesh has no per-instance opacity infrastructure.

## Granularity hierarchy (each level finer than the last)

1. **Per-strand / per-helix sets** (`fadeOpts.revealInStrandIds` / `revealInHelixIds`) — too coarse for continuation extrudes (same `strand_id`, same `helix_id`, just more bps).
2. **Per-domain (per `RoutingClusterLogEntry` child)** — better, but still too coarse when a single scaffold domain spans the whole helix (e.g. teeth.nadoc).
3. **Per-bp-range coverage** ✅ — for each render element, check which actual bp_indices exist in `fromPosMap` / `toPosMap` for the element's helix, and use the covered subrange to position+scale.

## Implementation per element type

| Element | Fade source | Notes |
|---------|-------------|-------|
| Backbone beads | `(helix_id, bp_index, direction)` key in fromPosMap/toPosMap | Per-nuc; pre-existing → 1, to-only → t, from-only → 1-t, neither → 0. |
| Slabs | Same per-nuc key in fromBnMap/toBnMap | Same treatment. |
| Cones | Both endpoint nucs' presence in posMaps | Cone exists iff both endpoints exist. |
| Helix shaft cylinders (`_domainCylData` etc.) | Per-domain `bp_lo`/`bp_hi` via `_segFadeFor` (any-bp-in-range) | `bp_lo`/`bp_hi` captured at scene-build from domain's `[min(start_bp,end_bp), max(...)]`. Falls back to per-strand+per-helix if `bp_lo`/`bp_hi` missing. |
| Axis stick segments | **Per-bp-range subrange** via `_coveredBpRange` + `_projectBpRange` | Each segment positioned + scaled per frame to span actual covered subrange on each side, lerped between sides. |
| Axis arrow shaft (curved helices) | Per-helix bp presence | Single tube; can't be split. Existing opacity transition between curved and straight kept. |

## Critical gotchas

1. **Default cluster includes ALL helices.** The `_isExcluded(helixId)` check from `excludeHelixIds` (cluster-owned helices) returns true for nearly every helix on a typical design. v1 of the fade code skipped all logic for excluded entries — fade was never applied. Fix: apply scale fade even for excluded entries; only skip when `fade === 1` (so cluster transform's matrix is preserved).
2. **`applyClusterTransform` writes position + quaternion, never scale.** So per-element scale fade must be written independently. For `seg.mesh` (axis segments), this means scale fade always runs even when excluded.
3. **Per-bp coverage is too permissive when a domain spans the whole helix.** `_segCovers([0..100]) && _segCovers([0..30])` returns 1 because bp 0 is in both — fade=1 → segment renders full bp 0–100 at t=0. The fix is `_coveredBpRange` (find actual `[lo, hi]` of populated bps) + `_projectBpRange` (position segment along axis using `arrow.bpStart + BDNA_RISE_PER_BP`), then lerp endpoints between sides.
4. **`arrow.segments[]` is captured at scene-build time.** Reflects the LATEST design state (post-mutation). Animating to an earlier feature_log index, segments may include bp ranges where no nucs exist on that side — must hide them via `_coveredBpRange` returning null.
5. **Continuation extrudes extend existing strands.** `strand_id` and `helix_id` stay the same; only the bp range grows. Per-strand and per-helix fade both return 1 — invisible to those checks. Per-bp-range catches it.

## Snapshot integration

Geometry-batch (`/design/geometry-batch`) goes through `_seek_feature_log` → `_seek_snapshot_base`, so the `posMap`/`axesMap`/`bnMap` baked into each animation keyframe **already** comes from snapshot-hydrated design state. No additional snapshot wiring needed in the player. Direct client-side snapshot decode would be a refactor (would need to port `_geometry_for_design` to JS) and only saves the network round-trip — doesn't change visible behavior.

## Commits (feature-log-update branch, 2026-05-02)

- `c9b5df7` — initial per-strand/per-helix scale fade
- `fe5a599` — apply fade scale even to cluster-excluded helices (default-cluster bug)
- `c771d2f` — helix shaft cylinders fade
- `7f6dc2f` — per-nuc fade for beads/slabs/cones (handles continuation extrudes)
- `0ef2f98` — initial per-domain fade for axis stick segments
- `4803ba7` — per-domain fade for cylinders (`bp_lo`/`bp_hi` captured at scene build)
- `860ee17` — **per-bp-range axis stick recomputation** (covered subrange + projected endpoints; current state)

## Verification

- Backend: `uv run pytest tests/test_animation.py tests/test_feature_log_clusters.py tests/test_feature_log_snapshot.py -q` → 39 passed.
- Visual test: teeth.nadoc, 5 extrude features. Axis sticks should grow along the helix as bps appear, not jump to full length at t=0.

---
name: Domain-ends refactor — complete architecture and known quirks
description: Coverage-map domain-end detection system replacing blunt_ends.js; post-Apply snap bug root cause and fix; shaft ownership
type: project
originSessionId: b9e1d3af-a80f-454f-b4b3-cfc80c55c3bb
---
## Status (2026-04-26, kinematics-cleanup) — COMPLETE

Full hard refactor of the blunt-end / helix-label system shipped. `blunt_ends.js` deleted.
`domain_ends.js` owns rings, labels, AND shaft cylinders for overhang domains.
`helix_renderer.js` `shaftsInfo`/`applyDomainShaftTransforms`/`_cbShafts` fully removed.

**Why:** The old 4-loop algorithm (free endpoints, interior termini, overhang crossover junctions, shared stubs) had ad-hoc special cases, encoded fields (`sourceBp`, `offsetNm`, `physicsBp`), and a parallel transform system. The result was wrong label counts for multi-domain overhang helices (OHtest2: 3 labels for 4 domain ends).

---

## New detection algorithm (`_computeDomainEnds`)

Coverage-map scan: for each domain endpoint `bp ∈ {lo, hi}`:
```
hasPlus  = covMap["helixId:dir"].has(bp + 1)
hasMinus = covMap["helixId:dir"].has(bp - 1)
isDomainEnd = hasPlus XOR hasMinus   // nick = both; isolated = neither; skip both
openSide = hasPlus ? -1 : +1
diskBp   = bp + openSide
```
Staple suppression: skip if `scaffoldCovMap[helix_id].has(diskBp)` (scaffold on open side).  
Dedup key: `"helixId:diskBp"` — multiple strand directions producing the same gap → one ring.  
Transform key: `overhangId ?? helixId` — per-domain isolation during overhang gizmo drag.

---

## Post-Apply snap bug (shared stub helix) — ROOT CAUSE + FIX

**Symptom:** After clicking Apply on overhang rotation, rings snapped back to unrotated positions despite preview showing correct positions.

**Root cause:** A stub helix hosting TWO overhang domains (e.g. `h_XY_1_0` with domains at bps 0–9 and 32–41) has only 2 axis samples from the no-deformations path: `[bp=0, bp=42]`. `_apply_ovhg_rotations_to_axes` only rotates samples where `domain_min ≤ sample_bp ≤ domain_max`. For domain [32, 41] with samples at bp 0 and bp 42: **neither sample is in range**, so `new_samples = unchanged`. The main `ax["start"]/ax["end"]` remain unrotated. `_rebuild` in `domain_ends.js` then called `_axisPoint(h, axDef, diskBp)` using those unrotated positions → wrong rings.

**Fix:** Use `axDef.ovhgAxes[overhangId]` (per-domain rotated axis, always computed by backend regardless of rotation magnitude) for overhang ring/label positioning:

```js
// domain_ends.js _rebuild():
const ovhgAx = rec.overhangId ? (axDef?.ovhgAxes?.[rec.overhangId] ?? null) : null
const diskPos = ovhgAx ? _axisPointOvhg(ovhgAx, rec.diskBp) : _axisPoint(h, axDef, rec.diskBp)
```

**`ovhg_axes` format** (from backend): `{bp_min, bp_max, start:[x,y,z], end:[x,y,z]}`  
- `start` = axis position at `bp_min`  
- `end` = axis position at `bp_max + 1` (one bp BEYOND domain end)  
- Always populated for all overhangs by `_apply_ovhg_rotations_to_axes`, even identity rotation

**`_axisPointOvhg` formula:**  
```js
const bpSpan = ovhgAx.bp_max - ovhgAx.bp_min + 1
const t = (bp - ovhgAx.bp_min) / bpSpan
// t=0 → start (bp_min), t=1 → end (bp_max+1), extrapolates for diskBp outside domain
```

**Small positional discrepancy:** Backend uses `/length_bp` denominator; frontend uses `/(physLen-1)`. Both initial and post-Apply calls use the same formula, so the preview and apply positions match exactly — only a fraction-of-nm offset from what the backbone bead formula would give.

---

## Shaft ownership (Part 3 of refactor)

**Before:** Shaft cylinders for overhang domains lived in `helix_renderer.js` under `shaftsInfo` + `applyDomainShaftTransforms` + `_cbShafts`. Required separate call in `main.js` after ring transforms.

**After:** Domain_ends.js creates one `THREE.CylinderGeometry` per unique `overhangId` using `ovhgAx.start → ovhgAx.end`. Shaft shortened by `SHAFT_HEAD = 0.55 nm` for last domain (leaves room for helix_renderer's arrowhead cone). Transform key = `overhangId` — same as rings, so `captureClusterBase`/`applyClusterTransform` handle rings + shafts in one call.

**Helix_renderer change:** When `axDef?.ovhgAxes` is present, shaft-loop intervals matching an ovhg entry are skipped with `continue` (no cylinder created — domain_ends.js owns it).

**main.js simplification:** `_helixShaftOps` Map and `helixCtrl.applyDomainShaftTransforms` calls removed from both `_ooPreviewIncrement` and gizmo `onPreview`.

---

## Files changed (full refactor)

| File | Change |
|------|--------|
| `frontend/src/scene/blunt_ends.js` | Deleted |
| `frontend/src/scene/domain_ends.js` | Created — full rewrite of detection + rendering |
| `frontend/src/scene/helix_renderer.js` | Removed `shaftsInfo`/`applyDomainShaftTransforms`/`_cbShafts`; skip ovhg intervals |
| `frontend/src/main.js` | Removed `_helixShaftOps` + `applyDomainShaftTransforms` calls |
| `scripts/blunt_ends_report.py` | Rewritten with `compute_domain_ends` (coverage-map algorithm) |
| `tests/test_blunt_ends.py` | Deleted |
| `tests/test_domain_ends.py` | Created — structural invariants + OHtest2 regression |

---

## All outstanding items resolved (2026-04-26)

1. **`_overhangCylData` shared-stub fix** — `helix_renderer.js`: loop now tracks `domIdx`; each entry stores `wsStart/wsEnd` from `ovhgAx.start/end`, `domainIndex`, `overhangId`. New `_cbOvhgCyls` map snapshots world-space endpoints in `captureClusterBase`. `applyClusterTransform` step 5 removed `!domainKeySet || forceAxes` guard; entries with `wsStart` rotate from snapshot (per-domain isolation); entries without `wsStart` fall back to `arrow.aStart/aEnd`. `applyDeformLerp` step 5b skips entries with `wsStart` (overhang stubs don't bend).

2. **`applyDeformLerp` t=0 overhang rings** — `domain_ends.js`: added `if (end.overhangId) continue` at top of the loop — overhang stubs don't participate in bend deformations; rings stay at current rotated position.

3. **`slice_plane.showAtEnd`** — added `showAtEnd(helixId, diskBp, continuation)` method that derives `plane` from helixId regex and `offsetNm` from `getHelixAxes()` + linear axis-point formula. main.js extrude handlers (both left-click and right-click) now call `slicePlane.showAtEnd(helixId, diskBp, true)`.

4. **Rename `_bluntInfo`/`_bluntCtxInfo`** — renamed to `_domainEndInfo`/`_domainEndCtxInfo` throughout `main.js`.

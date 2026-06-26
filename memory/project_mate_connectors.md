---
name: Mate connector alignment — overhang blunt ends
description: Status and known issues for assembly mate connector placement at overhang blunt ends after overhang rotation transforms
type: project
originSessionId: 292b0b35-a6b9-4693-be07-bd8f4db21d5a
---
Mate connectors at overhang blunt ends partially fixed (2026-04-29). Work is on `kinematics-cleanup` branch.

## Atomic create-mate endpoint (2026-05-19)
Mate creation used to fire **4 sequential round-trips** from `_alignAndAddJoint` (`assembly_joint_renderer.js`): `addInstanceConnector` ×2 → `propagateFk` → `addAssemblyJoint`. Each replaced `currentAssembly` and ran the renderer's store subscriber; the two connector-register responses carried an unchanged transform and snapped the live preview back to the stored pose ("moved three times" jank).

Now ONE round-trip: `POST /assembly/joints/create-mate` (`createMate()` in client.js). `_alignAndAddJoint` still computes the align transform on the frontend (reads live world connector frames) and passes child/parent connector specs + the moved-instance transform + joint params. Backend (`create_mate` in `backend/api/assembly.py`) registers blunt-end connectors (idempotent), runs FK to the aligned pose, composes the joint, and applies ONE feature-log mutation → ONE store update / ONE undo step.

Refactor: extracted `_propagate_fk_inplace(assembly, instance_id, transform_values, inst_by_id)` (shared by `propagate_fk` endpoint) and `_compose_add_joint(assembly, body) -> (new_assembly, joint, label, params)` (shared by `add_joint` endpoint) so the math isn't duplicated. New `op_kind='assembly-create-mate'` added to the `SnapshotOpKind` Literal in `models.py` (forgetting this = 500 in `_apply_assembly_mutation_with_feature_log`). Also paired with the frontend subscriber fix: the transform-only branch in `main.js` now pushes only instances whose transform actually changed (`_sameInstanceTransform`), so even multi-update flows don't reset a preview. Verified via probe: 1 store update (was 4), joint added, no snap-back.

## Shared-renderer path (2026-05-19, path-to-thousands)
On the shared-instancing renderer (`window.NADOC_SHARED_RENDERER`), `getInstanceBluntEnds()` was previously a stub `() => []`, so clicking **Define Mate** showed no gold connector indicators. Fixed by extracting the legacy ~210-line computation into a module-level pure helper `_computeInstanceBluntEnds(design, helixAxes, mat4, instId, instName)` and adding shared-path `getInstanceBluntEnds` / `getConnectorClusterId` / `getConnectorClusterIds` that iterate `_sources` (per-instance world matrix read from `srcEntry.xformData[i*16..]`). Removed those three from `_SHARED_RENDERER_STUB_DEFAULTS`. `_defineAssemblyMate()` in `main.js` feeds blunt ends directly into `assemblyJointRenderer.setExtraConnectors(...)` regardless of the ambient `bluntEnds` tool-filter (that filter is normal-view display only). Data path note: `getAssemblyGeometry()` passes `helix_axes` as a raw array (client.js), so the `Array.isArray` branch in `_setSourcesFromAssembly` runs `_convertHelixAxesArray`, which camelCases `ovhg_axes`→`ovhgAxes` (the field `_computeInstanceBluntEnds` reads). Verified via Playwright probe: 1-hinge fixture → non-empty connectors + 351 hit-meshes after Define Mate click.

## What was fixed (legacy path)
Three-part fix in `assembly_renderer.js` `getInstanceBluntEnds()`:

1. **Backend (`backend/api/assembly.py`):** Both `get_instance_geometry` and `get_assembly_geometry` now call `_apply_ovhg_rotations_to_axes(design, axes, nucleotides)` — previously the rotated ovhg axis data was never included in assembly geometry responses.

2. **`_axesArrayToMap` (`assembly_renderer.js` ~line 193):** Added `ovhgAxes: ax.ovhg_axes ?? null` — previously `ovhg_axes` was silently stripped when converting the array response to a map, so `buildHelixObjects` never received per-domain axis data for assembly instances.

3. **`getInstanceBluntEnds()` (`assembly_renderer.js` ~line 754):** Added `ovhgBpToPos` lookup built from `ax.ovhgAxes` entries. Used to:
   - Patch `localEps[h.id].start/end` for shared-inline stub helices whose endpoints coincide with an ovhgAx `bp_min`/`bp_max`.
   - Override `_posAlongHelix` in the interior strand termini section for overhang domain endpoints — uses the rotated ovhgAx position instead of interpolating along the unrotated stub axis.

For **extrude overhangs** `ax.start`/`ax.end` is updated directly by the backend; the new code is a no-op (extrude stubs have `ovhgAxes: null`).

## Known remaining issues

User confirmed unspecified issues remain. Suspected structural problems (not yet diagnosed):

- **Cache invalidation:** `_sourceKey` only changes when the source file/design changes, not when overhang rotations change on a cached part. After `patchOverhangRotationsBatch`, `entry.helixAxes` may be stale for that instance. Check whether `invalidateInstance` is called on the affected instance ID after an overhang rotation mutation.

- **Duplicate connectors on extrude stubs:** `_isFree` returns true for BOTH endpoints of an extrude overhang stub (neither coincides with a main-helix endpoint, since the attachment is a crossover at an interior bp, not a helix endpoint). This emits two connectors per extrude overhang — one at the free tip (correct) and one at the attachment side (redundant; overlaps with the crossover junction connector from the "overhang crossover junctions" section).

- **Normal direction for patched `localEps`:** When two ovhgAx domain endpoints patch `localEps[h.id].start` and `.end` for the same shared-inline stub, `localAxisDir = ep.end.clone().sub(ep.start)` gives the vector between two rotated domain positions rather than the per-domain axis direction. May produce slightly wrong connector normals on shared-inline stub helices.

- **Nick suppression may suppress valid overhang tips:** The interior strand termini section skips a strand endpoint at `bp` if `_cov.has(bp-1) && _cov.has(bp+1)`. For an overhang domain whose free tip is interior to the stub and is flanked by another domain on the stub, the tip could be incorrectly suppressed.

## Why/How to apply
**Why:** Assembly mate connectors must align with transformed overhang tips so parts can be correctly mated in the assembly view after overhang orientation adjustments.
**How to apply:** Before touching `getInstanceBluntEnds`, `setExtraConnectors`, or `_syncBluntConnIndicators`, read this file. Start investigation with the cache invalidation issue — check `_ooApply`/`_ooApplyDelta` in `main.js` to see if `assemblyRenderer.invalidateInstance(instId)` is called after `patchOverhangRotationsBatch`.

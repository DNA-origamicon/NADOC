---
name: deformation
description: Bend/twist deformation — preview/confirm flow, ghost meshes, lerp between straight and deformed.
paths:
  - "backend/core/deformation.py"
  - "frontend/src/scene/deformation_editor.js"
  - "frontend/src/scene/deform_view.js"
  - "frontend/src/ui/bend_twist_popup.js"
---

# deformation

## Architecture

## Entry & Initialization
- **Frontend**: `frontend/src/scene/deformation_editor.js`
- **Init**: `initDeformationEditor(scene, camera, canvas, controls, designRenderer, onExit)` — main.js ~line 822
- **Popup**: `frontend/src/ui/bend_twist_popup.js` — `initBendTwistPopup({onPreview, onConfirm, onCancel})` — main.js ~line 827
- **Backend**: `backend/core/deformation.py`

## State Machine
```
IDLE → AWAITING_A → A_PLACED → BOTH_PLANES_PLACED → confirm/cancel → IDLE
```
- Plane A = fixed reference; Plane B = mobile end
- Both placed → bend_twist_popup opens with angle/direction sliders
- `previewDeformation(params)` runs each slider change (no undo push)
- `confirmDeformation()` persists; `cancelDeformation()` reverts

## Store Keys
| Key | Semantics |
|-----|-----------|
| `deformToolActive` | Tool is active; selection manager disabled |
| `deformVisuActive` | Deformed geometry visible (lerp t=1); can toggle even without active tool |
| `straightGeometry` | Un-deformed geometry for lerp t=0 anchor |
| `straightHelixAxes` | Un-deformed helix axes for lerp t=0 anchor |

## API Endpoints
| Method | Path | Effect |
|--------|------|--------|
| `POST` | `/design/deformation` | Add op, push undo |
| `POST` | `/design/deformation?preview=true` | Add op, NO undo push; returns preview geometry |
| `PATCH` | `/design/deformation/{op_id}` | Update params only, NO undo push |
| `DELETE` | `/design/deformation/{op_id}` | Remove op, push undo |

## Feature-log revert/delete for bend/twist (Phase 1, 2026-06-12)
A bend/twist logs a lightweight `DeformationLogEntry` (delta entry, carries the
op — NOT a baked topology snapshot). The deformation is a geometric OVERLAY
applied at geometry time; topology is never bent.
- **Revert** (`POST /design/features/{i}/revert`) now accepts delta entries
  (deformation / cluster_op / overhang_rotation): it truncates the log to
  `[0..i-1]` and re-seeks via `_seek_feature_log`, rebuilding `design.deformations`
  WITHOUT this entry (and dropping every later entry) — same contract as snapshot
  revert. Empty-truncation routes through the `-2` (no-features) reset because
  `_seek_feature_log`'s empty-log fast path skips the overlay rebuild. Frontend ↶
  button lives on the deformation row in `feature_log_panel.js`.
- **Delete** (`DELETE /design/features/{i}`) already drops the op from
  `design.deformations` via replay; flat appends / bulk geometry un-bend correctly.
- **Phase 2 (SHIPPED 2026-06-14): primitive on a BENT face re-places on
  delete/edit of the bend.** `make_bundle_deformed_continuation` still BAKES
  deformed world-coords into the new helices, BUT the op is now REPLAYABLE:
  `BundleDeformedContinuationRequest.source_bp` is stored, and
  `_build_extrude_deformed_continuation` RECOMPUTES the frame from the live design
  at `source_bp` (`deformed_frame_at_bp`) instead of trusting the baked frame.
  `_rebuild_deformed_continuations(design)` (crud.py) forward-replays the log from
  the first deformed-continuation entry — folding deformation deltas into the
  evolving overlay, re-running DC + other replayable snapshot ops via
  `_edit_dispatch_run` (frames recomputed live), accepting baked post-state for
  non-replayable ops (auto-*/circle) — and rewrites the DC entries' baked
  snapshots. Called from `delete_feature` (deformation entry) and
  `_edit_deformation_feature`. With the bend gone/zeroed the recomputed frame is
  straight → the appended segment re-places flat. **Legacy DCs without source_bp
  re-run with their baked frame (no re-placement) — graceful degradation.**
  Frontend threads `source_bp` (= `continuationBp`): `blunt_end_menus.js` →
  `slice_plane.showDeformed/showPlacementDeformed` (`_deformedSourceBp`) →
  onPlace/onExtrude → `client.addBundleDeformedContinuation`. Tests:
  `tests/test_deformed_continuation_replace.py` (4) + `blunt_end_menus.test.js`
  pins the `sourceBp` arg. **Not handled:** a non-DC snapshot wedged BETWEEN two
  re-placed DCs keeps its stale baked helices (best-effort); slider-seek still
  shows baked (only delete/edit trigger the replay).

## Backend Files
- `backend/core/deformation.py` — `compute_bundle_centroid`, `world_frame_at`, `deformed_nucleotide_positions(helix, design)`, `deformed_helix_axes(design)`, `compute_bend_centers(design)`
- `backend/core/geometry.py` — transparent: calls `deformed_nucleotide_positions` when `design.deformations` non-empty
- `backend/core/models.py` — `DeformationOp`, `TwistParams`, `BendParams`
- `backend/core/periodic_polymer.py` — `derive_periodic_delta`, `closure_residual`, `solve_closing_curvature` (used by polymerize panel's snap-κ button)

## Bend parameterization (2026-05-28)
`BendParams.curvature_deg_per_bp` (κ) is the canonical bend storage — NOT a window-spanning angle. The bend's geometric semantics:
- κ applies inside `[plane_a_bp, plane_b_bp]` only. No auto-extension. Outside the planes, helices are straight.
- Visual bend between plane A and plane B = `κ × (plane_b − plane_a)`. The popup reads this back as the displayed "Angle" so the user-typed θ always matches what they see in the scene.
- Staggered helices: each helix's rotation = `κ × overlap_with_window`. Helices that don't fully span the window get partial rotation. For uniform rotation across stagger, move the planes to bracket the bundle's bp extrema.
- Polymer closure is a SEPARATE concern. Per-tile rotation (Kabsch δ) is roughly `κ × (seam_length − 1)` due to the straight +1 ligation step; it varies with stagger. The polymerize panel's "Snap κ to close" button calls `solve_closing_curvature` which probes the design and inverts the linear δ_rot(κ) relationship — gives exact closure regardless of stagger.

`_effective_bend_window(op, arm_helices)` exists in `deformation.py` but is a no-op (returns the typed planes). Kept for symmetry; future helpers can use it to introspect stagger zones for UI hints.

## CRITICAL Invariant
Every `Design(...)` constructor call in `backend/core/lattice.py` that rebuilds from an existing design **MUST** include `deformations=existing_design.deformations`. Missing this causes silent deformation loss after any topology mutation (nick, extrude).

Functions in lattice.py that rebuild Design: `make_bundle_segment`, `make_bundle_continuation`, `make_bundle_deformed_continuation`, `make_nick`, and others. Grep `Design(` in lattice.py when debugging.

## Canvas Event Priority
Deformation editor uses **capture-phase** listeners on canvas (main.js ~lines 119-143). These run BEFORE OrbitControls and selection_manager. If `deformPointerDown` returns `true`, the event is stopped — OrbitControls never sees it.

## Known Bug
Intermittent hard-to-reproduce bug: bend/twist geometry wrong after certain sequences of routing ops. Needs exhaustive combinatorial testing — see `RUNBOOK_DEFORMATION.md`.

## Cross-Feature Interactions
- `store.deformToolActive = true` → selection manager disabled (main.js gates canvas events)
- Preview op cleanup: `_previewOpId` must be deleted before `previewDeformation` creates new one
- `deformView.reapplyLerp()` must be called after physics off to restore deform state
- **Transient mutations don't auto-save / propagate to assemblies (2026-05-27):**
  `client.js::_syncFromDesignResponse(json, {transient})` sets `_designSyncTransient`
  (getter `wasLastDesignSyncTransient()`) during the setState. The design auto-save
  subscriber (main.js ~9272) reads it synchronously and SKIPS transient changes, so a
  bend/twist preview / live PATCH / cancel-revert never writes the file (→ SSE) or pushes
  the part to the assembly (→ `part-design-updated`). Tagged transient: `addDeformation`
  when `preview=true`, `updateDeformation` (always — preview + cancel-revert), and
  `deleteDeformation` when `preview=true`. COMMITS (`addDeformation` preview=false,
  `editFeature`) leave it false → they save → the assembly updates. Net effect: assemblies
  update ONLY on Apply; cancel / no-net-change does nothing. The flag resets to false at
  the end of every `_syncFromDesignResponse` so non-routed paths (undo / diff syncs) save.
  The RENDERER subscriber is NOT gated — previews still draw.

## Diagnostics → `RUNBOOK_DEFORMATION.md`

## Diagnostics

## Symptoms
- Bend/twist deformations disappear after a topology mutation (nick / extrude)
- "Structure appears straight" after topology mutation when deformations should be visible
- Ghost geometry stuck in scene after cancel/confirm
- Preview geometry not updating when slider moves
- deformVisuActive toggle has no visual effect

## First-Check Invariants

1. **Design rebuild includes deformations** — Every `Design(...)` constructor in `backend/core/lattice.py` that rebuilds from an existing design MUST include `deformations=existing_design.deformations`. Check by grepping `Design(` in `lattice.py`.

2. **Preview op lifecycle** — `_previewOpId` in `deformation_editor.js` must be deleted before `previewDeformation` creates a new one. If cleanup is missing, stale preview ops accumulate.

3. **straight geometry fetched** — `deformView` fetches `getStraightGeometry()` when design changes with deformations. If `straightGeometry` is null, lerp can't work.

## Diagnosis Tree

### Deformations vanish after topology mutation
1. Grep `Design(` in `backend/core/lattice.py`
2. Find the function called for that operation (e.g., `make_nick`, `make_bundle_segment`)
3. Check if `deformations=existing_design.deformations` is in the constructor call
4. If missing → add it. Also check: `cluster_transforms`, `overhangs`, `extensions` for same pattern.

### Ghost plane / preview overlay stuck in scene
1. Check `deformation_editor.js` confirm/cancel/exit paths
2. The plane ghosts `_ghostA`/`_ghostB` should be removed from scene (see `_removePlanes`)
3. The deform preview OVERLAY (committed solid `_frozenRoot` + translucent result) is
   torn down by `designRenderer.endDeformPreview()`, called from `_cancelPreview` (the
   universal teardown). If a frozen reference lingers, check that `_cancelPreview` ran.
4. If `confirmDeformation()` fails (API error), does cleanup still run?
NB (2026-05-27): the deform preview shows the COMMITTED design SOLID + a translucent
ghost of the deformed RESULT (`begin/endDeformPreview`, `PREVIEW_GHOST_OPACITY`=0.38).
The old straight "before-ghost" (opposite opacity) was replaced by this.

### Preview not responding to slider
1. Check `previewDeformation(params)` is called from `bend_twist_popup.js` `onPreview`
2. Check that `?preview=true` is set on the API call (new-deformation) or the op is PATCHed (edit)
3. Check that `store.currentGeometry` updates after preview API response

### deformVisuActive toggle has no effect
1. Check `deformView.js` subscription to `store.deformVisuActive`
2. `deformView.activate()` → fetches straight geometry + starts lerp
3. `deformView.deactivate()` → snaps to t=0 (straight)
4. If straight geometry is null, activate is a no-op

## Known Intermittent Bug
Hard-to-reproduce: bend/twist geometry wrong after certain sequences of routing operations. Interactions between deformation bp-index math and routing state (extrude_near/far, scaffold topology). Needs exhaustive combinatorial tests:
- Multiple bend plane positions (near end, 1/3, 1/2, 2/3, near far end)
- HC and SQ; different extrude amounts
- Verify both `deformed_nucleotide_positions` and `deformed_helix_axes`

## Files to Read
- `backend/core/lattice.py` — grep `Design(` for missing deformations field
- `backend/core/deformation.py` — `world_frame_at`, `deformed_nucleotide_positions`
- `frontend/src/scene/deformation_editor.js` — `_previewOpId`, cleanup paths
- `frontend/src/scene/deform_view.js` — `activate()`, `reapplyLerp()`

## Related
- `MAP_DEFORMATION.md` — tool architecture
- `REFERENCE_DEFORMATION_THEORY.md` — DTP-6 decisions, bend/twist theory


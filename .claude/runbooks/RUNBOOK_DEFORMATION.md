# deformation — diagnostics runbook
Loaded on demand from the `deformation` rule's Diagnostics pointer. Symptom → diagnosis content; not auto-loaded.

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

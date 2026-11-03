# Loop/skip and linker handling (2026-08-11) — supporting detail

[Topic head](../../project_reference_geometry.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Loop/skip and linker handling (2026-08-11)
The bulk **Add Loops/Skips** tool ignores reference-only, overhang, and virtual linker
helices. It neither generates nor clears marks on them, and ignores their transitions for the
required-crossover gate. Existing marks remain intact; mixed active/reference helices remain
active.

Zero-length ss linkers have one authoritative connector: the thick curved, strand-colored
tube owned by `overhang_link_arcs.js`. The generic crossover-record arc is suppressed for
the same linker-owned endpoint pair, removing the duplicate thin line. The retained tube
multiplies its base opacity by cluster and reference opacity (reference alpha 0.4), and is
fully hidden with depth writes disabled when reference geometry is hidden or the Simulations
tab is active.

## Frontend
- 3D true alpha: `helix_renderer._installInstanceAlpha(mesh)` clones the shared GEO_*
  template, adds an `instanceAlpha` InstancedBufferAttribute, and patches the material
  via onBeforeCompile (`diffuseColor.a *= vInstanceAlpha; if (a<0.02) discard;` — only
  touches diffuseColor.a, D5-safe). Installed ONLY when the design has reference strands
  (so plain designs keep opaque materials — zero regression). REF_ALPHA=0.4; hide =
  alpha 0 (discarded). `setReferenceStrands`/`setReferenceHidden` reapplied by
  design_renderer after rebuild + on the `showReferenceGeometry` store toggle. Impostor
  meshes (flag-gated `?impostors=1`) are skipped → not translucent in impostor mode.
  Atomistic-overlay reference transparency is NOT done (out of scope v1).
- 3D toggle-OFF hides ALL reference elements, not just beads (multi-module, 2026-05-23):
  the design-geometry visibility rule (5 scene owners). Coverage:
  * beads/cones/slabs/fluoros/EXTENSIONS/MODIFICATIONS — already hidden by the alpha=0
    path (extension+fluoro geometry nucs carry `strand_id`, crud.py `_strand_extension_geometry`).
  * HELICAL AXIS — `helix_renderer._applyReferenceAlpha` hard-hides axis arrows of
    reference-ONLY helices (`_refOnlyHelixIds`) when `_refHidden`; restores via
    `_applyShaftModeVisibility(_currentShaftMode)` when shown (gated on `_axisArrowsVisible`).
  * CROSSOVER EXTRA-BASES — `design_renderer._applyReferenceXoverVisibility()` zero-scales
    (hide) / repositions via `updateExtraBaseInstances`+`_liveXoverPos` (show) the bead/slab
    instances of crossovers whose BOTH endpoints are reference; called post-rebuild + in the
    `showReferenceGeometry` subscriber. Mirrors the cluster `_applyXoverVisibility` path.
  * CROSSOVER ARC LINES — `unfold_view._reapplyArcHidden` now also sets `e.hidden` for arcs
    whose both endpoints are reference when `showReferenceGeometry===false`; a new store
    subscriber re-runs `_reapplyArcHidden`+`_updateArcPositions`+`_refreshArcGlow` on toggle
    (same refresh path the cluster `setHiddenNucs` uses). Arcs show in the default 3D view too.
  All keyed on the reference-only-helix / both-endpoints-reference test; zero effect when no
  reference strands. NOTE: domain-cylinder LOD (Cylinders/Sticks rep) is NOT yet covered.
  GOTCHA (cost me several E2E cycles): design_renderer's single store subscriber has an early
  `if (!geoChanged && !designChanged && !loopChanged) return` — a PURE view toggle
  (showReferenceGeometry) has no geo/design change, so any handler placed AFTER that return
  never fires. The reference-hide handler MUST sit BEFORE it (next to the `coloringMode` pure-
  toggle handler). The pre-existing `staplesHidden`/`isolatedStrandId` handlers are also after
  the return — likely latent-dead for live toggles (not fixed here). Verified 2026-05-23: all-
  reference 6hb_test, toggle off → instanceAlpha 0 on all bead meshes + empty 3D scene.
  E2E note: the 3D app opens on a launcher (File>New to enter editor); API calls must be
  doc-scoped (`X-NADOC-Doc` from the tab's `?doc=`), and the refetch broadcast must carry the
  matching `docId` (`isSameDoc`) or the editor ignores it (see [[session_recovery]] multi-doc).
- Context menu "Make Reference"/"Make Active" in selection_manager.js `_showColorMenu`
  (single, incl. scaffold) + `_showMultiMenu` (lasso/shift). View toggle
  `menu-view-reference` (default on). client.js `patchStrandsReference` (no skipGeometry).
- cadnano-editor (separate window/store): reference strands render DASHED, not
  transparent (user feedback 2026-05-23 — alpha was too subtle in 2D). `_drawDomain`
  takes a `dashed` param → bodies become dashed strokes + caps become hollow dashed
  outlines (fill→stroke helpers `_capRect`/`_bodyFill`/`_capTri`); `_drawExtensions`,
  `_drawCoaxialArcs`, and both loops of `_drawCrossoverArcs` set
  `setLineDash([6/_zoom,5/_zoom])` + **`lineCap='butt'`** (round caps swallow the gaps at
  working zoom). Each loop also skips reference geometry when `_viewTools.referenceGeometry
  === false`. `referenceGeometry:true` view-tool (`data-vt`) + dynamic strand context menu
  `_showStrandCtxMenu`. The 3D View toggle and the cadnano view-tool are INDEPENDENT in v1.
- cadnano crossover SPRITES skip reference geometry (2026-05-24): a crossover may
  never involve a reference strand, so `_drawCrossoverIndicators` builds a `refRanges`
  coverage map (reference strands only, parallel to `strandRanges`) + `_slotIsReference`
  and gates BOTH sprite pushes (staple + scaffold) with
  `!_slotIsReference(hid,bp,A) && !_slotIsReference(target.hid,bp,B)`. Suppresses sprites
  ON a reference strand AND sprites whose OTHER half would land on one — so the editor
  can't form a crossover with reference geometry (sprite is the only manual new-xover path;
  no sprite ⇒ `_hitTestCrossoverSprite` returns null ⇒ no placement). Mechanical is_reference
  filter, no geometric reasoning. Backend manual `place_crossover` route is NOT guarded
  (auto_crossover already is) — out of scope; editor sprite removal was the requested fix.
- cadnano pathview ARC dashing must be replicated per arc-drawing loop — there is no
  single chokepoint. Reference dashing (`setLineDash([5/_zoom,3.5/_zoom])` when both ends
  on reference strands) lives in `_drawCrossoverArcs` (registered xovers), `_drawCoaxialArcs`
  (continuations), AND `_drawCrossoverArcs`'s forced-ligation loop. The FL loop was MISSED
  on first ship → FL arcs drew solid; fixed 2026-05-23 by computing `isRefFL` (both ligated
  strands reference) and applying the same dash + `referenceGeometry===false` skip.
  NOTE: arcs use `lineCap:'round'` + thickness `CELL_H*0.20` world (scales with zoom), while
  the dash is screen-constant (÷_zoom). At high zoom the round caps swallow the gaps and a
  *correctly* dashed arc LOOKS solid; verify dashing zoomed-OUT (≤~1.4×) or via a stroke probe.
- cadnano LOOP/SKIP markers (`_drawLoopSkips`): loop/skips live on the HELIX, not the strand,
  so "reference" = the helix is reference-ONLY (helper `_referenceOnlyHelixIds()`, mirrors
  backend `reference_helix_ids`; a mixed active+ref helix is NOT hidden — its loop/skip affects
  the active strand). Guarded with the same `refHelix && (_ghostPass !== 0 ||
  _viewTools.referenceGeometry === false)` → hidden when the ref toggle is off AND in
  periodic-boundary mirror passes (verified 2026-05-23: toggle-off hides the loop circle).

Tests: `tests/test_reference_geometry.py` (model round-trip, helpers, sequence skip,
validator, deformation freeze via real pipeline, route round-trip + 404, CSV export omit).
See [[deformation-cluster-scope]] for the masking-pattern lineage.

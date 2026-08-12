---
name: reference-geometry
description: Per-strand is_reference flag — inactive translucent backdrop strands that auto-features ignore and exports/validation exclude. Shipped 2026-05-23.
metadata: 
  node_type: memory
  type: project
  originSessionId: 01eb753c-9ca3-4aad-8714-645b7751981c
---

# Reference geometry (is_reference flag)

## Helical Axis Lines toggle (2026-07-16, out-of-session work)

View ▸ **Helical Axis Lines** (`#menu-view-helical-axes`, default ON) + the `/` hotkey hide/show the
helix axis arrows via `designRenderer.setAxisArrowsVisible`. Shortcut is `blockedInInput: true` (no
firing while typing). **Caveat worth knowing before touching it:** `setAxisArrowsVisible` is a SHARED
setter — `scene/cadnano_view.js` forces it false on entry / true on exit, and `scene/photo_mode.js`
drives it too. The new `_helicalAxisLinesVisible` flag is module-local to `main.js` and is **not**
reconciled with those, so a cadnano round-trip can silently re-show axes the menu thinks are hidden.

Shipped 2026-05-23. Lets the user build a new origami against an existing one:
mark strands `is_reference=True` and every generative/auto feature ignores them
while they stay visible (translucent) and manually editable. Single-design editor
(3D scene + cadnano-editor window) shows reference geometry; the **assembly view
EXCLUDES it entirely** (2026-05-24, see "Assembly exclusion" below) — a part used
as a backdrop reference inside an assembly renders only its active strands.

`Strand.is_reference: bool = False` (models.py, no migration — default-safe load).
Helpers `Design.active_strands()` / `reference_strands()`.

## Exclusion architecture (two patterns — decided deliberately)
- **Generative loops** (sequences, scaffold_router, seamed/seamless_router, lattice
  autostaple/break/merge + overhang autodetect, crud.auto_crossover): per-site
  `if strand.is_reference: ... continue`, mirroring the existing SCAFFOLD/LINKER skip.
  Loops that REBUILD `design.strands` must append-and-continue reference strands
  (never drop them — that would delete topology). seamless inherits the filter via
  seamed's `_scaffold_coverage`. auto_crossover filters by building `build_strand_ranges`
  from `active_strands()` so reference slots read as uncovered.
- **Passive whole-design consumers** (exports: oxDNA/PDB/PSF/NAMD/GROMACS/caDNAno/
  sequence-CSV): single entry-layer filter `_design_for_export()` in crud.py = a
  `model_copy(strands=active_strands())`. Works because exporters are strand-driven
  (look up positions from per-helix geometry by slot), so dropping reference strands
  omits their nucleotides with no dangling crossovers. **Display/overlay geometry is
  NOT filtered** (get_atomistic, atomistic_batch, /design/geometry) — reference must
  stay VISIBLE. Validator (validator.py) skips reference per-strand (scaffold-count,
  seq-length, loop, domain-ref) but keeps the unique-ID check over all strands.

## Assembly exclusion (2026-05-24)
Assembly DISPLAY drops reference strands. Helper `_display_design(design)` in
[backend/api/assembly.py](backend/api/assembly.py) = the same active-strands
`model_copy` as `_design_for_export` (strands only, never helices — no dangling
helix refs; returns input unchanged when no reference strands, zero-alloc common
case). Applied at all 5 assembly display-geometry sites: `get_assembly_geometry`,
`get_instance_geometry`, `seek_instance_features` (CG nucleotides + design dict),
`get_instance_atomistic_geometry`, `get_instance_surface_geometry`. **Never feed
the result into persisted assembly state** — `seek_instance_features` keeps the
unstripped `updated_design` for `_replace_instance_design` and strips only the
shipped geometry/design_dict (topology preserved). The `_GEO_CACHE` only serves
these display endpoints, so caching the stripped form is consistent. Frontend
needed NO change — `buildHelixObjects` renders from `nucleotides`, which the
backend now omits for reference strands. Regression:
`test_assembly_geometry_excludes_reference_strands` in `tests/test_reference_geometry.py`.

## Bend/twist freeze (user chose per-strand freeze on possibly-shared helices)
deformation.py: `_reference_nuc_mask(arrs, helix, design)` (bp-range+direction mask,
same shape as the domain-level cluster mask). Restore straight values for masked rows
BEFORE cluster transforms (so manual cluster moves still apply) in BOTH
`deformed_nucleotide_arrays` (array fast-path, used by /design/geometry) and
`deformed_nucleotide_positions` (object path). `deformed_helix_axes` keeps a straight
axis for a helix whose strands are ALL reference (bare helices still bend).
**Accepted v1 caveat**: on a MIXED helix (active + reference strands), the axis bends
(driven by active strands) while reference beads stay straight → they detach from the
bent stick. Documented in the function docstrings.

## Clusters exclude reference geometry (2026-05-23)
Reference geometry must never be a cluster member or enter cluster/deformation
calculations — it's a fixed backdrop at its BASE (topological) position, immune to
cluster joints/drags AND deformations. Mechanism = MEMBERSHIP exclusion (not a
per-helix application-time filter — `_clusters_for_helix` is in the geometry hot path,
too costly to check per call):
- `Design.reference_helix_ids()` (models.py) = helices with ≥1 reference domain and 0
  active domains (reference-ONLY; a mixed active+ref helix is NOT excluded — the active
  part needs it; ref rows on it still get cluster transforms = mixed-helix caveat).
- `_ensure_default_cluster` (crud.py) excludes ref helices from the default cluster.
- `cluster_reconcile._compute_helix_membership` drops ref-only helices from `kept` and
  never assigns new ref helices → every mutation keeps clusters clean.
- `patch_strands_reference` route PRUNES ref-only helices from `helix_ids` and reference
  strands' `DomainRef`s from `domain_ids` of every cluster (immediate effect on toggle).
- `deformation._arm_helices_for` excludes ref helices (unioned into `overhang_helix_ids`)
  so the bend/twist bundle centroid/tangent isn't skewed by the frozen reference part.
- **Autodetect builders (`_autodetect_clusters` + `_cluster_by_*`) were NOT changed** —
  they only run on cadnano/scadnano IMPORT, and imported designs have no reference strands
  (the user marks reference afterward). Reconcile + toggle-prune cover the post-import flow.
- All guarded by empty `reference_helix_ids()` → ZERO behavior change for reference-free
  designs (verified: full suite green vs the 2 pre-existing teeth-fixture failures).
- Side effect: marking a cluster-POSED part reference snaps it to base (loses the pose),
  because membership exclusion drops it from the transform. Acceptable — reference parts
  are normally imported with identity cluster transforms. Loaded `.nadoc` with a ref helix
  saved inside a cluster keeps it until the next toggle/mutation (no prune-on-load — would
  violate native-load preserve-positions).

## Route + payload
`PATCH /design/strands/reference {strand_ids, is_reference}` → returns
partial compact geometry for only the toggled strands' real helices (NOT metadata-only —
the freeze can move those nucleotides). Synthetic `__lnk__` bridge helices need no
geometry response. The route also slims old feature-log bodies, so large designs do not
re-ship their entire recovery history. On `VoltronCoreArm.nadoc` this reduced the measured
request from ~3.28 s + 394 ms browser JSON parse to ~0.22 s and ~0.74 MB. The frontend
patches the retained renderer in place, refreshes its reference ID/alpha state immediately,
and completes operation timing after the next paint (no reload or fallback-timeout wait).
`op_subtype='strands-reference'` had to be ADDED to the `MinorMutationLogEntry`
Literal in models.py (~line 1098) — forgetting it 500s the route. Per-nucleotide
`is_reference` added to `_strand_nucleotide_info` payload.

Same-path workspace autosaves now return acknowledgment metadata only. The frontend already
discarded the returned design for `identity_disposition='confirmed'`; omitting that multi-MB
body avoids a second unnecessary parse. Simulation recommendation/job-list refreshes are
likewise gated to the open, expanded Simulations tab rather than running after every edit.

## Simulation exclusion (2026-08-11)
Reference geometry is editor-only and never enters a simulation. The canonical
`Design.without_reference_geometry()` projection removes reference strands and
reference-only helices while retaining mixed helices needed by active strands. All job-create
paths (oxDNA, LAMMPS, mrDNA, CanDo, SNUPI, BLADE, and NAMD) use this projection before
counts, geometry, topology, sizing, and setup. Engine preparers apply it again before writing
their frozen `design.json`/engine inputs, providing a defense against internal callers that
bypass an API route. While the expanded Simulations tab is active, reference geometry is
temporarily hidden in the 3D and unfold renderers without changing the user's persistent View
toggle; leaving the tab restores the normal preference.

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

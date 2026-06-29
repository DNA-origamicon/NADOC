---
name: Overhangs Manager feature (overhang-overhaul branch)
description: Tools menu → Overhangs Manager (renamed 2026-04-30) — metadata + linker complement strands + 3D arc; selection-driven prepopulation; new StrandType.LINKER
type: project
originSessionId: 4eb5150c-d5c5-448a-9b7f-709c431b0162
---
Branch: `overhang-overhaul` (off `master`, created 2026-04-29). First feature is **Overhangs Manager** (renamed from "Overhang Connections" 2026-04-30).

**UI / authoring flow lives in [[ct_tab]]** (Connection Types tab — selected-linker model, bridge_sequence field on `OverhangConnection`, live-computed Sequence column, 12 icon variants covering all 4 attach combos × {ss, ds}, dsDNA strand selection). This file documents the underlying **topology + geometry** generation; the tab file documents how the user interacts with it.

## Cylinder-rep rendering of linkers (2026-05-21)

All in [helix_renderer.js](frontend/src/scene/helix_renderer.js) `buildHelixObjects` cylinder pass — so BOTH the per-design view AND the assembly linker group (which calls `buildHelixObjects` via `_rebuildLinkerHelices`) get it from one place.

- **Binding (complement) domains → half-cylinder, linker strand colour, opposite the overhang half.** A linker complement (`strand.strand_type === 'linker'` && helix NOT `__lnk__`) used to draw as a full white cylinder overlapping the overhang. Now deferred (`_deferredBindings`) and drawn into `iLinkerBindingCylinders` (GEO_HALF_CYL) using the paired **overhang's** captured pose (`_ovhgBuildXform`, keyed `helixId|lo|hi`) rolled π about the cyl axis (`_QUAT_ROLL_PI`) → overhang half (its colour) + binding half (linker colour) = one two-toned full duplex cylinder. The user explicitly chose "opposite half / split duplex" + "linker strand's own colour".
- **ds bridge → one simple full cylinder per `__lnk__` helix** in `iLinkerBridgeCylinders` (GEO_UNIT_CYL), spanning the bridge duplex axis recovered by **averaging the paired bridge beads at min/max bp** (the `__lnk__` helix is skipped in the axis-arrow loop, so it has no normal domain cylinder; built from `geometry` nucs so it tracks relax/cluster transforms on rebuild). ss bridges are untouched — still the FJC bead chain in `overhang_link_arcs.js`.
- Both meshes are dedicated + build-time-only (not woven into the revert/unfold/physics recompute passes); they re-track via the full rebuild that fires on any geometry change. Shown only at coarse LOD (level 2), wired in `setDetailLevel`.
- **Fallback** (no paired overhang in this `buildHelixObjects` call — e.g. the **assembly linker group**, whose synthetic design has the complement but not the part's overhang; or a curved overhang helix): place the binding half from the complement's own arrow + π-roll. Visually fine; not guaranteed perfectly opposite the part-clone overhang since that's a different renderer path.
- **Assembly LOD:** `_rebuildLinkerHelices` ([assembly_renderer.js](frontend/src/scene/assembly_renderer.js)) now builds the linker group at the rep the part instances use (`_CG_LOD[inst.representation]`, non-CG → cylinders) and calls `setDetailLevel` on the captured `linkerHelixCtrl` (stored on `_linkerGroup.userData.helixCtrl`). Before, the linker group was always built at 'full' (beads) regardless of the assembly rep. A rep change re-runs `rebuild → rebuildLinkers`, so the linker LOD self-syncs.
- **Latent bug fixed in passing:** ds bridge domains were previously COUNTED into `_domainCylCount` but never emitted (no arrow) → phantom zero-matrix cylinder at the origin in cylinder rep. Now excluded from the count.
- Verified in-app (Playwright `e2e/linker_cylinder_rep.spec.js` + screenshots): `dsdna-link-sel-test.nadoc` + `Ultimate Polymer Hinge.nadoc` (parts) and `Linker_Assem_test2.nass` (assembly). `__NADOC_DBG__` now also exposes `controls` + `animateCameraTo` for camera framing in tests.

## ds-linker bridge — CG vs atomistic alignment (2026-05-05)

**KEY:** the bridge has TWO separate placement formulas that MUST stay in lockstep:
- **CG path** (`_emit_bridge_nucs` in `crud.py`) → `bridge_axis_geometry(...)` in `linker_relax.py` — axis is **offset perpendicular to chord** by `−(radial_a + radial_b) / 2 * R` so boundary beads colocalize with OH anchors at native B-DNA radius.
- **Atomistic / stored helix path** (`_make_virtual_linker_helix` in `lattice.py`) — fixed 2026-05-05 to also call `bridge_axis_geometry(p_a, n_a, p_b, length_bp, comp_first_a, comp_first_b)` for `axis_start`/`axis_end`. Falls back to chord-midpoint on exception (legacy designs).

Before the fix: atomistic linker atoms placed ~1 nm off from CG bridge beads (chord-centred vs offset axis). User reported "linker bridge missing in atomistic mode" — it wasn't missing, it was just hovering nearby in the wrong spot.

**Don't break:** if you change the offset formula in `bridge_axis_geometry`, change `_emit_bridge_nucs`, `_bridge_boundary_radials`, AND `_make_virtual_linker_helix` together. The relax loss in `_arc_chord_lengths` is intentionally chord-magnitude-only (folding the perpendicular offset into the loss creates a degenerate minimum at chord ≈ 0).

**Three entry points:**
1. **Tools → Overhangs Manager…** — global menu (`#menu-tools-overhangs-manager`). Opens with whatever's in the current overhang selection.
2. **Right-click a strand while 1–2 overhangs are selected** — the strand color menu (`_showColorMenu` in [selection_manager.js](frontend/src/scene/selection_manager.js)) injects an "Open Overhangs Manager (N selected)…" item at top. Wired via new `onOpenOverhangsManager(ovhgIds)` callback in `initSelectionManager`. Cone hit-test was hoisted above the multi-overhang divert so a strand-cone right-click reaches the strand menu instead of the OH context menu.
3. **Ctrl+click overhangs** when `selectableTypes.overhangs` is on — toggles in/out of `multiSelectedOverhangIds`, capped at 2 (oldest drops via `slice(-2)`). Implemented in `_handleCtrlClickNuc` early branch. Lasso multi-select unchanged.

The popup's `open(preselect?)` accepts an optional ids array (up to 2). With no arg it pulls from store: `multiSelectedOverhangIds` first, then `selectedObject?.data?.overhang_id`. Side A and Side B fill in array order. Validated against the live `currentDesign.overhangs` list — stale ids are dropped.

## Data model

`OverhangConnection` lives on `Design.overhang_connections` ([backend/core/models.py](backend/core/models.py)):
- `id`, `name` (auto L1, L2, …), `overhang_a_id`, `overhang_a_attach`, `overhang_b_id`, `overhang_b_attach`, `linker_type` ("ss"|"ds"), `length_value`, `length_unit` ("bp"|"nm").
- `attach`: `"root"` = embedded end on bundle; `"free_end"` = protruding tip.

`StrandType.LINKER = "linker"` added to the enum. Linker strands are auto-generated; never user-created directly.

## Generation rules — CRITICAL

`generate_linker_topology(design, conn)` in [backend/core/lattice.py](backend/core/lattice.py) produces the SAME complement domains for ss and ds; only the bridge differs:

| | ss | ds |
|---|---|---|
| Strand `__lnk__<id>__a` | `[complement on OH-A real helix]` | `[complement on OH-A real helix, bridge FORWARD on virtual]` |
| Strand `__lnk__<id>__b` | `[complement on OH-B real helix]` | `[complement on OH-B real helix, bridge REVERSE on virtual]` |
| Virtual `__lnk__<id>` helix | not created | created (length = `linker_bp`) |

**Complement domain construction** (`_make_complement_domain`): same `helix_id` and bp range as the OH domain, but `start_bp`/`end_bp` SWAPPED and `direction` flipped. This puts the linker bead at the same `(helix_id, bp_index)` as the OH bead but with opposite `direction` — antiparallel pairing.

**Why ss has no virtual helix in v1:** the bridge is purely the frontend arc; ss-bridge strand topology will be added later when arcs are materialised into real ss/ds strands (per user direction).

**Length conversion** (`_length_value_to_bp`): `bp = round(value)`; `nm = round(value / BDNA_RISE_PER_BP)` (0.334 nm/bp). Same conversion for ss and ds (pragmatic v1 — ssDNA contour length differs but not modelled).

## Validation rules — unified Watson-Crick polarity test (2026-05-02)

One test for all 16 (end_a, attach_a, end_b, attach_b) combos. Define each
side's polarity:

```
comp_first := (5p AND free_end) OR (3p AND root)
```

`comp_first` means the linker strand traverses `[complement, bridge]` (the
bridge attaches at the complement's 3' end). `bridge-first` is the inverse.

- **dsDNA accepted iff `comp_first(A) == comp_first(B)`** — both bridge halves on the virtual `__lnk__` helix run antiparallel and form a real Watson-Crick duplex. Mismatched polarity makes them parallel — non-physical.
- **ssDNA accepted iff `comp_first(A) != comp_first(B)`** — single strand traverses `[complement_a, bridge, complement_b]` (5'→3'), so the boundary at A is at complement_a 3' (comp-first) and at B is at complement_b 5' (bridge-first). Both sides agreeing breaks the continuity.

Eight of 16 combos accepted for each linker type; the two sets are disjoint. Implementation: [`_check_linker_compatibility` + `_comp_first_polarity` in backend/api/crud.py](backend/api/crud.py) and frontend mirror [`_checkRules` + `_compFirst` in overhangs_manager_popup.js](frontend/src/ui/overhangs_manager_popup.js).

**Examples** — both `5p+free_end / 5p+free_end` and `5p+free_end / 3p+root` are valid ds (matching polarity); `5p+free_end / 5p+root` is invalid ds (would force a parallel duplex). The same combos give the inverse for ss (the first two are invalid ss; the third is valid).

**Per-end uniqueness** (`_used_overhang_ends`): each `(overhang_id, attach)` pair can appear in at most one connection. Backend returns 400 with "already linked at its {root|free end}".

**Per-end uniqueness** (`_used_overhang_ends`): each `(overhang_id, attach)` pair can appear in at most one connection. Backend returns 400 with "already linked at its {root|free end}".

## Cross-cutting LINKER policy

| Subsystem | Behaviour |
|---|---|
| `Design.scaffold()` | naturally excludes (LINKER ≠ SCAFFOLD) |
| Validator | skips LINKER strands in helix-ref + sequence-length + loop-strand checks |
| Geometry pipeline | `_geometry_for_helices` skips `__lnk__` helices in helix loop. `_strand_nucleotide_info` does **NOT** skip LINKER strands (critical — needed so complement nucs render) |
| Default color | `#ffffff` (set on strand creation) |
| Auto-scaffold / auto-crossover / autobreak / cluster autodetect / sequence assignment / caDNAno+scadnano export / oxDNA / atomistic | **NOT YET** updated to skip LINKER. Defer until a tool is run on a design with linkers and breaks. Forced ligation explicitly allowed. |
| Undo/redo | none. `FeatureLogEntry` discriminator not extended. |
| Sequence | linker strands stay `sequence=None` → 'N's at assignment time. No auto-update on overhang sequence change. |

## API

[backend/api/crud.py](backend/api/crud.py) ~ line 4960:
- `POST   /design/overhang-connections` — body has overhang ids, attach, linker_type, length_value, length_unit, optional name; auto-generates topology.
- `PATCH  /design/overhang-connections/{id}` — name / length_value / length_unit only. Length change auto-rebuilds topology (`remove_linker_topology` then `generate_linker_topology`). Other fields immutable; delete & recreate.
- `DELETE /design/overhang-connections/{id}` — strips metadata + linker strands + virtual helix atomically.

`assign_overhang_connection_names(design)` fills `L{n}` to the smallest unused slot. Survives delete/re-add (preserves existing names).

## Frontend

[frontend/src/ui/overhang_connections_popup.js](frontend/src/ui/overhang_connections_popup.js) — three-column popup (overhang A list | controls | overhang B list) + linkers table below. Inline-editable name and length cells (click → input → blur/Enter saves; Esc cancels). Live rule validation disables Generate with inline error. Window stays open after Generate.

[frontend/src/scene/overhang_link_arcs.js](frontend/src/scene/overhang_link_arcs.js) — white tube arc per connection. **Anchors on the LINKER complement strand**, not the OH strand. Two-step lookup:
1. Find OH attach nuc to learn `(helix_id, bp_index)` (5'/3'-flagged tip for `free_end`, farthest-bp nuc for `root`).
2. Find linker complement nuc at the same `(helix_id, bp_index)` on `__lnk__<conn_id>__a` / `__b` (opposite direction → antiparallel partner).

Falls back to OH bead if no linker partner in geometry (synthetic test seed without backing OH domain). Bezier control offset = chord × 0.30 perpendicular to chord. Tube radius 0.30 nm (visibly thicker than backbone beads). DEBUG flag at top of file for console logging.

[frontend/src/api/client.js](frontend/src/api/client.js) — `createOverhangConnection`, `patchOverhangConnection`, `deleteOverhangConnection`.

[frontend/src/main.js](frontend/src/main.js) — popup init + `menu-tools-overhang-connections` click handler. Arc renderer init (`initOverhangLinkArcs(scene)`) with **initial rebuild** after subscription registration (handles persisted designs that loaded before the listener was wired).

## Critical gotcha — `currentGeometry` shape

`store.currentGeometry` is the **bare nucleotides array** (assigned from `json.nucleotides` in [client.js:189](frontend/src/api/client.js#L189)), NOT an object with a `.nucleotides` field. Initial bug: arc renderer read `geometry.nucleotides ?? []` → always empty → arcs never drew. Fix uses `Array.isArray(geometry) ? geometry : (geometry.nucleotides ?? [])`.

## Debug + tests

[scripts/debug_linker_pipeline.py](scripts/debug_linker_pipeline.py) — end-to-end debugger. Run via `uv run python -m scripts.debug_linker_pipeline [fixture.nadoc]` (default `workspace/linker_test.nadoc`). Sections:
- Inspect overhang domains + 5p/3p tags
- Live ds creation → topology + complement validation + geometry emission + arc anchor probe
- Live ss creation → same
- USER-FLOW SIMULATION: load fixture verbatim and probe arc anchors (this is the path the user actually exercises)

The arc-anchor probe mirrors the frontend logic exactly: OH attach nuc → linker partner at same `(helix_id, bp_index)`.

[tests/test_overhang_connections.py](tests/test_overhang_connections.py) — 39 tests covering: rules (8), per-end uniqueness (3), CRUD + name auto-assignment (10), patch (6), strand topology shape (4 — incl. the real-OH-domain seed `_seed_with_real_oh_domains` which mimics extruded overhangs), geometry emission (2), validator quietness (1).

## Files modified / created

**Backend:**
- [backend/core/models.py](backend/core/models.py) — `StrandType.LINKER`, `OverhangConnection`, `Design.overhang_connections`
- [backend/core/lattice.py](backend/core/lattice.py) — `_length_value_to_bp`, `_find_overhang_domain`, `_make_complement_domain`, `_make_virtual_linker_helix`, `generate_linker_topology`, `remove_linker_topology`, `assign_overhang_connection_names`
- [backend/api/crud.py](backend/api/crud.py) — POST/PATCH/DELETE endpoints, `_overhang_end`, `_used_overhang_ends`, `_check_linker_compatibility`; `_geometry_for_helices` skips `__lnk__`; `_strand_nucleotide_info` does NOT skip LINKER
- [backend/core/validator.py](backend/core/validator.py) — skip LINKER in 3 places

**Frontend:**
- [frontend/index.html](frontend/index.html) — Tools menu item (`#menu-tools-overhangs-manager`), modal `#overhangs-manager-modal` with Root/Free-End SVG icons (duplex bundle + diagonal + base-pair rungs)
- [frontend/src/ui/overhangs_manager_popup.js](frontend/src/ui/overhangs_manager_popup.js) — new (renamed from `overhang_connections_popup.js` on 2026-04-30); exports `initOverhangsManagerPopup`, `open(preselect?)`
- [frontend/src/scene/overhang_link_arcs.js](frontend/src/scene/overhang_link_arcs.js) — new
- [frontend/src/scene/selection_manager.js](frontend/src/scene/selection_manager.js) — ctrl+click overhang toggle in `_handleCtrlClickNuc`; cone hit-test hoisted above multi-overhang divert; `_showColorMenu` accepts `ovhgMultiIds` + `onOpenOverhangsManager` and injects the manager entry; new `onOpenOverhangsManager` opt on `initSelectionManager`
- [frontend/src/api/client.js](frontend/src/api/client.js) — 3 client methods
- [frontend/src/main.js](frontend/src/main.js) — popup + arc renderer wiring; `onOpenOverhangsManager` wired to `openOverhangsManager(ovhgIds)`

**Tooling:**
- [scripts/debug_linker_pipeline.py](scripts/debug_linker_pipeline.py) — new
- [tests/test_overhang_connections.py](tests/test_overhang_connections.py) — new

## Status

User-verified in app: ss linker on `linker_test.nadoc` (t1 + t2) shows white tube arc anchored on linker complement beads + complement nucleotides paired antiparallel with each overhang. Full backend suite 725 pass. Frontend builds clean.

## Next steps (deferred)

### 1. ss linker: replace tube arc with rendered bridge nucleotides — RESOLVED 2026-05-11

The polarity-rule blocker (originally listed here) is **resolved** as of 2026-05-02 — `_check_linker_compatibility` now uses the unified Watson-Crick test (see "Validation rules" above). Both `_make_complement_domain` ordering and bridge directions are computed per-side from `comp_first`, so the ds atomistic / bond topology is correct on every accepted combo (verified end-to-end across all 16 (end × attach)² combos in `tests/test_overhang_connections.py::test_polarity_rule_accepts_only_physical_combos`).

**Visual upgrade SHIPPED 2026-05-11.** ss bridges now render as the FJC bead chain from the pre-baked slab+SAW lookup table, picked by the user via the interactive R_ee×Rg config modal. Pre-relax draws a Bezier fallback arc; post-relax draws N beads positioned by `transform_to_chord` on the selected bin's representative shape. See [project_ssdna_linker_relax](project_ssdna_linker_relax.md) for the full pipeline, schema, and gotchas.

**For ds:** the bead+slab+cone duplex from `_makeDsLinkerMeshes` already serves; future improvement would be a real helix layout for the bridge so atomistic + CG share one source of truth (atomistic already aligns now via `position_linker_virtual_helices` + the deformed-anchor `_linker_anchor_nuc` fix).

### 2. Other deferred work

3. Linker sequence generation (currently `None` → 'N').
4. Add `LINKER` skip guards to auto-scaffold / auto-crossover / autobreak / cluster autodetect / sequence assignment / caDNAno+scadnano export when those tools are run on linker-bearing designs.
5. Cross-part / assembly-level connections.
6. Undo/redo via `FeatureLogEntry` discriminator extension.

## Relax Linker (shipped 2026-05-01, ds + 1-DOF only)

Right-click a linker → "Relax linker" optimizes the joint angle so the dsDNA linker's connector arcs collapse to zero length (chord between anchors = duplex `(bp - 1) × BDNA_RISE_PER_BP`). v1 scope: dsDNA only, exactly 1 DOF (one `ClusterJoint` on either overhang's owning cluster, not both, no joints in shared clusters). Other cases gray out with a tooltip. Endpoint: `POST /api/design/overhang-connections/{id}/relax`. Lightweight `GET …/relax-status` mirrors the DOF check for the menu. Cluster transform composition: `q_new = q_joint(θ*) ⊗ q_existing`, `t_new = R_joint(pivot + t − O) + O − pivot` (pivot unchanged). Appends a `ClusterOpLogEntry` so the op is undoable. Implementation: [backend/core/linker_relax.py](backend/core/linker_relax.py); frontend mirror helper `_linkerRelaxStatus` in [selection_manager.js](frontend/src/scene/selection_manager.js).

### Joint angle range (re-added 2026-05-09)

`ClusterJoint` now carries `min_angle_deg` / `max_angle_deg` (degrees, defaults `[-180, +180]` ≡ unbounded for backwards compat with old `.nadoc` files). Honoured by the linker-relax optimizer (1-DOF grid + bracket are clipped to the window; N-DOF Powell call passes `bounds=`). API: both `AddJointBody` and `PatchJointBody` accept the fields; the model validator and the patch endpoint reject `max < min` with 400.

Still unconstrained (open work, do NOT delete this note):
- the joint rotate gizmo / live-drag UI in `cluster_gizmo.js`
- the seek/animation player when interpolating `cluster_op` log entries

When you wire those, read `joint.min_angle_deg` / `joint.max_angle_deg`, convert to radians, and clamp the user's drag delta or interpolated angle against the cluster's *current* θ relative to the joint's pose. Tests for the existing optimizer clamp live in `tests/test_joints.py` (range fields + dict round-trip + 400 on inverted range) and `tests/test_overhang_connections.py::test_relax_respects_joint_angle_bounds` (end-to-end optimizer clamp).

### Future: relax v2

- Multi-DOF (co-optimize joints on both clusters; multi-basin search).
- ssDNA target length from physics (worm-like chain or similar) instead of geometric duplex length.
- Frontend live preview before commit.

## ds-linker bridge — real geometry pipeline (shipped 2026-05-03)

Bridge nucs are now **first-class geometry payload entries** emitted by `_emit_bridge_nucs` ([backend/api/crud.py](backend/api/crud.py), called at the end of `_geometry_for_helices`). The standard helix renderer draws their backbone beads / slabs / cones via the normal pipeline — no JS-synthesized bridge mesh anymore.

### Anchor lookup rule (corrected 2026-05-03)

The anchor on side X is the **complement nuc on the OH's helix at the OH's `attach`-end bp** — direct same-bp lookup, NOT a "farthest from tip" heuristic. Per the user-facing rule:
- `attach=root` → anchor at OH-crossover bp (the bonded end where OH joins the bundle)
- `attach=free_end` → anchor at the OH-free-tip bp (opposite end from the crossover)

Both cases match the `_is_comp_first` derivation in [backend/core/lattice.py](backend/core/lattice.py), so the polarity rule itself is unchanged. Implemented identically in three places (must stay in sync):
- backend `_anchor_pos_and_normal` ([backend/core/linker_relax.py](backend/core/linker_relax.py))
- backend `_anchor_for` inside `_emit_bridge_nucs` ([backend/api/crud.py](backend/api/crud.py))
- frontend `_linkerAttachAnchor` ([frontend/src/scene/overhang_link_arcs.js](frontend/src/scene/overhang_link_arcs.js))

`_anchor_pos_and_normal` now takes `conn` (not `conn_id`) so it can read `overhang_a_attach` / `overhang_b_attach`.

### Bridge axis offset for native B-DNA radius

`bridge_axis_geometry(p_a, n_a, p_b, base_count, comp_first_a, comp_first_b)` in [linker_relax.py](backend/core/linker_relax.py) is the **single source of truth** for bridge geometry. Used by both `_emit_bridge_nucs` (rendering) and `_arc_chord_lengths` (relax loss).

Symmetric placement: `axis_start = (p_a + p_b) / 2 − (radial_a + radial_b)/2 · R − fz · visualLength/2` chosen so the two boundary residuals are equal in magnitude and opposite in sign. Boundary beads sit at full `HELIX_RADIUS_NM` from the axis (native B-DNA), not at radius 0. When the relax target is reached both boundary beads exactly colocalize with their anchors. Polarity-aware boundary radials:
- side A's bridge bp 0:  FORWARD if `comp_first_a` else REVERSE
- side B's bridge bp L−1: REVERSE if `comp_first_b` else FORWARD

(Mirrors `_make_bridge_domain` in [lattice.py](backend/core/lattice.py).)

### Cross-helix arc dedup

The linker strand spans an OH helix and the virtual `__lnk__` helix, so its inter-domain transition would normally generate a cross-helix arc via `getCrossHelixConnections()` in [helix_renderer.js](frontend/src/scene/helix_renderer.js) — duplicating the connector arc that `overhang_link_arcs.js` already draws. Fix: skip any cross-helix connection where either side is a `__lnk__` helix (both the strand-cone branch and the placed-crossover branch).

### Right-click on bridge bead → linker context menu

Right-click on any part of a linker strand (complement bead, bridge bead, or strand cone) now routes to `_showLinkerMenu` (Delete + Relax), not `_showColorMenu`. Single dispatch point in [selection_manager.js](frontend/src/scene/selection_manager.js): `directLinkerConn = linkerConnectionForStrandId(hitCone?.strandId ?? hitBead?.nuc?.strand_id)`.

### Debug overlay (Help → "Show Linker Anchor Debug")

Per side: red OH tip · pink OH attach · green anchor · cyan bridge bp. Cyan must coincide with green post-relax; pre-relax there's a visible offset.

### Critical gotcha for future linker work

Three independent pieces of code compute the bridge anchor and geometry. They MUST stay in lockstep, otherwise the rendered bridge, the relax loss, and the debug overlay will disagree:
1. `_anchor_pos_and_normal` (linker_relax.py) — relax loss + debug
2. `_anchor_for` inside `_emit_bridge_nucs` (crud.py) — backend rendering
3. `_linkerAttachAnchor` (overhang_link_arcs.js) — connector arc anchor in JS

For the bridge geometry, `bridge_axis_geometry` in linker_relax.py is the shared helper — DO NOT duplicate its math. The JS `_makeDsLinkerMeshes` no longer needs to compute bridge geometry at all; it just looks up bridge boundary positions from the geometry payload via `_bridgeBoundaryPos(nucsByStrand, connId, side, bp)`.

The JS-synthesized bridge mesh (beads/slabs/cones/coarse-cylinder) was removed entirely from `_makeDsLinkerMeshes`. The function now only draws the two connector arcs (anchor → bridge boundary). DO NOT re-add bridge mesh synthesis to `_makeDsLinkerMeshes` — the standard helix renderer handles it now. If you do, you'll get double-rendered bridges.

### Relax loss MUST be chord-magnitude-only (decoupled from bridge offset)

`_arc_chord_lengths` returns `|visualLength − |chord||/2` per side — a SCALAR magnitude residual, NOT the full 3D anchor-to-bridge-boundary distance. Fixed 2026-05-03 after the hinge over-relaxed to a fully-collapsed configuration. Why folding the bridge boundary offset into the loss is a trap: the boundary radials sit perpendicular to the chord, so the "gap to anchor" term decomposes into two INDEPENDENT components — a chord-magnitude residual AND a perpendicular term that varies with chord DIRECTION. The perpendicular term creates a degenerate minimum near chord ≈ 0 (the fz-fallback frame at chord = 0 makes some of the perpendicular offset cancel), and the optimizer happily collapses the hinge into a chord ≈ 0 saddle. The only physically meaningful relax constraint is `|chord| → visualLength` (the bridge duplex spans its native length); the small perpendicular offset between anchor and bridge boundary post-relax is absorbed by the connector arc visualisation.

DO NOT re-fold the boundary offset into the relax loss. If you ever need a tighter post-relax visual fit, do it by changing the rendering (e.g. shifting the bridge axis to anchor one boundary exactly, accepting a small offset on the other) — never by adding the perpendicular term back to the loss.

`comp_first_a`/`comp_first_b` are still passed to `_arc_chord_lengths` for API symmetry with `bridge_axis_geometry`, but the scalar form ignores them.

### Multi-minima selection in 1-DOF relax (shipped 2026-05-03, commit 7d8e093)

A 1-DOF cluster rotation typically produces **two** θ values per period at which `|chord| = visualLength` — chord descends through the target on one side of its valley, ascends through it on the other. They can be 50°+ apart, and very often only one of them avoids clashing with neighbouring clusters / scaffold geometry.

The prior optimizer used coarse-grid `argmin` + bracketed `minimize_scalar` refine — which deepest-valley the grid happened to sample first decided the choice, effectively at random. A small λ·θ² regularizer in the loss is **not** strong enough to swing the grid pick (the chord term has nm² scale and dominates the grid sort).

**Current 1-DOF strategy** (`_optimize_angle` in `linker_relax.py`):
1. Pure `chord_loss(θ)` (no regularizer) — used everywhere so refinement converges on the actual chord minimum.
2. Enumerate ALL grid local minima (`losses[i] < losses[i±1]` with periodic wrap).
3. Refine each in its ±2-step bracket with `minimize_scalar`.
4. Among refined minima within `tol = 1e-6` nm² of the best chord-residual, pick the smallest `|θ|`.

Test case (polymer hinge): two minima at θ ≈ −36.79° and θ ≈ −18.00°; both achieve chord = 9.686 nm. Old optimizer picked −36.79° (clashed). New optimizer picks −18.00° (clean).

**Multi-DOF path keeps the λ·θ² regularizer** in its Powell loss because Powell only finds one basin per call — `enumerate-all-minima` doesn't apply. `_THETA_REG_LAMBDA = 1e-3` is small enough that it never distorts chord fit but breaks ties between near-equivalent basins seeded from different θ_0.

### Bridge axis side / `_BRIDGE_PHASE_OFFSET` (shipped 2026-05-03, commit 7d8e093)

The symmetric `bridge_axis_geometry` placement puts the bridge axis on one specific side of the chord. The user wanted the opposite side (visually reads better against neighbouring structure — bridge sits ON TOP of the join rather than UNDER it).

The fix: a single constant `_BRIDGE_PHASE_OFFSET = π` added to every bridge radial angle. Applied IDENTICALLY in two places that MUST stay in sync:
- `_bridge_boundary_radials` in `linker_relax.py` (used by `bridge_axis_geometry` to compute axis_start)
- `_emit_bridge_nucs` in `crud.py` (used to place every per-bp bead, both boundary AND interior)

If those two diverge, the rendered bridge sits in a different place than what the relax loss / debug overlay believes, and gaps look wrong.

To flip the bridge to the other side again, change `_BRIDGE_PHASE_OFFSET` between `0.0` and `π` (any value works mathematically — π is just the symmetric flip — but only `0` and `π` give sensible duplex geometry, since other values rotate the radials without flipping which strand is which).

Net geometric effect: the gap vector `bridge − anchor` exactly negates (same magnitude, opposite direction); the duplex itself is 180°-rotated around its own axis (still a valid B-DNA duplex).

### Critical gotchas summary

1. **Three anchor implementations must agree** — `_anchor_pos_and_normal` (linker_relax), `_anchor_for` inside `_emit_bridge_nucs` (crud), `_linkerAttachAnchor` (overhang_link_arcs.js).
2. **`bridge_axis_geometry` is the single source of truth for bridge axis math** — don't duplicate.
3. **Relax loss MUST be chord-magnitude-only** — folding boundary offset in creates a degenerate `chord ≈ 0` minimum.
4. **`_BRIDGE_PHASE_OFFSET` must match across `_bridge_boundary_radials` and `_emit_bridge_nucs`** — diverging breaks geometric self-consistency.
5. **`_optimize_angle` enumerates ALL grid minima for 1-DOF, not just the global** — there are typically two equivalent chord-minima per joint period; the smaller-|θ| one usually avoids cluster clashes.
6. **JS `_makeDsLinkerMeshes` only draws connector arcs** — re-adding bridge mesh synthesis double-renders.
7. **OH rotation must be co-applied to ALL binding-partner domains** (updated 2026-06-29) — `apply_overhang_rotation_if_needed` (deformation.py) builds the synthetic Layer-1 transform `domain_ids` from the OH domain PLUS every partner from `_overhang_binding_partner_refs` (renamed from `_linker_complement_domain_refs`). The predicate now matches **`d.binds_overhang_id == oh_domain.overhang_id`** (legacy `strand_type == LINKER` fallback), NOT strand type — so it co-rotates LINKER complements, standalone OH_BINDER strands, AND end-to-root binders spliced into a **STAPLE** strand (`apply_end_to_root_binder`; STAPLE-typed, so the old `strand_type == LINKER` filter missed them and they rendered un-rotated). A binder extending past the OH on the same helix (toehold) rides along because the domain mask uses the binder's OWN full bp range. Layer-2 (`_linker_complement_for_bp_range`, sub-domain θ/φ chains) is deliberately left LINKER-only (slice-truncation would shear a past-the-tip binder). Frontend live-preview parity: `ovhgBinderDomainIds` (design_queries.js, keyed on `binds_overhang_id`) is folded into all 4 orientation-panel preview sites via `domsForOverhang`. Regressions: `tests/test_overhang_linker_rotation.py` + `tests/test_overhang_binder_rotation.py` (OH_BINDER-with-toehold + end-to-root, both proven red under the old filter); `design_queries.test.js` (`ovhgBinderDomainIds`).
8. **`patch_overhang` extrude branch must look up junction bp from `design.crossovers`** — never assume "junction at helix bp_start". −Z extrudes have the junction at the helix's high bp end. Resize the *other* domain endpoint and rebuild axis around the invariant junction world-position. Regression: `tests/test_overhang_sequence_resize.py`.

# Hinge primitives (2026-06-25) — supporting detail

[Topic head](../../project_primitive_library.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Hinge primitives (2026-06-25)

Three SQUARE-lattice hinges: two rigid 2×N bundles (the leaves) separated by a 2-row gap,
joined across the gap by scaffold/staple crossover **links**. "single/double/triple" =
the number of cross-gap links (wider cross-section → more links):
- `2x2_single_hinge_link` — 8 helices (two 2×2 leaves), 1 link.
- `2x4_double_hinge_link` — 16 helices (two 2×4 leaves), 2 links.
- `2x6_triple_hinge_link` — 24 helices (two 2×6 leaves), 3 links.

Structure: `feature_log` = one `bundle-create` (cells e.g. `[[0,0],[0,1],[1,1],[1,0],
[4,0],[4,1],[5,1],[5,0]]`, length 40, plane XY, SQUARE) + a grouped follow-up op. As-saved
they have **`name=None`, no `primitive_kind`, no `description`, no camera_poses** → they'll
list in the catalog by file-stem with NO preview GIF. To make them first-class catalog
cards: set `metadata.name/description`, add camera_poses + `just build-primitives`, and (for
parametric placement) add a `primitive_kind="hinge"` branch (AF-12 P2c — not built; see
[[design-automation-loop]] / `design_automation_backlog.md`).

**The angle-confinement gap:** these primitives give hinge GEOMETRY only. Making a hinge
that a *linker confines to a specific angle* still needs headless linker creation +
linker-relax wrappers + a length→angle oracle — see the gap analysis below / handoff.

## Placement (2026-06-11)

Decisions (from the user): placement = **append the primitive's feature-log ops** onto
the current design (additive, revertable/editable — NOT a destructive new-bundle);
**anchor helix → cursor cell**; length **pre-filled from the primitive, editable**;
controls **inline in the Primitives panel**; **exit after one placement**.

Key collapse: both seed primitives are **single-op** designs — their whole
`feature_log` is one `bundle-create` whose params (`cells`, `length_bp`, `plane`,
`strand_filter`, `ligate_adjacent`, `lattice_type`) ARE the footprint. So placement of
a pure-extrusion primitive = one **`POST /design/bundle-segment`** (`addBundleSegment`)
— already additive + feature-logged (revert ↶ / edit ✎ both work). `bundle-create` (the
destructive reset sibling) is deliberately NOT used.

Pipeline: select card → read its `placement` spec → translate footprint so `anchor_cell`
lands on the hovered lattice cell → on click, `addBundleSegment({cells, lengthBp, plane})`.

**Backend** (`backend/core/primitive_catalog.py` + `routes_primitives.py`):
`derive_placement_spec(design)` (pure) reads the `bundle-create` op params (falls back to
helices' `grid_pos` + helix `length_bp`); returns `{cells, anchor_cell (min row→col),
length_bp, plane, strand_filter, ligate_adjacent, lattice}`. Attached as `placement` on
each `GET /primitives` entry (no new route). Tests in `test_primitives_router.py` (+5);
`test_lattice.py::test_bundle_segment_from_empty_design_builds_full_bundle` pins
segment-onto-EMPTY (first primitive into a blank workspace — no helix carries grid_pos →
zero offset → canonical positions).

**Frontend:**
- `scene/primitive_placement_logic.js` (NEW, pure, tested): `translateFootprint(cells,
  anchorCell, hoverCell)` (rigid shift; anchor→hover) + `latticeCompatible(designLattice,
  primLattice, designIsEmpty)` (empty accepts any; populated must match — no lattice mixing).
- `scene/slice_plane.js` (+118): a **placement mode** reusing the plane/lattice/snap/
  conflict machinery. `showPlacement(plane, spec)` (opens lattice via `show(...,{newBundle:
  true})` + arms), `setPlacementLength(bp)` (live ghost update), `isPlacement()`.
  `_updatePlacementPreview()` renders the footprint as ghost cylinders anchored at
  `_hoverCell` (reuses `_previewMeshes` pool + `_cellExtrudeConflict` red-flagging);
  `_commitPlacement()` translates + calls `onPlace` (blocks on conflict). Pointer handlers
  branch on `_placementMode` (move → ghost-follow, no lasso; up → clean-click commits;
  context-menu suppressed). Reset in `show()`/`hide()`.
- `ui/primitive_library.js` (+73): `_fromApi` carries `placement`; `_select` → `_enterPlacement`
  (lattice-compat guard via store; prefill plane+length; reveal `#primitive-placement`;
  `placement.enter(spec)`); plane dropdown → re-enter; length input → `placement.setLength`;
  Cancel/`exitPlacement()` tear down (clear highlight + hide controls). New API method
  `exitPlacement` (host calls after commit). Deps add `placement:{enter,setLength,cancel}`.
- `index.html`: `#primitive-placement` block (name + `#primitive-plane` XY/XZ/YZ dropdown +
  `#primitive-length` input + Cancel), hidden until a primitive is selected.
- `main.js` (+35, pure wiring): slicePlane `onPlace` (→ `addBundleSegment` + `exitPlacement`
  + hide) + the `placement` dep adapters (enter→showPlacement, setLength→setPlacementLength,
  cancel→hide) + mode-indicator text. `keyboard_shortcuts.js`: Escape in the slice-plane
  branch also calls `primitiveLibrary.exitPlacement()` when `isPlacement()`.

**Honeycomb parity snap (2026-06-11, bug fix).** Arbitrary integer (row,col) translation
does NOT preserve a honeycomb footprint's shape: the cell carries a parity term
`(row+col)%2` that sets BOTH the y-stagger (`honeycombCellWorldPos` / `honeycomb_position`)
AND the scaffold FORWARD/REVERSE direction (`scaffold_direction_for_cell`). A shift with
**odd `dRow+dCol`** flips every cell's parity → distorts the shape (a closed 6hb ring
collapses toward an "I") AND inverts each helix's polarity. **Rule: a honeycomb placement
is valid iff the hover cell has the SAME `(row+col)` parity as the anchor** (= even shift);
square has no stagger → any cell. Enforced by snapping the raw hovered cell to the nearest
same-parity cell: `validParityCandidates(rawCell, anchorCell, lattice)` (pure — returns the
cell itself if valid, else its 4 edge-neighbours which all flip back to anchor parity) +
`placementPreservesShape(anchorCell, hoverCell, lattice)` in `primitive_placement_logic.js`;
`slice_plane.js` `_snapPlacementCell(raw)` picks the candidate nearest the cursor's
plane-intersection (`_cursorPlanePoint`). Applied in `_onPointerMove` before the ghost.

**Verified:** `just smoke` green; backend 1924 passed/31 skipped; frontend 1202 passed
(incl. `primitive_placement_logic.test.js` +1 file, `primitive_library.test.js` +7 placement
tests). Two throwaway e2e probes (removed after) drove the **real raycast**: (1) select 6hb →
click a lattice cell **committed 6 new helices** + exited placement, zero errors; (2) across
many click points (incl. wrong-parity targets) the committed anchor **always kept parity 1**
(even shift) → never the distorted "I". So the live gesture + the parity snap are verified.

**Validation tests:**
- `frontend/.../primitive_placement_logic.test.js` (15): translateFootprint, latticeCompatible,
  `placementPreservesShape` (even allowed / odd rejected / square any), `validParityCandidates`,
  + a **shape-congruence** test (6hb `relShape` equal under even shift, differs under odd).
- `tests/test_primitive_placement.py` (13): derive-spec on the real 6hb; segment-into-empty
  builds the footprint + **revertable**; additive-over-existing; parametrized **even-shift
  preserves cross-section geometry + per-helix polarity** vs **odd-shift distorts + flips
  polarity**; built-segment geometry congruent to the predicted shape.
- `tests/test_primitives_router.py` (+5 placement-spec); `tests/test_lattice.py`
  (segment-from-empty).

**Deferred (architecture leaves room):** ~~multi-op feature-log replay~~ (shipped
HEADLESS as AF-35, 2026-06-27 — see below), SQUARE + other lattices, non-origin **face**
selection, footprint rotation. The `placement` spec + the `derive_*` seam generalize.

**Headless multi-op placement (AF-35, 2026-06-27) — backend/core, not the GUI yet.**
`backend/core/primitive_placement.place_primitive_into` + `hb.place_primitive(name, *,
anchor_cell, plane)` place a WHOLE hinge (or any helices/strands/FL/cluster primitive) into
a design. **User decision: preserve the primitive's scaffold/FL routing VERBATIM** → built
as a rigid GRAFT (copy the primitive's own geometry + translate by one lattice vector +
remap ids), NOT a feature-log op-replay (a replay routes through `bundle-segment`, a
different builder → AF-30 ISSUE-13 axis drift). Pinned by `assert_primitive_placed`
(additive + anchored + verbatim + FL/cluster survived). This is the HEADLESS path; the GUI
placement pipeline is still single-op (`bundle-segment`) — wiring the graft into the
frontend placement flow is a future follow-up.

## Parametric circle (flat disc) — 2026-06-11

A "circle" is a flat **disc**: one row of SQUARE-lattice helices whose **lengths**
trace a circular chord profile (disc lies in the plane *containing* the helix axis,
one helix-layer thick). `small_circle.nadoc` flagged `metadata.primitive_kind="circle"`.

User decisions (asked + locked): **emit final geometry** (NOT resize-replay — the
hand-built example's 43 trial `strand-end-resize` ops are skipped; the generator lays
down final per-column lengths directly); **min-chord cutoff** (floor 16 bp, even-bp
symmetric trim, centred ON a column → odd N → true diameter helix); **reuse
small_circle** as the card with default radius = `fit_radius` of its helices (~10.4 nm).

Follow-ups (2026-06-11, same day): **(1)** card is named **"Circle"**, no lattice in the
description/meta (`derive_metadata` circle branch → name="Circle", short="DISC",
desc="Flat disc — set the radius"; `_fromApi` meta="Disc · variable radius"). **(2)**
**lattice-agnostic** — `make_circle_segment` already builds into `design.lattice_type`
(cells are bare row/col), so the circle places into HONEYCOMB *or* SQUARE; frontend
`_isCircle` skips the `latticeCompatible` guard and `_specFor` sets the snap
`latticeType` = the DESIGN's lattice. **(3)** disc placed **tangent to the plane, all in
+bp** (was bisected): `make_circle_segment` shifts every (centred) helix up by R =
`max(cell_lengths)·rise/2`, so the disc spans `[offset, offset+2R]` and its lowest point
touches the plane. Preview ghost + `_cellExtrudeConflict(...,centerNm)` match the shift.

Follow-ups #2 (2026-06-11, after user re-saved the file with gif poses):
- **`primitive_kind` is now a REAL `DesignMetadata` field** (`models.py`), default None.
  CRITICAL: storing it as a freeform metadata key was fragile — the app's load→save
  round-trip (through the Pydantic model) DROPPED it, silently reverting the circle to a
  fixed 9-helix bundle. As a real field it persists. Pinned by
  `test_primitive_kind_survives_design_roundtrip`. **If the circle ever stops being
  detected, check the file still has `metadata.primitive_kind:"circle"`.**
- **Anchor on the CENTRE column** (`circle_footprint`/`circleFootprint` →
  `anchor_cell=[0,(N-1)//2]`, the longest chord), so the cursor sits at the disc's
  **tangent point** with the plane (where it touches), not at the first helix.
- The hand-built circularity baseline in `test_circle_primitive.py` is now a HARDCODED
  constant `HAND_BUILT_BASELINE=[16,32,54,60,64,64,60,54,32,16]`, NOT read from the file
  — the user regenerates `small_circle.nadoc` with the (clean) generator, so it's no
  longer a wobbly baseline. Re-bake gifs with `just build-primitives` when poses change.

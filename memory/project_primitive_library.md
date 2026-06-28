# Primitive library ("Add Primitive") — topic

Pre-validated DNA-origami building blocks offered in the part editor's right
sidebar. Tools → Add Primitive reveals a collapsible **Primitives** panel
(`#primitives-panel`) listing each primitive as a card: rendered thumbnail +
name + "NHB" badge + short description + "Honeycomb · N helices" meta.

## Status

- **Shipped 2026-06-11 (UI shell):** panel + live catalog + animated hover previews.
- **Shipped 2026-06-11 (placement):** selecting a card now **arms placement** — the
  primitive's cross-section drops onto the lattice as an **additive, feature-logged,
  revertable** extrude. See "Placement" below.
- **Shipped 2026-06-11 (parametric circle):** a `metadata.primitive_kind="circle"`
  primitive (`small_circle.nadoc`) places as a **flat disc of variable radius** — a
  radius-nm box instead of a length box. See "Parametric circle" below.
- Seed primitives: **6hb + 18hb beams + small_circle (disc)** in `workspace/Primitives/`.
- **Hinge primitives (added by user 2026-06-25):** `2x2_single_hinge_link`,
  `2x4_double_hinge_link`, `2x6_triple_hinge_link` in `workspace/Primitives/`. See
  "Hinge primitives" below. **These are THE canonical building blocks for any hinged
  component** — whenever a design (or text-to-DNA request) calls for a hinge, start from
  one of these rather than hand-routing a new one.

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

- **Geometry core** = `backend/core/circle_primitive.py` (pure: `column_lengths`,
  `circle_footprint`, `implied_radii`, `circularity_spread`, `fit_radius`,
  `DEFAULT_MIN_CHORD_BP=16`), **mirrored** in `frontend/src/scene/circle_primitive_logic.js`.
  Both pinned to the SAME oracle (R=10.6 → `[34,48,56,62,62,62,56,48,34]`) so live
  preview == server build. Request carries client-computed `cells` + `cell_lengths`.
- **Builder** `lattice.make_circle_segment(d, cells, cell_lengths, plane, offset, filter)`
  — like `make_bundle_segment` but per-cell length + centred. **Route** `POST
  /design/circle-segment` (`add_circle_segment`, op_kind `circle-segment` — registered
  in `models.py SnapshotOpKind`). Additive, feature-logged "Place circle", revertable.
- **Catalog** `derive_placement_spec` branches on `primitive_kind`: a circle returns
  `_circle_placement_spec` = `{kind:"circle", lattice, plane, default_radius_nm,
  min_chord_bp, anchor_cell}` (no fixed cells — generative). Passed through `GET
  /primitives` verbatim (router spreads `**meta`).
- **UI:** `index.html` adds `#primitive-radius-row`/`#primitive-radius` (hidden by
  default). `primitive_library.js`: `_isCircle` → swap Length row for Radius row,
  prefill `default_radius_nm`; `_specFor` computes `circleFootprint(radius)` → spec with
  `cellLengths` + `centered`; radius `input` → `placement.setCircle` →
  `slicePlane.setPlacementCircle` (live ghost). `slice_plane.js`: `_placementSpec` gains
  `cellLengths`/`centered`; `_updatePlacementPreview` draws each column at its own length
  centred (no `+dir·len/2`); `_cellExtrudeConflict(...,centered)` checks the ±L/2 span;
  commit passes `cellLengths`. `main.js` (+5, pure wiring): `onPlace` branches
  `cellLengths ? addCircleSegment : addBundleSegment`; `setCircle` dep adapter.
  `client.js`: `addCircleSegment`.
- **Circularity** = spread of per-column implied radius `√(x²+(L/2)²)`; generator beats
  the hand-built ~1.23 nm baseline ~5–25× (≈0.05–0.29 nm). Constants: SQUARE col pitch
  **2.25 nm** (constants.py `# = 2.6` comments are STALE), rise 0.334.
- **Tests:** `tests/test_circle_primitive.py` (20: geometry invariants, circularity vs
  baseline, centred/additive/revertable placement, catalog spec) + `frontend/.../
  circle_primitive_logic.test.js` (7, same oracle). `just test` 1999 passed; frontend
  1209 passed; lint Δ0. **Live gesture/visual NOT hand-checked → MV-CIRCLE** (server
  unreachable via localhost under WSL this session).
- **Deferred:** HONEYCOMB circles, multi-op replay, face-pick, rotation.

## Add a primitive onto an existing part's FACE — 2026-06-11

Place a primitive onto a blunt-end face of an existing part = "extrude from a blunt end,
but with the primitive's predetermined cells." User decisions: face = **click a blunt-end
ring** (reuse the domain-end pick); topology = **mixed continue+fresh** (cells over an
existing helix-end EXTEND it, empty cells → fresh helices — exactly `make_bundle_
continuation`); scope = flat end faces + 6HB/18HB beams (+ Circle-on-face and bent/deformed
faces selected but DEFERRED).

Shipped this round = **beam on a FLAT end face**. Reuses the existing `bundle-continuation`
route — **no backend change**. Frontend wiring only:
- `main.js` isDisabled: relaxed to `slicePlane.isVisible() && !slicePlane.isPlacement()` so a
  blunt-end ring click can reach `onDomainEndClick` *during placement* (capture-phase: the
  slice plane only consumes clicks that hit its own meshes, so a ring click falls through).
- `main.js` onDomainEndClick: `if (slicePlane.isPlacement()) _bluntMenus.placeOnEnd(info)
  else showPanel(info)`.
- `blunt_end_menus.js` `placeOnEnd(info)`: mirrors `_bluntExtrude`'s targeting (continuationBp
  = `bp + max(0, openSide)`, dir = openSide) but arms placement via
  `slicePlane.showPlacementAtEnd` instead of the extrude panel. Bent face (hasDeformations &&
  deformVisuActive) → toast "not supported yet".
- `slice_plane.js`: `_endPlaneOffset(helixId, diskBp)` extracted (shared by showAtEnd +
  showPlacementAtEnd). `showPlacementAtEnd(helixId, diskBp, {defaultDirSign})`: captures
  `_placementSpec`, `this.show(plane, offset, true)` (continuation lattice — wipes placement),
  re-arms `_placementSpec={...spec, continuation:true, plane}`, `_setDirSign(openSide)`.
  Returns false for a circle (cellLengths) — not on faces yet. Preview dir =
  `continuation ? _extrudeDirForCell() : _placementDir`. Commit signs the length by
  `_sliceDirSign` and adds `continuationMode:true` to the onPlace payload.
- `main.js` onPlace: `continuationMode ? api.addBundleContinuation : cellLengths ?
  addCircleSegment : addBundleSegment`.

**Bug found + fixed same session (ring-click swallowed).** First cut didn't work: the
slice plane's placement pointerdown consumed the click via `_rayAnyCells()` — the origin
lattice cells sit at the SAME screen positions as the part's blunt-end rings, so the ring
click never reached `onDomainEndClick`. Fix: slice_plane now YIELDS the pointerdown to the
ring pick when `_placementMode && !continuation && getBluntEnds().isRingHit(e)` (returns
without `stopImmediatePropagation`, so domain_ends' capture handler picks the ring +
retargets; its pointerup `stopImmediatePropagation` then suppresses the stray commit). Once
on a face (`continuation` true) clicks commit normally — rings stop stealing them.
`domain_ends.isRingHit(e)` (+ `getEndScreenInfo` for e2e) added; `slice_plane` gets a lazy
`getBluntEnds` dep.

Verified: vitest 1209 green + the **gesture is e2e-verified** —
`frontend/e2e/primitive_face.spec.js` drives the real raycast (arm → ring-click flips slice
to continuation → click grows helix count, zero console errors). New dev hooks
`__nadocTest.getDomainEndScreenPositions()` + `getSliceState()`. Live "ghost looks right on
the face" remains **MV-PRIM-FACE** (Tier-3 visual).

### Bent/deformed faces — 2026-06-11 (shipped, e2e-verified)
Same gesture on a BENT end. `blunt_end_menus.placeOnEnd`: when `hasDeformations &&
deformVisuActive`, fetch `api.getDeformedFrame(continuationBp, helixId)` →
`slicePlane.showPlacementDeformed(frame, {plane, refHelixId, defaultDirSign})` (mirror of
showPlacementAtEnd but via `showDeformed`). slice_plane now deformed-aware in placement:
`_placementCellWorldPos(row,col)` = `_deformedFrame ? _cellWorldPosDeformed : cellWorldPos`
(ghost + parity-snap nearest-pick); `_cursorPlanePoint` intersects the deformed plane
(axis_dir @ grid_origin); commit adds `deformedFrame`+`refHelixId` to the onPlace payload;
`main.js` onPlace routes `continuationMode && deformedFrame →
api.addBundleDeformedContinuation`. Conflict check is already a no-op in deformed mode.
Reuses the shipped deformed-continuation backend (no backend change). `slicePlane.isDeformed()`
+ `getSliceState().deformed` added for the e2e. Verified by the bent test in
`primitive_face.spec.js`. **Only Circle-disc-on-face remains deferred** (new route +
tangent-vs-dome geometry decision — ASK before building).

**Bug found + fixed (2026-06-11, soup.nadoc):** a LARGE footprint on a bent end (18hb on a
6hb → mostly FRESH cells) collapsed to a single 45° row. The deformed-continuation path was
only ever exercised with all-continuation cells before; fresh cells exposed a latent
deformation-geometry bug — fresh helices' `h_XY_{r}_{c}` ids get `grid_pos` back-filled, so
`_normalize_helix_for_grid` canonicalised their (deliberately bent) axis to straight-+Z and
the bend re-applied → collapse. Fixed in `deformation.py` (`_normalize_helix_for_grid` now
preserves a helix whose stored Z deviates >1 nm from canonical). Full detail in **LESSONS E6**;
pinned by `tests/test_deformed_continuation_pose.py`. Visually confirmed on soup.nadoc (proper
wide 18hb bundle, not a sheet).

### Suppress origin grid on an existing structure — 2026-06-11
On an EMPTY workspace, arming a primitive shows the origin grid immediately (only way to
start). On a NON-EMPTY design, the origin grid is SUPPRESSED — the user must pick an origin
plane from the dropdown OR click a blunt end. New slice_plane state `_placementArmed`
(armed-but-no-grid): `armPlacement(spec)` records the footprint without showing anything;
`isArmed()` (true across the wait, vs `isPlacement()` = grid actually shown);
`disarmPlacement()` for Cancel/Esc. `main.js` onDomainEndClick now branches on `isArmed()`
(not isPlacement) so a blunt-end click retargets even with no grid shown; the placement dep
gains `arm`; `keyboard_shortcuts` Esc branch extended to `isVisible() || isArmed()`.
`primitive_library._enterPlacement`: empty → `placement.enter` (grid); non-empty →
`placement.arm` + blank the plane dropdown (`selectedIndex=-1`) so any pick fires change →
enter. All 4 paths e2e-pinned in `primitive_face.spec.js` (empty-shows-grid, dropdown-shows-
grid, ring-retarget flat, ring-retarget bent). `getSliceState().armed` added. **Deferred follow-ups:** bent/
deformed faces (needs deformed-aware placement ghost + `bundle-deformed-continuation` route;
`showPlacementDeformed` not built) and **Circle-disc-on-face** (needs a new `circle-
continuation` route AND a geometry decision — a tangent disc on a face leaves outer helices
floating above it; likely wants "each helix extends from the face by its chord length"=dome
instead — ASK before building).

## Architecture

- **Catalog source (temporary):** backend scans `workspace/Primitives/*.nadoc`
  live. `backend/core/primitive_catalog.py` (pure: `derive_metadata`,
  `list_primitives`, path helpers — metadata auto-derived from the design; a
  design `name` equal to the file stem is ignored so it shows "6-Helix Bundle"
  not "6hb_primitive"). Router `backend/api/routes_primitives.py`: `GET
  /primitives`, `GET /primitives/{id}/preview.gif`, `…/poster.png` (FileResponse).
  Registered in `main.py`. **Better future solution documented but NOT built:**
  in-repo `primitives/<id>/` registry + `manifest.json` — see
  `workspace/Primitives/README.md`.
- **Hover preview pipeline:** `just build-primitives` →
  `frontend/scripts/build-primitives.mjs` (Playwright) loads each design in the
  real app, drives the camera through its **saved camera poses** (ping-pong loop,
  eased), captures frames, encodes a **GIF** (+ first-frame poster PNG) written
  next to the `.nadoc`. Re-run after editing a design/poses.
- **Capture core:** `frontend/src/scene/primitive_preview_capture.js` —
  `buildCameraPath(poses,…)` is the pure, unit-tested planner;
  `capturePosesGif({renderer,…})` renders + grabs in the SAME tick (the
  `export_video.js` pattern → **no `preserveDrawingBuffer` needed**) and encodes
  with the already-bundled `gifenc`. Driven by a DEV-only hook
  `window.__nadocTest.capturePrimitivePreview(opts)` (main.js).
- **Encoder choice:** GIF now (zero new deps — gifenc was already present). The
  encode is isolated in `capturePosesGif`, so swapping to **animated WebP** later
  = change there + the file extension in the baker + the served media type.
  (User picked WebP, but no webp encoder is installed; chose GIF-now to ship.)
- **Panel:** `frontend/src/ui/primitive_library.js` `initPrimitiveLibrary({store,
  api})`. Renders the static `primitive_catalog.js` fallback immediately, then
  upgrades in place from `api.listPrimitives()`. Cards show the poster `<img>`
  that swaps `src` → `preview.gif` on `mouseenter`, back on `mouseleave` (never
  autoplay a wall of GIFs). No preview → inline SVG cross-section schematic
  (`primitiveThumbSvg`). main.js gains only imports + factory init + the
  `menu-tools-add-primitive` handler (module-first; LOC Δ pure wiring).
- **Hover zoom (2026-06-11):** hovering a card ALSO shows a larger preview pinned
  to the **upper-right of the workspace** — a `position:fixed` `#primitive-preview-zoom`
  div (created in `primitive_library.js`, appended to body, `pointer-events:none`).
  `_positionZoom` anchors it against `#viewport-container`.right (just left of the
  right panel, near the cursor) and `#filter-view-strip`.bottom+12 (below the
  selectable strip), size-constrained to the visible workspace so it never spills
  over the left sidebar. Shows
  `preview_url` (animated) → `poster_url` → SVG schematic, with a name caption.
  Dismissed on `mouseleave` and in `hide()`.

## Gotchas / notes

- Build script uses a **unique `?doc` per primitive** (fresh page each) so the
  "wait for backboneSpheres count>0" readiness check starts from 0 — reusing one
  doc would pass instantly on a stale prior design.
- Loads a design by POST `/api/design/load` {path: "workspace/Primitives/…"} +
  a `new BroadcastChannel('nadoc-design')` `design-changed` msg carrying
  `docId` (mirrors `scene_harness.loadScaffoldedPart`). The welcome overlay is
  DOM-only — it doesn't taint canvas pixel capture.
- Posters currently include the origin axes helper (yellow/green/blue lines) when
  visible in the scene — minor; a future polish could hide axes before capture.

## Tests

- Backend `tests/test_primitives_router.py` (9): derive_metadata (incl. stem
  ignore), scan/sort/skip-broken/asset-flags, list + asset-serve + 404 + safe-id.
- Frontend: `primitive_catalog.test.js`, `primitive_library.test.js` (fallback →
  API upgrade, poster thumb, hover swap, selection survives re-render),
  `primitive_preview_capture.test.js` (buildCameraPath).

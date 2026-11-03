# Parametric circle (flat disc) — 2026-06-11 — supporting detail

[Topic head](../../project_primitive_library.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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

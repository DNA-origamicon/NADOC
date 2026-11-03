# ⚡ Field direction: rotation RINGS + Az/El inputs (replaces tip-drag + xyz boxes) — 2026-07-16 (out-of-session work) — supporting detail

[Topic head](../../project_oxdna_efield.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ⚡ Field direction: rotation RINGS + Az/El inputs (replaces tip-drag + xyz boxes) — 2026-07-16 (out-of-session work)

- **`scene/efield_gizmo.js` rewritten.** Direction is set by dragging three great-circle rotation rings
  — "Match the cluster rotation tool exactly: TransformControls in rotate-only, world-space mode,
  attached to a dummy at the field origin." The draggable tip `_handle` + the `rayPlaneVector` drag path
  are DELETED. **Dragging no longer changes magnitude.** New API: `setDirection`, `setArrowLength`,
  `setControlsVisible`, `setOffset`.
  - **BREAKING: `getVector()` now returns a UNIT direction, not dir×length** (`setVector` splits the
    magnitude into `_arrowLength`).
  - Far-zoom cap via an override of `_helper.updateMatrixWorld`: TransformControls keeps rings a
    constant SCREEN size, which at large camera distance makes them enormous in world units — its
    screen-size setting is reduced only once a ring would exceed 25 nm diameter (geometry has unit
    radius, scaled by `factor*size/4`, so diameter = `factor*size/2`). Arrow capped at
    `_MAX_ARROW_LENGTH_NM = 25`.
- **`ui/forces_card.js`: Az/El degrees (5° steps)** replace the x/y/z boxes. The DOM is REUSED, not
  replaced — the legacy three Cartesian boxes become a spherical editor and `dirZ` is hidden
  (`display:none`, pinned `'0'`) but still in the DOM. Elevation clamps to ±90°; `_dirFromAngles` snaps
  |v|<1e-12 to 0 so payloads stay exact (`[0,0,1]`).
- **Collapsible "Arrow offset (nm)" is COSMETIC and must never reach the payload** — pinned by
  `expect(api.getFieldSpec()).not.toHaveProperty('offset')`. Plus a "Show rotation controls" checkbox
  (default on) that hides the rings while keeping the arrow.
- Magnitude/direction split is now strict: "Ring drag changes direction only. Magnitude remains
  exclusively controlled by the force input" (the `pnForArrowLen` import is gone; `setOnChange` no
  longer writes `_pN`).

Sibling of [[project_oxdna_relaxation]]. Goal: subject a relaxed DNA-origami model to a
(quasi-static) electric field in oxDNA, holding part of the structure with anchors so the
rest deflects, then visualize the deflection. Three-Layer Law holds throughout: field results
are **Physical-layer display only**, never written back to topology.

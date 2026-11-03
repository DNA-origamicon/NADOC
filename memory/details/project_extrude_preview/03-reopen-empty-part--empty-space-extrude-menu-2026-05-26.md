# Reopen-empty-part + empty-space "Extrude" menu (2026-05-26) — supporting detail

[Topic head](../../project_extrude_preview.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Reopen-empty-part + empty-space "Extrude" menu (2026-05-26)

Two entry points to the new-bundle plane-picker (`workspace.show(lattice)` → `onPlanePicked('XY')`
→ slice plane in `newBundle` mode — the "initial extrude operation"):

1. **Empty part reopens into the plane-picker.** A part created but never extruded (0 helices),
   saved + closed, now reopens straight into the workspace grid instead of an empty scene.
   `main.js _revealWorkspaceForEmptyPart()` (defined just after the `workspace` init) replaces the
   bare `workspace.hide()` in the two part-load paths — `_openPartFromServer` (covers File>Open,
   library panel, and the `?open=` boot action) and the recent-file menu loader. It calls
   `workspace.show()` when `currentDesign.helices.length === 0 && !assemblyActive`, else `hide()`.
   Observable signal: `#mode-indicator` becomes `NEW BUNDLE — select cells · …`. (The existing
   non-empty→empty subscriber at ~`main.js:3319` already handles "deleted last helix"; this adds the
   "reopen already-empty" case it can't see, since prevCount is also 0.)

2. **Right-click empty 3D space → minimal "Extrude" menu.** New `#empty-space-ctx-menu` (one
   `#empty-extrude-btn`, in index.html next to `#slice-ctx-menu`). selection_manager gained an
   `onEmptyContextMenu(x,y)` opt, invoked at the END of its `contextmenu` handler — the
   `if (_mode === 'none' || !_strandId)` fall-through, i.e. the right-click hit NO pickable
   geometry (cone/bead/arc/overhang) AND nothing is selected. (A *selected* strand still shows its
   own color menu on empty right-click — unchanged.) main.js's callback guards: skip if
   `assemblyActive` or `slicePlane.isVisible()` or `workspace.isVisible()` (so it never doubles the
   slice/workspace flow). The menu's Extrude calls `_startEmptySpaceExtrude()` → `_extrudePanel.activate('newBundle')`.

   **ADDITIVE empty-space extrude (2026-06-20 — replaces the old destructive guard).** Empty-space /
   Tools→Extrude no longer wipes a populated part. The destructive `showConfirm` ("Start a new bundle? …
   replaces the current part") in `_startEmptySpaceExtrude` is GONE. The routing now lives in `onExtrude`
   (main.js): `freshBundle = newBundle && helices.length === 0`. Only an EMPTY workspace routes to
   `api.createBundle` (`POST /design/bundle`, which `clear_history()` + resets); with a part already present
   the new-bundle extrude falls through to `api.addBundleSegment` (`POST /design/bundle-segment`, append-only,
   reads lattice from the existing design) — a fresh, disconnected set of helices in the SAME design. The
   slice-plane's existing per-cell conflict guard (`_anySelectedConflict`, red ghost) still blocks cells that
   overlap existing DNA, so the user picks empty lattice cells. Post-processing: freshBundle resets
   `unfoldHelixOrder`; additive appends to it (the segment branch). The `newBundle` UI flag (clean lattice,
   no slab/handle) is unchanged — it's a UI affordance, decoupled from the reset semantics. Frontend-only;
   backend `bundle-segment` append path already tested (`test_extrude_segment_appends_fresh_disconnected_helices`).
   Live gesture (right-click empty space on a populated part → pick cells → build → existing structure intact +
   new bundle added) = **MV-EXT-ADD**, canvas-raycast / human-eye only.

## Minus-extrude backend bug (fixed 2026-05-25)

The preview surfaced a real **backend** bug: a minus (−axis) extrude created a helix
whose **axis pointed −Z but whose nucleotides rendered on the +Z side** ("axis arrows
right, helices wrong"). Root cause: `make_bundle_design` / `make_bundle_segment` /
`make_bundle_continuation` stored `length_bp` as the positive magnitude but baked the
sign only into `axis_end` (so `axis_end < axis_start`), while the geometry normalizer
`_normalize_helix_for_geometry` (deformation.py, the shared CG/atomistic/deform decision
point) derives bead z from `bp_start + length_bp` (canonical +) — so beads landed on the
+side, opposite the stored axis used for `helix_axes`/arrows.

Fix (user chose "canonical helix below the plane"): those three helix-creation sites now
store a **canonical** axis — `axis_start` = lower coordinate, `axis_end` = higher —
spanning `[offset+min(0,L·rise), offset+max(0,L·rise)]`. So −L places the helix in
`[offset−|L|, offset]` (below the plane) as an ordinary +axis helix; `bp_start` (from
`_helix_global_bp_start`) then comes out negative for a new bundle at offset 0
(e.g. −42 → bp_start=−42, beads z∈[−14,0]). Verified: `+42`→beads above, `−42`→beads
below; 1481 backend tests pass. Six negative-length tests in `tests/test_lattice.py`
were updated from the old `axis_end<axis_start` convention to the canonical one.
The arrow now points +Z (canonical) for a minus helix — the DNA region (not the arrow)
is what matters and it matches the preview.

Verification note: directions verified in-app via Playwright, including a cross-check
that the continuation ghost's sign equals the actual `addBundleContinuation` extrude
sign (new-bundle +dir→+Z; near-end continuation→away from body; far-end→away the other
way; ghosts cleared on hide). Overhang path earlier verified via a temporary
`window.__TEST_openOverhang` hook (the right-click→contextmenu arrow path doesn't
propagate through OrbitControls under headless — it is a shipped real-app interaction).
All temp probes/hooks removed after.

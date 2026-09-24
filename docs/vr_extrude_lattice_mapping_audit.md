# VR Extrude lattice mapping audit — 2026-09-22

## Conclusion

**Frame candidate increment (2026-09-22):** explicit lattice-frame records and
helix references now persist, with an isolated independent-bundle candidate builder
using existing rigid clusters. Membership lookup keys frame + cell. Cadnano export
packs explicit frames into separate bands and discloses pose loss; same-frame
segment consolidation and editor/neighbor/continuation consumers remain unfinished.
This is not yet a VR commit path. Current details and evidence are in
[the active authoring campaign](vr_authoring_workflows.md#lattice-frame-candidate-increment-2026-09-22).
The table below records the original audit baseline, not completion of the refactor.


**First increment implemented (2026-09-22):** native VR now has an `EXTRUDE FROM`
control cycling XY/XZ/YZ. The scene carries a canonical source-plane default and lattice
type. Desktop's existing dropdown now resolves the loaded part. Known native helix
source-plane IDs take precedence; otherwise unanimous axis-aligned rest geometry
determines the plane. Mixed/oblique geometry is explicitly a fallback (XY in a new VR
scene, current valid UI plane on desktop). This selects a draft source plane; it does
not implement placement or commits. The gaps below still apply.

The approved future Freeform contract is canonical-plane topology plus a persisted
rigid placement transform matching the user's pose. Blunt-end and freeform options
remain unavailable until implemented. Independent-frame cell ownership and export
collision handling remain prerequisites for committing freeform beside existing geometry.

Arbitrarily oriented VR extrusion is not currently an end-to-end authoring feature.
The painted footprint is a native draft; even the separate existing-end continuation
descriptor only preflights. A targeted coordinate/ownership refactor and commit adapter
are needed. Reuse the existing topology, lattice builders, rigid transforms and feature
history rather than introducing VR-specific helices or rewriting the geometry engine.

## Findings from current code

| Boundary | Current behavior | Consequence |
|---|---|---|
| Native footprint | `ExtrudeLatticeDraft` in `native/vr_viewer/src/interaction.hpp` stores integer cells. `main.cpp` paints and observes the draft. | No persistent frame/part ownership or bundle commit for the painted cells. |
| Native lattice math | `latticeCellOffsetNanometers` uses the same square and cadnano-style honeycomb displacement/parity as desktop `slice_plane/lattice_math.js` and backend `lattice.py`. | Reuse and cross-check these formulas; panel placement alone does not assign design coordinates. |
| Existing-end VR operation | `vr_tool_context.js` resolves one end/cell; `vr_tool_execution_plan.js` accepts XY/XZ/YZ and rejects transformed/deformed targets. | An existing rigid cluster rotation currently triggers the deformed-frame refusal. |
| Commit | `frontend/src/main.js` handles `commit_requested` for Move/Rotate; other tools explicitly say their mutation executor is not attached. | The successful paint/wheel tests did not create DNA. |
| Backend new segment | `make_bundle_segment` accepts cells, axial offset and XY/XZ/YZ. Its transverse origin comes from the first helix with grid metadata. | No arbitrary placement frame; origin selection is not scoped to a chosen bundle. |
| Persistent model | `Helix.grid_pos`, `bp_start`, direction and strand domains encode logical addresses; `ClusterRigidTransform` stores rotation/translation independently. | Standard cell editing can survive a rigid 3D pose. The model has no explicit per-helix lattice-frame identity. |
| Membership | `crud._origins_by_grid_pos` matches new helices to old ones by cell alone. | A new independent bundle can inherit an unrelated existing cell's cluster. |
| Cadnano slice editor | `sliceview.js::_activeMap` keys by `row:col`. | Distinct helices in different planes/frames at the same cell overwrite one another in this map. |
| Other consumers | Crossover lookup also builds cell-keyed maps; cadnano export prefers `grid_pos`. | Fixing only the VR payload or slice view is insufficient. |

## Executed checks

In-memory probes used the real backend builders, model JSON serialization and exporter;
no user part or live viewer was mutated.

Existing `vr_tool_context.test.js` and `vr_tool_execution_plan.test.js`: **18 tests
passed across two files**. These verify the current context/preflight contract, not
the proposed arbitrary-frame authoring workflow.

- HC and SQ: build two XY helices at `(0,0)` and `(0,1)`, then append an XZ
  segment at `(0,0)`. All three helices persist, but export has only two unique
  cells: HC `[(15,15),(15,15),(15,16)]`; SQ `[(25,25),(25,25),(25,26)]`.
  This confirms ambiguous exported placement. Slice-view overwriting was established
  by inspecting its map implementation, not by claiming a live editor exercise.
- Both lattice types reject `plane='OBLIQUE'` with a ValueError listing XY/XZ/YZ.
- Both lattice types: a 37° Y rotation and translation `[12,-4,8]` on an existing
  cluster survive `Design.model_dump_json()` / `Design.model_validate_json()`.
  Cell addresses remain unchanged and cadnano export equals the unrotated export.
  This proves model-level preservation, not full filesystem/UI roundtrip validation.

Reproduce the collision with:

```python
from backend.core.models import Design, LatticeType
from backend.core.lattice import make_bundle_segment
from backend.core.cadnano import export_cadnano

d = make_bundle_segment(Design(lattice_type=LatticeType.SQUARE), [(0, 0), (0, 1)], 32)
d = make_bundle_segment(d, [(0, 0)], 32, plane="XZ")
print([(v["row"], v["col"]) for v in export_cadnano(d)["vstrands"]])
```

## Required coordinate contract

Keep the viewing tablet pose separate from the authored extrusion frame. Tilting the
tablet to inspect a footprint must not silently rotate an already anchored bundle.
Show the authored origin, axes and preview on the part so the distinction is visible.

Logical identity should resolve through the selected part/document, lattice frame,
cell `(row,col)`, helix identity/segment and bp interval. Cell identity alone cannot
distinguish independent bundles or disjoint axial segments on one lattice line.

Use one authoritative transform chain:

`lattice-local nm → part-rest nm → instance/cluster pose → viewer normalization → OpenXR metres`

Invert the applicable chain for controller placement; do not store stage coordinates,
viewer scale, recentering or diagnostic tablet tilt as molecular lattice coordinates.
Transform orientations with the rigid rotation, independently of scale. Assembly
instances require explicit target ownership and instance transform inversion too.

Support two explicit authoring modes:

1. **Extend a selected lattice:** resolve its frame and open end, map the gesture into
   that local frame, and retain its cell/bp convention. A rotated part must not force
   global-axis snapping. Existing deformed-continuation machinery is a reuse candidate,
   but requires separate review for non-rigid frames and inherited transforms.
2. **Create a separately oriented bundle:** construct standard local lattice topology,
   persist its frame and chosen rigid placement, and scope occupancy/membership to it.
   Do not infer ligation or crossover adjacency merely from reused local cell numbers.

A dedicated lattice-frame identity is preferable to treating editing clusters as the
frame identifier: clusters can split, merge and have domain-level or hierarchical
transforms. Bind frame placement to existing transform machinery without applying the
same rotation twice. Legacy parts can have an implicit frame; mixed-plane and ambiguous
legacy designs require detection, not a blanket assignment or bulk file migration.

## Implementation sequence

1. Define the frame/address contract and pin HC/SQ mapping, signed cells, bp origins,
   segment multiplicity and distinct-frame collisions with executable regressions.
2. Extract shared frame resolution/placement logic. Make backend occupancy, membership,
   continuation and lattice-neighbor lookup frame-aware. Preserve existing strand
   polarity and locked phase conventions.
3. Add a browser-authoritative Extrude transaction: target/document revision, frame,
   selected cells, length, direction and explicit create/continue mode. Preflight the
   same candidate that is committed. Create topology plus placement atomically as one
   undoable feature; reject stale targets and duplicate confirmations. Use thin native
   and browser adapters rather than growing composition roots.
4. Give desktop slice/cadnano editing a frame selector or disambiguated layout; keep
   edits bound to canonical helix IDs. Reconcile save/load, undo/redo and feature replay.
5. Define export behavior: cadnano v2 can represent the topological layout but its
   current format/exporter does not store arbitrary rigid placement. Use separate
   frame exports or a deterministic collision-free flattened layout with identity
   mapping and explicit pose-loss notice. `.nadoc` retains pose; do not promise exact
   3D reconstruction from bare cadnano JSON. Handle cross-frame connectivity explicitly.

## Acceptance before calling this supported

- Load an existing part; create and extend at oblique poses and under viewer rotation,
  translation and scale. Include independent bundles reusing the same local cells.
- Test HC/SQ, negative cells/bp offsets, imported origins, rotated/nested clusters,
  assembly instances and stale targets. Distinguish rigid placement from bent geometry.
- Preview and committed axes agree in part nm and in both rendered eyes. Diagnostic
  panel tilt leaves the authored frame unchanged after anchoring.
- Save/reload and undo/redo retain cells, bp intervals, connectivity, frame and pose.
- Edit the resulting strands in desktop 3D and cadnano views; no cell disappears or
  changes another frame's helices. Export/reimport preserves supported topology and
  reports unsupported pose information.
- Use `steady_fast` first, then all four human-motion presets. Verify actual committed
  topology and pixels, not only painted selections or successful transport.

The original audit was read-only; the subsequent source-plane field increment is
described at the top. Arbitrary-angle authoring remains unimplemented, and no
production geometry or polarity was changed.

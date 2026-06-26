---
name: assembly-linker-relax
description: "Cross-part ds linker relax — rigid-place a free PartInstance into a coaxial native-length duplex. New /assembly/overhang-connections/{id}/relax[-status] + assembly_linker_relax.py. Shipped 2026-05-20."
metadata: 
  node_type: memory
  type: project
  originSessionId: 547f7627-f3a3-471c-aece-ab7831233cc0
---

# Cross-part ds linker relax (shipped 2026-05-20)

Makes a cross-part `AssemblyOverhangConnection` (ds) *connect* two parts the way
intra-origami linkers connect clusters: the per-design `relax_linker` rotates
`ClusterJoint`s to bring the bridge to native length; the assembly analog
**rigid-places one free `PartInstance`** instead (no joint required).

## User decisions (firm)
- Kinematics = **two-translation rigid placement** (2026-05-21 — supersedes the
  earlier single rigid-place / rotate-if-mated design). **No rotation, ever.**
  - **T1 — slide the whole bridge** so its FIXED-side boundary bead lands on the
    fixed overhang's anchor (closes the fixed-side connector arc).
  - **T2 — slide the MOVED part** (pure translation) so its overhang anchor lands
    on the bridge's other boundary bead, after T1 (closes the moved-side arc).
  - Result: BOTH connector arcs collapse to ~0; the bridge rigidly extends from
    the fixed overhang and is **no longer auto-centered** between the parts. The
    moved part is translated only, so each overhang's **binding domain (its
    complement) stays fixed relative to its overhang**. Verified: arcs → 0.0000 nm
    at 0/37/90° tilt; tests `test_relax_collapses_both_connector_arcs`,
    `test_relax_is_translation_only`, `test_relax_keeps_binding_domain_fixed...`.
  - The old mate-based rotation (`rotate=` flag, `relax_info.rotated`,
    `target_chord_nm`) was **removed**. No mate detection in the route anymore.
- **Minimizes the ACTUAL emitted backbone beads (2026-05-21).** Mirrors the
  per-design relax, whose hard-won correctness is that `_anchor_pos_and_normal`
  reads the real `backbone_position` from `_geometry_for_design` (not a re-derived
  position). The assembly relax now does the same: it emits the fresh bridge via
  `_linker_geometry_for_assembly` and resolves the anchor + bridge bead from the
  emitted nucs (`_connector_arc_endpoints`), so T1/T2 act on exactly the beads
  the renderer shows. Earlier it re-derived them (`_world_anchor_axial` +
  `_bridge_boundary_beads`, now gone) — equal in practice but not the same source
  of truth.
- **Checker:** `assembly_connector_arc_lengths(assembly)` ([backend/api/assembly.py](backend/api/assembly.py))
  → `{conn_id: {a,b}}` actual 3D arc lengths between the emitted complement-junction
  bead and bridge-boundary bead. Use it to verify a relax (post-relax → ~0). The
  arc-collapse test uses it.

## Backend
- `backend/core/assembly_linker_relax.py`:
  - `assembly_relax_status(assembly, conn, inst_a, inst_b)` — gate. ds-only;
    `length_value==0`→no; same-instance→no. Which part moves: one side `fixed`
    → the other; neither → A held, B moves; both fixed → unavailable.
  - `_connector_arc_endpoints(nucs, strands, conn)` → `{a,b: (anchor, bead)}` from
    the EMITTED `nucs`. `anchor` = complement-domain junction bead (on the part
    helix), `bead` = bridge-domain junction bead (on `__lnk__`), found by the
    cross-helix domain-junction `domain[i].end_bp ↔ domain[i+1].start_bp` rule
    (mirrors the frontend connector-arc logic). These are the rendered arc ends.
  - `relax_assembly_linker(conn, nucs, strands, inst_moved, *, movable_id,
    fixed_id)` → `(moved_transform_values, bridge_translation_t1, info)`. Resolves
    endpoints, `t1 = anchor_fixed − bead_fixed`, `t2 = (bead_moved + t1) −
    anchor_moved`; moved transform = pure-translation `T(t2) @ inst_moved.transform`.
  - `_world_anchor_axial` kept (used by tests' `_live_anchor`).
- `backend/api/assembly.py`: `GET .../relax-status`, `POST .../relax`. The POST:
  generates a fresh bridge from current anchors, builds a temp assembly,
  **emits** `_linker_geometry_for_assembly(temp)`, calls `relax_assembly_linker`
  on the emitted nucs, `_propagate_fk_inplace` moves the part (deep copy), then
  commits the fresh bridge with its `__lnk__` helix translated by t1 (NOT
  regenerated from the moved pose). Commit via
  `_apply_assembly_mutation_with_feature_log` (op_kind
  `assembly-overhang-connection-relax`).
- `_linker_geometry_for_assembly(assembly)` — extracted pure emission (was inline
  in `get_linker_geometry`), reused by the route + checker.
- Relax is snapshot-only (NOT in `_REPLAYABLE_OP_KINDS`/`_EDITABLE_OP_KINDS`):
  undo/redo + timeline seek work; only mid-history surgical-delete-before-a-
  relax is blocked. v1 limitation.

## Frontend
- `client.js`: `relaxAssemblyOverhangConnection(id)` (POST + sync),
  `getAssemblyOverhangConnectionRelaxStatus(id)` (GET, read-only).
- `assembly_overhangs_manager_popup.js`: per-row **Relax** button (ds rows
  only); lazy `relax-status` fetch disables + retitles it when unavailable;
  `_onRelaxConnection` handler.
- **Right-click → Relax menu (2026-05-21):** right-clicking ANY part of a 3D
  linker (complement/bridge beads OR connector arc) opens a small context menu
  with "Relax linker", mirroring the per-design linker right-click. Renderer
  `pickLinker(ndc, camera)` (BOTH paths) raycasts `_linkerGroup`: connector arcs
  carry `userData.connId`; bead hits fall back to nearest of
  `_linkerGroup.userData.linkerNucs` (`[{connId, pos}]`, stashed in
  `_rebuildLinkerHelices` from the linker-geometry nucs by stripping
  `__lnk__<connId>__{a,b,s}`). `main.js` `_onAssemblyContextMenu` calls
  `pickLinker` before `pickInstance`; `_showAssemblyLinkerMenu(connId,x,y)`
  awaits `relax-status` to gate the item, then `createContextMenu`. **Caveat:**
  linker-priority-when-hit (no depth compare vs parts), so a linker mesh behind
  a part body along the ray can shadow the part's right-click — acceptable since
  linker meshes are small/visible; revisit if it annoys.
- **`main.js` `_assemblyTransformOnlyChange` GOTCHA (fixed here):** it only
  compared `instances`, so a relax (moves a part AND regenerates the bridge)
  was misclassified as transform-only → the light `setLiveTransform` path
  skipped `rebuildLinkers` → stale bridge. Added an `assembly_helices` /
  `assembly_strands` JSON compare so a linker-topology change forces the full
  `rebuild → rebuildLinkers` path. **If you add another op that changes both a
  part transform AND assembly topology, this guard already covers it.**

## Bridge-not-rendering — 3 stacked bugs (fixed 2026-05-20)

User reported the bridge never appeared on create. Root cause was a chain, all
in the `GET /assembly/linker-geometry` → frontend `rebuildLinkers` path:
1. **500 from lowercase lattice_type** — the synthetic `Design` in
   `get_linker_geometry` ([assembly.py](backend/api/assembly.py)) passed
   `lattice_type="honeycomb"`, but `LatticeType` values are uppercase
   (`"HONEYCOMB"`/`"SQUARE"`) → Pydantic `ValidationError` → 500. The frontend
   `_rebuildLinkerHelices` wraps `getLinkerGeometry()` in `try/catch` so it failed
   silently → no bridge, no error. Fixed: `lattice_type="HONEYCOMB"`.
2. **Bridge nucs never emitted** — `_geometry_for_helices` (crud.py) skips
   `__lnk__` helices and emits the bridge via `_emit_bridge_nucs`, which iterates
   `design.overhang_connections`. The assembly synthetic design has NONE (they
   live on the `Assembly`), so the bridge rendered as 0 nucs (only the complement
   beads at each part). Fixed: added `include_linker_helices` param to
   `_geometry_for_helices`/`_geometry_for_design`; the assembly path passes True
   to render the world-space `__lnk__` bridge helix directly (its axis is already
   baked by `_make_world_virtual_linker_helix`).
3. **Shared renderer: detached linker group** — shared `rebuild()` calls
   `dispose()` at its top, and my `dispose()` did `scene.remove(_linkerGroup)`;
   main.js runs `rebuild().then(rebuildLinkers)`, so `rebuildLinkers` filled an
   orphaned (off-scene) group → invisible on the DEFAULT renderer (legacy
   `dispose` only clears children, so legacy was fine). Fixed: shared
   `rebuildLinkers` re-attaches `if (!_linkerGroup.parent) scene.add(_linkerGroup)`.
   Both groups now named `'assembly_linkers'`.

**Pre-relax visual caveat (CLOSED 2026-05-21):** the ds bridge renders at its
NATIVE length at the chord midpoint, so when parts are far apart there's a gap
between each part's anchor and the bridge ends. **Connector arcs are now ported
to the assembly view** (mirrors per-design `overhang_link_arcs.js`): a white/
strand-colored tube bridges each ds linker strand's complement↔bridge domain
junction. Implemented in `assembly_renderer.js` module helpers
`_buildAssemblyConnectorArcs` + `_lnkConnectorArc`, called at the end of the
shared `_rebuildLinkerHelices` (so BOTH renderer paths get them). Topological —
`domain[i].end_bp ↔ domain[i+1].start_bp` where exactly one of the adjacent
domains is on the `__lnk__<conn>` bridge helix; verified equal to the design's
anchor↔bridge-boundary in all 4 polarity cases. ds side strands only
(`__lnk__<conn>__a`/`__b`); ss not ported. **Relax** still moves the free part
to collapse the gap (arcs then shrink below the 1e-3 nm draw threshold).
Verified E2E: `frontend/e2e/assembly_linker_arcs.spec.js` (loads
`Linker_Assem_test2.nass` → 2 arcs, spans ~4.7 nm).

## Tests / verification
- `tests/test_assembly_linker_relax.py` (8, incl. `test_linker_geometry_emits_bridge_nucleotides` which would have caught the 500 + missing-bridge bugs) — the acceptance test asserts
  post-relax chord ≈ L AND the two overhang axial dirs are antiparallel
  (dot ≈ −1); this is what catches a wrong axdir sign. Full suite 1392 pass.
- In-app: Playwright drove the Relax button on BOTH shared + legacy renderers
  (part moves, no uncaught errors) using `workspace/Linker_Assem_test.nass`
  (gitignored fixture; the throwaway spec was removed, not committed).

## Indirect (zero-length ss) relax — single translation (2026-06-07)
The ds path above is a TWO-translation (bridge slide + part slide). A zero-length
INDIRECT ss linker has no bridge — just one complement↔complement arc (the
`__lnk__<id>__s` strand `[comp_a, comp_b]`, see [[assembly-overhang-bindings]]
"Indirect (zero-length) linkers") — so its relax is a SINGLE translation of the
moved part landing its binding-domain endpoint on the fixed part's endpoint.
- `assembly_relax_status`: now allows ss when `length_value == 0` (rejects ss
  length>0 with "only supported for zero-length"; rejects ds length 0). Same
  fixed/movable resolution as ds.
- `_indirect_arc_endpoints(nucs, strands, conn)` → `{instance_id: endpoint}` from
  the EMITTED `__s` beads: `comp_a.end_bp` ↔ `comp_b.start_bp`, each mapped to its
  part via `parse_namespaced_helix_id`. `relax_assembly_indirect_linker(...)` →
  `(moved_T_values, info)`, `t = p_fixed − p_moved`, pure-translation T.
- Route `POST .../relax`: branches on `length_value == 0` BEFORE the bridge path —
  emits CURRENT geometry (no fresh bridge), single translation, `_propagate_fk_inplace`,
  commit. assembly_strands/helices unchanged (complement beads follow the moved
  part on re-emit). op_kind still `assembly-overhang-connection-relax`.
- Checker `assembly_connector_arc_lengths` is still ds-only; the indirect test
  measures the arc via `_indirect_arc_endpoints` on re-emitted geometry instead.
- Frontend: right-click "Relax linker" already gates on relax-status → auto-enables
  for indirect. Popup row Relax button condition widened to `ds || (ss && length 0)`.
  Both success toasts genericised ("…to close the connector arc", was "coaxial
  native-length duplex"). Tests: 3 new in `test_assembly_linker_relax.py`
  (status-available, arc-collapses-translation-only, holds-fixed-part).

## Related
- [[assembly-overhang-bindings]] — the cross-part connection model + topology
  generation this relaxes.
- [[overhang-connections]] — the per-design linker + `relax_linker` analog.
- [[path-to-thousands]] — Phase 7b (`rebuildLinkers` shared-path port) shipped
  alongside this.

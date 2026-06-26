---
name: assembly-overhang-bindings
description: "Cross-part overhang manager — AssemblyOverhangBinding (sub-domain WC pair) + AssemblyOverhangConnection (cross-part linker, ss/ds with bridge sequence) + ported Connection Types tab with exclusion rules + Assembly feature-log target. Shipped 2026-05-14."
metadata: 
  node_type: memory
  type: project
  originSessionId: b3ee46f4-5e87-467e-b773-893ba2171f60
---

# Assembly Overhang Bindings + Connections (shipped 2026-05-14)

Cross-part Watson-Crick pairing **and** cross-part linker design for the Assembly overhaul. Pure topology metadata — no geometry application, no joint coupling. Connection Types tab from the per-part Overhangs Manager is ported here in full, including exclusion rules.

## What ships

### Data models (both on `Assembly`)
- `AssemblyOverhangBinding` — sub-domain Watson-Crick pair. References `{instance_a_id, sub_domain_a_id, overhang_a_id, instance_b_id, sub_domain_b_id, overhang_b_id}` plus `binding_mode` / `allow_n_wildcard`. Self-binding rejected by validator.
- `AssemblyOverhangConnection` — cross-part linker. References `{instance_a_id, overhang_a_id, overhang_a_attach}` + B side + `linker_type` (ss/ds), `length_value`, `length_unit` (bp/nm), `bridge_sequence`. Mirrors `OverhangConnection` but qualified per PartInstance.

### Routes
- Bindings: `POST/PATCH/DELETE /assembly/overhang-bindings[/{id}]` — duplicate pair = 409.
- Connections: `POST/PATCH/DELETE /assembly/overhang-connections[/{id}]` — server-side polarity rule (`_check_polarity_allowed` in [backend/api/assembly.py](backend/api/assembly.py)) returns 422 on forbidden combos. Mirrors the frontend's `_isForbidden` function.
- `POST /assembly/features/seek` — `{ position }` -1 / -2 / N walks `assembly_state.undo()/redo()` until `feature_log` length matches target.

All mutations route through `_apply_assembly_mutation_with_feature_log` in [backend/api/assembly.py](backend/api/assembly.py) — snapshot to deque, append `SnapshotLogEntry(evicted=True)` with one of the new op_kinds.

### New `SnapshotOpKind` literals
`assembly-overhang-bind`, `assembly-overhang-bind-patch`, `assembly-overhang-unbind`, `assembly-overhang-connection-add`, `assembly-overhang-connection-patch`, `assembly-overhang-connection-delete`.

### Frontend
- **Assembly → Overhangs Manager…** menu entry at the bottom of the Assembly dropdown. Tools menu's per-part manager untouched.
- New popup [frontend/src/ui/assembly_overhangs_manager_popup.js](frontend/src/ui/assembly_overhangs_manager_popup.js) replaces the v1 list view with a full Connection Types layout:
  - Three columns: Side A overhang list (cyan, grouped by part), center variant picker + length + action button, Side B overhang list (magenta).
  - 12 connection-type variants in dropdown (direct ×2, indirect ×2, ss linker ×4, ds linker ×4).
  - Forbidden-polarity reason shown in red below the dropdown. Action button disables when forbidden / cross-part-same-instance / no selection.
  - Per-side sequence input + Gen button (writes via `patchInstanceOverhang`).
  - Bridge sequence box (shown when a linker row is selected in the table). Input + Gen.
  - Mixed table: linkers (AssemblyOverhangConnection) and bindings (AssemblyOverhangBinding) rendered together, each with Delete button. Connection rows are click-selectable to enable the bridge box.
  - "Make Complementary" button (variant = direct): writes RC(A) to B's sequence, then creates an AssemblyOverhangBinding using each side's first sub-domain.
- Feature Log target dropdown gets `Assembly: <name>` at the top, default-selected when entering assembly mode. New `_assemblyFeatureMode` state + `_rebuildAssemblyFeatureLog` path in [frontend/src/ui/feature_log_panel.js](frontend/src/ui/feature_log_panel.js).

### Tests
[tests/test_assembly_overhang_bindings.py](tests/test_assembly_overhang_bindings.py) — 20 tests: model round-trip, CRUD for bindings and connections, duplicate/self-binding rejection, polarity-forbidden rejection (422), seek to -1/-2/explicit index. All assembly suites (116 tests) green.

## Mechanics worth remembering

- **Seek semantics**: each assembly mutation pushes one snapshot to `assembly_state._history`. So `feature_log` length == snapshot count. Seek to position N just walks `undo()`/`redo()` until the live feature_log matches `N+1`. No payload embedding, no replay logic. Simple and stack-walking-based.
- **Why `evicted=True`**: assembly entries carry no payload; the snapshot lives in the deque, not in the entry. Mirrors the per-part mutation helper's behaviour at [backend/api/assembly.py:1180](backend/api/assembly.py#L1180).
- **Inventory data source (frontend)**: popup reads overhangs from `inst.source.design.overhangs` (inline source). File-backed instances need a deferred fetch — not handled in v1.

## Cross-part linker topology (shipped 2026-05-15)

POST `/assembly/overhang-connections` now also generates linker topology onto the assembly itself — complement strands + a virtual `__lnk__<conn.id>` helix + bridge strand are appended to `assembly.assembly_strands` / `assembly.assembly_helices`. The two designs are NOT mutated; the complement domains reference *namespaced* helix ids of the form `<instance_id>::<original_helix_id>`, and `GET /assembly/linker-geometry` synthesises world-space alias helices under those ids so the geometry pipeline can resolve cross-part lookups.

**Phase correction on aliased helices (2026-05-21):** the geometry pipeline's `_frame_from_helix_axis` is NOT rotation-equivariant (it picks the radial frame from a fixed world reference), so building the complement on a world-space aliased helix put the binding domain at the wrong roll/phase relative to its overhang for any *tilted* part (the overhang is built local-frame then placed by `T`; the complement was built directly in world). `get_linker_geometry` now bakes the roll-discrepancy angle `δ` into each aliased helix's `phase_offset` so the world pass reproduces `R·(local geometry)`. δ=0 for untilted parts. See [[LESSONS]] A4; regression `test_linker_complement_phase_matches_tilted_overhang`.

- Generator: `generate_assembly_linker_topology` in [backend/core/assembly_linker.py](backend/core/assembly_linker.py). Mirrors `generate_linker_topology` in [backend/core/lattice.py](backend/core/lattice.py) but operates across two `PartInstance.transform`s. Reuses `_make_complement_domain`, `_is_comp_first`, `_length_value_to_bp` and the shared `bridge_axis_geometry` math.
- Cleanup: `remove_assembly_linker_topology` filters by `__lnk__<conn.id>` prefix; called from DELETE + the regenerate branch of PATCH.
- Sequence composition: each generated strand carries its assembled full sequence (`RC(OH)` + bridge for ds per-side; `RC(OH_A) + bridge + RC(OH_B)` for ss). PATCH on `bridge_sequence` recomposes via `recompose_strand_sequences_for_connection`.
- Frontend: [frontend/src/scene/assembly_renderer.js](frontend/src/scene/assembly_renderer.js) `rebuildLinkers()` reads `aliased_helices` from the geometry response and includes them in the synthetic design used by `buildHelixObjects`. The strand spreadsheet ([frontend/src/ui/spreadsheet.js](frontend/src/ui/spreadsheet.js)) appends rows for `currentAssembly.assembly_strands` of type `linker` when `assemblyActive` is true.
- Cross-cutting LINKER policy (see [project_overhang_connections](project_overhang_connections.md)) extends to cross-part linkers — auto-scaffold / autobreak / atomistic / oxDNA / caDNAno export still don't have explicit guards, same as the per-design path. Don't broaden in this scope.

### Indirect (zero-length) linkers + ss connector arcs (2026-06-07)
- **Indirect = zero-length ss.** `generate_assembly_linker_topology` previously early-returned `[], []` for `length_value == 0`, so indirect linkers rendered NOTHING. Now it emits a single ss strand `__lnk__<id>__s` with domains `[comp_a, comp_b]` (the two namespaced complement BINDING domains, NO bridge helix/domain) and sequence `RC(OH_A) + RC(OH_B)`. The `comp_a→comp_b` backbone jump renders as the connector arc. Each overhang shows its binding domain; the geometry endpoint emits beads on both `::` complement helices (no `__lnk__` helix). Pin: `test_post_indirect_zero_length_generates_binding_strand_no_bridge` (topology + geometry-endpoint end-to-end).
- **ss linker arcs now render in assemblies (were ds-only).** The connector-arc endpoint logic was extracted to a pure module [frontend/src/scene/assembly_connector_arcs.js](frontend/src/scene/assembly_connector_arcs.js) (`assemblyConnectorArcEndpoints`, mirrors backend `_connector_arc_endpoints`). Rule changed from "exactly one adjacent domain is the bridge" (ds `__a`/`__b` only) to "the two adjacent domains are on DIFFERENT helices" — which also matches ds + length>0 ss (`__s`, comp↔bridge↔comp = 2 arcs) AND length-0 indirect (comp↔comp = 1 arc). `_buildAssemblyConnectorArcs` in assembly_renderer.js now just maps those endpoints → tube meshes (mesh name kept `assemblyDsConnectorArc` for the existing e2e). Pin: `assembly_connector_arcs.test.js` (7 cases). **Live indirect-create gesture (Overhangs Manager) not hand-driven — pinned via backend geometry endpoint + frontend unit, NOT a WebGL exercise.**

Tests: 7 new in [tests/test_assembly_overhang_bindings.py](tests/test_assembly_overhang_bindings.py) (`test_post_overhang_connection_generates_ds_linker_topology` + 6 siblings) cover POST/DELETE/PATCH paths + ds/ss sequence composition.

## 3D overhang hover/click selection → manager prefill (shipped 2026-05-20; redesigned to hover/proximity 2026-05-21)

Hovering near an overhang in the 3D assembly view reveals its label; clicking selects it (green ring + persistent label) and prefills the manager's Side A / Side B. **Gated on the overhang tool** (the `data-key="ovhg"` "Overhang locations" button under Tools: → `toolFilters.overhangLocations`, default **off**). When the tool is off, overhangs ignore the pointer entirely so a part buried under a forest of overhangs stays hoverable/selectable; arm the tool to interact with overhangs. (Gating added 2026-05-23 — user reported overhang-covered parts were unselectable.)

- **No overhang *selectable* button (design-mode filter):** `_enterAssemblyMode` ([frontend/src/main.js](frontend/src/main.js)) hides the **whole `#select-filter` section** in assembly mode (was: keep only `ovhangs`). The old `selectableTypes.overhangs` default-on logic was removed. `_DESIGN_STRIP_SELECTORS` now hides `#select-filter` + the leading view-tools divider + the design-only view-tools buttons. The gate is instead the **`ovhg` Tools button** (the design-view overhang-locations tool), reused as the assembly overhang-interaction arm.
- **Tool gate:** both `_onAssemblyHoverMove` and the overhang branch of `_onAssemblyClick` early-out unless `store.getState().toolFilters.overhangLocations`. Turning the tool off in assembly mode also clears any transient hover (handled in the `toolFilters` subscriber + on the next hover move).
- **Proximity hit-testing (not raycast):** the shared renderer ([frontend/src/scene/assembly_renderer.js](frontend/src/scene/assembly_renderer.js)) exposes `getOverhangAnchors()` → world-space label anchors for every labeled overhang × visible instance (computed on rebuild via the extracted `_overhangLabelAnchorsLocal` helper, also used by the per-instance sprite builder). `main.js` `_nearestOverhangAt(clientX, clientY, _OVHG_PICK_RADIUS_PX=36)` projects anchors to screen and returns the nearest within a medium px radius (perf cap: skip if >1200 anchors). `_onAssemblyHoverMove` (canvas pointermove, skipped while a button is held) calls `assemblyRenderer.setHoveredOverhang(hit|null)`; `_onAssemblyClick` calls `_nearestOverhangAt` → `_toggleAssemblyOverhangSelection` (returns before instance selection if a hit). **A click that misses all overhangs (part body or empty space) clears `assemblyOverhangSelection`, then falls through to part selection.**
- **Renderer label model:** `_ovhgLabelGroup` ('sharedOverhangNames') renders the union of (showAll ? all) ∪ selected ∪ hovered, via cached per-label CanvasTextures; `setHoveredOverhang` (transient) + `setOverhangSelectionHighlight` (selected → persistent labels + green rings in `_ovhgSelGroup`). `rebuildOverhangNames` = recompute anchors + relabel + rings (called on geometry rebuild / photo toggle). `pickOverhang` was **removed** (replaced by anchors + proximity). The **"overhang names" toggle** (`showOverhangNames`) still force-shows every label.
- **Ordered store selection:** `assemblyOverhangSelection: [{instanceId, overhangId, label}]` (store.js, `assembly` slice). Cleared on assembly exit (+ hover cleared). Manager `open()` snapshots the first two → `_selA`/`_selB` (no auto-open, no live updates — user's spec). Sprite/anchor `overhangId === design.overhang.id` → matches popup row keys.
- Verified E2E: [frontend/e2e/assembly_overhang_select.spec.js](frontend/e2e/assembly_overhang_select.spec.js) — hover shows transient label, click → ring + persistent label (persists after cursor leaves), two clicks → Side A/B, show-all renders all anchors, no `#select-filter`. Two separated file-backed Arm.nadoc instances (a single part's labels stack within a few px). **Per-instance (legacy) renderer path: getOverhangAnchors/setHoveredOverhang absent → optional-chained → overhang hover/select no-ops there.**

## Deferred for follow-up tasks

- **Domain Designer tab** (Pathview Three.js + Annotations pane with Tm/GC/Gen + sub-domain split/merge). Sub-domain edits are read-only in the assembly view per current scope decision.
- SVG tile variant picker (currently a plain dropdown).
- Inline editing for name + length on table rows.
- Bound-toggle checkbox in the table's Bound column for bindings.
- Apply geometry on bind (move/rotate parts to satisfy the WC pairing).
- Automatic joint creation between bound parts.
- File-backed PartInstance support in the inventory pane (relies on `inst.source.design` being inline).
- Atomistic linker rendering between bound parts.
- Typed log entries (we currently piggyback on `SnapshotLogEntry` tagged via `op_kind`).
- Selection layer: clicking an assembly linker bead in 3D → highlight the spreadsheet row (and vice versa) needs `selection_manager.js` to understand `assembly_strands`. Not wired in v1.

## Related

- [[overhang-binding-extensions]] — the per-design `OverhangBinding` class (Phase-5 within-design bindings) is what this assembly variant mirrors.
- [[overhang-subdomains]] — sub-domain IDs are what `AssemblyOverhangBinding` references on each side.
- [[assembly-overhaul]] — broader assembly initiative this lands under.

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

## ⭐ Duplex convergence — BACKEND SHIPPED 2026-07-11 (see [[overhang-duplex-foundation]])

The assembly overhang layer is being converged onto the per-design **Duplex graph**
(Proposal B). Backend foundation done + full-suite green (4649). Two decisions locked
by user: (1) converge onto Duplex (don't keep building on `AssemblyOverhangBinding`);
(2) fix the linker→flatten bug first.

- **PREREQ FIX — `flatten_assembly` linker dangling refs (was silent).** Linker
  complement domains address a part helix as `<inst>::<helix>`; flatten blindly
  `asm::`-prefixed them → dangling `asm::<inst>::<helix>`. Fix
  ([assembly_flatten.py](backend/core/assembly_flatten.py) `_remap_assembly_domain`):
  remap onto the REAL flattened part helix `inst-<inst>::<helix>`. Binding complement +
  overhang onto the SAME flattened helix also **sidesteps LESSONS A4** (no world-alias
  to phase-correct). Gate: [test_assembly_flatten.py](tests/test_assembly_flatten.py).
- **Model (Phase A):** `AssemblyDuplex` + `AssemblyDuplexEnd{instance_id, overhang_id,
  start_bp, end_bp}` ([models.py](backend/core/models.py)), mirroring `Duplex`/`DuplexEnd`
  with per-instance qualification; `Assembly.duplexes`; equal-length + self-pair
  validators. `connection_id` field ties a duplex to a linker `AssemblyOverhangConnection`.
- **Core (Phase B):** [assembly_duplex.py](backend/core/assembly_duplex.py) —
  `synthesize_assembly_duplexes_from_bindings` (migration), `sync_…` (idempotent),
  `classify_assembly_duplex` / `assembly_overhang_pairing_map` / `summarize_…` (oracle).
  **Reuses the per-design kernel:** `core/duplex.py` was refactored to expose
  `classify_antiparallel` (shared antiparallel WC walk) — both the per-design and
  cross-part classifiers call it, so polarity/register can't fork. Per-side bases come
  from each instance's own design.
- **Materialization (Phase D) — the DoD centerpiece.** `flatten_assembly` now (a) carries
  namespaced part **overhangs** into the merged Design (`_prefix_overhang`, and
  `_prefix_domain` namespaces `overhang_id`), and (b) `_materialize_direct_duplexes`
  relocates the driven overhang of every DIRECT (`connection_id is None`) AssemblyDuplex
  onto the driver's flattened helix at the register — reusing the PROVEN
  `compute_bind_topology`/`apply_bind_topology` with `target_*_override` from the
  driver register (exactly mirrors `duplex.relocate_duplex`). Result: a direct WC pair
  becomes a real antiparallel co-located duplex in the flattened topology. **Parts stay
  pristine** (flatten output is a derived artifact — Three-Layer clean).
- **Load derivation:** `/assembly/load` + `/assembly/import` run
  `_derive_assembly_duplexes_if_empty` ([assembly.py](backend/api/assembly.py)) so
  existing binding-designs populate `duplexes` (bindings KEPT).
- **Legacy-marked (Phase F):** `AssemblyOverhangBinding` docstring now says superseded +
  migrated-on-load; new code creates AssemblyDuplex.
- Tests: [test_assembly_duplex.py](tests/test_assembly_duplex.py) (12),
  [test_assembly_flatten.py](tests/test_assembly_flatten.py) (7: zero-dangling ds/ss/
  indirect, direct-WC materialize, import-derives).

### Phase B CRUD routes — SHIPPED 2026-07-11 (backend)
Cross-part AssemblyDuplex CRUD mirrors [routes_duplex.py](backend/api/routes_duplex.py),
added to [routes_assembly_overhangs.py](backend/api/routes_assembly_overhangs.py) (same
already-mounted router):
- `GET /assembly/duplexes` · `POST /assembly/duplexes` (explicit register + WC gate) ·
  `POST /assembly/duplexes/connect` (producer: min-length register, longest-drives,
  409 on duplicate pair) · `POST /assembly/duplexes/sync-from-bindings` (idempotent,
  no-op skips the feature-log entry) · `PATCH /assembly/duplexes/{id}` (register/driver/
  bound/name — driver just persists, read by flatten; NO live relocation) ·
  `DELETE /assembly/duplexes/{id}` · `GET /assembly/duplexes/{id}/pairing` ·
  `GET /assembly/overhangs/pairing-map?instance_id=&overhang_id=`.
- Core producer helpers `assembly_connect_register` / `assembly_longest_driver` added to
  [assembly_duplex.py](backend/core/assembly_duplex.py) (cross-part mirror of
  `core.duplex.connect_register`/`longest_driver`, reuse `_end_from_sub_domain` +
  `_sub_domain_at_attach` → no forked polarity). Validation helper
  `_validate_assembly_duplex_placement` (404/422/409 + WC gate) resolves each end's
  backing domain per instance design.
- New `SnapshotOpKind` literals: `assembly-duplex-{add,connect,patch,delete,sync}`
  ([models.py](backend/core/models.py)). All mutations route through
  `_apply_assembly_mutation_with_feature_log` (seek via stack-walk; not replay-registered,
  same as the binding ops). Gate: [test_assembly_duplex_routes.py](tests/test_assembly_duplex_routes.py) (15).

### Phase C frontend — SHIPPED 2026-07-11 (verified in app)
- **Client API fns** — `listAssemblyDuplexes` / `connectAssemblyDuplex` /
  `patchAssemblyDuplex` / `deleteAssemblyDuplex` / `syncAssemblyDuplexesFromBindings`
  added to [client.js](frontend/src/api/client.js) (right before `seekAssemblyFeatures`),
  all `_syncFromAssemblyResponse` + return json; `connect` guards `if(!json)return null`
  for the 409-already-connected case. Mirror of the per-design duplex fns in
  [overhang_endpoints.js](frontend/src/api/overhang_endpoints.js).
- **JS kernel refactor (reuse, don't fork).** [design_queries.js](frontend/src/scene/design_queries.js)
  now exposes `classifyAntiparallel(leftDom,rightDom,leftEnd,rightEnd,leftBases,rightBases,allowN)`
  (mirror of backend `duplex.classify_antiparallel`); `classifyDuplex` delegates to it
  (now also returns `n_complementary`/`n_mismatch` — additive, existing tests still green
  = the adapted-code pin). New `classifyAssemblyDuplex(designA,designB,duplex)` sources each
  side's bases from its OWN instance design and delegates to the same kernel; new
  `assemblyOverhangDuplexCoverage(assembly,instanceId,overhangId,designFor)` (mirror of
  `assembly_duplex.assembly_overhang_pairing_map`). Pins: 7 new cases in
  [design_queries.test.js](frontend/src/scene/design_queries.test.js) (53 pass; full FE 2633).
- **Manager viewer reads the register.** [assembly_overhangs_manager_popup.js](frontend/src/ui/assembly_overhangs_manager_popup.js)
  binding-row **Status** now comes from `_duplexStatus` → `classifyAssemblyDuplex` (using
  the popup's existing `_designFor` cache) when an `AssemblyDuplex` covers the pair, else
  falls back to the naive `_pairStatus`. Shows `paired Nbp` / `M mismatch / K paired`.
- **Fixture:** [workspace/duplex_demo.nass](workspace/duplex_demo.nass) — 2 inline parts, 1
  direct WC binding (`ACGTACGT` self-RC pair → migrates to AD1 on load, 8bp fully paired) +
  1 ds-linker connection. Verified in the running app (Playwright throwaway, since removed):
  manager opens clean, AB1 row shows "paired 8bp", L1 shows dsDNA/21bp, zero console errors.
- **Still open (not this session):** `patch`/`delete`/`connect`/`sync` client fns exist but
  no UI gesture calls them yet (manager still creates bindings via Make-Complementary, which
  migrate to duplexes on load); connector-arc rendering already ships from the linker path so
  it wasn't re-touched. `assemblyOverhangDuplexCoverage` is wired for use but not yet consumed
  by a per-overhang side-column color pass.
- **NOT in scope (downstream):** simulation-engine wiring / `flatten_assembly_for_simulation`.

### Sidebar Overhangs list — SHIPPED 2026-07-11 (verified in app)
New right-sidebar section **"Overhangs"** in assembly mode (`#assembly-overhang-panel`
in [index.html](frontend/index.html), after `#assembly-panel`), rendered by a NEW module
[assembly_overhang_list_panel.js](frontend/src/ui/assembly_overhang_list_panel.js)
(`initAssemblyOverhangListPanel({store, getInstanceDesign, fetchInstanceDesign})`). Lists
every overhang across all parts, grouped by part (collapsible headers), styled like the
Overhangs Manager popup's Side A/B lists (`.ohc-list-row` + `.aohc-part-header`, scoped CSS).
- **Two-way selection:** shares the `assemblyOverhangSelection` store slice with the 3D
  overhang-selection tool. Row click toggles that slice (same semantics as
  `assembly_pointer.js._toggleAssemblyOverhangSelection`, no toast) → drives the 3D green
  ring; a 3D-tool click repaints the matching rows via the store subscription. Selected rows
  colored by ORDER: index 0 = Side A (cyan `ct-selected-a`), 1 = Side B (magenta
  `ct-selected-b`), ≥2 = generic.
- **Design resolution:** inline sources are spilled to disk on import (instances are
  file-backed, no client `source.design`), so the module resolves per-instance designs via
  `assemblyRenderer.getInstanceDesign` (sync fast-path) with an async `api.getInstanceDesign`
  fallback + per-instance cache (mirrors the popup's `_ensureDesignCache`; `_fetchAttempted`
  guards against refetch loops). Renderer cache is empty until it finishes building, so the
  async fetch is what actually populates the list on first entry.
- **main.js wiring** (thin): import + factory init (~after `initAssemblyPanel`) + show/hide
  in `_enterAssemblyMode`/`_exitAssemblyMode` + one `.rebuild()` on enter. main.js LOC Δ ≈ +12
  (pure wiring, no cohesive block).
- Pins: [assembly_overhang_list_panel.test.js](frontend/src/ui/assembly_overhang_list_panel.test.js)
  (pure helpers `endTagFor`/`selectionClass`/`groupOverhangs`); app-exercised via throwaway
  Playwright (lists PartA/PartB overhangs, row-click ↔ store two-way, store-driven repaint,
  zero console errors) + `just smoke` green.

### Sidebar Overhang CONNECTIONS panel — SHIPPED 2026-07-11 (verified in app)
Cross-part twin of the per-part `#overhang-connections-section`, so you create connections
between two parts from A/B **dropdowns** (populated + two-way synced with the 3D tool) instead
of scrolling long lists. New section `#assembly-oconn-panel` (index.html, after the Overhangs
list) + NEW module [assembly_overhang_connections_panel.js](frontend/src/ui/assembly_overhang_connections_panel.js)
(`initAssemblyOverhangConnectionsPanel({store, getInstanceDesign, fetchInstanceDesign})`).
- **Layout mirrors the part editor:** Overhang A `<select>` (grouped by part via `<optgroup>`,
  cyan border) · connection-type icon button + popover (all 12 variants) · Overhang B `<select>`
  (magenta) · length (hidden for direct/indirect) · Generate ("Make Complementary" for the two
  DIRECT variants, else "Generate Linker") · forbidden-polarity warning · a linkers+bindings list
  with delete (click a linker row → reselect its A/B + variant).
- **Two-way A/B:** A = `assemblyOverhangSelection[0]`, B = `[1]`. Dropdown change → `setState`
  the slice; a 3D-tool click → dropdown values follow (subscription). Shared with the list panel
  + rings.
- **Reuse, don't fork:** variant rules/icons from [ct_icons.js](frontend/src/ui/ct_icons.js)
  (`CT_VARIANTS`/`ctIsForbidden`/`ctForbiddenReason`/`ctAttachPair`/`ctIsDirect`/`ctIsIndirect`/
  `ctLinkerType`/`ctVariantForConnection`/`ctTileSvg`) — same source of truth as the per-part
  panel + manager popup; grouped overhang model from `groupOverhangs`; create bodies mirror the
  popup's `_onGenerateLinker`/`_onMakeComplementary` (assembly client fns
  `createAssemblyOverhangConnection`/`createAssemblyOverhangBinding` + `patchInstanceOverhang`
  RC write).
- **Shared per-instance design cache extracted:** [assembly_instance_designs.js](frontend/src/ui/assembly_instance_designs.js)
  `initInstanceDesignCache` (renderer sync fast-path + async `api.getInstanceDesign` fallback +
  `attempted` refetch-guard + `prune`) — BOTH sidebar panels use it (list panel refactored onto
  it; pure-helper tests stayed green = the pin). Each panel holds its own cache instance (dedup
  within a panel; ~2× fetch across panels is negligible).
- **Pins:** [assembly_instance_designs.test.js](frontend/src/ui/assembly_instance_designs.test.js)
  (5) + [assembly_overhang_connections_panel.test.js](frontend/src/ui/assembly_overhang_connections_panel.test.js)
  (5: `encodeOption`/`decodeOption`/`revcomp`/`connectionBody`/`canGenerate`). App-exercised
  (throwaway Playwright): dropdowns show PartA/PartB optgroups + 4 options, two-way sync both
  directions, creating an end-to-root ds linker grew the list (1→2 conns), zero console errors.
- main.js LOC Δ (both panels total): ~+22, pure wiring (2 imports + 2 factory inits + show/hide +
  rebuild). No cohesive block in the closure.

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

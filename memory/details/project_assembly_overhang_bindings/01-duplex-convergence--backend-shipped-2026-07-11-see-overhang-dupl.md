# ⭐ Duplex convergence — BACKEND SHIPPED 2026-07-11 (see [[overhang-duplex-foundation]]) — supporting detail

[Topic head](../../project_assembly_overhang_bindings.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ⭐ Duplex convergence — BACKEND SHIPPED 2026-07-11 (see [[overhang-duplex-foundation]])

The assembly overhang layer is being converged onto the per-design **Duplex graph**
(Proposal B). Backend foundation done + full-suite green (4649). Two decisions locked
by user: (1) converge onto Duplex (don't keep building on `AssemblyOverhangBinding`);
(2) fix the linker→flatten bug first.

- **PREREQ FIX — `flatten_assembly` linker dangling refs (was silent).** Linker
  complement domains address a part helix as `<inst>::<helix>`; flatten blindly
  `asm::`-prefixed them → dangling `asm::<inst>::<helix>`. Fix
  ([assembly_flatten.py](../../../backend/core/assembly_flatten.py) `_remap_assembly_domain`):
  remap onto the REAL flattened part helix `inst-<inst>::<helix>`. Binding complement +
  overhang onto the SAME flattened helix also **sidesteps LESSONS A4** (no world-alias
  to phase-correct). Gate: [test_assembly_flatten.py](../../../tests/test_assembly_flatten.py).
- **Model (Phase A):** `AssemblyDuplex` + `AssemblyDuplexEnd{instance_id, overhang_id,
  start_bp, end_bp}` ([models.py](../../../backend/core/models.py)), mirroring `Duplex`/`DuplexEnd`
  with per-instance qualification; `Assembly.duplexes`; equal-length + self-pair
  validators. `connection_id` field ties a duplex to a linker `AssemblyOverhangConnection`.
- **Core (Phase B):** [assembly_duplex.py](../../../backend/core/assembly_duplex.py) —
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
  `_derive_assembly_duplexes_if_empty` ([assembly.py](../../../backend/api/assembly.py)) so
  existing binding-designs populate `duplexes` (bindings KEPT).
- **Legacy-marked (Phase F):** `AssemblyOverhangBinding` docstring now says superseded +
  migrated-on-load; new code creates AssemblyDuplex.
- Tests: [test_assembly_duplex.py](../../../tests/test_assembly_duplex.py) (12),
  [test_assembly_flatten.py](../../../tests/test_assembly_flatten.py) (7: zero-dangling ds/ss/
  indirect, direct-WC materialize, import-derives).

### Phase B CRUD routes — SHIPPED 2026-07-11 (backend)
Cross-part AssemblyDuplex CRUD mirrors [routes_duplex.py](../../../backend/api/routes_duplex.py),
added to [routes_assembly_overhangs.py](../../../backend/api/routes_assembly_overhangs.py) (same
already-mounted router):
- `GET /assembly/duplexes` · `POST /assembly/duplexes` (explicit register + WC gate) ·
  `POST /assembly/duplexes/connect` (producer: min-length register, longest-drives,
  409 on duplicate pair) · `POST /assembly/duplexes/sync-from-bindings` (idempotent,
  no-op skips the feature-log entry) · `PATCH /assembly/duplexes/{id}` (register/driver/
  bound/name — driver just persists, read by flatten; NO live relocation) ·
  `DELETE /assembly/duplexes/{id}` · `GET /assembly/duplexes/{id}/pairing` ·
  `GET /assembly/overhangs/pairing-map?instance_id=&overhang_id=`.
- Core producer helpers `assembly_connect_register` / `assembly_longest_driver` added to
  [assembly_duplex.py](../../../backend/core/assembly_duplex.py) (cross-part mirror of
  `core.duplex.connect_register`/`longest_driver`, reuse `_end_from_sub_domain` +
  `_sub_domain_at_attach` → no forked polarity). Validation helper
  `_validate_assembly_duplex_placement` (404/422/409 + WC gate) resolves each end's
  backing domain per instance design.
- New `SnapshotOpKind` literals: `assembly-duplex-{add,connect,patch,delete,sync}`
  ([models.py](../../../backend/core/models.py)). All mutations route through
  `_apply_assembly_mutation_with_feature_log` (seek via stack-walk; not replay-registered,
  same as the binding ops). Gate: [test_assembly_duplex_routes.py](../../../tests/test_assembly_duplex_routes.py) (15).

### Phase C frontend — SHIPPED 2026-07-11 (verified in app)
- **Client API fns** — `listAssemblyDuplexes` / `connectAssemblyDuplex` /
  `patchAssemblyDuplex` / `deleteAssemblyDuplex` / `syncAssemblyDuplexesFromBindings`
  added to [client.js](../../../frontend/src/api/client.js) (right before `seekAssemblyFeatures`),
  all `_syncFromAssemblyResponse` + return json; `connect` guards `if(!json)return null`
  for the 409-already-connected case. Mirror of the per-design duplex fns in
  [overhang_endpoints.js](../../../frontend/src/api/overhang_endpoints.js).
- **JS kernel refactor (reuse, don't fork).** [design_queries.js](../../../frontend/src/scene/design_queries.js)
  now exposes `classifyAntiparallel(leftDom,rightDom,leftEnd,rightEnd,leftBases,rightBases,allowN)`
  (mirror of backend `duplex.classify_antiparallel`); `classifyDuplex` delegates to it
  (now also returns `n_complementary`/`n_mismatch` — additive, existing tests still green
  = the adapted-code pin). New `classifyAssemblyDuplex(designA,designB,duplex)` sources each
  side's bases from its OWN instance design and delegates to the same kernel; new
  `assemblyOverhangDuplexCoverage(assembly,instanceId,overhangId,designFor)` (mirror of
  `assembly_duplex.assembly_overhang_pairing_map`). Pins: 7 new cases in
  [design_queries.test.js](../../../frontend/src/scene/design_queries.test.js) (53 pass; full FE 2633).
- **Manager viewer reads the register.** [assembly_overhangs_manager_popup.js](../../../frontend/src/ui/assembly_overhangs_manager_popup.js)
  binding-row **Status** now comes from `_duplexStatus` → `classifyAssemblyDuplex` (using
  the popup's existing `_designFor` cache) when an `AssemblyDuplex` covers the pair, else
  falls back to the naive `_pairStatus`. Shows `paired Nbp` / `M mismatch / K paired`.
- **Fixture:** [workspace/duplex_demo.nass] (recorded path: `workspace/duplex_demo.nass`) — 2 inline parts, 1
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
in [index.html](../../../frontend/index.html), after `#assembly-panel`), rendered by a NEW module
[assembly_overhang_list_panel.js](../../../frontend/src/ui/assembly_overhang_list_panel.js)
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
- Pins: [assembly_overhang_list_panel.test.js](../../../frontend/src/ui/assembly_overhang_list_panel.test.js)
  (pure helpers `endTagFor`/`selectionClass`/`groupOverhangs`); app-exercised via throwaway
  Playwright (lists PartA/PartB overhangs, row-click ↔ store two-way, store-driven repaint,
  zero console errors) + `just smoke` green.

### Sidebar Overhang CONNECTIONS panel — SHIPPED 2026-07-11 (verified in app)
Cross-part twin of the per-part `#overhang-connections-section`, so you create connections
between two parts from A/B **dropdowns** (populated + two-way synced with the 3D tool) instead
of scrolling long lists. New section `#assembly-oconn-panel` (index.html, after the Overhangs
list) + NEW module [assembly_overhang_connections_panel.js](../../../frontend/src/ui/assembly_overhang_connections_panel.js)
(`initAssemblyOverhangConnectionsPanel({store, getInstanceDesign, fetchInstanceDesign})`).
- **Layout mirrors the part editor:** Overhang A `<select>` (grouped by part via `<optgroup>`,
  cyan border) · connection-type icon button + popover (all 12 variants) · Overhang B `<select>`
  (magenta) · length (hidden for direct/indirect) · Generate ("Make Complementary" for the two
  DIRECT variants, else "Generate Linker") · forbidden-polarity warning · a linkers+bindings list
  with delete (click a linker row → reselect its A/B + variant).
- **Two-way A/B:** A = `assemblyOverhangSelection[0]`, B = `[1]`. Dropdown change → `setState`
  the slice; a 3D-tool click → dropdown values follow (subscription). Shared with the list panel
  + rings.
- **Reuse, don't fork:** variant rules/icons from [ct_icons.js](../../../frontend/src/ui/ct_icons.js)
  (`CT_VARIANTS`/`ctIsForbidden`/`ctForbiddenReason`/`ctAttachPair`/`ctIsDirect`/`ctIsIndirect`/
  `ctLinkerType`/`ctVariantForConnection`/`ctTileSvg`) — same source of truth as the per-part
  panel + manager popup; grouped overhang model from `groupOverhangs`; create bodies mirror the
  popup's `_onGenerateLinker`/`_onMakeComplementary` (assembly client fns
  `createAssemblyOverhangConnection`/`createAssemblyOverhangBinding` + `patchInstanceOverhang`
  RC write).
- **Shared per-instance design cache extracted:** [assembly_instance_designs.js](../../../frontend/src/ui/assembly_instance_designs.js)
  `initInstanceDesignCache` (renderer sync fast-path + async `api.getInstanceDesign` fallback +
  `attempted` refetch-guard + `prune`) — BOTH sidebar panels use it (list panel refactored onto
  it; pure-helper tests stayed green = the pin). Each panel holds its own cache instance (dedup
  within a panel; ~2× fetch across panels is negligible).
- **Pins:** [assembly_instance_designs.test.js](../../../frontend/src/ui/assembly_instance_designs.test.js)
  (5) + [assembly_overhang_connections_panel.test.js](../../../frontend/src/ui/assembly_overhang_connections_panel.test.js)
  (5: `encodeOption`/`decodeOption`/`revcomp`/`connectionBody`/`canGenerate`). App-exercised
  (throwaway Playwright): dropdowns show PartA/PartB optgroups + 4 options, two-way sync both
  directions, creating an end-to-root ds linker grew the list (1→2 conns), zero console errors.
- main.js LOC Δ (both panels total): ~+22, pure wiring (2 imports + 2 factory inits + show/hide +
  rebuild). No cohesive block in the closure.

## What ships

# Traps — supporting detail

[Topic head](../../project_overhang_subdomains.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Traps

- **`models.py:204` `SubDomain`'s own docstring is wrong** — it still says the rotation fields are
  "stored but UNUSED in Phase 1". Geometry has read them since Phase 4
  (`deformation.py:1246` beads, `:2070` axes). Don't "clean up" the fields on the docstring's word.
- **Feature-log slot semantics.** `OverhangRotationLogEntry` (`models.py:1351`, validator `:1382`)
  packs two kinds of slot into parallel lists: `sub_domain_ids[i] is None` → legacy whole-overhang
  slot where `rotations[i]` is the real quaternion; a UUID → sub-domain slot where `rotations[i]`
  is the placeholder `[0,0,0,1]` and θ/φ carry the data. Anything walking `overhang_rotation`
  entries (seek, rollback) **must** branch on that.
- **The DD modal suppresses main-scene rebuilds.** `domainDesigner.modalActive` →
  `design_renderer.js:639-674` stashes pending rebuilds and flushes exactly once on close. A change
  expecting live 3D feedback while the Domain Designer is open will silently not render.
- **`_sub_domain_at_attach` is a coarse heuristic** (root → first sd, free_end → last sd) and it is
  load-bearing: it builds the binding/linker mutex pair-set in the `Design` validator
  (`models.py:2396`) and is used by `assembly_duplex.py:132`. It **moved out of `crud.py` to
  `models.py:458`**; a second copy `_cv_sub_domain_at_attach` lives at `crud.py:7614` for the
  connection-version path.
- φ-ref can snap when a φ-only rotation crosses 90° relative to world-Y. Accepted for v1.

## Backend — probed locations (2026-07-31)

The router carve-up did **not** touch these: every sub-domain and binding route is still in
`backend/api/crud.py`, live under `crud_router` (`main.py:226`, prefix `/api`).

| Thing | Where |
|---|---|
| `SubDomain` (13 fields, exactly as documented) | `models.py:204`; backfill validator `:302` |
| `OverhangSpec.sub_domains` / `TmSettings` / `Design.tm_settings` | `models.py:283` / `:1867` / `:2269` |
| `OverhangBinding` (20 fields — grew 6 since the log) / `Design.overhang_bindings` / mutex validator | `models.py:579` / `:2255` / `:2363` |
| `OverhangRotationLogEntry` + slot validator | `models.py:1351` / `:1382` |
| Tiling validation (carved out) | `crud.py:6217` is a shim → `core/overhang_ops.py:195` |
| Tm/GC/hairpin annotation | `core/overhang_ops.py:266` → `core/thermo.py:78/87`, `overhang_generator.py:48/71/129` |
| Sub-domain-aware sequence assembly | `core/sequences.py:410 _assemble_overhang_5to3` (shared by overhang + binder RC branches); `is_watson_crick_complement:73` |
| Creation sites | `lattice.py:3047` (`make_overhang_extrude`), `:3291` (`_reconcile_inline_overhangs`), `:3424/3516/3553` (`autodetect_overhangs`) |
| ss single-strand linker `__lnk__{id}__s` | `lattice.py:4435 _build_ss_linker_strand`, called `:4469` |
| **θ/φ geometry chain (beads)** | `deformation.py:1131 apply_overhang_rotation_if_needed` — gate `:1173`, walk `:1241-1319`, quat `:897 _quat_from_theta_phi` |
| **θ/φ geometry chain (axes/shafts)** | `deformation.py:1897 _apply_ovhg_rotations_to_axes` — gate `:2034`, walk `:2063-2132` |
| Routes: list / split / merge / patch / recompute / generate-random / tm-settings / resize-free-end | `crud.py:6531 / 6547 / 6650 / 6751 / 6870 / 6934 / 7080 / 6374` |
| Routes: rotation / rotations-batch / frame | `crud.py:5249 / 5333 / 5410` |
| Routes: bindings GET/POST/PATCH/DELETE + relax + display-pose | `crud.py:8444 / 8491 / 8585 / 8887 / 7812 / 8828` |
| Complement-bp-range snapshot+restore across linker resize | `crud.py:7331-7370` (in `patch_overhang_connection:7262`) |

All mutating sub-domain routes wrap `mutate_with_feature_log('overhang-bulk')`.

**Tests (all fast, none `slow`):** `test_sub_domains.py` 11 · `test_subdomain_boundary_hairpin.py` 5
· `test_subdomain_chain_math.py` 9 · `test_subdomain_rotation.py` 15 · `test_overhang_bindings.py`
**27** (grew from 15) · `test_overhang_connections.py` 59. Every test name the log cites exists in
code. `scripts/smoke_test_subdomains.py` still targets only live endpoints.

## Frontend — probed locations (2026-07-31)

Entry: menu **Tools → Overhangs Manager** (`main.js:4131`), or right-click an overhang
(`main.js:959/6386`, `overhang_orientation_menu.js:159`). No hotkey. Tab controller
`overhangs_manager_popup.js:1763 _switchTab('domain-designer')` → sets `modalActive`, widens the
modal, lazy-inits on the next macrotask.

| Module | LOC | State |
|---|---|---|
| `ui/overhangs_manager_popup.js` | 2473 | live — tab controller, builds the `ddApi` object |
| `ui/overhang_pathview.js` | 2212 | live — sole importer is the popup (`:33`) |
| `ui/domain_designer_panel.js` | 1065 | live — sole importer is the popup (`:34`) |
| `ui/domain_designer_preview.js` | — | **deleted (Phase 7), zero dangling refs** |
| `scene/sub_domain_gizmo.js` | 381 | **dead** — retained only by `void initSubDomainGizmo` (`main.js:4670-4680`) |
| `state/store.js` `domainDesigner` | — | `selectedOverhangId`, `selectedSubDomainId`, `expandedHelices`, `modalActive` live; `activePane` dead |
| `scene/design_renderer.js:639-674` | — | live — the modal-open rebuild deferral |
| `scene/animation_player.js:167` `_subDomainStateAtIndex` | — | snapshot-only; still no seek-restore consumer |

`overhang_pathview.js` forks the cadnano editor: it imports `BP_W, CELL_H, PAIR_Y, GUTTER` from
`cadnano-editor/pathview.js:252-256` and 15 palette constants from
`cadnano-editor/pathview/palette.js`. Changing either propagates here.

**Perspective lock (Phase 7, user-locked):** `selectedOverhangId` is the multi-grid anchor and is
changed **only** by clicks in the listing; `selectedSubDomainId` may belong to the listing-selected
*or* the partner overhang. `_focusedOvhg()` walks all overhangs to resolve the owner so PATCHes hit
the right `overhang_id`.

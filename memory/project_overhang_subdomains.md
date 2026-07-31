---
name: Overhang sub-domains + Domain Designer (Phases 1-7)
description: SubDomain model, Domain Designer tab, per-sub-domain rotation (backend-only now), OverhangBinding. Audited 2026-07-31.
type: project
---

# Overhang sub-domains + Domain Designer

**Rank:** P2 — the feature ships and is in daily use; what remains is a dead-rotation carcass to
remove, two live endpoints with no UI, one latent geometry asymmetry, and zero frontend tests.
No wanted capability is blocked, and `OverhangBinding` is on a documented deprecation path.

**Status (audited 2026-07-31 against the code — every anchor below was probed):**

| Phase | Claim in the log | Reality |
|---|---|---|
| 1 `SubDomain` model + CRUD + thermo | shipped | **SHIPPED, live** |
| 2 | folded into 3 | n/a |
| 3 Domain Designer tab | shipped | **SHIPPED, live** — minus the Tm-settings panel, which was never built |
| 4 per-sub-domain θ/φ rotation | shipped | **Backend SHIPPED and still read by geometry. UI DELETED by the user 2026-05-11.** Editing path is a carcass |
| 5 `OverhangBinding` | shipped | Model + CRUD **SHIPPED**. Its headline behaviour — bind ⇒ freeze the joint at a solved angle — was **REVERTED at user request 2026-05-14**. The solver is dead code |
| 6 binding-event animations | "not started" | **Shipped elsewhere, under a different architecture** → [[project_strand_animations]]. Nothing named in the Phase-6 plan (`BindingEventLogEntry`, `scene/binding_overlay.js`, `event_type`) exists |
| 7 pathview rework + ss single-strand linker | shipped | **SHIPPED, live** |

History (the verbatim 7-phase log) → `project_overhang_subdomains_archive.md`. Don't read it in a
routine loop.

## Two facts the phase log gets backwards

1. **Binding no longer locks a joint.** `crud.py:8724-8733`: *"no automatic post-bind cluster
   relax… Earlier iterations auto-rotated the joint on bind; reverted at user request
   2026-05-14."* Bind now does **topology relocation only** (`compute_bind_topology` /
   `apply_bind_topology`), and `locked_angle_deg` stays `None` unless an external caller supplies
   one — which nothing does. Consequences: `binding_relax.compute_locked_angle` (`:610`) has
   **zero callers repo-wide**, and `cluster_gizmo`'s grey "locked" ring (`cluster_gizmo.js:395`,
   keyed on `joint.min_angle_deg === joint.max_angle_deg`) no longer fires from a binding. The
   *bound* semantics that survived live in [[project_overhang_binding_extensions]], not here.
2. **Phase 6 is not open work.** Unzip / toehold-displacement animation shipped as the
   `frontend/src/strand-anim/` subsystem + `scene/overhang_unzip_overlay.js` +
   `scene/overhang_strand_anim.js` (both imported at `main.js:112-113`), driven by
   `OverhangSpec.strand_anim_setup` (`models.py:300`) and `AnimationKeyframe.strand_anim_phi`
   (`models.py:1726`), with modes `unzip` / `displacement` (`animation_panel.js:58`). `shear` was
   dropped. Keyframed φ ⇒ the export-determinism carryover is satisfied by construction.

## Which doc to open (this territory has seven)

| Question | Doc |
|---|---|
| SubDomain model, tiling, split/merge, Tm, the Domain Designer tab | **this file** |
| What `bound=True` actually does (topology relocation, snapshot/revert, joint lock) | [[project_overhang_binding_extensions]] |
| The `Duplex` model that supersedes `OverhangBinding` | [[project_overhang_duplex_foundation]] |
| The right-sidebar connections panel + Connect/Apply pipeline | [[project_overhang_connections_panel]] |
| Assembled-sequence display + the read-only sidebar field | [[project_overhang_sequence_display]] |
| Binder strands, `Domain.binds_overhang_id` | [[project_oh_binder]] |
| Unzip / TMSD animation | [[project_strand_animations]] |

## Locked decisions (still binding — do not renegotiate)

1. Sub-domains are addressable segments of ONE continuous strand — no new nicks, no new strand
   entities. Gapless tiling: Σ `length_bp` == backing domain length, contiguous, every bp owned.
2. Every overhang always has ≥1 sub-domain. Old files lazy-migrate via the `OverhangSpec`
   `@model_validator(mode='after')` (`models.py:302`, idempotent, UUID5 from `NADOC_SUBDOMAIN_NS`).
   The validator can't see the backing domain length, so **creation-site construction in
   `lattice.py` is primary** and `crud.py:6232 _backfill_sub_domains_if_empty` repairs
   validator-made length-1 stubs on load *and* import.
3. Sequence ownership = parent canonical + per-sub-domain override. Top-level overhang sequence
   write returns 409 if any sub-domain has an active override.
4. Resize policy: the **last** sub-domain absorbs Δ length; 422 if that pushes it below 1 bp or
   below its own override length.
5. Rotation = 2-DOF parent-relative chain. θ ∈ [-180,180] around the parent axis, φ ∈ [0,180] from
   it; φ-ref = world-Y projected ⊥ parent_axis, **world-Z fallback when `|parent_axis·Y| > 0.9`**.
   sd 0's parent axis = helix tangent at the junction bp; sd N>0's = the upstream sub-domain's END
   tangent after all upstream rotations. Compose θ first, then φ.
6. **Three-Layer Law: `SubDomain` is TOPOLOGY.** Geometry/atomistic read only.
7. `feedback_overhang_definition`: the overhang stays one contiguous strand region; sub-domains are
   pure metadata over it.

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

## Open items (live, probed 2026-07-31)

1. **Merge is unreachable from the UI.** `mergeSubDomains` is put into `ddApi`
   (`overhangs_manager_popup.js:1834`) and **never invoked**; the panel binds split (pathview
   right-click) with no merge affordance. Backend `crud.py:6650` is live and tested. Split is
   currently one-way.
2. **Tm settings has no UI** — same shape: `patchTmSettings` in `ddApi:1835`, zero invocations;
   `PATCH /design/tm-settings` (`crud.py:7080`) live. The Phase-3 "Tm settings panel" deliverable
   was never built, so `na_mM`/`conc_nM` are only reachable by API.
3. **Decide the fate of the rotation-editing carcass.** Dead: `scene/sub_domain_gizmo.js` (381
   LOC), the wrappers `patchSubDomainRotation` / `patchSubDomainRotationsBatch` /
   `getSubDomainFrame` (`overhang_endpoints.js:217/226/236`, zero production callers), and
   `e2e/sub_domain_rotation.spec.js` — 4 of its 8 specs probe `window.__nadocSubDomainGizmo`, which
   production no longer sets, and the rest target θ/φ inputs deleted in Phase 7. **Do NOT delete
   the backend side with it:** `crud.py:5249/5333/5410` and the `deformation.py` chain walk still
   read θ/φ out of saved files, pinned by 24 tests. Either restore the gizmo or delete
   gizmo+wrappers+spec and keep the backend as a file-format-only path.
4. **Latent geometry asymmetry: beads and shafts disagree on a duplex-cluster driver.** The axes
   path `continue`s past the sub-domain chain when `_overhang_is_duplex_cluster_driver`
   (`deformation.py:808`) is true (`:1969`); the bead path (`:1131`) never calls that check and
   still applies the chain. A saved design with non-zero sub-domain θ/φ on a bound-duplex driver
   would render beads and shaft in different places. Latent only because no UI can set θ/φ.
   **Static analysis, not app-verified.**
5. **`compute_locked_angle` is dead code** (`binding_relax.py:610`, 0 callers) — see "backwards"
   above. The old "multi-DOF locked-angle relax" carryover is moot while nothing calls the 1-DOF
   path. Decide: delete, or re-wire behind an explicit user action.
6. **Zero frontend tests over ~5.7k LOC.** No vitest file touches `overhang_pathview`,
   `domain_designer_panel`, `overhangs_manager_popup`, or the `domainDesigner` store slice. The
   only coverage is e2e: `domain_designer.spec.js` (11), `overhang_bindings.spec.js` (6), and the
   broken rotation spec (8).
7. **Orphan exports to prune:** `listSubDomains` (`overhang_endpoints.js:155`, 0 callers);
   `listOverhangBindings` (e2e-only — so `GET /design/overhang-bindings` `crud.py:8444` has no
   production consumer); `store.domainDesigner.activePane`, which defaults to `'preview'`, a pane
   deleted in Phase 7, and is read by nobody.
8. **`OverhangBinding` is on a documented deprecation path, and sub-domain granularity is what gets
   lost.** `models.py:519` declares `Duplex` supersedes it;
   `duplex.py:63 synthesize_duplexes_from_bindings` runs on **every** load and import
   (`crud.py:1367/1401`), so every binding design carries a parallel duplex graph; Phase 6 of
   [[project_overhang_duplex_foundation]] retires bindings outright. But `DuplexEnd` is
   `{overhang_id, start_bp, end_bp}` — **bp intervals, not sub-domain refs** — and
   `OverhangBinding.sub_domain_a_id/_b_id` is read by the duplex path in exactly one place, the
   one-shot migration at `duplex.py:76-78`. `design_automation_backlog.md:162` already flags the
   sub-domain-binding half of AF-37 ⚠ ASK USER FIRST for this reason. **Ask before assuming
   sub-domain-level bindings survive the retirement.**
9. Phase-7 follow-ups, carried unverified: ss linker bridge nucleotides don't flow through
   `/api/design/geometry` (3D ssDNA bridge deferred); the orphan-overhang three-tier helix-id
   fallback could be resolved at load time instead; linker resize while a binding is selected may
   need a `cluster_joints` cache invalidation.

Both geometry entry points are fully wired — `apply_overhang_rotation_if_needed` ←
`design_geometry.py:397/761`, `crud.py:5478`; `_apply_ovhg_rotations_to_axes` ← `crud.py:403/410/1295`,
`routes_blade.py:357` — so items 3 and 4 are about a live path, not a dormant one.

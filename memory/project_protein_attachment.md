---
name: project-protein-attachment
description: Protein import, conjugation, and representation parity across designs, assemblies, and photomode. SHIPPED and live.
metadata: 
  node_type: memory
  type: project
  originSessionId: 10db5144-b0d9-4f8c-9ecd-5f861f8987a9
---

# Protein import + attachment to DNA overhangs

**Status (updated 2026-09-01): SHIPPED AND LIVE.** Import → free placement →
attach-to-overhang → gizmo move → SASA-based conjugation-atom picking work end to end.
Imported proteins now participate in Full, Cylinders, Surface, VDW, Ball & Stick, and Stick
representations in design view, legacy/shared assemblies, and photomode.

History (Phases 1–2, free proteins, gizmo, lifecycle/delete fixes) → `project_protein_attachment_archive.md`.
The MD/simulation side of proteins is a **different doc**: [[project-proteins-in-simulation]]
(`protein_cg.py` Cα beads + ANM, `protein_enm.py` extrabonds, `oxdna_protein.py` hybrid runs).
This file is the **design/display layer only**.

Goal: model DNA origami decorated with proteins. Biological picture: a protein is conjugated to
a ssDNA *handle* that hybridizes an *overhang*.

## Confirmed scope (user decisions, 2026-05-22 — still binding)
- **Visualization first** — no MD/force-field topology for proteins *in this doc's scope*.
- **Handle = AUXILIARY ANCHOR, never a strand.** Display-only data; must not enter the
  scaffold/staple strand graph (Three-Layer Law). Handle seq auto-derived as overhang complement, cached for display.
- **Scope: both** design-level (overhang in a `.nadoc`) and assembly-level (`.nass` part /
  interface point). ← the assembly half is the one thing still unbuilt (Phase 3 below).
- **All-atom rendering**, reusing the per-element InstancedMesh atomistic renderer.
- **Conjugation atom + adjustable pose**: user picks a conjugation residue/atom; snap to handle free tip pointing outward; gizmo to adjust.
- **Library + instances**: import a PDB once, attach many instances via per-instance transforms; atoms stored once.
- **One PDB = one rigid `ProteinAsset`** (multi-chain rides together; per-chain split deferred).

## Code locations (verified 2026-07-30 — trust this table over any prose)

| Thing | Where | Note |
|---|---|---|
| `ProteinAtom` / `ProteinAsset` | `backend/core/models.py:2106` / `:2119` | asset has `bonds`, `default_conjugation_atom_serial`, `center_of_mass`, `metadata` |
| `ProteinTargetFree` / `…Design` / `…Assembly` | `models.py:2157` / `:2136` / `:2143` | **discriminator strings are `"free"` / `"overhang"` / `"assembly"`** — design-scope is `"overhang"`, not `"design"`. Assembly variant is declared but consumed nowhere |
| `ProteinTarget` union | `models.py:2167` | `Field(discriminator="kind")` |
| `ProteinAttachment` | `models.py:2173` | + undocumented-until-now `handle_complement_bp`, `handle_spacer_nt` |
| `Design.protein_assets/_attachments` | `models.py:2267-2268` | live |
| `Assembly.protein_assets/_attachments` | `models.py:3127-3128` | **orphaned slots** — serialize into `.nass`, nothing writes/reads them |
| Parse / classify | `protein.py:102` `parse_protein_pdb(…, exclude_dna=)`, `:60` `classify_pdb_content`, `:51` `_AMINO_ACIDS` | |
| Render math | `protein.py:314` `resolve_overhang_anchor`, `:355` `protein_base_world`, `:388` `compose_protein_world_transform`, `:402` `gizmo_move_to_pose` | `world = pose · base` |
| Atomistic emit | `protein.py:215` `protein_asset_to_atomistic`, `:35` `PROTEIN_SENTINEL_PREFIX="__protein__"`, `:202` `protein_asset_meta` | |
| Bond inference | `protein.py:251` `infer_bonds_by_distance` → `:445` `build_protein_attachment_atoms` → `backend/core/atomistic.py:1197` | **built and called** (the old doc called this unbuilt "Phase 4") |
| Azide/conjugation | `protein.py:528` `azide_attach_end`; `backend/core/conjugation.py:59` `atom_sasa`, `:116` `find_conjugation_candidates` | |
| Routes (all but one) | `backend/api/routes_protein.py` — import `:53`, library `:76`, delete-asset `:82`, atomistic `:90` (`?asset_id=` preview `:111`), conjugation-candidates `:151`, conjugate `:246`, attachments POST `:192` / PATCH `:329` / DELETE `:380` | router registered `backend/api/main.py:272`. **Moved out of `crud.py` by the carve-up.** PATCH takes BOTH `pose` (16 floats, `:321`) and `gizmo_move` (`:322`) |
| `POST /design/import/pdb-auto` | **still `backend/api/crud.py:1771`** (+ `_import_protein_free` `:1843`) | returns `needs_dna_decision` `crud.py:1807` |
| Session library | `backend/api/state.py:106` `_protein_library`, helpers `:704/:710/:716/:722`; cleared in `close_session` `:676` | `documents.py:69` deliberately keeps it on document close |
| Feature-log op kinds | `models.py:1502-1506` — `protein-import`, `protein-attach`, `protein-attach-patch`, `protein-attach-delete`, `protein-conjugate` | **no protein special-case** in the delete path; handled data-driven via `feature_dependencies.py:49` `_ID_COLLECTIONS` + `crud.py:9350` `_filter_removed_ids_from_design` |
| Frontend subsystem | `frontend/src/scene/protein_subsystem.js` (renderer + gizmo + refresh + store subscriptions), wired `main.js:103` | `proteinRenderer` `main.js:1836`, `_refreshProteins` `main.js:1838` |
| Gizmo | `scene/protein_gizmo.js` (imported by `protein_subsystem.js:11`, **not** main.js) | |
| Modals / menus | `ui/protein_attach_modal.js` (`main.js:102`, menu `menu-file-attach-protein`), `ui/import_pdb_modal.js` (via `ui/import_menu.js:22`, menu `menu-file-import-pdb`) | `menu-file-import-protein` is gone (correct) |
| Conjugate Manager | `ui/conjugate_manager.js` (463 LOC, 3D marker picking `:65`/`:309`) + `conjugate_manager_logic.js`, wired `main.js:104`; Tools ▸ Conjugate Manager `main.js:4126`, protein right-click `main.js:1738` | |
| Renderer hooks | `scene/atomistic_renderer.js` — `raycastPick:258`, `centroidOf:278`, `beginLiveTransform:295`, `applyLiveTransform:310`, `endLiveTransform:325` | |
| Selection / color | `selection_manager.js:1650` dep `getProteinRenderer` (provided `main.js:821`), pick branch `:3512`; `atomistic_renderer/color_resolver.js:75` `'protein'` branch; inspector `ui/properties_panel.js:306` | |
| API client | `api/client.js` — `importPdbAuto:1573`, conjugation-candidates `:1602`, `createProteinAttachment:1611`, `conjugateProteinToOverhang:1628`, `patchProteinAttachment:1640`, `deleteProteinAttachment:1646` | |
| Recents | `api/recent_files.js:40` key `nadoc:recentProtein`, `:45/:66/:75` | |
| Tests | `tests/test_protein.py` (**36**), `test_conjugation.py` (7); MD-side `test_protein_cg.py`/`test_protein_md.py`/`test_oxdna_protein.py` belong to the other doc. Vitest: `scene/protein_subsystem.test.js`, `ui/conjugate_manager{,_logic}.test.js`, `ui/import_menu.test.js` | |

**Render source of truth:** `GET /design/protein/atomistic` renders ONLY
`design.protein_attachments` (`routes_protein.py:126-146`) — the session-library-at-origin
fallback was deliberately removed so undo/delete/move stay correct. Frontend mirrors this: a
single `store.subscribe` on `currentDesign` identity (`protein_subsystem.js:76-81`) drives
`_refreshProteins`; a second subscription `:85` handles selection visuals.

## Representation parity and cylinder invariants (2026-09-01)

- **Full:** C-alpha tube/trace (`scene/protein_trace_renderer.js`), replacing the visually
  noisy all-atom default while retaining exact all-atom centroids, picking, and transforms.
- **Cylinders:** one padded atom-bounds ovoid per protein attachment. Conjugated DNA uses
  paired half-cylinders: the overhang and its `oh_binder` complement share one pose.
- **Surface:** protein atoms are included in the molecular-surface payload.
- **Atomistic:** VDW, Ball & Stick, and Stick use the dedicated protein atomistic renderer.
- **Assembly + photomode:** legacy and shared-instancing assembly renderers support the same
  abstract/atomistic modes; `proteinTrace` and `proteinOvoid` have explicit photo mappings.

### Authoritative overhang-cylinder geometry

Protein-constrained moves return partial nucleotide geometry plus partial helix axes. The
frontend must reject nucleotide-only patches whenever `currentHelixAxes` changes. Backend
`ovhg_axes` and the owning domain `segments` must carry identical transformed endpoints.
Segment ownership is determined by either `ovhg_id` or `domain_ids`: VoltronCoreArm OH7 is
represented by its binder domain and therefore has a null segment `ovhg_id`.

The deformation-lerp pass must preserve `_overhangCylData.wsStart/wsEnd`; rebuilding from the
whole parent helix axis snaps an inline overhang back to its old pose. `oh_binder` strands must
be routed through the complementary binding-half cylinder path, not emitted as an additional
ordinary full cylinder. `getOverhangCylinderDiagnostics(overhangId)` exposes endpoints decoded
from the actual rendered instance matrix for future visual regression work.

Permanent real-design regressions load `workspace/VoltronCoreArm.nadoc`, apply a protein
rotation plus translation, and compare the final cylinder vector with the paired nucleotide
backbone centerline (cosine > 0.99), as well as exact `segments`/`ovhg_axes` endpoint parity.

## Open items (rewritten against the probe)

1. **Assembly-owned attachment authoring.** Proteins embedded in part designs now render in
   assemblies in every applicable representation. The distinct `ProteinTargetAssembly` model
   still lacks authoring UI/API for attaching a protein directly to an assembly-level target;
   this is separate from the now-shipped part-protein assembly rendering path. Gated on
   [[project-path-to-thousands]] (shared-renderer default) before touching assembly render code.
2. **`.nass` carries the slot but not the feature.** `Assembly.protein_assets/_attachments`
   serialize (pydantic) yet have no producer or consumer — a save/load round-trip preserves
   whatever is there, but nothing ever puts anything there. Fill or drop as part of item 1.
3. **`ProteinAsset.bonds` is never populated.** `parse_protein_pdb` hard-codes `bonds=[]`
   (`protein.py:191`); `protein_asset_to_atomistic:247` consumes the empty list, so the protein
   *preview* render is bond-free by construction. Bonds only exist on the design-wide atomistic
   export path (`build_protein_attachment_atoms` → `infer_bonds_by_distance`). → ball-and-stick
   proteins work in export, not in the viewer.
4. **Stale docstring in live code:** `routes_protein.py:97` still promises "plus any imported
   asset not yet referenced by an attachment"; the code at `:129-133` removed exactly that.
   One-line fix.
5. **Per-chain split** of a multi-chain PDB is still deferred (original scope decision).

## Gotchas
- [[project-path-to-thousands]] is required reading before touching assembly render code (item 1).
- `tests/test_seamless_router.py::test_teeth_closing_zig` (`:152`) is PRE-EXISTING hash-order-FLAKY
  (asserts exactly 4 scaffold strands; the router yields 4 or 5 by set-iteration order). Adding
  tests can flip it in default randomized runs — NOT a protein regression. Don't chase it from here.
- The design-scope discriminator is `"overhang"`, not `"design"`. `ProteinTargetDesign` is the
  class name; `kind="overhang"` is the wire value.

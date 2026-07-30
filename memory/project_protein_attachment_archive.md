---
name: project-protein-attachment-archive
description: History of the protein import/attachment build-out (Phases 1-2, free proteins, gizmo, lifecycle fixes). Head is project_protein_attachment.md — never read this in a routine loop.
metadata:
  node_type: memory
  type: project
---

# Protein attachment — ARCHIVE (history only)

Split out of `project_protein_attachment.md` on 2026-07-30 during a `/audit-plan` pass. The head
holds current state, the code-location table, and open items. **Read this file only to mine a
specific past decision.** Paths below are as-of the dated entry and are in many cases stale —
the head's table is authoritative for where code lives now.

## Phase 1 SHIPPED (2026-05-22) — import + library + render-at-origin
- Parser keeps protein/HETATM, drops water+ions. **Handles CHARMM-format PDBs**: reads 4-char resnames (cols 18-21, so TIP3 isn't truncated to TIP), drops CHARMM ion names (SOD/CLA/POT…), infers element from atom-name first char when the element column is blank — and deliberately does NOT treat `CA` as calcium (it's C-alpha carbon).
- Session library in `state.py` (`_protein_library` dict + add/get/list/remove), decoupled from any one design, cleared on `close_session`. Phase 1 import goes to the library only (NOT through feature log / design embed — that's Phase 2's job at attachment time).
- Routes (crud.py at the time): `POST /design/protein/import`, `GET /design/protein/library`, `DELETE /design/protein/{id}`, `GET /design/protein/atomistic?asset_id=` (renders at PDB coords; no attachment yet).
- Atomistic palette generalized for proteins: backend `VDW_RADIUS`/`CPK_COLOR` + `DEFAULT_*` and a new `_element_meta()` that emits meta for every element present; frontend `atom_palette.js` `ELEMENTS` + `DEFAULT_ELEMENT`, and the renderer bucket loop now uses `ELEMENTS[el] ?? DEFAULT_ELEMENT` instead of dropping unknown elements.
- Frontend: a second independent `proteinRenderer = initAtomisticRenderer(scene)` in main.js (coexists with DNA; does NOT hide CG), `_refreshProteins()` fetches `/api/design/protein/atomistic`.

## Phase 2 SHIPPED (2026-05-22) — attach to overhang + pose (design scope)
- `backend/core/protein.py`: `resolve_overhang_anchor(nucs, oh_id, attach_end)` → (tip_pos, outward) where outward = (attach_end − opposite_end) normalized (robust; no axis-sign guessing; `_oh_attach_nuc` from linker_relax picks the tip). `compose_protein_world_transform(asset, att, tip, outward)` = `T(tip_out)·AnchorRot·pose·R_canon·T(-conj)` — conjugation atom lands at the tip, body (com−conj) points outward, user `pose` (Mat4x4) applied in the anchor frame (+Z=outward). `reverse_complement()` for the cached display-only handle seq.
- `SnapshotOpKind` += `protein-attach` / `protein-attach-patch` / `protein-attach-delete`.
- Routes (crud.py at the time): `POST/PATCH/DELETE /design/protein/attachments[/{id}]` via `mutate_with_feature_log`; create embeds the asset into `design.protein_assets` + caches `handle_sequence`. `GET /design/protein/atomistic` (no arg) now places visible overhang attachments at their anchor; `?asset_id=` previews one at PDB coords; an asset with ANY attachment (visible or not) is excluded from the unattached→origin fallback (visible:false HIDES, doesn't relocate).
- Frontend: `ui/protein_attach_modal.js` (File ▸ Attach Protein to Overhang…) — pick protein + overhang, attach; lists attachments w/ visibility + detach. API client: `createProteinAttachment/patchProteinAttachment/deleteProteinAttachment`.

## Merged "Import PDB" SHIPPED (2026-05-22)
- The two menu items merged into ONE **File ▸ Import PDB…** → popup (`ui/import_pdb_modal.js`): a 4-char RCSB id (server-side download via `https://files.rcsb.org/download/{id}.pdb`) OR import-from-file. Routing is AUTO-DETECT: `classify_pdb_content` sniffs residues → DNA → DNA design importer (merges into current design); protein → library; a complex does both.
- Endpoint `POST /design/import/pdb-auto {content?|pdb_id?, name}` → `{imported:{dna,protein}, design?, protein?, import_warnings?, source}`. Client `importPdbAuto` returns raw json (no auto-sync); the menu handler `_runPdbImport` does reset+`syncDesignResponse` for DNA and `_refreshProteins` for protein. The standalone `menu-file-import-protein` item + handler were REMOVED (the `/design/protein/import` endpoint stays for tests).

## Verified (2026-05-22)
- `tests/test_protein.py` = 19 tests (parse/CHARMM, asset→atomistic, anchor math, attachment CRUD, placement, classify, pdb-auto routing). Full suite stable-order: 1416 passed, 1 PRE-EXISTING deterministic failure `test_seamed_router…teeth_reroute` (fails on baseline too). Frontend `npm run build` clean.

## Free proteins + select + move + DNA-prompt SHIPPED (2026-05-23)
Model now: `world = pose · base`. `base` = identity for `ProteinTargetFree` (atoms at PDB coords) or the overhang anchor-compose; `pose` is a WORLD-space rigid delta (default identity). A move left-multiplies `pose` by the world delta — uniform for free + anchored, and anchored proteins keep following the overhang.
- **New `ProteinTargetFree` (kind="free")** added to the union. `protein_base_world` + `compose_protein_world_transform = pose·base`. `gizmo_move_to_pose(pose, pivot, translation, rotation)` builds D=T(trans)·T(piv)·R·T(-piv) and returns D·pose (all matrix math server-side + tested).
- **Import now places a free, logged protein**: `/design/import/pdb-auto` protein branch → `_import_protein_free` embeds asset + adds a `free` ProteinAttachment via `mutate_with_feature_log("protein-import")` (new op_kind); auto-creates an empty Design if none. Routing changed: **protein-present → protein import (free); DNA-only → design import** (no more dual-import).
- **DNA-removal prompt**: `parse_protein_pdb(..., exclude_dna=)`. When a structure has BOTH protein+DNA and `remove_dna_from_protein` is undecided, pdb-auto returns `{needs_dna_decision, content, ...}` WITHOUT importing; the import modal shows Remove/Keep DNA, then re-calls with the flag + returned content (no re-download). `classify_pdb_content` + `_AMINO_ACIDS` in protein.py.
- **Move = logged**: PATCH `/design/protein/attachments/{id}` accepts `gizmo_move {pivot,translation,rotation}` (cluster-gizmo shape) or absolute `pose` (16 floats); logs `protein-attach-patch` ("Move protein").
- **Frontend select**: `atomistic_renderer.raycastPick(raycaster)` + `centroidOf(pred)`; `selection_manager.js` injected `getProteinRenderer`, protein pick added in the click handler (depth-respecting, early-return, `selectedObject={type:'protein',id:attachmentId}`); `color_resolver` 'protein' branch dims non-selected proteins. NOT logged (selection is transient).
- **Frontend gizmo**: `scene/protein_gizmo.js` (TransformControls on a dummy at the protein centroid; T/R toggle, Esc detach); on drag-end commits `gizmo_move`, then `onCommitted` refreshes + re-anchors. main.js: `initProteinGizmo`, selectedObject subscription attaches/detaches, `_resetForNewDesign` detaches.
- **Tests**: test_protein.py now 26.

## Gizmo live-preview + hotkey-disable SHIPPED + VERIFIED IN-APP (2026-05-23)
- **Live preview**: `atomistic_renderer` got `beginLiveTransform(pred)` / `applyLiveTransform(mat4)` / `endLiveTransform()` — snapshots the selected protein's instances and re-writes their InstancedMesh matrices each frame. `protein_gizmo.js` `change` handler computes the world delta `M = T(pos)·R(quat)·T(-pivot)` and calls `onLive(M)`; main.js wires onLiveStart/onLive/onLiveEnd to the renderer. On drag-end it commits the same delta as a `gizmo_move` (so the authoritative re-render matches the preview — no jump).
- **Hotkeys disabled while typing a PDB code**: `e.stopPropagation()` on the import-modal PDB input (codebase convention), plus the gizmo `_onKey` ignores events when an INPUT/TEXTAREA/contentEditable is focused.
- **Debug hooks**: `window.__NADOC_DBG__.proteinRenderer` / `.proteinGizmo` exposed.
- **Verified live** (2026-05-23): backend on the running server — import→free placement+`protein-import` log; `gizmo_move` PATCH translates ONLY the targeted protein (centroid Δ matched 9530/9539 ratio) + `protein-attach-patch` log; complex → `needs_dna_decision` then remove→9 atoms. Frontend (one-off non-destructive Playwright): `applyLiveTransform(+9)` shifts the rendered instance matrix by ≈9; a `keydown('r')` in the PDB field does NOT reach the document dispatcher. The actual TransformControls handle-drag was not simulated (fragile in Playwright) — mechanism + wiring verified, drag feel left for manual confirmation.

## Import-PDB Recents SHIPPED + VERIFIED (2026-05-23)
- Import-PDB popup got a **Recent** section listing both recently-used PDB codes (blue "PDB" chip → re-download) and files (grey "FILE" chip → re-import). Storage in `api/recent_files.js`: `getRecentProteinImports` / `addRecentProteinCode` / `addRecentProteinFile`, key `nadoc:recentProtein`, max 8, mixed entries `{kind:'code',code}` / `{kind:'file',name,content}`. Files cache CONTENT (re-importable without a path — browsers don't expose full file paths; "location" = filename) up to 3MB; over that, name-only and clicking re-opens the picker. Quota-exceeded retry drops cached file contents. `recentMeta` is threaded through the import `run()` (incl. the DNA-decision re-call) so a code stays recorded as a code. Verified non-destructively (seed localStorage → modal shows both rows).

## Lifecycle fix — move/delete/undo/redo (2026-05-23)
Bug reports: (1) moving a protein created a duplicate; (2) reverting/undoing the import didn't remove the rendered protein. Root cause: ad-hoc `_refreshProteins()` calls with NO single source of truth, the import didn't sync `currentDesign`, and the placement endpoint rendered unattached SESSION-LIBRARY assets at the origin (so an undone import reappeared at origin).
- **Backend**: `GET /design/protein/atomistic` now renders ONLY `design.protein_attachments` (assets resolved from `design.protein_assets`, session library as fallback). REMOVED the library-at-origin fallback; `?asset_id` is the only origin-preview path. → undo/delete/move are correct because the design's attachments are the sole source.
- **Frontend**: protein rendering is driven by a SINGLE `store.subscribe(currentDesign)` → `_refreshProteins` (coalesced via in-flight/pending flags; always `clearScene`+rebuild). `_syncProteinSelectionVisual()` re-anchors the gizmo at the selected protein's new centroid after every render and detaches when the protein is gone. Gizmo `onCommitted` REMOVED (the move's design-sync drives the subscription). Protein import now calls `api.syncDesignResponse(json)` (was missing → stale currentDesign) + hides the welcome screen.
- **Tests**: `test_undo_import_removes_rendered_protein`, `test_delete_attachment_clears_render` (28 total).
- **In-app gizmo-drag check was cut short — dev server wedged** (recurring `--reload` CPU-spin on the WSL2 tree; a fresh server with no requests also pegs CPU → environmental, not code). The verification test had reset the active design and the wedge blocked its restore, so the user's in-memory design was lost.

## Delete-feature fix — protein-import row (2026-06-19)
Bug: deleting the **protein-import** feature-log row left the protein in the 3D view (proteins live in `protein_assets`/`protein_attachments`, not topology fields `_seek_feature_log` rebuilds, so the old "delete keeps geometry" path stranded them). **Superseded same day by the general option-1 delete rework** (see [[feature-log-overhaul]] "Delete = roll back geometry"): the old per-op special-case was removed; protein-import now rolls back through the unified `_delete_snapshot_feature` path (it's a non-reconstructable snapshot → deleting it restores the pre-import design; threading the full pre-state carries the protein-field removal). Deleting the LAST import surgically keeps earlier proteins; deleting an EARLIER import lists later imports as dependents (protein-import isn't replayable).

## Historical gotcha (resolved — kept for provenance)
- **Dev-server wedge (2026-05-22):** `just dev` (uvicorn `--reload`) pegged a CPU core and hung all requests on this WSL2 tree; restarting reproduced it. Suspected `--reload` file-watcher choking on the huge repo (NAMD_3.0.2/runs/experiments/.venv/node_modules). Workaround: scope it (`--reload-dir backend`) or drop `--reload`. See [[project-dev-server-shutdown-hang]].

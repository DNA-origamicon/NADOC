---
name: Forced ligation feature
description: Pencil tool forced ligation — connect any 3' to any 5' end, bypassing crossover tables. Manual only, NOT for autocrossover.
type: project
originSessionId: 1de548ef-f79d-4998-ba75-26358c25d4a2
---
Forced ligation feature on branch `feature/forced-ligation` (created 2026-04-11). Merged to master 2026-04-12.

**What:** Pencil tool mode — click a 3' end, then click a 5' end to ligate. Purple dashed preview arc, red anchor dot on 3' end, green highlight on valid 5' targets.

**Selection echo fix (2026-09-06):** 3D design reconciliation rebuilds the canonical selection object. Cross-tab sync now compares the selected strand-ID sets before broadcasting, so an unchanged prior selection does not return to the cadnano editor and highlight the merged strand after ligation. Reproduced with the real pencil gesture on an in-memory import of `workspace/Hinge_test.nadoc`; regression lives in `frontend/e2e/cadnano_forced_ligation_selection.spec.js` and `frontend/src/app/cross_tab_sync.test.js`.

**Gesture fixture correction:** The Hinge regression chooses endpoints using the editor's hit-test and excludes higher-priority crossover sprites/arcs when selecting a domain. Raw domain coordinates alone can hit a different strand's crossing arc; a midpoint between a multi-domain strand's ends is not a reliable body click. Verified forced ligation, cleared selection, and successful saves through undo/redo with these checks.

**Duplicate autosave conflict (2026-09-06):** Revision materialization compared a winning save with the old embedded loadout snapshot, so identical overlapping saves after a topology edit could return `409 branch_diverged`. Active editable branches now also compare the live content; a commit-time race adopts the winning revision only when its snapshot hash matches exactly. Different edits still conflict. The Hinge Playwright regression now saves a private project/file and checks the persisted ligation, with failure-safe cleanup of its revision directory.

**Undo/history autosave follow-up (2026-09-06):** Duplicate-save handling alone did not resolve old branch heads restored from undo/history snapshots. Workspace saves now use heads already observed by the same document session (including its undo/redo history); unknown heads still conflict. Successful save acknowledgements preserve edits made during disk I/O. Session recovery stores these persistence cursors separately in `workspace_heads.json`, so automatic backend reload does not lose them. Regression covers ligation → save → undo → save → redo → save, competing external edits, in-flight edits, and restart recovery. `start.sh` now enables source-only reload by default, matching `just dev`; opt out with `NADOC_RELOAD=0`.

**Why:** Users need to connect strand ends that are not at canonical crossover positions (not in the HC/SQ lookup tables). This is a manual override for edge cases in design.

**How to apply:**
- Backend: `POST /design/forced-ligation` with `{three_prime_strand_id, five_prime_strand_id}` — calls `_ligate()` directly, NO crossover record created, single undo checkpoint
- Frontend: pathview.js `_forcedLig*` state variables, `_drawForcedLigationArc()`, integrated into pencil tool pointerdown/move/up flow
- API client: `forcedLigation()` in `api.js`, wired via `onForcedLigation` callback in `main.js`
- Tests: `tests/test_forced_ligation.py` — 5 tests covering same-helix, cross-helix, self-rejection, 404, and undo

**Autoscaffold protection (2026-04-11):**
- `ForcedLigation` model on `Design.forced_ligations` records (helix, bp, direction) for both the 3' and 5' endpoints at ligation time
- `_forced_ligation_protected(design)` in `lattice.py` returns protected strand IDs and helix IDs
- All autoscaffold variants (`auto_scaffold`, `auto_scaffold_basic`, `auto_scaffold_seamless`, `auto_scaffold_jointed`) plus `compute_scaffold_routing` skip protected helices and preserve protected scaffold strands

**Additional fixes shipped on this branch (2026-04-12):**
- SQ lattice overhang position: `make_overhang_extrude` now uses `_lattice_position()` instead of `honeycomb_position()`
- -Z overhang direction: axis flipped to +Z so domain extends leftward in cadnano 2D; phase recomputed
- `grid_pos` added to overhang helices
- Shared overhang helix: two overhangs at same lattice cell reuse one helix (union bp range)
- Nick rendering bug: `changed_helix_ids` now includes all helices from the nicked strand; `_tryPatchInPlace` checks `is_three_prime`
- Overhang autodetect false positives: `reconcile_all_inline_overhangs()` cleans stale inline tags after scaffold mutations and on .nadoc load
- Spreadsheet: Start/End columns (helix label `N[bp]` format) replace Strand ID/Helix; 3D click highlights spreadsheet for all selection types

**CRITICAL:** Forced ligation must NEVER be used by autocrossover, autobreak, or any automated pipeline. It is manual user-only.

**2026-06-27 — both autoscaffold routers are FL-hinge-aware (arbitrary even k×N, compliant + self-gated).** `auto_scaffold_seamed` and `auto_scaffold_seamless` each try a hinge realizer first when FLs are present, routing ONE strand through cross-gap FL bridges for ANY leaf thickness k≥2 and even column count: seamed = a double-pass weave + seam max-matching (`hinge_weave_router.realize_hinge_weave`); seamless = a single-pass Hamiltonian cycle with a buried nick (`realize_hinge_weave_seamless`). Both are self-gated against `scaffold_routing_invariants` (+ `validate_design` + FL-preservation) so they can never regress the contract — the FL records are preserved VERBATIM (the rungs are skipped, never re-placed). A genuine one-off manual FL between lattice-adjacent helices is NOT a gap bridge → the realizer declines → the preserve-the-anchor behavior above is unchanged for it. `build_hinge(k,n)` (`headless_hinge_build.py`) generates kxN hinge primitives for the build→route→verify pipeline. (The 2026-06-26 v1 seamed-raster attempt regressed the contract and was reverted; see [[LESSONS]] H8.) See [[project_hinge_autoscaffold]].

---
name: cluster-copy-paste-ctrl-c-ctrl-v-in-the-3d-part-editor
description: "Lattice-legal duplication of hand-routed clusters — extract/graft core, cluster-paste route, slice-plane ghost. Phase 0+1 shipped 2026-07-09; overhangs/extensions still refused."
metadata: 
  node_type: memory
  type: project
  originSessionId: 606bdeca-6c0a-44d2-ada9-e8bb46c57291
---

## What it is

Select one or more clusters in the 3D part editor → **Ctrl+C** → **Ctrl+V** arms a
translucent ghost that follows the cursor on the slice plane → click places an
identical copy at that lattice offset. For repeating/tiling a hand-crafted routing
that can't be expressed as a primitive.

Shipped 2026-07-09 (Phases 0 + 1). `just test` 4447 passed; `just test-frontend` 2469 passed.

## The invariant that makes it correct (read this first)

Helix FORWARD/REVERSE polarity is `(row + col) % 2` on **both** lattices
(`lattice.scaffold_direction_for_cell` / `square_cell_direction`). Crossover legality
is a pure table lookup on `(is_forward, bp_index % period)` — period 21 HC / 32 SQ
(`crossover_positions.crossover_neighbor`, tables in `constants.py`). Therefore:

> **even-parity grid shift `(Δrow+Δcol) % 2 == 0`, with `Δbp == 0`
> ⇒ every copied helix keeps its polarity AND every copied crossover stays legal.**

`Δbp` is not a parameter — bp indices are copied verbatim. The parity guard is in
`graft_cluster_subdesign`. Pinned by `test_every_pasted_crossover_stays_legal`.

**The cadnano 2D view needs no work.** It derives rows/tracks entirely from the
geometry nucleotide stream (`helix_id, bp_index, direction, strand_type`), so correct
`grid_pos` + `direction` on the grafted helices is sufficient. Verified live.

## Two traps (both cost real debugging time if forgotten)

1. **`cluster_reconcile` steals the pasted helices.** `reconcile_cluster_membership`
   runs inside `mutate_with_feature_log` and assigns a new helix to a pre-existing
   cluster when a lattice neighbour within **Manhattan ≤ 2** belongs to one. A paste
   landing near its source gets swept into the SOURCE's membership. Fix: the mutation
   `fn` returns `MutationReport(new_helix_origins={hid: None for hid in pasted})` —
   the same explicit-orphan hint `__lnk__` bridge helices use.
   Reproduced and pinned both ways: `test_reconcile_without_orphan_hint_steals_pasted_helices`
   (theft happens) and `test_reconcile_with_orphan_hint_leaves_pasted_helices_alone`.
   *Only fires at Δ within Manhattan 2* — a Δ=(0,4) test will not reproduce it.

2. **The inherited rigid guard does NOT catch square-lattice odd parity.** Honeycomb `y`
   depends on `(row+col)` parity, so an odd shift distorts the footprint and trips the
   `primitive_placement` guard. **Square positions are linear** — an odd square shift
   passes that guard silently while inverting every polarity. Hence an *explicit*
   `(Δrow+Δcol) % 2` check, independent of the footprint guard.
   Same reason `placementPreservesShape()` (primitive_placement_logic.js) is NOT
   reusable here: it answers "does the SHAPE survive" and correctly returns `true` for
   any square shift, because primitive placement re-derives helices from the
   destination cell. A **graft copies helices verbatim**. Different question →
   separate predicate `pastePreservesPhase()` in `cluster_copy_logic.js`.

## Files

**Backend**
- `backend/core/cluster_copy.py` — pure. `extract_cluster_subdesign(design, cluster_ids)`
  (what to copy, source coords, truncation) + `graft_cluster_subdesign(host, sub, grid_delta)`
  (where it lands, id remap, additive merge) + `paste_clusters()` convenience.
  Reuses `primitive_placement.py`'s `translate_design` / `_world_delta` / `_fresh_id` /
  `detect_plane` / `primitive_anchor_cell`. **`place_primitive_into`'s "verbatim or
  refuse" contract is untouched** — cluster paste has its own graft.
- `backend/api/routes_clusters.py` — `POST /design/cluster-paste`
  `{cluster_ids, delta_row, delta_col}` → `mutate_with_feature_log(op_kind='cluster-paste')`.
  Response carries `paste_report`. `ValueError` → 400.
- `backend/core/models.py` — `'cluster-paste'` added to the `SnapshotOpKind` Literal.
  **That one string buys undo + revert + delete + feature-slider seek for free** — no
  new feature-log wiring, no `feature_dependencies.py` change. (Keep it OUT of
  `REPLAYABLE_SNAPSHOT_OPS`.)

**Frontend**
- `frontend/src/scene/cluster_copy_logic.js` — pure: `clusterClosure`,
  `footprintForClusters`, `pasteGridDelta`, `pastePreservesPhase`, `pasteParityCandidates`.
- `frontend/src/scene/cluster_clipboard.js` — `initClusterClipboard({store, api, scene,
  slicePlane, showToast}) → {copy, paste, onCommit, cancel, isActive}`. Owns the ghost.
- `frontend/src/scene/slice_plane.js` — small spec hatch: `commitKind` / `onGhostUpdate` /
  `candidateCells` on the placement spec + an `onPlacePaste` init opt. Non-`'segment'`
  commitKind skips the pooled cylinders and delegates drawing to the caller, while still
  reusing the hover raycast, anchor snap and occupied-cell conflict.
- `store.js` — `multiSelectedClusterIds` (the strand union in `multiSelectedStrandIds`
  can't say which cluster a strand came from). Every path that can select a cluster keeps
  both pools in sync (2026-07-09): 3D Ctrl/Shift+click (`_toggleClusterById`), the
  cluster-level lasso (bead + cylinder-LOD), and Ctrl/Shift+click on the sidebar
  "Movable Clusters" rows (`selectionManager.toggleCluster`). A plain click anywhere is a
  SINGLE selection (`selectedObject`); the first additive click folds it into the pool via
  `_promoteSelectionToMulti`. The toggle rule is pure: `toggleClusterSelection()` in
  `selection_level.js` — presence is the cluster-id pool, not "all its strands selected",
  because a bridging staple can belong to two clusters.
  **Gotcha:** a plain cluster click AUTO-OPENS Move/Rotate (`decideSelectionAction`). The
  additive branch in `main.js`'s `onClusterClick` must therefore bypass the tool entirely;
  nulling `selectedObject` inside the promote is what auto-closes (auto-commits) it.
- `keyboard_shortcuts.js` — Ctrl+C / Ctrl+V currently use
  `blockedWhen: assemblyActive || isDeformActive`. **The assembly block records missing host wiring,
  not intended product scope.** Per `project_assembly_feature_parity.md`, an assembly port should reuse
  the same copy/graft core and explicitly choose shared-source edit vs instance fork; do not cite this
  historical guard as a reason to omit parity.
  Ctrl+C yields to the browser's text copy when no cluster is selected (no `preventDefault`).
  Escape cancels the ghost first.

**Ghost trick:** built from `store.currentHelixAxes`, which already holds the LIVE
posed + deformed axes. So a bent, rotated cluster ghosts correctly with **zero pose math**.

## Decisions (user, 2026-07-09)

| | |
|---|---|
| Δbp | always 0 — no UI, no axial shift |
| Boundary strands | **truncate**; a straddling staple becomes a shorter strand, scaffold becomes a free fragment |
| Sequences | **NOT copied** (`sequence=None`) — identical staple sequences would cross-hybridize. Side benefit: truncation never slices a sequence string |
| Posed clusters | copy the pose; `pivot` shifts by the same rigid world vector as the helices |
| Child/domain-level clusters | transitive parent↔child closure; report what was auto-added |
| `ClusterJoint`s | **not** copied (v1) |
| Overhang bindings | copy the pairing, reset `bound=False`, `prior_driven_topology=None`, `target_joint_id=None` |
| `StrandExtension` sequences | kept (terminal tag, not a hybridizing staple body) |

## Current state / what's left

Phase 0 (core) + Phase 1 (route + UI) shipped. **Deformations ARE copied** (cheap
filter + id remap; bp windows verbatim since Δbp=0).

**Still refused, not silently dropped** (`_refuse_unsupported`): a copied helix carrying
an **overhang**, or a copied strand carrying an **extension**, raises `ValueError` →
400 with a clear message. Dropping an `OverhangSpec` while keeping its backing `Domain`
would leave a dangling `Domain.overhang_id` and silently render an ssDNA overhang as
duplex. So `hingeV4` / `Hinge_scaff_test` (36/24 overhangs) are currently uncopyable —
pinned by `test_extract_refuses_overhangs_rather_than_dropping_them`.

**Phase 2 (unbuilt)** = lift that refusal: overhangs (regenerate the
`ovhg_{helix}_{bp}_{5p|3p}` id — it *encodes* the helix), sub-domains, extensions,
`overhang_connections` + `overhang_bindings`, `representation_overrides`,
`flexible_segment_marks` (its `domain_index` needs the same split-map remap as `DomainRef`).
The split map `(orig_strand_id, orig_domain_index) → (frag_strand_id, new_domain_index)`
already exists in `_truncate_strands` for exactly this.

**Phase 3 (unbuilt)** = surface `paste_report` in the UI; higher-fidelity ghost from
cloned rendered meshes.

## Silent-failure bug (found on first real use, 2026-07-09) — fixed

Symptom: "preview snaps to lattice positions, but clicking doesn't manifest real helices."

Root cause: **`client.js` `_request` records failures in `store.lastError` but never
toasts.** `onCommit` did `if (!res) return`, so a 400 (overhangs on a copied helix, a
collision) was indistinguishable from "the click did nothing". Most real designs 400 here:
`2x2_OH_test`, `1hb_efield_test`, `2x6_triple_strut` all carry overhangs on their clusters.

Three fixes:
1. `onCommit` now reads `store.lastError` and toasts it; the ghost stays **armed** on
   failure so the user can retry at another cell.
2. **`unsupportedCopyReason()`** (`cluster_copy_logic.js`) mirrors the backend's
   `_refuse_unsupported` so Ctrl+C refuses *immediately* with the reason, instead of
   letting the user aim a ghost at a doomed cell. Backend stays authoritative.
3. `slice_plane._cellOccupied` now reads **`getDesign().helices` `grid_pos`**, not
   `_circleMeshes[].state`. A circle's state is computed at the current slice offset, so a
   helix spanning z=2.3–14 nm read 'free' at offset 0 → the ghost stayed blue over occupied
   cells and the click sailed into a backend collision 400. Now it matches the backend's
   collision guard exactly (offset-independent, whole-helix).

The ghost group carries `name = 'clusterPasteGhost'` (exported `GHOST_NAME`) — several
modules use `renderOrder = 999`, so that is NOT a usable handle.

**Conflict geometry insight:** occupied cells are excluded from the slice-plane raycast, so
the ghost's ANCHOR can never land on existing DNA. For a solid convex bundle every
overlapping hover is therefore unreachable, and the red tint never fires. It only fires when
the anchor sits on a free cell while a distant footprint cell hits DNA — i.e. multi-cluster
or non-convex designs. Verified on `workspace/2x4_Hinge_autoscaff_test1.nadoc` (2 clusters).

## Validation debt

`MV-CLIPBOARD` in `manual_validation_debt.md`. Driven in a real browser via synthetic
`PointerEvent`s on the slice-plane discs (they ARE raycastable, unlike beads — but at
pixel precision, so **spiral-retry until the ray confirms the cell**, per LESSONS §H):
Ctrl+C refusal, hover, blue-over-free, red-over-conflict + blocked click + zero backend
calls, click-to-place commit, Escape, design-change disposal — all pass, 0 console errors.
Still human-eye only: the posed-ghost appearance and the cadnano 2D layout of the copy.

See also [[project_cluster_reconcile]], [[project_primitive_library]], [[project_feature_log_overhaul]].

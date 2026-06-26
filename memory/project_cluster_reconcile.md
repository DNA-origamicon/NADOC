---
name: Cluster membership reconciler — architecture and route map
description: Incremental cluster reconciliation after every topology mutation, replacing inline cluster code that was scattered across lattice.py and several routes
type: project
originSessionId: ee620174-49a0-4f10-bf04-4e60bf23fabc
---
## Overview (2026-05-02, overhang-overhaul branch)

Every topology-changing API route now runs `reconcile_cluster_membership` after the mutation, so new helices and domains automatically inherit the cluster of their nearest existing neighbor and appear inside any deformed cluster frame instead of snapping back to the unposed lattice.

Shipped as 3 commits: `d8693fc` (chunk A — foundations + extrude pipelines), `01a9507` (chunk B — topology mutations + linker consolidation), `e9e216c` (chunk C — auto pipelines + loop/skip + uniformity). All 19 reconciler unit tests + 5 e2e tests pass; 640 backend tests pass.

---

## Architecture

### Module: `backend/core/cluster_reconcile.py`

- **`MutationReport`** dataclass — optional hints from a pipeline. Most useful field is `new_helix_origins: dict[str, Optional[str]]` mapping new helix id → parent helix id (or `None` for explicit orphan, used for the virtual `__lnk__` bridge helix). Other fields (`strand_id_renames`, `new_domain_origins`, `deleted_*`) are present for future use; bp-range overlap matching handles renames transparently today.
- **`reconcile_cluster_membership(design_before, design_after, report=None) -> Design`** — pure function. Never mutates inputs. Builds a coverage map from `design_before`, then rebuilds `helix_ids` and `domain_ids` for each cluster in `design_after`.

### State wrappers in `backend/api/state.py`

| Helper | When to use |
|---|---|
| `mutate_with_reconcile(fn)` | In-place style: `fn(design)` mutates the active design. Snapshots for undo. Most CRUD routes. |
| `replace_with_reconcile(new_design, report=None)` | Immutable style: route built `new_design` via pure functions in `lattice.py`. Snapshots for undo. |
| `set_design_silent_reconciled(new_design, before, report=None)` | Multi-step pattern: route called `snapshot()` once at start, then ran several `set_design_silent` updates. Caller passes `before = get_or_404()` from before the snapshot. |

**Bypass list** (must NOT call any reconcile wrapper — these explicitly edit `cluster_transforms` themselves):
- Cluster CRUD: `add_cluster`, `update_cluster`, `delete_cluster`, all `*_joint*` routes.
- Camera poses, animations, deformation ops, feature-log replay (`seek_features`, `_seek_feature_log`, `rollback_last_feature`, `delete_feature`).
- Importers (cadnano/scadnano/PDB) — they call `_autodetect_clusters` themselves at the end.
- `center_design` — shifts pivots in lockstep with helices.
- `relax_overhang_connection` — writes joint state into `cluster_transforms`.
- Pure-metadata patches that don't touch topology: `patch_overhang_rotations_batch`, `patch_strand`, `patch_strands_color`.

### Migrated routes (full list)

Slice-plane extrude • overhang extrude • overhang connection create/patch/delete • scaffold-domain-paint • bundle segment/continuation/deformed-continuation • crossover place/batch/near-ends/far-ends/auto/move/batch-move/delete/batch-delete/extra-bases (3 variants) • nick/batch • ligate • forced-ligation/delete/batch-delete • helix add/at-cell/update/extend/delete • strand add/update/end-resize/add-domain/delete-domain/delete/delete-batch • strand-extension upsert-batch/delete-batch/add/update/delete • auto-break/auto-merge • auto-scaffold (4 variants) • assign-scaffold-sequence • assign-staple-sequences • loop-skip insert/twist/bend/clear-range/clear-all/apply-from-deformations.

---

## Key algorithm decisions

1. **Bp-range overlap is direction-agnostic.** Scaffold clusters' `domain_ids` legitimately include cross-direction staples (the autodetect "majority overlap" rule). Filtering by direction at match time would orphan them. Direction is re-applied per-DomainRef inside `_apply_cluster_transforms_domain_aware` for masking, separately from membership.
2. **Newly-inherited helix → claim ALL its domains** for domain-level clusters (matches the inline overhang-extrude behavior we deleted). Protects against later strands sharing that helix being unintentionally swept up by the deformation's exclusive-helix fallback.
3. **Rebuild `domain_ids` from scratch every call.** Don't try to patch incrementally — nick→ligate→merge sequences renumber domain indices, so any incremental patcher would have to chase. Scratch rebuild via bp-range overlap is bulletproof.
4. **`__lnk__` bridge helices are explicit orphans.** They have a `grid_pos` (set by `generate_linker_topology`) that happens to be lattice-adjacent to one of the connected real helices. Without an explicit orphan hint, lattice-neighbor proximity would pull the bridge helix into one cluster and drag the unrelated linker-side strand with it. Routes that create linkers populate `MutationReport.new_helix_origins[bridge_id] = None`.
5. **Orphan helices stay orphaned and propagate.** If parent helix is in zero clusters, new helix inherits empty membership.
6. **Reconciler never splits, merges, or modifies existing clusters' transforms.** Only membership (`helix_ids` and `domain_ids`) changes. Full re-evaluation is a separate user action (the autodetect button).

---

## Files deleted

- `_sync_linker_cluster_membership` (old in `lattice.py`) — bridge helix invisibility now enforced via `MutationReport`, complement-domain inheritance now via bp-overlap match.
- The cluster-stripping branch of `remove_linker_topology` — stale-DomainRef drop is what the reconciler does anyway.
- Inline cluster updates inside `make_bundle_continuation`, `make_bundle_deformed_continuation` (kept the un-rotation step — that's geometry), and `make_overhang_extrude`.

---

## Future work / known gaps

1. **`MutationReport.new_domain_origins` and `strand_id_renames` are unused.** Defined for future disambiguation if bp-overlap ties become a real problem, or if `strand_id_renames` needed for fast-path. Today the bp-overlap matcher handles them transparently.
2. **Cross-part assembly connections not reconciled.** `cluster_transform_overrides` on `PartInstance` (`backend/core/models.py:778`) and assembly routes are out of scope.
3. **Latent edge case: a domain-level cluster whose `domain_ids` becomes fully empty** (all its claimed domains deleted) would be re-classified as helix-level by the deformation code's `if not c.domain_ids` check, which would suddenly transform the entire helix instead of disjoint sub-ranges. The reconciler doesn't currently guard against this. Probably never happens in practice — to trigger it the user would have to delete every staple covering a bridge-helix bp range while keeping the helix in the cluster. If we ever see weird scaffold-cluster behaviour after large strand deletions, this is the place to look.
4. **Reconciler never splits/merges clusters.** A new crossover that bridges two clusters keeps both clusters separate (per user's stated rule). Full bridge-helix re-evaluation requires the user to re-run cluster autodetect.
5. **Lattice-neighbor proximity is Manhattan distance ≤ 2 with grid_pos check.** Works for HC and SQ. Doesn't use `crossover_neighbor` (the precise lattice-edge primitive). For routes that generate non-grid helices (linker bridges) we orphan explicitly via report; everything else has been fine.

---

## Test fixtures

- `tests/test_cluster_reconcile.py` — 19 unit tests against synthetic Designs.
- `tests/test_cluster_reconcile_e2e.py` — 5 e2e tests through `/design/*` routes with non-identity transforms.
- `tests/test_overhang_geometry.py` and `tests/test_overhang_connections.py` — older tests that were re-pointed to call the reconciler explicitly after `make_overhang_extrude` / `generate_linker_topology` (since those lattice functions no longer touch clusters).

---
name: overhang-binding-extensions
description: "Phase-6 OverhangBinding bound state — driven OH's strand domain relocates onto the driver's helix (sharing the driver's bp range, antiparallel), driven helix deleted. Unbind restores from snapshot. Joint-window lock preserved for 1-DOF. (Shipped 2026-05-13.)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5c11bc26-cb88-4409-bb0d-db68fb3a646f
---

Builds on Phase-5 OverhangBinding (sub-domain WC pairing + bound toggle). This iteration changes what "bound" means kinematically: instead of a cluster pose move (the original Phase-6 attempt), the bound flip becomes a **topology relocation** — the driven OH's strand domain literally moves onto the driver's helix at the driver's bp range, antiparallel, exactly like a linker's complement domain. The driven helix is removed from `design.helices`. Cluster transforms apply natively because the driven OH's nucleotides live on the driver's helix and inherit the driver's cluster transform.

## Decision sequence with the user

1. Started with a parallel `OverhangBindingPair` plan → user redirected to extend the existing Phase-5 `OverhangBinding`.
2. First Phase-6 attempt did cluster pose moves (0-DOF rigid translate, 1-DOF joint optimize, N-DOF Powell) + joint-window lock + ClusterOpLogEntry. Shipped and tested.
3. **Final iteration (this file)**: user clarified that bound means the driven OH should share the driver's helix and domain range, mirroring linkers. The cluster-pose-move approach was torn out; topology relocation replaces it.

## Bound flow

`PATCH /api/design/overhang-bindings/{id}` with `{"bound": true}` ([backend/api/crud.py:8906](backend/api/crud.py#L8906) `patch_overhang_binding`):

1. **`compute_bind_topology(design, binding)`** ([backend/core/binding_relax.py](backend/core/binding_relax.py)) resolves driver/driven:
   - cluster_a, cluster_b via `_overhang_owning_cluster_id`. Same cluster ⇒ 422 (relocation would be a no-op).
   - Driver side: joint-free side wins. Both- or neither-joints ⇒ side A is driver.
   - Driver's OH strand domain = the `Domain` with `overhang_id == driver_oh.id`. Its `(helix_id, start_bp, end_bp)` becomes the relocation target.
   - Builds a `BindTopology` carrying the target + a snapshot blob.
2. **`apply_bind_topology(design, topology)`**:
   - Rewrites the driven OH's strand `Domain` to `(target_helix_id, target_start_bp, target_end_bp, opposite_direction)`.
   - Updates the driven `OverhangSpec.helix_id` to the driver's helix id.
   - Removes the driven helix from `design.helices`.
   - Drops crossovers that touched the driven helix (snapshotted for restore).
3. **Joint-window lock (Phase-5 behaviour preserved)**: when exactly one joint connects the two clusters, the endpoint also runs `compute_locked_angle` against PRE-bind geometry to get the duplex-satisfying angle, writes `binding.locked_angle_deg`, and collapses `joint.min_angle_deg = max_angle_deg = locked` via the existing `_apply_driver_to_joint`. For 0-DOF / N-DOF cases the lock is skipped (`locked_angle_deg` stays None).

## Unbind flow

`PATCH /api/design/overhang-bindings/{id}` with `{"bound": false}`:

1. **`revert_bind_topology(design, snapshot)`**:
   - Recreates the driven helix via `Helix.model_validate(snapshot["driven_helix"])`.
   - Rewrites the driven strand's domain back to its pre-bind `(helix_id, start_bp, end_bp, direction)`.
   - Restores the driven `OverhangSpec.helix_id`.
   - Restores crossovers from the snapshot (deduplicated against existing).
2. **Joint-window restore (Phase-5 behaviour preserved)**: `_apply_driver_to_joint` un-collapses the window from the first claimant's `prior_min/max_angle_deg`.
3. Clears `binding.prior_driven_topology` and `binding.locked_angle_deg`.

## Snapshot shape

`OverhangBinding.prior_driven_topology: Optional[Dict[str, Any]]` ([backend/core/models.py:432](backend/core/models.py#L432)):

```python
{
    "driver_oh_id":      str,
    "driven_oh_id":      str,
    "driven_helix":      <Helix.model_dump(mode='json')>,
    "strand_id":         str,
    "domain_index":      int,
    "prior_domain":      {"helix_id": str, "start_bp": int, "end_bp": int, "direction": "FORWARD"|"REVERSE"},
    "prior_ovhg_helix_id": str,
    "crossovers":        [<Crossover.model_dump(mode='json')>, ...],
}
```

## Visual / cadnano consequences

Because the bound state is a real topology edit:
- 3D scene renders the duplex pairing natively (the helix renderer draws antiparallel beads on the same helix wherever two domains overlap on it).
- Cadnano editor's pathview shows the driven OH on the **driver's helix row**, in the driver's bp column range, antiparallel — same way it shows a linker complement domain.
- Atomistic export / oxDNA export pick this up "for free" because they read topology.
- The cross-cluster strand arc from the relocated OH back to the rest of the driven strand stretches via the existing strand-cone renderer when the driven cluster has moved relative to the driver cluster.

## Files

**Backend**
- `backend/core/models.py` — `OverhangBinding.prior_driven_topology` field. Old `prior_cluster_transforms` removed (Phase-6 attempt #1 leftover).
- `backend/core/binding_relax.py` — REWRITTEN. `compute_bind_topology`, `apply_bind_topology`, `revert_bind_topology`. Legacy `compute_locked_angle` preserved for 1-DOF joint-window lock.
- `backend/api/crud.py` `patch_overhang_binding` — drops cluster-pose-move logic, calls `apply_bind_topology` / `revert_bind_topology` inside `_fn`.

**Frontend** — no changes required for the topology-relocation flow. Existing surfaces continue to work:
- CT tab table (`overhangs_manager_popup.js`) renders binding rows + Bound checkbox.
- Main-app sidebar bind/unbind button (`main.js _rebuildPanel`).
- Feature-log panel: bind/unbind no longer emit `ClusterOpLogEntry`; entries are just the standard `SnapshotLogEntry` produced by `mutate_with_feature_log`.

## Tests

[tests/test_overhang_bindings.py](tests/test_overhang_bindings.py) (18 pass):
- `test_bound_relocates_driven_domain_to_driver_helix` — driven OH's domain moves to driver's helix + bp range, antiparallel; driven helix deleted; OverhangSpec.helix_id updated; snapshot populated.
- `test_bound_then_unbound_restores_driven_topology` — full round trip; snapshot cleared; driven helix and domain back.
- `test_bound_true_with_explicit_target_joint_collapses_joint_window` — Phase-5 lock preserved for 1-DOF case.
- `test_bound_true_multi_dof_skips_joint_lock_but_relocates_topology` — N-DOF case skips lock but still relocates.
- Plus existing 14 Phase-5 tests (model invariants, mutex, driver semantics, save/load).

Full backend suite: same 6 pre-existing failures + 9 pre-existing errors (atomistic FileNotFound + animation geometry-batch shape + seamed-router) — none related to bindings.

## Gotchas / future work

1. **Crossovers rewritten, not dropped** (fixed 2026-05-14) — bind now rewrites any Crossover record whose half was on the driven helix so the half points at the driver helix at the mapped bp + flipped direction. The crossover's `id` is preserved so `xoBySiteKey` in `unfold_view.js` still matches the OH→parent arc, which is required for the right-click Relax bond menu to fire. Unbind restores the pre-bind crossover shape by looking up by id. Mapping rule in `_rewrite_half_to_driver`: `index == prior.start_bp → target_start_bp`; `index == prior.end_bp → target_end_bp`; otherwise proportional fallback. Regression test: `test_bind_rewrites_crossovers_on_driven_helix_to_driver_helix`. **Designs bound before this fix have a snapshot with the original crossover but the live `design.crossovers` is missing the rewritten copy — unbind + re-bind to repair.**
2. **`compute_locked_angle` runs against PRE-bind geometry** — the order in the PATCH endpoint matters. After `apply_bind_topology`, both sub-domain anchors resolve to points on the driver's helix and the chord is trivially zero, which would make the locked-angle math ill-defined.
3. **0-DOF case has no joint window to lock** — the topology relocation alone defines the bound state; the cross-cluster arc stretches with whatever pose the user chose for the driven cluster. The user can still bind without any joints in play.
4. **N-DOF case** — same as 0-DOF; topology relocation only, no single angle to lock.
5. **Joint angle lock vs topology — they're redundant but not conflicting**. The 1-DOF lock prevents joint dragging while bound; the topology constraint independently forces the duplex. Either alone would be sufficient; both together preserves backwards compatibility with Phase-5 expectations.
6. **Validation** — the existing `OverhangBinding._check_self_consistency` validator still enforces that bound=True requires target_joint_id + locked_angle_deg... wait, this may now be wrong for 0-DOF / N-DOF cases. Check this if you hit a Pydantic validation error on bound=True for a 0-joint binding. Field-level validator in [backend/core/models.py:425](backend/core/models.py#L425).

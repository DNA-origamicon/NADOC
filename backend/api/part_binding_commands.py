"""Native part binding lifecycle shared by routes and recipe execution."""

from typing import Optional, Dict, Any
from fastapi import HTTPException
from backend.core.models import Design, OverhangBinding
from backend.core.binding_drivers import (
    apply_driver_to_joint as _apply_driver_to_joint,
    first_claimant_for_joint as _first_claimant_for_joint,
    select_driver_for_joint as _select_driver_for_joint,
)
from backend.core.overhang_ops import _resolve_sub_domain_sequence

ACTIONS = frozenset(
    {"overhang-binding-create", "overhang-binding-patch", "overhang-binding-delete"}
)


def create(design, body, identity, created_at):
    from backend.api.routes_overhang_bindings import (
        _resolve_sd_for_binding,
        _binding_pair_keys,
        _smallest_unused_binding_name,
    )
    from backend.core.models import OverhangBinding as _OB
    from backend.core.sequences import is_watson_crick_complement as _is_wc

    if body.sub_domain_a_id == body.sub_domain_b_id:
        raise HTTPException(
            422, detail="sub_domain_a_id and sub_domain_b_id must differ."
        )

    ovhg_a, sd_a = _resolve_sd_for_binding(design, body.sub_domain_a_id)
    ovhg_b, sd_b = _resolve_sd_for_binding(design, body.sub_domain_b_id)
    if ovhg_a is None or sd_a is None:
        raise HTTPException(
            404, detail=f"sub_domain_a_id {body.sub_domain_a_id!r} not found."
        )
    if ovhg_b is None or sd_b is None:
        raise HTTPException(
            404, detail=f"sub_domain_b_id {body.sub_domain_b_id!r} not found."
        )

    if sd_a.length_bp != sd_b.length_bp:
        raise HTTPException(
            422,
            detail=(
                f"sub-domain lengths must match ({sd_a.length_bp} vs {sd_b.length_bp})."
            ),
        )

    seq_a = _resolve_sub_domain_sequence(ovhg_a, sd_a)
    seq_b = _resolve_sub_domain_sequence(ovhg_b, sd_b)
    if seq_a is None or seq_b is None:
        raise HTTPException(
            422,
            detail=(
                "Both sub-domain sequences must be resolvable (override or parent slice) "
                "before a binding can be created."
            ),
        )
    if not _is_wc(seq_a, seq_b, allow_n=body.allow_n_wildcard):
        raise HTTPException(
            422,
            detail=(
                f"sequences are not Watson-Crick complementary "
                f"(allow_n_wildcard={body.allow_n_wildcard})."
            ),
        )

    pair_key = frozenset({body.sub_domain_a_id, body.sub_domain_b_id})
    if pair_key in _binding_pair_keys(design):
        raise HTTPException(
            409,
            detail=("sub-domain pair is already claimed by another linker or binding."),
        )

    if body.target_joint_id is not None:
        joint_ids = {j.id for j in design.cluster_joints}
        if body.target_joint_id not in joint_ids:
            raise HTTPException(
                404, detail=(f"target_joint_id {body.target_joint_id!r} not found.")
            )

    binding = _OB(
        id=identity,
        name=_smallest_unused_binding_name(design),
        created_at=created_at,
        sub_domain_a_id=body.sub_domain_a_id,
        sub_domain_b_id=body.sub_domain_b_id,
        overhang_a_id=ovhg_a.id,
        overhang_b_id=ovhg_b.id,
        binding_mode=body.binding_mode,
        target_joint_id=body.target_joint_id,
        allow_n_wildcard=body.allow_n_wildcard,
        bound=False,
    )

    def _fn(d: Design) -> Design:
        return d.model_copy(
            update={
                "overhang_bindings": [*d.overhang_bindings, binding],
            }
        )

    return _fn(design)


def patch(design, binding_id, body):
    from backend.core.binding_relax import (
        BindTopology,
        apply_bind_topology,
        compute_bind_topology,
        revert_bind_topology,
    )

    target = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)

    if "name" in patch:
        new_name = (patch["name"] or "").strip()
        if not new_name:
            raise HTTPException(422, detail="name must be non-empty.")
        clash = next(
            (
                b
                for b in design.overhang_bindings
                if b.id != binding_id and b.name == new_name
            ),
            None,
        )
        if clash is not None:
            raise HTTPException(
                422, detail=f"binding name {new_name!r} is already in use."
            )
        patch["name"] = new_name

    if "target_joint_id" in patch and patch["target_joint_id"] is not None:
        joint_ids = {j.id for j in design.cluster_joints}
        if patch["target_joint_id"] not in joint_ids:
            raise HTTPException(
                404, detail=(f"target_joint_id {patch['target_joint_id']!r} not found.")
            )

    # Compute next binding state pieces. We resolve transitions explicitly
    # so all topology + joint mutations sit inside one mutate_with_feature_log atomic.
    prev_bound = target.bound
    prev_joint = target.target_joint_id
    next_joint = (
        patch.get("target_joint_id", prev_joint)
        if "target_joint_id" in patch
        else prev_joint
    )
    next_bound = patch.get("bound", prev_bound) if "bound" in patch else prev_bound

    # Topology change on bind / restore on unbind.
    #   topology: BindTopology | None — computed when we're entering bound state.
    #   restore_snapshot: dict | None — pre-bind topology snapshot to revert on unbind.
    topology: Optional[BindTopology] = None
    restore_snapshot: Optional[Dict[str, Any]] = None

    if next_bound and not prev_bound:
        # Going UNBOUND -> BOUND. compute_bind_topology snapshots the pre-bind
        # state; apply_bind_topology in _fn does the relocation. After the
        # relocation, the OH→parent crossover spans clusters and is what
        # visually matters — we run a bond-relax inside _fn (post-apply) to
        # rotate the joint's cluster so that crossover chord ≈ 0.67 nm, then
        # lock the joint at the resulting angle.
        # For a UNIFIED direct binding (created via apply_connection_version /
        # _cv_create_bound_binding) the driver/driven sides are already pinned on
        # the record. Pass driver_side so re-bind is a pure topology relocation —
        # this bypasses the same-cluster / cluster-None guards, which a root-to-root
        # binding on ONE rigid body would otherwise trip (422) on the second Bind.
        # Legacy pair bindings have driver_oh_id=None → driver_side stays None →
        # the guards still apply (unchanged behaviour).
        driver_side = None
        if target.driver_oh_id is not None:
            driver_side = "a" if target.driver_oh_id == target.overhang_a_id else "b"
        try:
            topology = compute_bind_topology(design, target, driver_side=driver_side)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, detail=f"compute_bind_topology failed: {exc!r}")
        # Snapshot for unbind restoration.
        patch["prior_driven_topology"] = topology.snapshot
        # Resolve the auto-pick joint id (when exactly one joint connects
        # the two clusters and the user didn't pin target_joint_id).
        if next_joint is None:
            from backend.core.linker_relax import _overhang_owning_cluster_id as _own

            cluster_a = _own(design, target.overhang_a_id)
            cluster_b = _own(design, target.overhang_b_id)
            cands = [
                j
                for j in design.cluster_joints
                if j.cluster_id == cluster_a or j.cluster_id == cluster_b
            ]
            if len(cands) == 1:
                next_joint = cands[0].id
                patch["target_joint_id"] = next_joint
        # locked_angle_deg is computed post-relocation inside _fn (see below).
        # Leave it None here; _fn writes the real value before _apply_driver_to_joint
        # reads it.
        patch["locked_angle_deg"] = None
        patch["bound"] = True
    elif prev_bound and not next_bound:
        # Going BOUND -> UNBOUND: clear locked_angle_deg + plan to restore
        # the topology snapshot taken at bind time (if any).
        patch["locked_angle_deg"] = None
        patch["bound"] = False
        restore_snapshot = target.prior_driven_topology
        patch["prior_driven_topology"] = None

    updated_target = target.model_copy(
        update={k: v for k, v in patch.items() if k in OverhangBinding.model_fields}
    )

    def _fn(d: Design) -> Design:
        # Replace the target binding in the list.
        new_bindings_list = []
        # Walk current bindings, swapping in updated_target.
        for b in d.overhang_bindings:
            if b.id == binding_id:
                new_bindings_list.append(updated_target)
            else:
                new_bindings_list.append(b)
        nxt = d.model_copy(update={"overhang_bindings": new_bindings_list})

        # ── Topology relocation (UNBOUND -> BOUND) or revert (BOUND -> UNBOUND).
        # The driven OH's strand domain moves onto the driver's helix at the
        # driver's bp range, antiparallel; driven helix is deleted. Unbind
        # restores the driven helix + the OH's domain from the snapshot.
        if topology is not None:
            nxt = apply_bind_topology(nxt, topology)
        elif restore_snapshot:
            nxt = revert_bind_topology(nxt, restore_snapshot)

        # NB: no automatic post-bind cluster relax. Binding does topology
        # relocation ONLY; the cross-cluster OH→parent crossover may end
        # up visibly stretched and the user closes it themselves via the
        # right-click "Relax bond" menu. (Earlier iterations auto-rotated
        # the joint on bind; reverted at user request 2026-05-14 so the
        # visual stretch is preserved as a kinematic-intent marker.)
        #
        # locked_angle_deg is therefore left None for Phase-6 bindings
        # unless an external caller provides it. _apply_driver_to_joint
        # below will not collapse the joint window when locked_angle_deg
        # is None (it only acts on the binding designated as joint
        # driver via locked_angle_deg).

        # ── Snapshot prior_min/max on first claimant if this is the first
        #    bound binding for next_joint and the snapshot hasn't been taken.
        if next_bound and next_joint is not None and not prev_bound:
            first = _first_claimant_for_joint(nxt, next_joint)
            # The first claimant might be this binding (often is). Snapshot
            # the joint's current min/max ONLY IF the first claimant has
            # no snapshot yet (idempotent re-toggle safe).
            if first is not None and first.prior_min_angle_deg is None:
                joint = next(
                    (j for j in nxt.cluster_joints if j.id == next_joint), None
                )
                if joint is not None:
                    new_first = first.model_copy(
                        update={
                            "prior_min_angle_deg": joint.min_angle_deg,
                            "prior_max_angle_deg": joint.max_angle_deg,
                        }
                    )
                    nxt = nxt.model_copy(
                        update={
                            "overhang_bindings": [
                                new_first if bb.id == first.id else bb
                                for bb in nxt.overhang_bindings
                            ],
                        }
                    )

        # ── Apply driver to affected joint(s). For 1-DOF bindings, this
        # collapses the joint window to [locked_angle, locked_angle].
        joints_to_recompute: set[str] = set()
        if prev_joint is not None:
            joints_to_recompute.add(prev_joint)
        if next_joint is not None:
            joints_to_recompute.add(next_joint)
        for jid in joints_to_recompute:
            nxt = _apply_driver_to_joint(nxt, jid)
            # If no driver left after release, clear the snapshot on the
            # first claimant (so a future re-binding picks up a fresh
            # snapshot from the restored window).
            if _select_driver_for_joint(nxt, jid) is None:
                first = _first_claimant_for_joint(nxt, jid)
                if first is not None and first.prior_min_angle_deg is not None:
                    new_first = first.model_copy(
                        update={
                            "prior_min_angle_deg": None,
                            "prior_max_angle_deg": None,
                        }
                    )
                    nxt = nxt.model_copy(
                        update={
                            "overhang_bindings": [
                                new_first if bb.id == first.id else bb
                                for bb in nxt.overhang_bindings
                            ],
                        }
                    )
        return nxt

    return _fn(design)


def delete(design, binding_id):
    target = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    joint_id = target.target_joint_id
    must_migrate_snapshot = (
        joint_id is not None
        and target.prior_min_angle_deg is not None
        and target.prior_max_angle_deg is not None
    )

    # Snapshot the joint window to restore when no heir exists.
    fallback_min = target.prior_min_angle_deg
    fallback_max = target.prior_max_angle_deg

    def _fn(d: Design) -> Design:
        bindings = list(d.overhang_bindings)
        # Identify next claimant BEFORE removing target.
        heir_migrated = False
        if must_migrate_snapshot:
            others = [
                b
                for b in bindings
                if b.target_joint_id == joint_id and b.id != binding_id
            ]
            others.sort(key=lambda b: (b.created_at, b.id))
            if others:
                heir = others[0]
                # Migrate snapshot onto heir (only if heir has no snapshot yet).
                if (
                    heir.prior_min_angle_deg is None
                    and heir.prior_max_angle_deg is None
                ):
                    new_heir = heir.model_copy(
                        update={
                            "prior_min_angle_deg": target.prior_min_angle_deg,
                            "prior_max_angle_deg": target.prior_max_angle_deg,
                        }
                    )
                    bindings = [new_heir if b.id == heir.id else b for b in bindings]
                    heir_migrated = True
        # Remove target.
        bindings = [b for b in bindings if b.id != binding_id]
        nxt = d.model_copy(update={"overhang_bindings": bindings})
        # Re-apply driver to joint (may restore from heir's migrated snapshot).
        if joint_id is not None:
            nxt = _apply_driver_to_joint(nxt, joint_id)
            # Final fallback: no heir AND target carried a snapshot ⇒ the
            # joint was bound until just now and has no surviving claimant
            # to restore from. Apply the stored fallback window directly so
            # the joint un-locks.
            if (
                not heir_migrated
                and fallback_min is not None
                and fallback_max is not None
            ):
                # Check whether driver-apply already restored (it would only
                # do so if a remaining claimant carried a snapshot — i.e.,
                # heir_migrated case).
                driver_after = _select_driver_for_joint(nxt, joint_id)
                if driver_after is None:
                    new_joints = []
                    for j in nxt.cluster_joints:
                        if j.id == joint_id:
                            new_joints.append(
                                j.model_copy(
                                    update={
                                        "min_angle_deg": fallback_min,
                                        "max_angle_deg": fallback_max,
                                    }
                                )
                            )
                        else:
                            new_joints.append(j)
                    nxt = nxt.model_copy(update={"cluster_joints": new_joints})
        return nxt

    return _fn(design)


def build(design, params):
    from backend.api.routes_overhang_bindings import (
        OverhangBindingCreateRequest,
        OverhangBindingPatchRequest,
    )

    action = params["action"]
    if action == "overhang-binding-create":
        return create(
            design,
            OverhangBindingCreateRequest.model_validate(params),
            params["binding_id"],
            params["created_at"],
        )
    if action == "overhang-binding-patch":
        return patch(
            design,
            params["binding_id"],
            OverhangBindingPatchRequest.model_validate(params),
        )
    return delete(design, params["binding_id"])

"""HTTP ownership for overhang-binding lifecycle and authored poses."""

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.crud import (
    BindingDisplayPoseBody,
    _design_response,
    _design_response_with_geometry,
)
from backend.core.binding_drivers import (
    apply_driver_to_joint as _apply_driver_to_joint,
    first_claimant_for_joint as _first_claimant_for_joint,
    select_driver_for_joint as _select_driver_for_joint,
)
from backend.core.models import Design, OverhangBinding, OverhangSpec, SubDomain
from backend.core.overhang_ops import _resolve_sub_domain_sequence
from backend.core.validator import ValidationReport

router = APIRouter()


def _binding_response(
    design: Design,
    report: ValidationReport,
    binding_id: Optional[str] = None,
    *,
    geometry_unchanged: bool = False,
) -> dict:
    """Standard envelope: full design response, optionally including the
    affected binding by id for client convenience.

    *geometry_unchanged* — set by callers whose mutation is metadata-only
    (create an UNBOUND binding, or an annotation-only display-pose patch):
    no strand relocates and no nucleotide moves, so shipping geometry at all
    is wasted bytes. NOT set for the general PATCH route, which can drive
    joint/cluster kinematics via _apply_driver_to_joint — an unbounded set of
    helices outside the one binding, same family as the relax_direct_binding
    routes (GEO-14/21) and not safely reducible to changed_helix_ids here.
    """
    if geometry_unchanged:
        base = _design_response(design, report)
        base["geometry_unchanged"] = True
    else:
        base = _design_response_with_geometry(design, report)
    if binding_id is not None:
        b = next((bb for bb in design.overhang_bindings if bb.id == binding_id), None)
        if b is not None:
            base["overhang_binding"] = b.model_dump()
    return base


@router.get("/design/overhang-bindings", status_code=200)
def list_overhang_bindings() -> dict:
    """List all OverhangBinding records on the active design."""
    design = design_state.get_or_404()
    return {"overhang_bindings": [b.model_dump() for b in design.overhang_bindings]}


class OverhangBindingCreateRequest(BaseModel):
    sub_domain_a_id: str
    sub_domain_b_id: str
    binding_mode: Literal["duplex", "toehold"] = "duplex"
    target_joint_id: Optional[str] = None
    allow_n_wildcard: bool = True


def _resolve_sd_for_binding(
    design: Design,
    sub_domain_id: str,
) -> tuple[Optional["OverhangSpec"], Optional["SubDomain"]]:
    for ovhg in design.overhangs:
        for sd in ovhg.sub_domains:
            if sd.id == sub_domain_id:
                return ovhg, sd
    return None, None


def _binding_pair_keys(design: Design) -> set[frozenset]:
    """Build the mutex pair-set for linkers + existing bindings."""
    from backend.core.models import _sub_domain_at_attach

    keys: set[frozenset] = set()
    for conn in design.overhang_connections:
        a = _sub_domain_at_attach(design, conn.overhang_a_id, conn.overhang_a_attach)
        b = _sub_domain_at_attach(design, conn.overhang_b_id, conn.overhang_b_attach)
        if a and b and a != b:
            keys.add(frozenset({a, b}))
    for binding in design.overhang_bindings:
        keys.add(frozenset({binding.sub_domain_a_id, binding.sub_domain_b_id}))
    return keys


def _smallest_unused_binding_name(design: Design) -> str:
    used = {b.name for b in design.overhang_bindings if b.name}
    n = 1
    while f"B{n}" in used:
        n += 1
    return f"B{n}"


@router.post("/design/overhang-bindings", status_code=201)
def create_overhang_binding(body: OverhangBindingCreateRequest) -> dict:
    """Create a new OverhangBinding. Starts unbound."""
    import time as _time
    from backend.core.models import OverhangBinding as _OB
    from backend.core.sequences import is_watson_crick_complement as _is_wc

    design = design_state.get_or_404()

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
        name=_smallest_unused_binding_name(design),
        created_at=_time.time(),
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

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Create binding {binding.name}",
        params={
            "binding_id": binding.id,
            "name": binding.name,
            "sub_domain_a_id": binding.sub_domain_a_id,
            "sub_domain_b_id": binding.sub_domain_b_id,
            "binding_mode": binding.binding_mode,
            "action": "overhang-binding-create",
        },
        fn=_fn,
    )
    # A freshly created binding always starts bound=False — pure metadata,
    # no strand/geometry change (binding it later is a separate PATCH).
    response = _binding_response(
        updated, report, binding_id=binding.id, geometry_unchanged=True,
    )
    # 201 Created — return the response payload with the new binding embedded.
    return response


class OverhangBindingPatchRequest(BaseModel):
    name: Optional[str] = None
    bound: Optional[bool] = None
    binding_mode: Optional[Literal["duplex", "toehold"]] = None
    target_joint_id: Optional[str] = None
    allow_n_wildcard: Optional[bool] = None


@router.patch("/design/overhang-bindings/{binding_id}", status_code=200)
def patch_overhang_binding(binding_id: str, body: OverhangBindingPatchRequest) -> dict:
    """Update fields on an OverhangBinding.

    `bound` transitions trigger driver-selection / joint-window updates:

      • False → True: resolve target_joint_id (explicit or auto-detect via
        relax solver), compute locked_angle_deg, snapshot prior_min/max on
        the first claimant (if not already), apply driver to joint.
      • True → False: clear bound; re-select driver; if no driver remains,
        restore prior window from the first claimant snapshot AND clear it.
      • bound=True idempotent re-toggle: no double-snapshot, no
        double-apply.

    A target_joint_id change while bound = release old joint, claim new.
    """
    from backend.core.binding_relax import (
        BindTopology,
        apply_bind_topology,
        compute_bind_topology,
        revert_bind_topology,
    )

    design = design_state.get_or_404()
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

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Patch binding {target.name}",
        params={
            "binding_id": binding_id,
            "fields": sorted(patch.keys()),
            "action": "overhang-binding-patch",
        },
        fn=_fn,
    )
    return _binding_response(updated, report, binding_id=binding_id)


def reapply_binding_driver(design: Design, binding_id: str) -> Design:
    """Re-place a BOUND binding's relocation after its driver changed (the duplex
    driver toggle, Phase 4b #4/#1–#3). Mechanically = unbind then re-bind with the
    binding's CURRENT ``driver_oh_id``, reusing the PROVEN bind primitives
    (``revert_bind_topology`` → ``compute_bind_topology(driver_side=…)`` →
    ``apply_bind_topology``) so the ENTIRE driven domain relocates onto the new
    driver's helix (Q4 #1). No-op when the binding isn't bound or has no snapshot.
    Best-effort: on any failure the design is returned unchanged so the driver
    field edit still sticks (the user can Unbind→Bind manually)."""
    from backend.core.binding_relax import (
        apply_bind_topology,
        compute_bind_topology,
        revert_bind_topology,
    )

    b = next((x for x in design.overhang_bindings if x.id == binding_id), None)
    if b is None or not b.bound or not b.prior_driven_topology:
        return design
    driver_side = "a" if b.driver_oh_id == b.overhang_a_id else "b"
    try:
        reverted = revert_bind_topology(design, b.prior_driven_topology)
        b2 = next((x for x in reverted.overhang_bindings if x.id == binding_id), None)
        topo = compute_bind_topology(reverted, b2, driver_side=driver_side)
        applied = apply_bind_topology(reverted, topo)
        out = applied.model_copy(
            update={
                "overhang_bindings": [
                    x.model_copy(update={"prior_driven_topology": topo.snapshot})
                    if x.id == binding_id
                    else x
                    for x in applied.overhang_bindings
                ]
            }
        )
        if b.target_joint_id:
            out = _apply_driver_to_joint(out, b.target_joint_id)
        return out
    except Exception:
        return design


@router.patch("/design/overhang-bindings/{binding_id}/display-pose", status_code=200)
def patch_binding_display_pose(binding_id: str, body: BindingDisplayPoseBody) -> dict:
    """Set the authored display-only hinge angles used by the animation player.

    Annotation-only: writes ONLY `unbound_angle_deg` / `bound_angle_deg`. Never
    touches `bound`, `target_joint_id`, `locked_angle_deg`, the joint's angle
    window, or `prior_driven_topology`. Does not relocate topology. Three-layer
    safe — these fields are read solely by the display/animation layer.
    """
    design = design_state.get_or_404()
    target = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)

    def _fn(d: Design) -> None:
        b = next((bb for bb in d.overhang_bindings if bb.id == binding_id), None)
        if b is None:
            return
        if "unbound_angle_deg" in patch:
            b.unbound_angle_deg = patch["unbound_angle_deg"]
        if "bound_angle_deg" in patch:
            b.bound_angle_deg = patch["bound_angle_deg"]

    updated, report = design_state.mutate_and_validate(_fn)
    # Annotation-only per this route's own docstring: "Does not relocate
    # topology."
    return _binding_response(
        updated, report, binding_id=binding_id, geometry_unchanged=True,
    )



@router.delete("/design/overhang-bindings/{binding_id}", status_code=200)
def delete_overhang_binding(binding_id: str) -> dict:
    """Remove an OverhangBinding.

    If the binding being deleted is the first claimant for a joint AND other
    bindings still claim that joint, the prior_min/max snapshot is migrated
    onto the next-earliest claimant before deletion so the restore path
    keeps working when the last bound binding eventually releases.
    """
    design = design_state.get_or_404()
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

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Delete binding {target.name}",
        params={
            "binding_id": binding_id,
            "name": target.name,
            "action": "overhang-binding-delete",
        },
        fn=_fn,
    )
    return _design_response_with_geometry(updated, report)

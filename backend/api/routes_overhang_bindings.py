"""HTTP ownership for overhang-binding lifecycle and authored poses."""

from typing import Literal, Optional

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
)
from backend.core.models import Design, OverhangSpec, SubDomain
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
    from backend.api.part_binding_commands import build
    from uuid import uuid4
    from time import time
    binding_id = str(uuid4())
    params = {**body.model_dump(mode="json", exclude_unset=True), "binding_id": binding_id, "created_at": time(), "action": "overhang-binding-create"}
    updated, report, _entry = design_state.mutate_with_feature_log(
        "overhang-bulk", "Create binding", params, lambda d: build(d, params))
    return _binding_response(updated, report, binding_id=binding_id, geometry_unchanged=True)


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
    from backend.api.part_binding_commands import build
    params = {**body.model_dump(mode="json", exclude_unset=True), "binding_id": binding_id, "action": "overhang-binding-patch"}
    updated, report, _entry = design_state.mutate_with_feature_log(
        "overhang-bulk", "Patch binding", params, lambda d: build(d, params))
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
    from backend.api.part_binding_commands import build
    params = {**{}, "binding_id": binding_id, "action": "overhang-binding-delete"}
    updated, report, _entry = design_state.mutate_with_feature_log(
        "overhang-bulk", "Delete binding", params, lambda d: build(d, params))
    return _design_response_with_geometry(updated, report)

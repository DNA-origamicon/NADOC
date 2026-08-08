"""
API layer — assembly polymerization route handlers (extracted from assembly.py).

Two ways to grow a repeating chain of parts:

  * **Mate-seeded** (``/assembly/polymerize``) — replicate an existing mate
    (a joint between two identical PartInstances) to grow a linear chain.
  * **Periodic** (``/assembly/polymerize-periodic``) — grow from a SINGLE part
    whose repeat transform is derived from its ``is_periodic_seam`` forced
    ligations; no hand-defined mate required. A companion read-only route
    (``GET .../periodic-closure``) reports the ring-closure residual so the
    panel can warn before committing a chain that won't close.

All of the record-assembly *math* (chain transforms, connector-union, seam-joint
wiring) lives in ``backend/core`` (``assembly_polymer`` #21/#22, ``periodic_polymer``);
these handlers own only validation, lookups, the design load, and the feature-log
commit — i.e. parse → look up → delegate → commit → respond.

Routes
------
  POST  /assembly/polymerize                                — mate-seeded linear chain
  GET   /assembly/instances/{instance_id}/periodic-closure  — ring-closure residual
  POST  /assembly/polymerize-periodic                       — single-part periodic chain

Back-imports (B=6 — all shared kernel/infrastructure, zero bespoke): ``_assembly_response``
(shared kernel, the assembly-side twin of crud.py's ``_design_response``),
``_apply_assembly_mutation_with_feature_log`` (the assembly mutate + feature-log
wrapper), the file-IO design-load infra ``_assembly_source_path`` /
``_design_with_instance_overrides`` (L4-blocked from core), and the trivial shared
lookups ``_find_instance`` / ``_find_joint``. The chain math is imported from
``backend/core`` DIRECTLY (not back from the god-file). The two request models moved
IN with the router.

GOTCHA: ``_replay_assembly_op`` (stays in assembly.py) calls ``polymerize_assembly``
and ``polymerize_periodic_assembly`` as plain functions while re-applying a logged
op. It imports them back from this module via a function-local import (top-level
would be circular — this module imports the kernel helpers from assembly.py).

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import assembly_state
from backend.api.assembly import (
    _apply_assembly_mutation_with_feature_log,
    _assembly_response,
    _assembly_source_path,
    _design_with_instance_overrides,
    _find_instance,
    _find_joint,
)
from backend.core.models import PartInstance

router = APIRouter()


# ── Polymerize Origami ────────────────────────────────────────────────────────
#
# Replicate an existing mate (joint between two identical PartInstances) to
# grow a linear chain of identical parts.  Math lives in
# :mod:`backend.core.assembly_polymer`; this route applies the resulting
# transforms + spawns new PartInstance + AssemblyJoint records.


class PolymerizeAssemblyRequest(BaseModel):
    joint_id: str
    count: int  # total chain length, ≥ 2
    direction: Literal["forward", "backward", "both"] = "forward"
    # Additional instances (beyond the seed mate's two) that should be
    # carried along as part of the pattern. Each gets cloned at every chain
    # step at `delta^step @ T(original)`, and any mate inside the pattern
    # unit (seed_a, seed_b, and these additionals) is replicated between
    # the corresponding new clones at each step.
    additional_instance_ids: list[str] = Field(default_factory=list)


@router.post("/assembly/polymerize", status_code=200)
def polymerize_assembly(body: PolymerizeAssemblyRequest) -> dict:
    """Grow a linear polymer of identical parts from a seed mate.

    The seed mate's two instances are the chain anchor + first primary.
    Additional instances passed in ``additional_instance_ids`` are carried
    along as part of the pattern — at each new chain step they get cloned
    with transform ``delta^step @ T(original)`` so the spatial relationship
    inside the pattern unit is preserved. Mates whose both endpoints live
    in the pattern unit are replicated at every step between the matching
    cloned instances.
    """
    from backend.core.assembly_polymer import _sources_match, build_polymer_chain

    if body.count < 2:
        raise HTTPException(400, detail="count must be at least 2 (the existing pair).")

    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, body.joint_id)
    if not joint.instance_a_id or not joint.instance_b_id:
        raise HTTPException(
            422,
            detail="Polymerize requires a mate between two instances (joint has only one side).",
        )
    inst_a = _find_instance(assembly, joint.instance_a_id)
    inst_b = _find_instance(assembly, joint.instance_b_id)
    if not _sources_match(inst_a.source, inst_b.source):
        raise HTTPException(
            422,
            detail="Polymerize requires identical parts on both sides of the mate.",
        )

    # Resolve "to pattern" additional instances. Silently drop ids that
    # match the seed pair (UI may include them by mistake), but 404 on
    # truly missing ones so the user knows something is off.
    seed_pair_ids: set[str] = {joint.instance_a_id, joint.instance_b_id}
    additional_instances: list[PartInstance] = []
    seen: set[str] = set()
    for aid in body.additional_instance_ids or []:
        if aid in seed_pair_ids or aid in seen:
            continue
        seen.add(aid)
        additional_instances.append(_find_instance(assembly, aid))

    # count == 2 is a no-op — chain is already that length.
    if body.count == 2:
        return _assembly_response(assembly)

    # Pure record-assembly (geometry + connector-union + pattern-mate
    # replication) lives in backend.core.assembly_polymer; this handler owns
    # only validation, lookups, and the feature-log commit.
    existing_instances, new_instances, new_joints = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        additional_instances,
        body.count,
        body.direction,
        assembly.instances,
        assembly.joints,
    )

    mutated = assembly.model_copy(
        update={
            "instances": existing_instances + new_instances,
            "joints": list(assembly.joints) + new_joints,
        }
    )

    new_instance_ids = [i.id for i in new_instances]
    new_joint_ids = [j.id for j in new_joints]
    extra_suffix = (
        f", +{len(additional_instances)} pattern part(s)"
        if additional_instances
        else ""
    )
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-polymerize",
        label=f"Polymerize {joint.name}: chain length {body.count} ({body.direction}){extra_suffix}",
        params={
            "joint_id": body.joint_id,
            "count": body.count,
            "direction": body.direction,
            "additional_instance_ids": [a.id for a in additional_instances],
            "new_instance_ids": new_instance_ids,
            "new_joint_ids": new_joint_ids,
        },
    )
    return _assembly_response(updated)


class PolymerizePeriodicRequest(BaseModel):
    instance_id: str
    count: int  # total chain length, ≥ 2
    direction: Literal["forward", "backward", "both"] = "forward"


@router.get("/assembly/instances/{instance_id}/periodic-closure", status_code=200)
def get_instance_periodic_closure(instance_id: str, count: int = 4) -> dict:
    """Return the polymer's ring-closure residual after ``count`` copies.

    Used by the polymerize-periodic panel to warn the user before they
    commit a chain that won't close. ``angle_deg`` is the rotational drift
    of δ**count from identity; ``translation_nm`` is the positional drift.
    Both should be near zero for a closed ring.

    Also returns ``suggested_curvature_deg_per_bp`` — the κ that *would* close
    the chain — when the design has exactly one bend op. The frontend's
    "snap to closing κ" button writes this back to the bend op.
    """
    from backend.core.periodic_polymer import (
        PeriodicSeamError,
        closure_residual,
        solve_closing_curvature,
    )

    assembly = assembly_state.get_or_404()
    seed = _find_instance(assembly, instance_id)
    design = _design_with_instance_overrides(seed, _assembly_source_path(assembly))
    if not any(
        getattr(fl, "is_periodic_seam", False) for fl in design.forced_ligations
    ):
        raise HTTPException(422, detail="Part has no periodic seam.")
    try:
        angle_deg, trans_nm = closure_residual(design, count)
        suggested = solve_closing_curvature(design, count)
    except PeriodicSeamError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {
        "count": int(count),
        "rotation_residual_deg": float(angle_deg),
        "translation_residual_nm": float(trans_nm),
        "suggested_curvature_deg_per_bp": None
        if suggested is None
        else float(suggested),
    }


@router.post("/assembly/polymerize-periodic", status_code=200)
def polymerize_periodic_assembly(body: PolymerizePeriodicRequest) -> dict:
    """Grow a polymer from a SINGLE periodic part — no hand-defined mate.

    The part's repeat transform is derived from its ``is_periodic_seam`` forced
    ligations (the end-to-end seam the user marked in the cadnano editor's
    periodic-boundary view) via :func:`derive_periodic_delta`.  Copy k is placed
    at ``T_seed @ delta**k`` (delta is part-local, so it left-multiplies the
    seed's world transform).  Consecutive copies are tied by synthesized rigid
    seam joints carrying a single replicated ``mate_relative_transform`` so the
    chain re-resolves on part edits and is feature-logged / undoable — mirroring
    :func:`polymerize_assembly`, but anchored on one instance instead of a pair.
    """
    from backend.core.assembly_polymer import build_periodic_chain
    from backend.core.periodic_polymer import (
        PeriodicSeamError,
        derive_periodic_delta,
        principal_seam_connectors,
    )

    if body.count < 2:
        raise HTTPException(400, detail="count must be at least 2.")

    assembly = assembly_state.get_or_404()
    seed = _find_instance(assembly, body.instance_id)

    # Resolve the seed's design with its cluster overrides.  NOT _display_design
    # — the seams reference real strands/helices, which display-only stripping
    # would not affect but we want the authoritative topology regardless.
    design = _design_with_instance_overrides(seed, _assembly_source_path(assembly))

    if not any(
        getattr(fl, "is_periodic_seam", False) for fl in design.forced_ligations
    ):
        raise HTTPException(
            422,
            detail="Part has no periodic seam. Mark the end-to-end seam across "
            "the cadnano editor's periodic-boundary mirror first.",
        )
    try:
        delta = derive_periodic_delta(design)  # 4×4 part-local SE3
        delta_inv = np.linalg.inv(delta)
    except PeriodicSeamError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except np.linalg.LinAlgError as exc:
        raise HTTPException(
            422, detail=f"Could not derive periodic repeat transform: {exc}"
        ) from exc

    specs = principal_seam_connectors(design)
    if specs is None:
        raise HTTPException(
            422, detail="Periodic seam did not resolve to helix geometry."
        )

    # Pure record-assembly (chain geometry + seam-connector union + seam-joint
    # wiring) lives in backend.core.assembly_polymer; this handler owns only
    # validation, the design load, the delta derivation, and the commit.
    existing_instances, new_instances, new_joints = build_periodic_chain(
        seed,
        delta,
        delta_inv,
        specs,
        body.count,
        body.direction,
        assembly.instances,
    )

    mutated = assembly.model_copy(
        update={
            "instances": existing_instances + new_instances,
            "joints": list(assembly.joints) + new_joints,
        }
    )
    updated = _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-polymerize-periodic",
        label=f"Polymerize (periodic) {seed.name}: chain length {body.count} ({body.direction})",
        params={
            "instance_id": body.instance_id,
            "count": body.count,
            "direction": body.direction,
            "new_instance_ids": [i.id for i in new_instances],
            "new_joint_ids": [j.id for j in new_joints],
        },
    )
    return _assembly_response(updated)

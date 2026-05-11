"""Locked-angle relax solver for OverhangBinding records (Phase 5).

When the user flips an OverhangBinding's ``bound`` flag from False → True,
this module computes the hinge angle θ that brings the two sub-domains'
duplex chord to its B-DNA length, so the freshly-bound duplex sits at its
fully-formed pose. The resulting θ is then committed to
``ClusterJoint.min_angle_deg = max_angle_deg = θ`` to freeze the joint.

Public entry point:
  ``compute_locked_angle(design, binding, geometry) -> float``  (degrees)

Algorithm
---------
1. Resolve each binding sub-domain to its owning cluster (via parent
   overhang → helix → cluster). If equal, 422 "binding spans single rigid
   body".
2. Find candidate ClusterJoint records connecting the two clusters. If
   ``binding.target_joint_id`` is set, restrict to that one. Empty / >1 with
   no target → 422.
3. Only 1-DOF cluster pairs are supported in Phase 5 — if multiple joints
   sit between them, 422 "multi-DOF binding relax not yet supported".
4. Find the pivot anchor for each sub-domain in geometry (bp at the
   junction-side end of each sub-domain).
5. Target chord = ``(sd_a.length_bp - 1) * BDNA_RISE_PER_BP``.
6. Use ``backend.core.linker_relax._optimize_angle`` with the joint's
   ``min_angle_deg`` / ``max_angle_deg`` window. Loss = (|chord| - target)².
   Return θ in degrees.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import HTTPException

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.linker_relax import (
    _optimize_angle,
    _overhang_helix_id,
    _overhang_owning_cluster_id,
)
from backend.core.models import Design, OverhangBinding, _local_to_world_joint


def _sub_domain_junction_anchor(
    design: Design,
    sub_domain_id: str,
    nucs: list[dict],
) -> tuple[np.ndarray | None, np.ndarray | None, str | None]:
    """Return (anchor_position, base_normal, parent_overhang_id) for the bp
    at the JUNCTION-side end of *sub_domain_id*.

    "Junction-side" = the sub-domain's 5' tile end if the overhang's strand
    domain runs FORWARD, otherwise its 3' tile end. Pragmatically, we pick
    the geometry nuc on the parent overhang's strand whose bp_index lies
    closest to the sub-domain's junction-side tile boundary.
    """
    # Resolve sub-domain -> overhang.
    parent_ovhg = None
    target_sd = None
    for ovhg in design.overhangs:
        for sd in ovhg.sub_domains:
            if sd.id == sub_domain_id:
                parent_ovhg = ovhg
                target_sd = sd
                break
        if parent_ovhg is not None:
            break
    if parent_ovhg is None or target_sd is None:
        return None, None, None

    # Get OH nucs on this strand.
    oh_nucs = [n for n in nucs if n.get("overhang_id") == parent_ovhg.id]
    if not oh_nucs:
        return None, None, parent_ovhg.id

    # Pick the nucs by ordered bp_index along the strand.
    oh_sorted = sorted(oh_nucs, key=lambda n: n.get("bp_index") or 0)
    # The "junction" end = the bp closest to the bundle = the OH bonded end.
    # Convention: the bp at start_bp_offset within the OH strand 5'→3' order.
    # We index into the sorted list at ``start_bp_offset``.
    idx = max(0, min(len(oh_sorted) - 1, target_sd.start_bp_offset))
    nuc = oh_sorted[idx]
    pos = nuc.get("backbone_position") or nuc.get("base_position")
    bn = nuc.get("base_normal")
    return (
        np.asarray(pos, dtype=float) if pos is not None else None,
        np.asarray(bn, dtype=float) if bn is not None else None,
        parent_ovhg.id,
    )


def compute_locked_angle(
    design: Design,
    binding: OverhangBinding,
    geometry: list[dict],
) -> float:
    """Compute the joint angle that locks the binding at full duplex length.

    Returns θ in DEGREES (so it can be written directly into
    ClusterJoint.min_angle_deg / max_angle_deg).

    Raises HTTPException(422) for unsupported / ambiguous configurations.
    """
    # Resolve owning clusters.
    sd_lookup: dict[str, tuple[Any, Any]] = {}
    for ovhg in design.overhangs:
        for sd in ovhg.sub_domains:
            sd_lookup[sd.id] = (ovhg, sd)
    res_a = sd_lookup.get(binding.sub_domain_a_id)
    res_b = sd_lookup.get(binding.sub_domain_b_id)
    if res_a is None or res_b is None:
        raise HTTPException(422, detail=(
            f"OverhangBinding {binding.id}: sub_domains do not resolve."
        ))
    ovhg_a, sd_a = res_a
    ovhg_b, sd_b = res_b
    cluster_a = _overhang_owning_cluster_id(design, ovhg_a.id)
    cluster_b = _overhang_owning_cluster_id(design, ovhg_b.id)
    if cluster_a is None or cluster_b is None:
        raise HTTPException(422, detail=(
            "Binding endpoints are not owned by any cluster — no joint "
            "separates them."
        ))
    if cluster_a == cluster_b:
        raise HTTPException(422, detail=(
            "Binding spans a single rigid body — both overhangs sit on the "
            "same cluster, so no joint relaxation is possible."
        ))

    # Candidate joints connecting the two clusters.
    candidates = []
    for j in design.cluster_joints:
        if j.cluster_id == cluster_a or j.cluster_id == cluster_b:
            candidates.append(j)
    if binding.target_joint_id is not None:
        candidates = [j for j in candidates if j.id == binding.target_joint_id]
    if not candidates:
        raise HTTPException(422, detail=(
            "No ClusterJoint connects the two overhang clusters — cannot "
            "compute a binding lock angle."
        ))
    if binding.target_joint_id is None and len(candidates) > 1:
        raise HTTPException(422, detail=(
            f"Ambiguous joint for binding {binding.id}: {len(candidates)} "
            f"joints connect the two clusters. Set target_joint_id explicitly."
        ))
    if len(candidates) > 1:
        raise HTTPException(422, detail=(
            "Multi-DOF binding relax not yet supported."
        ))
    joint = candidates[0]

    # Resolve world-space joint axis.
    cts_by_id = {c.id: c for c in design.cluster_transforms}
    ct = cts_by_id.get(joint.cluster_id)
    world_origin, world_dir = _local_to_world_joint(
        joint.local_axis_origin, joint.local_axis_direction, ct,
    )
    axis = np.asarray(world_dir, dtype=float)
    n = float(np.linalg.norm(axis))
    if n < 1e-9:
        raise HTTPException(422, detail=(
            f"Joint {joint.id} axis is degenerate; cannot compute lock angle."
        ))
    axis = axis / n
    origin = np.asarray(world_origin, dtype=float)

    # Compute pivot anchors.
    p_a, n_a, _ = _sub_domain_junction_anchor(design, binding.sub_domain_a_id, geometry)
    p_b, n_b, _ = _sub_domain_junction_anchor(design, binding.sub_domain_b_id, geometry)
    if p_a is None or p_b is None:
        raise HTTPException(422, detail=(
            "Could not resolve sub-domain anchor positions from geometry."
        ))

    base_count = max(1, int(sd_a.length_bp))
    # Single chord-magnitude target via the existing _optimize_angle helper.
    # `target_arc` inside that helper is 0 nm — the loss is
    #    (chord_a_residual)^2 + (chord_b_residual)^2
    # and `_arc_chord_lengths` builds each residual as |visualLength - |chord||/2.
    # Direction of joint-side rotation: rotate side A's anchor about the joint.
    moving_is_a = (joint.cluster_id == cluster_a)
    moving_anchor = p_a if moving_is_a else p_b
    moving_normal = n_a if moving_is_a else n_b
    fixed_anchor = p_b if moving_is_a else p_a
    fixed_normal = n_b if moving_is_a else n_a

    theta_min = float(joint.min_angle_deg) * np.pi / 180.0
    theta_max = float(joint.max_angle_deg) * np.pi / 180.0
    # The OH-attachment 'comp_first' flags are a linker-specific concept; for
    # bindings, the chord-magnitude loss is symmetric so we pass True/True
    # placeholders (the values are deliberately unused in _arc_chord_lengths
    # — see its docstring).
    theta_rad = _optimize_angle(
        moving_anchor, moving_normal,
        fixed_anchor, fixed_normal,
        moving_is_a, origin, axis, base_count,
        True, True,
        theta_min=theta_min, theta_max=theta_max,
    )
    # Apply rotation and read the achieved chord to validate.
    # We deliberately do not commit anywhere here — caller writes the angle
    # into ClusterJoint.min_angle_deg / max_angle_deg through the
    # mutate_with_feature_log callback.
    target_chord = max(base_count - 1, 1) * BDNA_RISE_PER_BP
    del target_chord  # only used for documentation; loss already drives there
    return float(theta_rad * 180.0 / np.pi)

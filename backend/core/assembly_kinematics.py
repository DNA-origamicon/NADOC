"""Revolute-drive + gear/belt coupling kinematics (pure, api-free).

This is the assembly's real-time kinematics-coupling kernel: it drives revolute
joints (apply an angle about a world-fixed axis), re-derives a joint's
``current_value`` after a direct transform edit, and propagates gear / belt
coupling so spinning one revolute drives every coupled counterpart. All of it is
**display-layer** transform math over the core models — it mutates
:class:`~backend.core.models.PartInstance` transforms + ``AssemblyJoint`` /
``GearRelation`` value fields **in place** and never touches Design topology.

Lifted verbatim out of ``backend/api/assembly.py`` (carve-up Refactor #15); the
only adaptations are the byte-identical matrix-converter swaps
``_mat4_from_model(x)`` -> ``x.to_array()`` and
``_mat4_to_model(m)`` -> ``Mat4x4.from_array(m)`` (both equal the api free
functions value-for-value), which drop the last api dependency so this module
imports **nothing** from ``backend.api`` (the dependency arrow is api -> core).
It reuses the already-extracted FK kernel (``assembly_fk``) and the write-side
connector re-dock (``assembly_connectors``). The api layer imports the
externally-called entry points back under their original names; the
kernel-internal helpers (``_derive_revolute_angle``, ``_axis_angle_rotation_matrix``,
``_belt_to_relation``, ``_coupling_relations``) are now module-private here.
"""

from __future__ import annotations

import math
import os

import numpy as np

from backend.core.models import GearRelation, Mat4x4
from backend.core.assembly_fk import (
    _build_inst_by_id,
    _fk_expand_rigid_group,
    _fk_propagate,
)
from backend.core.assembly_connectors import _enforce_connector_coincidence


def _apply_revolute_joint(
    base_mat: np.ndarray,         # 4×4 row-major base transform of instance_b
    axis_origin: list[float],
    axis_direction: list[float],
    angle_rad: float,
) -> np.ndarray:
    """
    Return a new 4×4 row-major transform for instance_b after applying a
    revolute joint rotation of *angle_rad* about the given world-space axis.

    The axis is fixed in world space: points on the axis do not move.
    Formula: p_new = o + R @ (p_base_origin - o) where p_base_origin is the
    world-space origin of instance_b at angle=0 (from base_mat).
    """
    from scipy.spatial.transform import Rotation
    o = np.array(axis_origin, dtype=float)
    d = np.array(axis_direction, dtype=float)
    d_norm = np.linalg.norm(d)
    if d_norm < 1e-9:
        return base_mat
    d = d / d_norm

    R = Rotation.from_rotvec(d * angle_rad).as_matrix()  # 3×3

    # Build 4×4 result.  The rotation is applied in world space about axis_origin.
    # Translation component: t_new = o + R @ (t_base - o)
    t_base = base_mat[:3, 3]   # column 3 in row-major = last column
    t_new  = o + R @ (t_base - o)

    # Rotation component: R_new = R @ R_base
    R_base = base_mat[:3, :3]
    R_new  = R @ R_base

    result = np.eye(4)
    result[:3, :3] = R_new
    result[:3, 3]  = t_new
    return result


def _derive_revolute_angle(base_T, current_T, axis_direction):
    """Given an instance's `base_transform` (pose at current_value=0) and its
    current world transform, derive the rotation angle about `axis_direction`
    such that current_T ≈ R(axis, angle) @ base_T. Used to re-anchor a
    revolute joint's `current_value` after the user moved its child via the
    instance gizmo or the group gizmo (paths that update transforms directly
    without ever touching joint.current_value).
    """
    try:
        delta = current_T @ np.linalg.inv(base_T)
    except np.linalg.LinAlgError:
        return None
    R = delta[:3, :3]
    cos_a = (np.trace(R) - 1.0) / 2.0
    cos_a = max(-1.0, min(1.0, cos_a))
    angle = float(np.arccos(cos_a))
    sin_a = float(np.sin(angle))
    if abs(sin_a) > 1e-9:
        axis = np.asarray(axis_direction, dtype=float)
        n = np.linalg.norm(axis)
        if n < 1e-9:
            return None
        axis = axis / n
        # Recover rotation axis from antisymmetric part of R; sign vs the
        # given axis_direction tells us which way the rotation went.
        w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2.0 * sin_a)
        if float(np.dot(w, axis)) < 0.0:
            angle = -angle
    return angle


def _sync_revolute_values_for_instances(assembly, instance_ids, *,
                                          base_transforms_override=None):
    """For each revolute joint whose ``instance_b_id`` is in ``instance_ids``,
    derive the new ``current_value`` from the current vs base transform and
    update the joint in place. Returns the list of joint ids whose value
    actually changed (suitable for then calling
    :func:`_propagate_gear_relations_from`).

    ``base_transforms_override``: optional ``{instance_id: Mat4x4}`` map used
    when the caller has already overwritten ``inst.base_transform`` and needs
    the *pre-mutation* base for angle derivation. ``transform_group`` uses
    this because ``apply_group_transform`` clears ``base_transform`` on every
    moved instance; without the override the sync would silently bail and the
    gear-coupled side wouldn't follow.
    """
    if not instance_ids:
        return []
    updated: list[str] = []
    inst_by_id = _build_inst_by_id(assembly)
    debug = os.environ.get('NADOC_GEAR_DEBUG', '1') != '0'
    for j in assembly.joints:
        if j.joint_type != 'revolute':         continue
        if j.instance_b_id not in instance_ids: continue
        inst = inst_by_id.get(j.instance_b_id)
        if inst is None:                       continue
        base_model = (base_transforms_override or {}).get(j.instance_b_id) or inst.base_transform
        if base_model is None:                 continue
        try:
            base_T    = base_model.to_array()
            current_T = inst.transform.to_array()
        except Exception:
            continue
        new_value = _derive_revolute_angle(base_T, current_T, j.axis_direction)
        if new_value is None or not math.isfinite(new_value):
            continue
        old_value = j.current_value
        # _derive_revolute_angle returns the angle mod 2π (atan2). Unwrap to the
        # continuation nearest the previous current_value so a revolute commit
        # past ±π stays continuous — otherwise a belt rider (which translates
        # along the loop) would teleport ~half the loop on the 2π jump.
        new_value += 2.0 * math.pi * round((old_value - new_value) / (2.0 * math.pi))
        if abs(old_value - new_value) < 1e-6:
            continue
        j.current_value = float(new_value)
        if debug:
            print(f"[gear-sync] joint={j.id[:8]} current_value {old_value:+.3f} → {new_value:+.3f}",
                  flush=True)
        updated.append(j.id)
    return updated


def _sync_revolute_values_for_parent_moves(assembly, moved_ids, world_delta_M):
    """Parent-side counterpart to :func:`_sync_revolute_values_for_instances`.

    For each revolute joint where ``instance_a_id`` (the parent / world side)
    is in ``moved_ids`` but ``instance_b_id`` (the child / rotating side) is
    NOT — the typical "user rotated the big wheel that the fixed axle hangs
    off of" case — we derive the rotation angle of ``world_delta_M`` about
    the joint axis and update ``joint.current_value`` by **−Δ**: a positive
    parent rotation means the child's angle relative to the parent goes
    DOWN by the same amount.

    Returns the joint ids whose ``current_value`` actually changed; callers
    pass these to :func:`_propagate_gear_relations_from` so any gear-coupled
    counterpart side fires.

    Without this helper, a gear on an assembly authored "axle-as-child"
    (file ``Big_wheel_base.nass`` for example) would silently never trigger
    because the moved set only contains the parent.
    """
    if not moved_ids or world_delta_M is None:
        return []
    M = np.asarray(world_delta_M, dtype=float).reshape(4, 4)
    updated: list[str] = []
    debug = os.environ.get('NADOC_GEAR_DEBUG', '1') != '0'
    for j in assembly.joints:
        if j.joint_type != 'revolute':           continue
        if not j.instance_a_id:                  continue
        if j.instance_a_id not in moved_ids:     continue
        if j.instance_b_id is None:              continue
        if j.instance_b_id in moved_ids:         continue   # both moved → standard FK
        delta_angle = _derive_revolute_angle(np.eye(4), M, j.axis_direction)
        if delta_angle is None or not math.isfinite(delta_angle):
            continue
        if abs(delta_angle) < 1e-9:
            continue
        old_value = j.current_value
        # Child angle relative to parent rotates by −Δ when parent rotates by +Δ
        # and child stays put. axis_direction is the parent-side convention used
        # by the joint, so the sign matches.
        j.current_value = float(old_value - delta_angle)
        if debug:
            print(f"[gear-sync-parent] joint={j.id[:8]} parent_rotated={delta_angle:+.3f} → "
                  f"current_value {old_value:+.3f} → {j.current_value:+.3f}", flush=True)
        updated.append(j.id)
    return updated


def _gear_endpoint_side(rel, which: str, joint) -> str:
    if joint is None:
        return "b"
    side = getattr(rel, f"endpoint_{which}_side", None)
    inst_id = getattr(rel, f"endpoint_{which}_instance_id", None)
    if side in ("a", "b"):
        return side
    if inst_id and inst_id == joint.instance_a_id:
        return "a"
    return "b"


def _axis_angle_rotation_matrix(axis, angle: float) -> np.ndarray:
    x, y, z = np.asarray(axis, dtype=float)
    c = math.cos(angle)
    s = math.sin(angle)
    C = 1.0 - c
    return np.array([
        [c + x * x * C,     x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C,     y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ], dtype=float)


def _apply_revolute_value_to_gear_endpoint(assembly, joint, endpoint_side: str, new_value: float,
                                           inst_by_id: dict, debug: bool = False):
    """Apply ``joint.current_value = new_value`` by moving the relation's chosen endpoint.

    Legacy revolute driving always moves ``instance_b``. Endpoint-aware gear
    relations may target ``instance_a`` instead, which is exactly the
    Big_wheel_base-style case where the fixed axle is authored as the child and
    the visually rotating wheel/base is the parent side.
    """
    old_value = joint.current_value
    old_seed_id = joint.instance_a_id if endpoint_side == "a" else joint.instance_b_id
    if not old_seed_id:
        return False
    seed = inst_by_id.get(old_seed_id)
    if seed is None or seed.fixed:
        if debug:
            print(f"[gear]   skip endpoint side={endpoint_side}: seed missing/fixed", flush=True)
        return False

    old_T = seed.transform.to_array()
    if endpoint_side == "b":
        base_mat = (seed.base_transform or seed.transform).to_array()
        new_T = _apply_revolute_joint(
            base_mat, joint.axis_origin, joint.axis_direction, new_value,
        )
    else:
        # Parent-side motion is the inverse of child-side current_value:
        # parent rotates by +(old-new) to make child-relative angle become new.
        delta_angle = float(old_value - new_value)
        axis = np.asarray(joint.axis_direction, dtype=float)
        n = np.linalg.norm(axis)
        if n < 1e-9:
            return False
        axis = axis / n
        origin = np.asarray(joint.axis_origin, dtype=float)
        R = _axis_angle_rotation_matrix(axis, delta_angle)
        T = np.eye(4)
        T[:3, :3] = R
        to_o = np.eye(4); to_o[:3, 3] = origin
        from_o = np.eye(4); from_o[:3, 3] = -origin
        delta = to_o @ T @ from_o
        new_T = delta @ old_T

    joint.current_value = float(new_value)
    seed.transform = Mat4x4.from_array(new_T)
    try:
        delta = new_T @ np.linalg.inv(old_T)
        visited = {old_seed_id}
        _fk_expand_rigid_group(assembly, old_seed_id, delta, visited, [], inst_by_id)
        _fk_propagate(assembly, visited.copy(), delta, visited, inst_by_id)
        _enforce_connector_coincidence(assembly, visited, inst_by_id)
    except np.linalg.LinAlgError:
        pass
    return True


def _belt_to_relation(belt, joint_by_id):
    """Express a BeltPath as a GearRelation-equivalent coupling edge.

    An open belt couples its two pulley joints so rotating one drives the other
    at angular ratio r_a/r_b (equal rim/tangential speed) in the SAME world
    rotational sense. We reuse the gear propagation machinery: ``ratio`` is the
    radius ratio and ``invert`` carries the direction sign.

    The current_value→physical-rotation map per pulley is ``s = +1`` for the
    child side ('b') and ``-1`` for the parent side ('a'); the world sense also
    flips when the two joint axes point opposite ways. Same world sense between
    the two pulleys' current_values therefore holds when
    ``s_a * s_b * sign(axis_a · axis_b) > 0`` (→ invert=False), else invert=True.
    Returns None if either joint is missing or a radius is non-positive.
    """
    pa, pb = belt.pulley_a, belt.pulley_b
    ja = joint_by_id.get(pa.joint_id)
    jb = joint_by_id.get(pb.joint_id)
    if ja is None or jb is None:
        return None
    if not (pa.radius > 1e-6) or not (pb.radius > 1e-6):
        return None
    s_a = -1.0 if pa.side == "a" else 1.0
    s_b = -1.0 if pb.side == "a" else 1.0
    dot = sum(float(x) * float(y) for x, y in zip(ja.axis_direction, jb.axis_direction))
    axis_sign = 1.0 if dot >= 0 else -1.0
    invert = (s_a * s_b * axis_sign) < 0
    return GearRelation(
        id=f"__belt__{belt.id}",
        name=f"Belt:{belt.name}",
        joint_a_id=pa.joint_id,
        joint_b_id=pb.joint_id,
        endpoint_a_instance_id=pa.instance_id,
        endpoint_b_instance_id=pb.instance_id,
        endpoint_a_side=pa.side,
        endpoint_b_side=pb.side,
        ratio=float(pa.radius) / float(pb.radius),
        invert=invert,
        joint_a_anchor=belt.joint_a_anchor,
        joint_b_anchor=belt.joint_b_anchor,
    )


def _coupling_relations(assembly, joint_by_id):
    """All real-time coupling edges: gear relations + belt-derived relations."""
    rels = list(assembly.gear_relations)
    for belt in assembly.belt_paths:
        r = _belt_to_relation(belt, joint_by_id)
        if r is not None:
            rels.append(r)
    return rels


def _propagate_gear_relations_from(assembly, source_joint_id):
    """BIDIRECTIONAL gear-relation propagation from ``source_joint_id``.

    Each :class:`GearRelation` provides two edges in the propagation graph:

      forward edge   joint_a → joint_b   θ_b = anchor_b + sign · (θ_a − anchor_a) · ratio
      inverse edge   joint_b → joint_a   θ_a = anchor_a + sign · (θ_b − anchor_b) / ratio

    So spinning EITHER side of a gear pair drives the OTHER — matching how
    real gears mesh, and matching the user's expectation when they grab the
    gold ring on either coupled wheel. Cycle-safe via ``visited_relations``;
    in chains (A ↔ B ↔ C), propagation walks both directions to settle
    every joint reachable from the source.

    First-wins rule: a joint already updated by an earlier relation this pass
    isn't re-driven, mirroring the frontend ticker policy.

    For each driven joint reached, we update ``current_value`` + instance_b
    transform + run FK propagation through any rigid-attached descendants,
    re-using the existing in-place mutation pattern from
    :func:`_fk_expand_rigid_group`.

    Diagnostics: emits one ``[gear]`` log line per relation processed and one
    summary. Toggle with ``NADOC_GEAR_DEBUG`` env var (default ON for now).
    """
    if not assembly.gear_relations and not assembly.belt_paths:
        return
    inst_by_id  = _build_inst_by_id(assembly)
    joint_by_id = {j.id: j for j in assembly.joints}
    relations   = _coupling_relations(assembly, joint_by_id)
    if not relations:
        return
    debug = os.environ.get('NADOC_GEAR_DEBUG', '1') != '0'
    if debug:
        print(f"[gear] propagate_from(source={source_joint_id[:8]!r}, "
              f"relations={len(relations)})", flush=True)
    visited_relations: set = set()
    written_set: set      = set()    # joint ids that have been driven by propagation (first-wins)
    queue: list           = [source_joint_id]
    n_applied             = 0

    def _apply(rel, src_joint, tgt_id, anchor_src, anchor_tgt, factor, direction,
               endpoint_side, source_endpoint_side):
        nonlocal n_applied
        tgt = joint_by_id.get(tgt_id)
        if not tgt:
            if debug: print(f"[gear]   skip rel={rel.id[:8]!r} ({direction}): target joint missing", flush=True)
            return
        if tgt.joint_type != 'revolute':
            if debug: print(f"[gear]   skip rel={rel.id[:8]!r} ({direction}): target not revolute", flush=True)
            return
        sign = -1.0 if rel.invert else 1.0
        raw_value = anchor_tgt + sign * (src_joint.current_value - anchor_src) * factor
        lo = tgt.min_limit if tgt.min_limit is not None else -math.inf
        hi = tgt.max_limit if tgt.max_limit is not None else  math.inf
        new_value = max(lo, min(hi, raw_value))

        if abs(new_value - raw_value) > 1e-9 and abs(factor) > 1e-12:
            source_raw = anchor_src + sign * (new_value - anchor_tgt) / factor
            src_lo = src_joint.min_limit if src_joint.min_limit is not None else -math.inf
            src_hi = src_joint.max_limit if src_joint.max_limit is not None else math.inf
            source_value = max(src_lo, min(src_hi, source_raw))
            if abs(source_value - src_joint.current_value) > 1e-9:
                _apply_revolute_value_to_gear_endpoint(
                    assembly, src_joint, source_endpoint_side, float(source_value), inst_by_id, debug,
                )

        old_value = tgt.current_value
        if not _apply_revolute_value_to_gear_endpoint(
            assembly, tgt, endpoint_side, float(new_value), inst_by_id, debug,
        ):
            return
        n_applied += 1
        if debug:
            print(f"[gear]   APPLY rel={rel.id[:8]!r} ({direction}) "
                  f"{src_joint.id[:8]}={src_joint.current_value:+.3f} → "
                  f"{tgt_id[:8]} {old_value:+.3f} → {new_value:+.3f} "
                  f"(ratio={rel.ratio} factor={factor:+.4f} invert={rel.invert} endpoint={endpoint_side})",
                  flush=True)

        # Recurse: the target joint may itself be coupled by further gear
        # relations on either side.
        queue.append(tgt_id)

    while queue:
        cur_id = queue.pop(0)
        cur_joint = joint_by_id.get(cur_id)
        if cur_joint is None:
            continue
        for rel in relations:
            if rel.id in visited_relations:
                continue
            # Forward edge: source is joint_a, target is joint_b
            if rel.joint_a_id == cur_id:
                if rel.joint_b_id in written_set:
                    continue
                visited_relations.add(rel.id)
                written_set.add(rel.joint_b_id)
                _apply(
                    rel, cur_joint, rel.joint_b_id,
                    anchor_src=rel.joint_a_anchor,
                    anchor_tgt=rel.joint_b_anchor,
                    factor=float(rel.ratio),
                    direction='fwd',
                    endpoint_side=_gear_endpoint_side(rel, "b", joint_by_id.get(rel.joint_b_id)),
                    source_endpoint_side=_gear_endpoint_side(rel, "a", cur_joint),
                )
                continue
            # Inverse edge: source is joint_b, target is joint_a
            if rel.joint_b_id == cur_id:
                if rel.joint_a_id in written_set:
                    continue
                visited_relations.add(rel.id)
                written_set.add(rel.joint_a_id)
                # Inverse factor = 1/ratio; ratio is validated non-zero by GearRelation
                _apply(
                    rel, cur_joint, rel.joint_a_id,
                    anchor_src=rel.joint_b_anchor,
                    anchor_tgt=rel.joint_a_anchor,
                    factor=1.0 / float(rel.ratio),
                    direction='inv',
                    endpoint_side=_gear_endpoint_side(rel, "a", joint_by_id.get(rel.joint_a_id)),
                    source_endpoint_side=_gear_endpoint_side(rel, "b", cur_joint),
                )
                continue
    if debug:
        print(f"[gear] done: {n_applied} joint(s) updated", flush=True)

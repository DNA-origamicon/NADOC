"""
Pure-math helpers for "Polymerize Origami" — replicate a single mate
(AssemblyJoint between two identical PartInstances) into a chain of N
identical parts.

The geometry of the chain is fully determined by:
  T_A    — transform of the first mate's instance_a
  T_B    — transform of the first mate's instance_b
  delta  = T_B @ inv(T_A)
  joint  — the AssemblyJoint that defines connector labels + axis + bounds

Forward chain step i (1-indexed) places a new instance at:
    T_{B+i} = delta^i @ T_B
Backward chain step i (1-indexed) places a new instance at:
    T_{A-i} = inv(delta)^i @ T_A

Joint axes are world-space at the original pair's pose; transforming each
axis through the corresponding step delta places the new joint's ring
exactly between the two new instances it bridges. No FastAPI imports here
— this module is unit-testable in isolation.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Literal, Optional, Tuple

import numpy as np

from backend.core.models import (
    AssemblyJoint,
    Mat4x4,
    PartInstance,
    PartSource,
    PartSourceFile,
    PartSourceInline,
)


Direction = Literal["forward", "backward", "both"]


# ── Source equality ──────────────────────────────────────────────────────────


def _design_dump_for_identity(design) -> dict:
    """Project a Design dump down to the fields that define structural identity.

    Excludes the auto-generated ``id`` UUID, metadata (name/timestamps may
    differ for two same-design instances), and feature_log (history rather
    than current shape). The remaining fields — helices, strands, overhangs,
    crossovers, lattice_type, etc. — determine whether two designs represent
    the same Part.
    """
    excluded = {"id", "metadata", "feature_log", "feature_log_cursor",
                "feature_log_sub_cursor", "camera_poses", "animations"}
    return {k: v for k, v in design.model_dump().items() if k not in excluded}


def _sources_match(a: PartSource, b: PartSource) -> bool:
    """True when two PartInstances are 'identical parts'.

    File-backed: identical .path string. (sha256 may legitimately differ
    between instances if one was loaded before a file edit; the path is
    the authoritative identity.)
    Inline: same Design object identity OR equal structural dump
    (ignores auto-generated id + metadata so two separately-loaded copies
    of the same Part match).
    """
    if isinstance(a, PartSourceFile) and isinstance(b, PartSourceFile):
        return a.path == b.path
    if isinstance(a, PartSourceInline) and isinstance(b, PartSourceInline):
        if a.design is b.design:
            return True
        try:
            return _design_dump_for_identity(a.design) == _design_dump_for_identity(b.design)
        except Exception:
            return False
    return False


# ── Chain math ───────────────────────────────────────────────────────────────


def _matrix_power(m: np.ndarray, k: int) -> np.ndarray:
    """4x4 matrix power for non-negative integer k.

    k=0 → identity; k=n → m @ m @ ... @ m (n times). Computed by repeated
    multiplication so we never need scipy / matrix logs.
    """
    if k < 0:
        raise ValueError(f"matrix power requires k >= 0, got {k}")
    out = np.eye(4, dtype=float)
    for _ in range(k):
        out = m @ out
    return out


def _split_count(count: int, direction: Direction) -> Tuple[int, int]:
    """How many new instances to add on each side, given total chain length.

    Total chain length includes the existing pair (A, B). For 'both', the
    new instances are split between forward and backward; if (count - 2)
    is odd, the extra goes forward.
    """
    new_total = max(count - 2, 0)
    if direction == "forward":
        return new_total, 0
    if direction == "backward":
        return 0, new_total
    forward = (new_total + 1) // 2   # extra-on-forward when odd
    backward = new_total - forward
    return forward, backward


def compute_additional_chain_transforms(
    t_a: Mat4x4,
    t_b: Mat4x4,
    t_orig: Mat4x4,
    n_forward: int,
    n_backward: int,
) -> Tuple[list[np.ndarray], list[np.ndarray]]:
    """Per-step transforms for an *additional* pattern-unit instance.

    The seed mate `(t_a, t_b)` defines the chain delta. Each step
    multiplies the additional instance's own transform by `delta^step`
    (forward) or `inv(delta)^step` (backward), so the additional part's
    relative position to the chain's primary instance is preserved at
    every step.

    Mirrors :func:`compute_chain_transforms` but starts from
    ``t_orig`` rather than ``t_b`` / ``t_a``.
    """
    if n_forward < 0 or n_backward < 0:
        raise ValueError("n_forward / n_backward must be non-negative")
    A = t_a.to_array()
    B = t_b.to_array()
    O = t_orig.to_array()
    try:
        A_inv = np.linalg.inv(A)
    except np.linalg.LinAlgError as exc:
        raise ValueError("seed instance_a transform is singular") from exc
    delta = B @ A_inv
    try:
        delta_inv = np.linalg.inv(delta)
    except np.linalg.LinAlgError as exc:
        raise ValueError("delta is singular") from exc

    forward: list[np.ndarray] = []
    cur = O.copy()
    for _ in range(n_forward):
        cur = delta @ cur
        forward.append(cur.copy())

    backward: list[np.ndarray] = []
    cur = O.copy()
    for _ in range(n_backward):
        cur = delta_inv @ cur
        backward.append(cur.copy())

    return forward, backward


def compute_delta_powers(
    t_a: Mat4x4,
    t_b: Mat4x4,
    n_forward: int,
    n_backward: int,
) -> Tuple[list[np.ndarray], list[np.ndarray]]:
    """Return (forward_powers, backward_powers) of the seed mate's delta.

    ``forward_powers[i] = delta^(i + 1)``; ``backward_powers[i] = delta^-(i + 1)``.
    Used to transform pattern-mate axes at each step so the replicated
    joint axis lands at the right world-space location.
    """
    A = t_a.to_array()
    B = t_b.to_array()
    delta = B @ np.linalg.inv(A)
    delta_inv = np.linalg.inv(delta)

    fwd: list[np.ndarray] = []
    cur = np.eye(4, dtype=float)
    for _ in range(n_forward):
        cur = delta @ cur
        fwd.append(cur.copy())

    back: list[np.ndarray] = []
    cur = np.eye(4, dtype=float)
    for _ in range(n_backward):
        cur = delta_inv @ cur
        back.append(cur.copy())

    return fwd, back


def compute_chain_transforms(
    t_a: Mat4x4,
    t_b: Mat4x4,
    count: int,
    direction: Direction,
) -> Tuple[list[np.ndarray], list[np.ndarray]]:
    """Return ``(forward_transforms, backward_transforms)``.

    Each entry is a 4x4 numpy array (row-major) for one new PartInstance.
    Forward list is ordered from closest-to-B outward; backward list is
    ordered from closest-to-A outward.
    """
    if count < 2:
        raise ValueError(f"count must be at least 2 (got {count})")

    A = t_a.to_array()
    B = t_b.to_array()
    try:
        A_inv = np.linalg.inv(A)
    except np.linalg.LinAlgError as exc:
        raise ValueError("instance_a.transform is singular — cannot invert") from exc
    delta = B @ A_inv
    try:
        delta_inv = np.linalg.inv(delta)
    except np.linalg.LinAlgError as exc:
        raise ValueError("delta transform between A and B is singular") from exc

    n_forward, n_backward = _split_count(count, direction)

    forward: list[np.ndarray] = []
    cur = B.copy()
    for _ in range(n_forward):
        cur = delta @ cur
        forward.append(cur.copy())

    backward: list[np.ndarray] = []
    cur = A.copy()
    for _ in range(n_backward):
        cur = delta_inv @ cur
        backward.append(cur.copy())

    return forward, backward


def transform_joint_axis(
    axis_origin: list[float],
    axis_direction: list[float],
    delta: np.ndarray,
) -> Tuple[list[float], list[float]]:
    """Apply a 4x4 transform to a joint axis (point + direction).

    Origin is a point (apply full 4x4); direction is a vector (rotate only).
    """
    o = np.array([axis_origin[0], axis_origin[1], axis_origin[2], 1.0], dtype=float)
    d = np.array([axis_direction[0], axis_direction[1], axis_direction[2]], dtype=float)
    new_o = (delta @ o)[:3]
    new_d = delta[:3, :3] @ d
    n = float(np.linalg.norm(new_d))
    if n > 1e-12:
        new_d = new_d / n
    return new_o.tolist(), new_d.tolist()


def compute_chain_joint_axes(
    orig_joint: AssemblyJoint,
    t_a: Mat4x4,
    t_b: Mat4x4,
    n_forward: int,
    n_backward: int,
) -> Tuple[list[Tuple[list[float], list[float]]], list[Tuple[list[float], list[float]]]]:
    """Per-step transformed (axis_origin, axis_direction) for new joints.

    Each new joint replaces the original mate's axis with one mapped by
    ``delta^i`` (forward) or ``delta^-i`` (backward). The 0-th element of
    each returned list corresponds to the joint between the original
    pair's near-end instance and the FIRST new instance on that side.
    """
    A = t_a.to_array()
    B = t_b.to_array()
    A_inv = np.linalg.inv(A)
    delta = B @ A_inv
    delta_inv = np.linalg.inv(delta)

    forward_axes: list[Tuple[list[float], list[float]]] = []
    for i in range(1, n_forward + 1):
        forward_axes.append(transform_joint_axis(
            orig_joint.axis_origin, orig_joint.axis_direction,
            _matrix_power(delta, i),
        ))

    backward_axes: list[Tuple[list[float], list[float]]] = []
    for i in range(1, n_backward + 1):
        backward_axes.append(transform_joint_axis(
            orig_joint.axis_origin, orig_joint.axis_direction,
            _matrix_power(delta_inv, i),
        ))

    return forward_axes, backward_axes


# ── Chain record assembly ──────────────────────────────────────────────────────


def build_polymer_chain(
    joint: AssemblyJoint,
    inst_a: PartInstance,
    inst_b: PartInstance,
    additional_instances: list[PartInstance],
    count: int,
    direction: Direction,
    all_instances: list[PartInstance],
    all_joints: list[AssemblyJoint],
) -> Tuple[list[PartInstance], list[PartInstance], list[AssemblyJoint]]:
    """Build the PartInstance + AssemblyJoint records for a polymer chain.

    Pure record-assembly: given the seed mate (``joint`` between identical
    ``inst_a`` / ``inst_b``), the resolved ``additional_instances`` pattern
    members, and the assembly's current ``all_instances`` / ``all_joints``,
    return ``(existing_instances, new_instances, new_joints)`` ready to be
    composed onto the assembly. The caller owns validation, instance/joint
    lookups, and the feature-log commit; this function owns the geometry +
    connector-union + pattern-mate replication logic. ``count == 2`` is a
    no-op the caller handles before calling here (this assumes ``count >= 3``).

    The chain math is delegated to the module's pure helpers
    (:func:`compute_chain_transforms` &c.); this function spends new ids,
    deep-copies per-instance state, and shifts replicated joint axes.
    """
    seed_pair_ids: set[str] = {joint.instance_a_id, joint.instance_b_id}

    forward_T, backward_T = compute_chain_transforms(
        inst_a.transform, inst_b.transform, count, direction,
    )
    n_forward, n_backward = _split_count(count, direction)
    forward_axes, backward_axes = compute_chain_joint_axes(
        joint, inst_a.transform, inst_b.transform, n_forward, n_backward,
    )
    # Compute delta powers to cover ALL iteration counts — the extended
    # additional-clone chain may need one more matrix than the primary
    # chain (see add_n_forward / add_n_backward below).
    forward_delta_pow, backward_delta_pow = compute_delta_powers(
        inst_a.transform, inst_b.transform,
        n_forward + 1, n_backward + 1,
    )

    # Mates in the pattern unit (excluding the seed mate itself). Each will
    # be replicated at every chain step. ``instance_a_id`` is Optional in
    # the model — a None side never participates in pattern replication.
    unit_ids: set[str] = seed_pair_ids | {i.id for i in additional_instances}
    pattern_mates = [
        j for j in all_joints
        if j.id != joint.id
        and j.instance_a_id is not None
        and j.instance_a_id in unit_ids
        and j.instance_b_id in unit_ids
    ]

    # ── Connector union ───────────────────────────────────────────────────────
    # The seed mate references one InterfacePoint label on each side; users
    # typically only `Define Connector` once per instance, so inst_a has just
    # the "a" label and inst_b has just the "b" label.  In a chain every
    # interior instance plays both roles, so each chained instance needs both
    # labels.  Build the union (deduped by label, source order preserved) and
    # apply it to A, B, and every new clone.  Positions are part-local; since
    # _sources_match is true above, the union is well-defined.
    union_ips: list = []
    seen_labels: set[str] = set()
    for ip in list(inst_a.interface_points) + list(inst_b.interface_points):
        if ip.label in seen_labels:
            continue
        seen_labels.add(ip.label)
        union_ips.append(ip.model_copy(deep=True))

    inst_a_updated = inst_a.model_copy(update={"interface_points": list(union_ips)})
    inst_b_updated = inst_b.model_copy(update={"interface_points": list(union_ips)})

    # Stitch the originals back into the assembly's instance list at their
    # original indexes so positional ordering is preserved.
    existing_instances = [
        inst_a_updated if i.id == inst_a.id else
        inst_b_updated if i.id == inst_b.id else i
        for i in all_instances
    ]

    # ── Build new PartInstances (forward side) ────────────────────────────────
    # Phase 4a path-to-thousands: bypass per-clone Pydantic deep validation
    # by using ``PartInstance.model_construct`` (skips validators) AND
    # sharing the heavy ``source`` field by reference across all clones.
    # The source field on a PartInstance is treated as immutable downstream
    # (loaded read-only via _load_design_from_source), so reference-sharing
    # is safe; the original code's ``model_copy(deep=True)`` was deep-copying
    # a heavy Design tree per clone for no semantic benefit.
    #
    # Net effect at N=500 polymerize_64: ~150 ms → ~10 ms inside the loop.
    new_instances: list[PartInstance] = []
    new_joints:    list[AssemblyJoint] = []

    base_name_b = inst_b.name
    base_name_a = inst_a.name

    # Pre-compute per-additional per-step transforms.  Additionals get one
    # MORE clone than the primary chain extension so each pattern member
    # ends up with the same total count as the primary chain — the seed
    # pair contributes two existing primaries (seed_a + seed_b), but each
    # additional contributes only one existing instance, so an extra
    # clone is needed.  The extra clone is placed in the dominant
    # direction (forward for 'forward' and 'both', backward for
    # 'backward').
    add_n_forward  = n_forward  + (1 if direction != "backward" else 0)
    add_n_backward = n_backward + (1 if direction == "backward" else 0)
    add_forward_transforms:  dict[str, list[np.ndarray]] = {}
    add_backward_transforms: dict[str, list[np.ndarray]] = {}
    for add_inst in additional_instances:
        f, b = compute_additional_chain_transforms(
            inst_a.transform, inst_b.transform, add_inst.transform,
            add_n_forward, add_n_backward,
        )
        add_forward_transforms[add_inst.id]  = f
        add_backward_transforms[add_inst.id] = b

    forward_primary_ids:  list[str]                = []
    forward_add_ids:      dict[str, list[str]]     = {a.id: [] for a in additional_instances}
    backward_primary_ids: list[str]                = []
    backward_add_ids:     dict[str, list[str]]     = {a.id: [] for a in additional_instances}

    # ``_make_clone`` constructs a PartInstance for a polymerize clone with
    # the heavy ``source`` field shared by reference from the seed.  We use
    # ``model_construct`` (no validation) — every field is already validated
    # on the seed, and the only field-typed changes (id, name, transform,
    # representation) are well-formed Python primitives or pre-built
    # Mat4x4 objects.  Interface points are passed through; we DO need
    # independent IP lists per clone (a shallow ``list(union_ips)`` at the
    # call site) because IPs are appended to / mutated by add_connector
    # etc. downstream.  The IP OBJECTS inside the list are shared by
    # reference — safe ONLY because every add/remove path in this module
    # uses ``model_copy(update=...)`` rather than in-place mutation; if a
    # future code path mutates an IP in place, switch the call sites to
    # ``[ip.model_copy(deep=True) for ip in union_ips]``.
    def _make_clone(seed: PartInstance, *, new_id: str, name: str,
                    transform: Mat4x4, base_transform: Optional[Mat4x4],
                    interface_points: list,
                    representation: str = "cylinders") -> PartInstance:
        return PartInstance.model_construct(
            id=new_id,
            name=name,
            source=seed.source,                 # shared by reference (read-only downstream)
            transform=transform,
            base_transform=base_transform,
            mode=seed.mode,
            visible=seed.visible,
            representation=representation,
            fixed=seed.fixed,
            allow_part_joints=seed.allow_part_joints,
            joint_states=dict(seed.joint_states),
            cluster_transform_overrides=list(seed.cluster_transform_overrides),
            interface_points=interface_points,
        )

    # Each new forward primary clones inst_b's per-instance state (overrides,
    # representation, mode, fixed/visible, joint_states) but takes the unioned
    # connectors so it can mate on both sides.
    prev_inst_id = inst_b_updated.id
    for i, T_arr in enumerate(forward_T):
        T_mat = Mat4x4.from_array(T_arr)
        new_id = str(_uuid.uuid4())
        new_inst = _make_clone(
            inst_b,
            new_id=new_id,
            name=f"{base_name_b} {i + 1}",
            transform=T_mat,
            base_transform=T_mat,   # base_transform = transform at value=0
            interface_points=list(union_ips),
        )
        forward_primary_ids.append(new_id)
        axis_origin, axis_direction = forward_axes[i]
        new_jt = AssemblyJoint(
            name=f"{joint.name} +{i + 1}",
            joint_type=joint.joint_type,
            instance_a_id=prev_inst_id,
            instance_b_id=new_id,
            cluster_id_a=joint.cluster_id_a,
            cluster_id_b=joint.cluster_id_b,
            axis_origin=axis_origin,
            axis_direction=axis_direction,
            current_value=0.0,
            min_limit=joint.min_limit,
            max_limit=joint.max_limit,
            connector_a_label=joint.connector_a_label,
            connector_b_label=joint.connector_b_label,
            # Replicate the seed mate's full SE3 relative frame so resolve does
            # an orientation-aware snap (not just translation). Without this,
            # polymerized rigid mates resolved POSITION but not ORIENTATION.
            mate_relative_transform=joint.mate_relative_transform,
        )
        new_instances.append(new_inst)
        new_joints.append(new_jt)
        prev_inst_id = new_id

    # Spawn additional clones forward.  Each additional gets `add_n_forward`
    # entries, which is `n_forward + 1` for direction ∈ {forward, both} so
    # the additional's total instance count (1 existing + add_n_forward new)
    # matches the chain length N — fixing the off-by-one the user reported.
    for add_inst in additional_instances:
        ip_seed = list(add_inst.interface_points)
        for i, T_add in enumerate(add_forward_transforms[add_inst.id]):
            T_mat = Mat4x4.from_array(T_add)
            new_id = str(_uuid.uuid4())
            new_inst = _make_clone(
                add_inst,
                new_id=new_id,
                name=f"{add_inst.name} {i + 1}",
                transform=T_mat,
                base_transform=None,
                interface_points=list(ip_seed),
            )
            new_instances.append(new_inst)
            forward_add_ids[add_inst.id].append(new_id)

    # ── Backward side ────────────────────────────────────────────────────────
    # Reuse inst_a's per-instance state.  Each backward instance is appended
    # in the order "closest to A outward" so the new joint binds
    # (backward_step_i, backward_step_{i-1}) — except the first backward
    # joint, which binds (first_new_backward, original inst_a).  Connector
    # labels stay the same as the original mate.
    prev_inst_id = inst_a_updated.id
    for i, T_arr in enumerate(backward_T):
        T_mat = Mat4x4.from_array(T_arr)
        new_id = str(_uuid.uuid4())
        new_inst = _make_clone(
            inst_a,
            new_id=new_id,
            name=f"{base_name_a} -{i + 1}",
            transform=T_mat,
            base_transform=T_mat,
            interface_points=list(union_ips),
        )
        backward_primary_ids.append(new_id)
        axis_origin, axis_direction = backward_axes[i]
        # The mate's "natural" direction is (a → b).  For backward
        # chaining, the previous instance (closer to the original a) plays
        # the role of "b" relative to the new (further-back) instance.
        # Preserve the original connector labels by setting
        # (instance_a = new_inst, instance_b = prev_inst) so connector_a
        # lands on the freshly-added part and connector_b on the existing
        # one — same labels as the seed mate.
        new_jt = AssemblyJoint(
            name=f"{joint.name} -{i + 1}",
            joint_type=joint.joint_type,
            instance_a_id=new_id,
            instance_b_id=prev_inst_id,
            cluster_id_a=joint.cluster_id_a,
            cluster_id_b=joint.cluster_id_b,
            axis_origin=axis_origin,
            axis_direction=axis_direction,
            current_value=0.0,
            min_limit=joint.min_limit,
            max_limit=joint.max_limit,
            connector_a_label=joint.connector_a_label,
            connector_b_label=joint.connector_b_label,
            # Replicate the seed mate's full SE3 relative frame so resolve does
            # an orientation-aware snap (not just translation). Without this,
            # polymerized rigid mates resolved POSITION but not ORIENTATION.
            mate_relative_transform=joint.mate_relative_transform,
        )
        new_instances.append(new_inst)
        new_joints.append(new_jt)
        prev_inst_id = new_id

    # Spawn additional clones backward.  Same off-by-one fix as forward —
    # add_n_backward = n_backward + 1 when direction == 'backward', else
    # n_backward.  Each additional ends up with chain-length-many total
    # instances combining backward + forward.
    for add_inst in additional_instances:
        ip_seed = list(add_inst.interface_points)
        for i, T_add in enumerate(add_backward_transforms[add_inst.id]):
            T_mat = Mat4x4.from_array(T_add)
            new_id = str(_uuid.uuid4())
            new_inst = _make_clone(
                add_inst,
                new_id=new_id,
                name=f"{add_inst.name} -{i + 1}",
                transform=T_mat,
                base_transform=None,
                interface_points=list(ip_seed),
            )
            new_instances.append(new_inst)
            backward_add_ids[add_inst.id].append(new_id)

    # ── Pattern-mate replication ──────────────────────────────────────────────
    # For each mate inside the pattern unit (excluding the seed mate), emit
    # one new joint per chain step between the matching cloned instances.
    # The new joint's axis_origin / axis_direction are shifted by the same
    # delta^step that placed the new instances, so the world-space axis
    # lands at the right spot.

    def _clone_id_forward(orig_id: str, step1: int) -> Optional[str]:
        """Return the id of *orig_id*'s clone at 1-indexed forward step,
        or None if no clone exists at that step (e.g. the seed_b-side
        primary chain is exhausted before the additional chain).

        - seed_a (level 0) shifts to primary at level `step1`.
        - seed_b (level 1) shifts to primary at level `step1 + 1`.
        - additional X shifts to its own clone array entry.
        """
        if orig_id == joint.instance_a_id:
            if step1 == 1:
                return joint.instance_b_id
            idx = step1 - 2
            return forward_primary_ids[idx] if 0 <= idx < len(forward_primary_ids) else None
        if orig_id == joint.instance_b_id:
            idx = step1 - 1
            return forward_primary_ids[idx] if 0 <= idx < len(forward_primary_ids) else None
        ids = forward_add_ids.get(orig_id)
        if not ids:
            return None
        idx = step1 - 1
        return ids[idx] if 0 <= idx < len(ids) else None

    def _clone_id_backward(orig_id: str, step1: int) -> Optional[str]:
        """1-indexed backward step. seed_a / seed_b shift inverse-delta^step."""
        if orig_id == joint.instance_b_id:
            if step1 == 1:
                return joint.instance_a_id
            idx = step1 - 2
            return backward_primary_ids[idx] if 0 <= idx < len(backward_primary_ids) else None
        if orig_id == joint.instance_a_id:
            idx = step1 - 1
            return backward_primary_ids[idx] if 0 <= idx < len(backward_primary_ids) else None
        ids = backward_add_ids.get(orig_id)
        if not ids:
            return None
        idx = step1 - 1
        return ids[idx] if 0 <= idx < len(ids) else None

    # Iterate up to the EXTENDED additional count so the bonus clone at
    # the end of the chain also gets its mate replicated.  _clone_id_*
    # returns None when the primary chain has been exhausted at this step
    # (e.g. mate involves seed_b which only goes up to n_forward), in
    # which case we silently skip that step for that mate.
    fwd_max  = max(n_forward,  add_n_forward)
    back_max = max(n_backward, add_n_backward)
    for pm in pattern_mates:
        for step_idx in range(1, fwd_max + 1):
            new_a_id = _clone_id_forward(pm.instance_a_id, step_idx)
            new_b_id = _clone_id_forward(pm.instance_b_id, step_idx)
            if new_a_id is None or new_b_id is None:
                continue
            d = forward_delta_pow[step_idx - 1]
            ao, ad = transform_joint_axis(list(pm.axis_origin), list(pm.axis_direction), d)
            new_joints.append(AssemblyJoint(
                name=f"{pm.name} +{step_idx}",
                joint_type=pm.joint_type,
                instance_a_id=new_a_id,
                instance_b_id=new_b_id,
                cluster_id_a=pm.cluster_id_a,
                cluster_id_b=pm.cluster_id_b,
                axis_origin=ao,
                axis_direction=ad,
                current_value=0.0,
                min_limit=pm.min_limit,
                max_limit=pm.max_limit,
                connector_a_label=pm.connector_a_label,
                connector_b_label=pm.connector_b_label,
                # Replicate the intra-unit mate's full SE3 relative frame so
                # resolve snaps orientation, not just position (see primary
                # chain joints above).
                mate_relative_transform=pm.mate_relative_transform,
            ))
        for step_idx in range(1, back_max + 1):
            new_a_id = _clone_id_backward(pm.instance_a_id, step_idx)
            new_b_id = _clone_id_backward(pm.instance_b_id, step_idx)
            if new_a_id is None or new_b_id is None:
                continue
            d = backward_delta_pow[step_idx - 1]
            ao, ad = transform_joint_axis(list(pm.axis_origin), list(pm.axis_direction), d)
            new_joints.append(AssemblyJoint(
                name=f"{pm.name} -{step_idx}",
                joint_type=pm.joint_type,
                instance_a_id=new_a_id,
                instance_b_id=new_b_id,
                cluster_id_a=pm.cluster_id_a,
                cluster_id_b=pm.cluster_id_b,
                axis_origin=ao,
                axis_direction=ad,
                current_value=0.0,
                min_limit=pm.min_limit,
                max_limit=pm.max_limit,
                connector_a_label=pm.connector_a_label,
                connector_b_label=pm.connector_b_label,
                # Replicate the intra-unit mate's full SE3 relative frame so
                # resolve snaps orientation, not just position (see primary
                # chain joints above).
                mate_relative_transform=pm.mate_relative_transform,
            ))

    return existing_instances, new_instances, new_joints

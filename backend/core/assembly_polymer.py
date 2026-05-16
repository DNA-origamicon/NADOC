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

from typing import Literal, Optional, Tuple

import numpy as np

from backend.core.models import (
    AssemblyJoint,
    Mat4x4,
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

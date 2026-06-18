"""Oriented bounding box (OBB) of a rigid-body cluster + the edge-alignment solver.

This is **pure geometry** in the three-layer sense: it READS the geometric layer
(``deformed_helix_axes`` — the cluster-posed helix axes) and never writes the
topological layer.  It is the shared foundation the kinematic-cluster items lean
on: AF-15 Phase 2 (cluster OBB-edge alignment, here) and AF-14 (revolute-joint
range-of-motion, later).  It imports nothing from ``backend.api``.

The OBB
-------
A cluster's OBB is an oriented box around its helices' axis endpoints, in a frame
``(u, v, w)`` derived **purely from the cluster's own geometry** so the box is
*equivariant* under a rigid cluster pose — applying a rigid transform ``g`` to the
cluster gives ``OBB(g · design) = g · OBB(design)`` (proved in the test
``test_obb_is_equivariant``).  That equivariance is the load-bearing property: it
is what lets a named edge (e.g. ``("w", +1, +1)``) refer to the **same physical
edge** before and after the alignment solver moves the cluster.

  * ``w`` — the bundle axial direction: the mean of every cluster helix's
    (end − start).  Signed by the helices' shared 5'→3' axis traversal, so it
    rotates with the cluster.
  * ``u`` — the cross-section direction of largest spread (PCA of the helix
    centres projected perpendicular to ``w``), sign-anchored to the helix with the
    largest perpendicular offset (an equivariant reference) so its sign tracks the
    cluster, not an arbitrary eigenvector sign.
  * ``v = w × u`` — completes a right-handed orthonormal frame.

We deliberately do NOT reuse ``deformation._initial_cross_section_frame`` (which
snaps ``u``/``v`` to world axes by the dominant tangent component): that frame is
world-aligned, not cluster-aligned, so it would *not* rotate with a posed cluster
and the edge keys would jump to different physical edges after a transform.

The edge-alignment solver
-------------------------
``align_edge_transform`` returns the ``(quaternion, translation, pivot)`` triple to
feed ``headless_build.transform_cluster`` so a chosen OBB edge of cluster M lands
on a target edge / world line.  Per the convention the user fixed (2026-06-17):

  * **minimal rotation, auto-flip** — rotate by the *smallest* angle that makes the
    edge directions collinear, choosing whichever of ±target_dir is nearer (so the
    rotation is ≤ 90°; no handedness is committed);
  * **midpoint snap** — translate so the src edge midpoint lands on the target
    midpoint (full endpoint coincidence when the edges are equal length);
  * **roll left free** — only the minimal single-axis rotation is applied; the
    remaining spin about the shared edge axis is not pinned.

The result is pinned by ``automation_harness.assert_edges_collinear`` (a
direction-AGNOSTIC oracle: the two edges share a line — parallel-or-antiparallel
direction AND on-line endpoints).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.deformation import deformed_helix_axes

# Axis order for the OBB frame rows and for naming edges/corners.
_AXES = ("u", "v", "w")

# Below this relative gap between the two in-plane PCA eigenvalues the cross-section
# is ~symmetric (e.g. a square bundle) and the u/v assignment is ambiguous — the
# frame would not be stably equivariant, so we refuse rather than silently mismatch.
_MIN_INPLANE_EIGEN_RATIO = 1.10


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("cannot normalise a ~zero vector")
    return v / n


@dataclass(frozen=True)
class OBB:
    """An oriented bounding box in the cluster's own ``(u, v, w)`` frame.

    ``axes`` rows are the orthonormal ``u, v, w`` directions (right-handed);
    ``half`` are the half-extents along each; ``center`` is the box centre.
    """

    center: np.ndarray  # (3,)
    axes: np.ndarray    # (3, 3) rows = u, v, w
    half: np.ndarray    # (3,) half-extents along u, v, w

    def corner(self, su: float, sv: float, sw: float) -> np.ndarray:
        """World position of the corner at the given ±1 signs along u, v, w."""
        s = np.array([su, sv, sw], dtype=float)
        return self.center + self.axes.T @ (s * self.half)

    def edge_endpoints(self, edge) -> tuple[np.ndarray, np.ndarray]:
        """Endpoints ``(p_lo, p_hi)`` of a named edge.

        ``edge`` is ``(axis, s1, s2)``: ``axis`` ∈ {'u','v','w'} is the direction the
        edge runs along; ``s1, s2`` ∈ {-1, +1} are the signs of the *other two* axes
        (in increasing index order, skipping ``axis``) that fix which of the 4 parallel
        edges this is.  ``p_lo``/``p_hi`` are the corners at the edge-axis sign −1/+1,
        so ``p_hi − p_lo`` points along ``+axis``.
        """
        axis, s1, s2 = edge
        if axis not in _AXES:
            raise ValueError(f"edge axis must be one of {_AXES}, got {axis!r}")
        if s1 not in (-1, 1) or s2 not in (-1, 1):
            raise ValueError(f"edge signs must be ±1, got ({s1}, {s2})")
        ai = _AXES.index(axis)
        others = [i for i in range(3) if i != ai]
        sgn = np.zeros(3)
        sgn[others[0]] = s1
        sgn[others[1]] = s2
        sgn[ai] = -1.0
        p_lo = self.center + self.axes.T @ (sgn * self.half)
        sgn[ai] = 1.0
        p_hi = self.center + self.axes.T @ (sgn * self.half)
        return p_lo, p_hi

    def edges(self) -> dict[tuple, tuple[np.ndarray, np.ndarray]]:
        """All 12 edges keyed by ``(axis, s1, s2)`` → ``(p_lo, p_hi)``."""
        out: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}
        for ai, axis in enumerate(_AXES):
            for s1 in (-1, 1):
                for s2 in (-1, 1):
                    out[(axis, s1, s2)] = self.edge_endpoints((axis, s1, s2))
        return out


def cluster_obb(design, cluster_id: str) -> OBB:
    """Build the OBB of ``cluster_id`` from its posed helix-axis geometry.

    Reads the cluster-posed axes via :func:`deformed_helix_axes` (so any existing
    pose is already baked in), builds the equivariant ``(u, v, w)`` frame, and fits
    a tight box around all the cluster helices' axis endpoints.

    Raises ``ValueError`` if the cluster is unknown, has < 2 helices with geometry,
    has a degenerate axial direction, or has a cross-section too symmetric to assign
    ``u``/``v`` stably (e.g. a square bundle) — failing loud beats a silently wrong,
    non-equivariant frame.
    """
    cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cluster is None:
        raise ValueError(f"no cluster {cluster_id!r} in design")
    # Sort helix ids so the point order is deterministic — the sign anchor below is a
    # *positional* pick (first id with a clear projection), which is tie-free and
    # equivariant; an argmax over symmetric extremes would let float rounding pick a
    # different corner after a rotation and silently flip the frame.
    helix_ids = sorted(set(cluster.helix_ids))
    axes_by_id = {a["helix_id"]: a for a in deformed_helix_axes(design)}

    starts, ends = [], []
    for hid in helix_ids:
        a = axes_by_id.get(hid)
        if a is None:
            continue
        starts.append(np.asarray(a["start"], dtype=float))
        ends.append(np.asarray(a["end"], dtype=float))
    if len(starts) < 2:
        raise ValueError(
            f"cluster {cluster_id!r} needs ≥2 helices with geometry to define an OBB "
            f"(found {len(starts)})"
        )
    starts = np.asarray(starts)
    ends = np.asarray(ends)

    # w — bundle axial direction (mean helix direction), equivariant + signed by traversal.
    w = (ends - starts).mean(axis=0)
    if float(np.linalg.norm(w)) < 1e-9:
        raise ValueError(
            f"cluster {cluster_id!r} has a degenerate axial direction (helices cancel out)"
        )
    w = _unit(w)

    # Cross-section spread from helix centres projected perpendicular to w.
    centres = (starts + ends) / 2.0
    offs = centres - centres.mean(axis=0)
    perp = offs - np.outer(offs @ w, w)

    cov = perp.T @ perp
    evals, evecs = np.linalg.eigh(cov)  # ascending; columns are eigenvectors
    # The two largest eigenvalues span the cross-section plane (the smallest ≈ along w).
    inplane = sorted(evals[1:])  # two largest, ascending
    big, small = inplane[1], inplane[0]
    if small <= 1e-9 or big / max(small, 1e-12) < _MIN_INPLANE_EIGEN_RATIO:
        raise ValueError(
            f"cluster {cluster_id!r} cross-section is too symmetric to assign u/v "
            f"stably (in-plane eigenvalue ratio "
            f"{big / max(small, 1e-12):.3f} < {_MIN_INPLANE_EIGEN_RATIO}); use a "
            "non-square cluster footprint, or this frame would not be equivariant."
        )

    u = evecs[:, int(np.argmax(evals))]  # eigenvector of the largest eigenvalue
    u = u - (u @ w) * w                  # strip any w component
    u = _unit(u)
    # Sign-anchor u *positionally*: the first cluster helix (in sorted-id order) whose
    # offset has a clear projection onto u sets the sign.  Per-helix |offset·u| is
    # invariant under a rigid pose, so the chosen helix and the resulting sign rotate
    # with the cluster (equivariant) — and being a positional pick, not a value-argmax,
    # it is immune to the corner-symmetry ties that would otherwise flip the frame.
    proj_u = np.abs(perp @ u)
    clear = proj_u > 0.5 * float(proj_u.max())
    ref = perp[int(np.argmax(clear))]  # first index where clear is True
    if float(u @ ref) < 0.0:
        u = -u
    v = _unit(np.cross(w, u))  # right-handed

    A = np.array([u, v, w])  # rows
    pts = np.vstack([starts, ends])
    proj = pts @ A.T  # coords in (u, v, w)
    lo = proj.min(axis=0)
    hi = proj.max(axis=0)
    half = (hi - lo) / 2.0
    centre_coords = (lo + hi) / 2.0
    center = A.T @ centre_coords
    return OBB(center=center, axes=A, half=half)


def _min_rotation(a, b) -> Rotation:
    """Smallest rotation taking unit vector ``a`` onto unit vector ``b``."""
    a = _unit(a)
    b = _unit(b)
    cross = np.cross(a, b)
    s = float(np.linalg.norm(cross))
    d = float(np.dot(a, b))
    if s < 1e-9:
        # Parallel (d > 0) → identity.  Antiparallel (d < 0) is avoided by the
        # caller's auto-flip, but be defensive: rotate 180° about any ⊥ axis.
        if d >= 0:
            return Rotation.identity()
        perp = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = _unit(np.cross(a, perp))
        return Rotation.from_rotvec(axis * math.pi)
    axis = cross / s
    angle = math.atan2(s, d)
    return Rotation.from_rotvec(axis * angle)


def align_edge_transform(
    design,
    cluster_id: str,
    src_edge,
    *,
    target_edge=None,
    target_line=None,
):
    """Rigid transform to bring ``cluster_id``'s ``src_edge`` onto a target.

    Returns ``(quaternion, translation, pivot)`` — quaternion ``[x, y, z, w]`` (the
    Three.js / scipy convention :class:`ClusterRigidTransform` stores), translation in
    nm, pivot the rotation centre — ready to feed
    :func:`backend.api.headless_build.transform_cluster`.

    Target is one of:
      * ``target_edge=(other_cluster_id, edge_key)`` — another cluster's OBB edge;
      * ``target_line=(point, direction)`` — an arbitrary world line.

    Convention (user-fixed 2026-06-17): **minimal rotation, auto-flip** (smallest
    angle onto ±target_dir, ≤ 90°), **midpoint snap** (src edge midpoint → target
    midpoint / the given point), **roll left free**.  Choosing ``pivot =
    src_midpoint`` makes ``translation = target_midpoint − src_midpoint`` exactly snap
    the midpoint while the rotation reorients the edge direction.
    """
    obb = cluster_obb(design, cluster_id)
    p_lo, p_hi = obb.edge_endpoints(src_edge)
    src_mid = (p_lo + p_hi) / 2.0
    src_dir = _unit(p_hi - p_lo)

    if target_edge is not None and target_line is not None:
        raise ValueError("pass exactly one of target_edge / target_line, not both")
    if target_edge is not None:
        other_id, edge_key = target_edge
        t_obb = cluster_obb(design, other_id)
        q_lo, q_hi = t_obb.edge_endpoints(edge_key)
        tgt_mid = (q_lo + q_hi) / 2.0
        tgt_dir = _unit(q_hi - q_lo)
    elif target_line is not None:
        point, direction = target_line
        tgt_mid = np.asarray(point, dtype=float)
        tgt_dir = _unit(direction)
    else:
        raise ValueError("pass target_edge or target_line")

    # Auto-flip: align to whichever of ±tgt_dir needs the smaller rotation.
    if float(src_dir @ tgt_dir) < 0.0:
        tgt_dir = -tgt_dir

    R = _min_rotation(src_dir, tgt_dir)
    quat = R.as_quat()  # [x, y, z, w]
    translation = tgt_mid - src_mid
    pivot = src_mid
    return quat.tolist(), translation.tolist(), pivot.tolist()

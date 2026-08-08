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

from backend.core.constants import HELIX_RADIUS
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
    axes: np.ndarray  # (3, 3) rows = u, v, w
    half: np.ndarray  # (3,) half-extents along u, v, w

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

    def face_normal(self, face) -> np.ndarray:
        """Outward unit normal of a named face ``(axis, sign)``.

        ``axis`` ∈ {'u','v','w'} picks the box axis the face is perpendicular to;
        ``sign`` ∈ {-1, +1} picks which of the two opposite faces.  The normal is
        ``sign · axes[axis]`` — equivariant (it rotates with the cluster).
        """
        axis, sign = face
        if axis not in _AXES:
            raise ValueError(f"face axis must be one of {_AXES}, got {axis!r}")
        if sign not in (-1, 1):
            raise ValueError(f"face sign must be ±1, got {sign}")
        return float(sign) * self.axes[_AXES.index(axis)]


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
    u = u - (u @ w) * w  # strip any w component
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
        perp = (
            np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        )
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


def hull_prism_axis(
    design, cluster_id: str, *, edge=None, corner=None, face=None, anchor="midpoint"
):
    """World-space revolute axis ``(origin, direction)`` for a named OBB feature.

    Turns a named feature of the cluster's hull-prism OBB into the
    ``(axis_origin, axis_direction)`` the ``/design/cluster/{id}/joint`` route expects
    (a revolute hinge is an axis *line*).  Two modes, mirroring the kinematic primitives
    (a revolute joint's anchor is an EDGE; a ball / point joint's is a CORNER):

      * ``edge=(axis, s1, s2)`` — the REVOLUTE primitive: the hinge runs **along** the
        named OBB edge.  ``direction`` = the edge line; ``origin`` depends on ``anchor``
        (below).  ``corner``/``face`` must be ``None``.  (The door-jamb principle from the
        AF-14 backlog: co-locating the axis with the OBB edge maximises range of motion.)
      * ``corner=(su, sv, sw)`` with ``face=(axis, sign)`` — the point / ball primitive:
        the hinge pivots **at** the named corner, swinging in the plane whose normal is
        the named face's outward normal.  ``origin`` = the corner, ``direction`` = the
        face normal.  The corner must lie on that face.

    ``anchor`` (edge mode only) picks the stored anchor point ON the edge line — it never
    changes the hinge *line*, only which point on it is recorded:

      * ``"midpoint"`` (default, backward-compatible) — the edge midpoint;
      * ``"corner"`` — a face CORNER (the edge's ``−axis`` endpoint).  The AF-14 Phase 3
        hinge-recommendation convention (user-fixed 2026-06-18): joints anchor at face
        corners, not edge midpoints.

    Direction-AGNOSTIC: an edge/corner names a line/point, never a swing *sense* — the
    +/− range-of-motion limit is AF-14 Phase 2, not here, so this introduces no
    DNA-directionality reasoning (the ASK-FIRST rule is untouched).  Reuses the
    equivariant :func:`cluster_obb`, so the world axis tracks the cluster under any pose.
    """
    obb = cluster_obb(design, cluster_id)

    if edge is not None:
        if corner is not None or face is not None:
            raise ValueError("edge mode takes neither corner nor face")
        if anchor not in ("midpoint", "corner"):
            raise ValueError(f"anchor must be 'midpoint' or 'corner', got {anchor!r}")
        p_lo, p_hi = obb.edge_endpoints(edge)
        direction = _unit(p_hi - p_lo)
        # "corner" stores the edge's −axis endpoint (a face corner); "midpoint" the
        # edge centre.  Either point lies on the same hinge line, so the revolute axis
        # is identical — only the recorded anchor moves.
        origin = p_lo if anchor == "corner" else (p_lo + p_hi) / 2.0
        return np.asarray(origin, dtype=float).tolist(), direction.tolist()

    if corner is not None:
        if face is None:
            raise ValueError(
                "corner mode requires a face=(axis, sign) to fix the hinge axis direction"
            )
        su, sv, sw = corner
        if any(s not in (-1, 1) for s in (su, sv, sw)):
            raise ValueError(f"corner signs must be ±1, got {corner}")
        f_axis, f_sign = face
        if f_axis not in _AXES:
            raise ValueError(f"face axis must be one of {_AXES}, got {f_axis!r}")
        if (su, sv, sw)[_AXES.index(f_axis)] != f_sign:
            raise ValueError(f"corner {corner} does not lie on face {face}")
        origin = obb.corner(su, sv, sw)
        direction = _unit(obb.face_normal(face))
        return origin.tolist(), direction.tolist()

    raise ValueError("pass exactly one of edge / corner")


# ── AF-14 Phase 2: swept-OBB range of motion (1-DOF revolute joint) ────────────
#
# A revolute joint lets the *anchored* cluster (the moving body) swing about a hinge
# line while the rest of the design stays put (the static frame).  The collision-free
# range of motion (ROM) is how far it can swing each way before its OBB runs into any
# other cluster's OBB.  Both bodies are oriented boxes, so the swept interference is an
# exact, cheap separating-axis test (SAT); we bisect the swing angle on first contact.
#
# Conventions (user-fixed 2026-06-17, the ASK-FIRST directionality decisions):
#   * the **anchored cluster swings**; every other cluster is a static obstacle;
#   * ROM is the **total two-sided free swing** (θ⁺ + θ⁻, each clamped to the joint's
#     angular limit) — a *magnitude*, direction-AGNOSTIC, so it needs no handedness
#     reasoning (the same discipline AF-6 used to stay clear of the ASK-FIRST rule);
#   * each OBB is **padded by the helix radius** so two bundles register contact
#     rim-to-rim (the box bounds the helix *axes*, not the ~1 nm-radius DNA surface).


def _obb_intersect(a: "OBB", b: "OBB", eps: float = 1e-9) -> bool:
    """True if two OBBs overlap, via the separating-axis theorem (Ericson, RTCD).

    Tests the 15 candidate separating axes (3 faces of each box + 9 edge-edge cross
    products); the boxes intersect iff none separates them.  ``eps`` cushions the
    cross-product axes against near-parallel edges (degenerate zero-length axis).
    """
    A, B = a.axes, b.axes  # rows = the box's own u, v, w directions
    ha, hb = a.half, b.half
    R = A @ B.T  # R[i, j] = A_i · B_j
    AbsR = np.abs(R) + eps
    t = b.center - a.center
    tA = A @ t  # translation in A's frame
    tB = B @ t  # translation in B's frame

    for i in range(3):  # A's three face axes
        rb = float(hb @ AbsR[i])
        if abs(tA[i]) > ha[i] + rb:
            return False
    for j in range(3):  # B's three face axes
        ra = float(ha @ AbsR[:, j])
        if abs(tB[j]) > ra + hb[j]:
            return False
    for i in range(3):  # the 9 edge-edge cross-product axes
        i1, i2 = (i + 1) % 3, (i + 2) % 3
        for j in range(3):
            j1, j2 = (j + 1) % 3, (j + 2) % 3
            ra = ha[i1] * AbsR[i2, j] + ha[i2] * AbsR[i1, j]
            rb = hb[j1] * AbsR[i, j2] + hb[j2] * AbsR[i, j1]
            tval = abs(tA[i2] * R[i1, j] - tA[i1] * R[i2, j])
            if tval > ra + rb:
                return False
    return True


def _padded(obb: "OBB", pad: float) -> "OBB":
    """Inflate an OBB's half-extents by ``pad`` (the DNA surface radius)."""
    if pad <= 0.0:
        return obb
    return OBB(center=obb.center, axes=obb.axes, half=obb.half + pad)


def _rotate_obb(obb: "OBB", rot: Rotation, axis_origin: np.ndarray) -> "OBB":
    """Rigidly rotate an OBB about a world axis through ``axis_origin``."""
    center = axis_origin + rot.apply(obb.center - axis_origin)
    axes = rot.apply(obb.axes)  # row-wise: each of u, v, w rotated
    return OBB(center=center, axes=axes, half=obb.half)


def _sweep_clearance(moving, obstacles, origin, axis_unit, limit_deg, sign, step_deg):
    """Free swing (degrees) in one rotational sense before first OBB contact.

    Scans ``θ`` from 0 to ``limit_deg`` in ``step_deg`` steps; on the first step that
    intersects an obstacle, bisects between the last-clear and first-contact angle for
    sub-step precision.  Returns ``limit_deg`` if nothing is hit (free to the joint's
    angular limit), or 0.0 if the body is already in contact at rest.
    """
    limit_deg = max(0.0, float(limit_deg))
    if not obstacles or limit_deg <= 0.0:
        return limit_deg

    def rotated(theta_deg):
        rot = Rotation.from_rotvec(axis_unit * math.radians(sign * theta_deg))
        return _rotate_obb(moving, rot, origin)

    if any(_obb_intersect(rotated(0.0), o) for o in obstacles):
        return 0.0

    prev = 0.0
    theta = 0.0
    while theta < limit_deg - 1e-12:
        theta = min(theta + step_deg, limit_deg)
        if any(_obb_intersect(rotated(theta), o) for o in obstacles):
            lo, hi = prev, theta
            for _ in range(40):  # ~1e-12° precision — far below tol
                mid = 0.5 * (lo + hi)
                if any(_obb_intersect(rotated(mid), o) for o in obstacles):
                    hi = mid
                else:
                    lo = mid
            return lo
        prev = theta
    return limit_deg


def obb_sweep_rom(
    moving: "OBB",
    obstacles,
    axis_origin,
    axis_direction,
    *,
    min_deg: float = -180.0,
    max_deg: float = 180.0,
    pad: float = 0.0,
    step_deg: float = 2.0,
) -> float:
    """Total two-sided collision-free swing of ``moving`` about a world axis.

    Pure geometry on OBBs (no ``design``): sweeps ``moving`` (padded by ``pad``) about
    the line ``(axis_origin, axis_direction)`` in both senses against the padded
    ``obstacles``, returning ``θ⁺ + θ⁻`` with ``θ⁺`` clamped to ``max_deg`` and ``θ⁻``
    to ``|min_deg|`` (the joint's angular limits).  Direction-AGNOSTIC magnitude.
    """
    origin = np.asarray(axis_origin, dtype=float)
    axis_unit = _unit(axis_direction)
    m = _padded(moving, pad)
    obs = [_padded(o, pad) for o in obstacles]
    plus = _sweep_clearance(m, obs, origin, axis_unit, max_deg, +1.0, step_deg)
    minus = _sweep_clearance(m, obs, origin, axis_unit, -min_deg, -1.0, step_deg)
    return plus + minus


def _obstacle_obbs(design, cluster_id):
    """OBBs of every cluster except ``cluster_id``; degenerate ones are skipped."""
    out = []
    for c in design.cluster_transforms:
        if c.id == cluster_id:
            continue
        try:
            out.append(cluster_obb(design, c.id))
        except ValueError:
            continue  # square/single-helix cluster has no stable OBB — can't bound it
    return out


def cluster_range_of_motion(
    design,
    cluster_id: str,
    axis,
    *,
    obstacles=None,
    min_angle_deg: float = -180.0,
    max_angle_deg: float = 180.0,
    pad: float = HELIX_RADIUS,
    step_deg: float = 2.0,
) -> float:
    """Collision-free range of motion (degrees) of ``cluster_id`` about ``axis``.

    ``axis`` is ``(origin, direction)`` — the world revolute line, as returned by
    :func:`hull_prism_axis`.  The anchored cluster is the moving body; ``obstacles``
    defaults to **every other cluster** in the design (each padded by the helix radius
    so contact is rim-to-rim).  Returns the total two-sided free swing, clamped to the
    joint's ``[min_angle_deg, max_angle_deg]`` limits (so a fully-clear joint reads
    ``max − min``, e.g. 360°).  Pass ``obstacles=`` an explicit list of cluster ids or
    :class:`OBB`s to override.
    """
    axis_origin, axis_direction = axis
    moving = cluster_obb(design, cluster_id)
    if obstacles is None:
        obstacle_obbs = _obstacle_obbs(design, cluster_id)
    else:
        obstacle_obbs = [
            o if isinstance(o, OBB) else cluster_obb(design, o) for o in obstacles
        ]
    return obb_sweep_rom(
        moving,
        obstacle_obbs,
        axis_origin,
        axis_direction,
        min_deg=min_angle_deg,
        max_deg=max_angle_deg,
        pad=pad,
        step_deg=step_deg,
    )


def grubler_mobility(
    n_links: int,
    *,
    revolute: int = 0,
    prismatic: int = 0,
    higher: int = 0,
) -> int:
    """Degrees of freedom (mobility) of a **planar** mechanism — Grübler / Kutzbach.

    ``M = 3·(n_links − 1) − 2·(lower pairs) − 1·(higher pairs)``, where ``n_links``
    counts every rigid link **including the ground/frame** (one of the bars is the
    fixed frame), revolute + prismatic joints are 1-DOF lower pairs (each removes 2
    planar DOF), and higher pairs (cam/gear contacts) remove 1.

    For the headless 4-bar parallelogram capstone: 4 links (4 bars, one grounded) +
    4 revolute joints → ``3·3 − 2·4 = 1`` (a 1-DOF mechanism).  Pure combinatorics —
    no geometry — so it is the rigorous kinematic DOF statement
    :func:`tests.automation_harness.assert_parallelogram_linkage` pairs with the
    geometric closure check.  Reusable for any planar linkage (the AF-12 linkage
    layer).
    """
    if n_links < 1:
        raise ValueError(f"n_links must be ≥ 1, got {n_links}")
    if min(revolute, prismatic, higher) < 0:
        raise ValueError("joint counts must be non-negative")
    return 3 * (n_links - 1) - 2 * (revolute + prismatic) - higher


def rank_joint_candidates(
    design,
    cluster_id: str,
    *,
    target_rom_deg=None,
    min_angle_deg: float = -180.0,
    max_angle_deg: float = 180.0,
    pad: float = HELIX_RADIUS,
    step_deg: float = 2.0,
):
    """Rank the cluster's 12 OBB edges as revolute hinges by range of motion.

    For each OBB edge, derives the hinge axis (:func:`hull_prism_axis`, edge mode) and
    computes its ROM against all other clusters, returning a list of
    ``{"edge", "axis_origin", "axis_direction", "rom_deg"}`` sorted by ``rom_deg``
    descending — the door-jamb principle made quantitative: an edge on the face *away*
    from a neighbour swings free, an edge that drives the bulk *into* it scores low.
    If ``target_rom_deg`` is given, only candidates meeting it are returned.

    (Edges are the revolute primitive; OBB *corners* are 3-DOF ball pivots — a single
    swing angle is ill-defined there — so they are deliberately not ranked here.)
    """
    obb = cluster_obb(design, cluster_id)
    obstacle_obbs = _obstacle_obbs(design, cluster_id)
    candidates = []
    for key in obb.edges():
        origin, direction = hull_prism_axis(design, cluster_id, edge=key)
        rom = obb_sweep_rom(
            obb,
            obstacle_obbs,
            origin,
            direction,
            min_deg=min_angle_deg,
            max_deg=max_angle_deg,
            pad=pad,
            step_deg=step_deg,
        )
        candidates.append(
            {
                "edge": key,
                "axis_origin": origin,
                "axis_direction": direction,
                "rom_deg": rom,
            }
        )
    candidates.sort(key=lambda c: c["rom_deg"], reverse=True)
    if target_rom_deg is not None:
        candidates = [c for c in candidates if c["rom_deg"] >= target_rom_deg]
    return candidates


def recommend_hinge_joints(
    design,
    cluster_id: str,
    *,
    anchor: str = "corner",
    axial_tol_deg: float = 20.0,
    target_rom_deg=None,
    min_angle_deg: float = -180.0,
    max_angle_deg: float = 180.0,
    pad: float = HELIX_RADIUS,
    step_deg: float = 2.0,
):
    """Recommend the most-likely revolute hinges for a cluster, ranked best-first.

    This is the AF-14 Phase 3 selector — it surfaces hinge candidates with the
    **user-fixed recommendation priority (2026-06-18, which takes precedence over the
    Phase-2 ROM-only sort in** :func:`rank_joint_candidates`**)**:

      1. **Hinge edge = the largest edge that is NOT parallel to the helical axis.**
         The OBB ``w`` axis IS the bundle/helical axis, so its 4 long edges are *axial*
         — hinging about them is a barrel-roll, not a fold — and are demoted below every
         cross-section (``u``/``v``) edge.  Among the cross-section edges the **longest**
         wins (for a 2×6 bar the wide ``u`` edge beats the narrow ``v`` edge).  ROM is
         only the secondary tiebreaker.
      2. **ROM is the secondary tiebreaker** (the Phase-2 door-jamb sort): among
         equal-length edges the one that swings freest against the other clusters ranks
         first.
      3. **Anchor at a face CORNER, not the edge midpoint** (``anchor="corner"``,
         default): the revolute axis *line* still runs along the chosen edge, but the
         stored ``axis_origin`` is an edge endpoint (a corner).  Pass
         ``anchor="midpoint"`` for the legacy edge-centre anchor.

    Returns ALL 12 OBB edges as dicts sorted best-first (axial edges demoted to the
    tail, still present so a caller can see them):
    ``{"edge", "edge_length", "angle_to_axis_deg", "is_axial", "rom_deg",
    "axis_origin", "axis_direction"}``.  ``axis_origin`` honours ``anchor``;
    ``axis_direction`` is the edge line either way.  ``target_rom_deg`` filters to
    candidates meeting that ROM.

    Direction-AGNOSTIC (edge length + angle-to-axis are magnitudes; ROM is the
    two-sided total) — it reuses the equivariant :func:`cluster_obb`, so introduces no
    new DNA-directionality reasoning (the ASK-FIRST rule is untouched).
    """
    if anchor not in ("midpoint", "corner"):
        raise ValueError(f"anchor must be 'midpoint' or 'corner', got {anchor!r}")
    obb = cluster_obb(design, cluster_id)
    w = obb.axes[_AXES.index("w")]
    obstacle_obbs = _obstacle_obbs(design, cluster_id)

    out = []
    for key in obb.edges():
        p_lo, p_hi = obb.edge_endpoints(key)
        edge_vec = p_hi - p_lo
        edge_len = float(np.linalg.norm(edge_vec))
        edge_dir = edge_vec / edge_len
        # Angle of the edge line to the helical (w) axis, 0–90° (line, not ray).
        angle_to_axis = math.degrees(math.acos(min(1.0, abs(float(edge_dir @ w)))))
        is_axial = angle_to_axis < axial_tol_deg
        # ROM is a property of the hinge LINE — measure it at the midpoint (anchor only
        # moves the stored point, not the line, so the swing is identical either way).
        rom = obb_sweep_rom(
            obb,
            obstacle_obbs,
            (p_lo + p_hi) / 2.0,
            edge_dir,
            min_deg=min_angle_deg,
            max_deg=max_angle_deg,
            pad=pad,
            step_deg=step_deg,
        )
        origin = p_lo if anchor == "corner" else (p_lo + p_hi) / 2.0
        out.append(
            {
                "edge": key,
                "edge_length": edge_len,
                "angle_to_axis_deg": angle_to_axis,
                "is_axial": is_axial,
                "rom_deg": rom,
                "axis_origin": np.asarray(origin, dtype=float).tolist(),
                "axis_direction": edge_dir.tolist(),
            }
        )

    # Priority: non-axial first, then longest edge, then freest swing (ROM).  Rounding the
    # length defeats float noise so the 4 parallel u-edges tie on length and ROM decides.
    out.sort(key=lambda c: (c["is_axial"], -round(c["edge_length"], 6), -c["rom_deg"]))
    if target_rom_deg is not None:
        out = [c for c in out if c["rom_deg"] >= target_rom_deg]
    return out

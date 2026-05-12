"""Relax-linker optimization.

Given an OverhangConnection, find joint angle(s) that bring the chord between
the two overhang anchors to the duplex's "fully bound" length so the connector
arcs vanish. Updates each joint's owning cluster_transform and appends one
ClusterOpLogEntry per moved cluster to feature_log.

v2 scope:
  • dsDNA only (ssDNA target length will require physics later).
  • 1-DOF: exactly one joint between the two overhang clusters (auto-pick).
  • N-DOF: caller passes joint_ids; multivariable optimization over angles.
  • Per-joint mechanical limits (`ClusterJoint.min_angle_deg` /
    `max_angle_deg`, defaults [-180°, +180°]) are honoured: the 1-DOF grid
    sweep + bracket refinement and the N-DOF Powell call are restricted to
    the joint's allowed θ window so the optimizer never lands on a global
    minimum the hinge cannot physically reach.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import ClusterOpLogEntry, Design


# ── Length unit helper (mirrors the frontend `linkerLengthToBases`) ──────────
def _linker_bp(conn) -> int:
    v = float(conn.length_value)
    if v <= 0:
        return 1
    if conn.length_unit == "nm":
        return max(1, round(v / BDNA_RISE_PER_BP))
    return max(1, round(v))


def _ds_target_length_nm(conn) -> float:
    """Distance between anchors at which both connector arcs collapse to zero
    length — equal to the duplex's visualLength in `_makeDsLinkerMeshes`."""
    return max(1, _linker_bp(conn) - 1) * BDNA_RISE_PER_BP


# ── Cluster ownership ────────────────────────────────────────────────────────
def _overhang_helix_id(design: Design, ovhg_id: str) -> str | None:
    """Return the helix the overhang's tagged domain lives on."""
    for s in design.strands:
        for d in s.domains:
            if d.overhang_id == ovhg_id:
                return d.helix_id
    return None


def _overhang_owning_cluster_id(design: Design, ovhg_id: str) -> str | None:
    """Cluster whose transform applies rigidly to the overhang's helix.

    A helix is "owned" by a cluster when:
      • cluster has no domain_ids (helix-level cluster), OR
      • every strand domain on the helix is listed in cluster.domain_ids — i.e.
        the helix is fully covered, no partial-overlap "bridge" semantics.

    When MULTIPLE clusters own the helix (common after caDNAno import: an
    auto-generated "all-scaffold" cluster spans every scaffold helix AND the
    user has finer-grained geometry sub-clusters that ALSO claim it), the
    SMALLEST cluster (by helix count) wins. The big convenience cluster is
    intended for "transform all scaffolds together" and should NOT shadow
    the smaller rigid sub-bodies that joints actually connect. Tiebreak:
    later position in cluster_transforms (user-defined clusters typically
    appear after auto-imported ones).

    A helix is a "bridge" only when SOME of its strand domains are in
    domain_ids and others aren't.
    """
    helix_id = _overhang_helix_id(design, ovhg_id)
    if helix_id is None:
        return None
    candidates: list[tuple[int, int, str]] = []  # (helix_count, neg_index_for_tiebreak, id)
    for idx, cluster in enumerate(design.cluster_transforms):
        if helix_id not in (cluster.helix_ids or []):
            continue
        if cluster.domain_ids:
            domain_keys = {(dr.strand_id, dr.domain_index) for dr in cluster.domain_ids}
            any_unmatched = False
            for s in design.strands:
                for di, dom in enumerate(s.domains):
                    if dom.helix_id != helix_id:
                        continue
                    if (s.id, di) not in domain_keys:
                        any_unmatched = True
                        break
                if any_unmatched:
                    break
            if any_unmatched:
                continue
        # Smallest helix_count first; tiebreak by later index (negative so smaller sorts first).
        candidates.append((len(cluster.helix_ids or []), -idx, cluster.id))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


# ── DOF topology ─────────────────────────────────────────────────────────────
def dof_topology(design: Design, conn) -> dict[str, Any]:
    """Describe the joint topology between the two overhangs.

    Returns:
      {
        cluster_a, cluster_b: cluster ids (or None),
        joints_a, joints_b:  ClusterJoint ids whose `cluster_id` matches each side,
        n_dof:               len(joints_a) + len(joints_b) — except 0 when the
                             two overhangs share a cluster (no axis separates them),
        status:              'ok'|'no_joints'|'shared_cluster'|'multi_dof'|'no_cluster',
        reason:              short user-readable string for display,
      }
    """
    ca = _overhang_owning_cluster_id(design, conn.overhang_a_id)
    cb = _overhang_owning_cluster_id(design, conn.overhang_b_id)
    if ca is None and cb is None:
        return _topology_dict(ca, cb, [], [], 0, "no_cluster",
                              "Neither overhang's helix is in a cluster.")
    if ca == cb and ca is not None:
        return _topology_dict(ca, cb, [], [], 0, "shared_cluster",
                              "Both overhangs are on the same cluster — no joint separates them.")
    joints_a = [j.id for j in design.cluster_joints if ca is not None and j.cluster_id == ca]
    joints_b = [j.id for j in design.cluster_joints if cb is not None and j.cluster_id == cb]
    n = len(joints_a) + len(joints_b)
    if n == 0:
        return _topology_dict(ca, cb, joints_a, joints_b, 0, "no_joints",
                              "No joints on either overhang's cluster.")
    if n == 1:
        return _topology_dict(ca, cb, joints_a, joints_b, 1, "ok", "")
    return _topology_dict(ca, cb, joints_a, joints_b, n, "multi_dof",
                          f"Relax requires exactly 1 DOF; this linker has {n}.")


def _topology_dict(ca, cb, ja, jb, n, status, reason):
    return {
        "cluster_a": ca, "cluster_b": cb,
        "joints_a": ja, "joints_b": jb,
        "n_dof": n, "status": status, "reason": reason,
    }


# ── Quaternion helpers (avoid scipy.spatial.transform dep) ──────────────────
def _quat_axis_angle(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    """[qx, qy, qz, qw] for rotation by *angle_rad* around unit *axis*."""
    half = 0.5 * angle_rad
    s = np.sin(half)
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, np.cos(half)])


def _quat_mul(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """Hamilton product q1 ⊗ q2 with [x,y,z,w] convention."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])


def _rot_axis_angle(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    """Rodrigues 3×3 rotation matrix around unit *axis*."""
    a = axis / max(1e-12, np.linalg.norm(axis))
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle_rad) * K + (1 - np.cos(angle_rad)) * (K @ K)


# ── Optimization ─────────────────────────────────────────────────────────────
def _moving_anchor_at(theta: float, base_anchor: np.ndarray,
                       axis_origin: np.ndarray, axis_dir: np.ndarray) -> np.ndarray:
    """Where the moving anchor lands when its cluster is rotated by *theta*
    around (axis_origin, axis_dir). The base_anchor is the anchor's CURRENT
    world position (already includes any prior cluster transform); we pivot
    it by `theta` around the joint axis."""
    R = _rot_axis_angle(axis_dir, theta)
    return R @ (base_anchor - axis_origin) + axis_origin


# Constants — must match the bridge geometry emitted by `_emit_bridge_nucs`
# in backend/api/crud.py so the relax loss minimizes the same gap that the
# renderer shows the user.
_BDNA_TWIST_RAD   = 34.3 * np.pi / 180.0
_MINOR_GROOVE_RAD = 150.0 * np.pi / 180.0
_HELIX_RADIUS_NM  = 1.0
# Target = 0: the bridge boundary bead must land EXACTLY on its anchor
# (= complement nuc at OH-attach-bp). Boundary is at native B-DNA radius
# (HELIX_RADIUS_NM); the bridge axis is offset off the chord so the
# boundary bead lands on the anchor when chord matches the "perfect" 3D
# vector fz·visualLength + (radial_b − radial_a)·R.
_ARC_TARGET_NM = 0.0

# Phase offset added to every bridge radial angle. 0 puts the bridge axis
# on one side of the chord (boundary bead at +radial·R from axis ends up
# at anchor − (radial_b−radial_a)/2·R post-relax); π flips the bridge to
# the OPPOSITE side of the chord, reversing the anchor↔bridge gap vector
# while preserving its magnitude and the duplex's internal geometry. Must
# be applied IDENTICALLY in `_bridge_boundary_radials` (here) and in
# `_emit_bridge_nucs` (crud.py) — they would otherwise disagree.
_BRIDGE_PHASE_OFFSET = np.pi

# Tiebreaker between equivalent global minima. The chord-magnitude loss
# `|visualLength − |chord||²` is genuinely flat between any two θ values
# that put the cluster at the right separation — for a typical hinge
# joint there are two such θ per period, often 100°+ apart, and only
# one of them avoids clashing with neighbouring geometry. Adding a
# small λ·θ² penalty makes the optimizer prefer the θ closest to 0
# (= the smallest cluster rotation from the user's current pose).
#
# Sizing: chord errors are O(nm²) for typical pre-relax geometry (1–40),
# θ² is O(rad²) ≤ π². With λ = 1e-3, the regularizer contributes ≤ 1e-2
# nm²-equivalent — three orders below typical chord error, so it never
# distorts the global chord fit, but it cleanly breaks ties when two
# minima both bottom out near zero residual.
_THETA_REG_LAMBDA = 1e-3


def _comp_first(ovhg_id: str, attach: str) -> bool:
    """Mirror of `backend.core.lattice._is_comp_first` — kept here as a
    micro-helper to avoid the lattice → linker_relax import direction.

    comp-first iff (5p + free_end) OR (3p + root)."""
    is_5p = ovhg_id.endswith("_5p")
    is_3p = ovhg_id.endswith("_3p")
    if is_5p and attach == "free_end": return True
    if is_3p and attach == "root":     return True
    if is_5p and attach == "root":     return False
    if is_3p and attach == "free_end": return False
    return True   # untagged synthetic fixtures — legacy behaviour


def _bridge_boundary_radials(fx: np.ndarray, fy: np.ndarray, base_count: int,
                             comp_first_a: bool, comp_first_b: bool
                             ) -> tuple[np.ndarray, np.ndarray]:
    """Unit radial directions at the two bridge boundary beads:
       side A's strand at bp 0, side B's strand at bp L−1.

    Bridge direction per side (mirrors `_make_bridge_domain` in
    backend/core/lattice.py):
      side a: comp_first → FORWARD; bridge_first → REVERSE
      side b: comp_first → REVERSE; bridge_first → FORWARD

    FORWARD bp i  → angle = i·twist
    REVERSE bp i  → angle = i·twist + minor_groove
    """
    # side A boundary at bp 0
    ang_a = (0.0 if comp_first_a else _MINOR_GROOVE_RAD) + _BRIDGE_PHASE_OFFSET
    radial_a = fx * np.cos(ang_a) + fy * np.sin(ang_a)
    # side B boundary at bp L−1
    base = (base_count - 1) * _BDNA_TWIST_RAD
    ang_b = ((base + _MINOR_GROOVE_RAD) if comp_first_b else base) + _BRIDGE_PHASE_OFFSET
    radial_b = fx * np.cos(ang_b) + fy * np.sin(ang_b)
    return radial_a, radial_b


def bridge_axis_geometry(p_a: np.ndarray, n_a: np.ndarray | None,
                         p_b: np.ndarray, base_count: int,
                         comp_first_a: bool, comp_first_b: bool
                         ) -> dict:
    """Compute bridge axis + boundary radials for a ds linker.

    Symmetric placement: axis_start chosen so that side-A and side-B
    boundary residuals are equal in magnitude (and opposite in sign), so
    the relax loss drives both gaps to zero together.

    Used by both the geometry emitter (`_emit_bridge_nucs`) and the relax
    loss (`_arc_chord_lengths`) so they stay in lockstep.
    """
    chord = p_b - p_a
    cl = float(np.linalg.norm(chord))
    axis_dir = chord / cl if cl > 1e-9 else np.array([0.0, 0.0, 1.0])
    fx, fy, fz = _frame_from_axis(axis_dir, n_a)
    visual_length = max(base_count - 1, 1) * BDNA_RISE_PER_BP
    radial_a, radial_b = _bridge_boundary_radials(fx, fy, base_count,
                                                  comp_first_a, comp_first_b)
    R = _HELIX_RADIUS_NM
    axis_start = (p_a + p_b) / 2 - (radial_a + radial_b) / 2 * R - fz * (visual_length / 2)
    axis_end   = axis_start + fz * visual_length
    return {
        "fx": fx, "fy": fy, "fz": fz,
        "axis_start": axis_start, "axis_end": axis_end,
        "radial_a_boundary": radial_a, "radial_b_boundary": radial_b,
        "visual_length": visual_length, "helix_radius": R,
    }


def _frame_from_axis(axis_dir: np.ndarray, preferred_normal: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build an orthonormal frame (fx, fy, fz) around *axis_dir*.

    Mirrors the JS `_frameFromAxis` so backend-computed aStart/bStart match
    the renderer's bead positions exactly. preferred_normal seeds fx (used
    for sliding the linker tube around its axis); falls back to a canonical
    axis if not provided or degenerate."""
    n = float(np.linalg.norm(axis_dir))
    z = axis_dir / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])
    x = preferred_normal.astype(float) if preferred_normal is not None else np.array([0.0, 0.0, 1.0])
    x = x - z * float(np.dot(x, z))
    if float(np.dot(x, x)) < 1e-6:
        x = np.array([0.0, 0.0, 1.0]) if abs(z[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        x = x - z * float(np.dot(x, z))
    x = x / float(np.linalg.norm(x))
    y = np.cross(z, x)
    y = y / float(np.linalg.norm(y))
    return x, y, z


def _arc_chord_lengths(p_a: np.ndarray, n_a: np.ndarray | None,
                        p_b: np.ndarray, base_count: int,
                        comp_first_a: bool, comp_first_b: bool) -> tuple[float, float]:
    """Half-residuals driving the relax — each equals |visualLength − |chord||/2.

    Why this form (not the full anchor-to-bridge-boundary distance):
    The bridge boundary radials are PERPENDICULAR to the chord, so
    folding their offset (radial_a − radial_b)·R into the loss creates a
    degenerate minimum at chord ≈ 0 (the "fz fallback" frame at
    chord = 0 happens to make the perp term cancel a chunk of the chord
    term). The only physically meaningful constraint is that the bridge
    duplex span its native length: |chord| → visualLength. The small
    perpendicular offset between anchor and bridge boundary (≤ 1 nm)
    is then absorbed by the connector arc visualisation; the renderer's
    symmetric `bridge_axis_geometry` still positions the bridge so the
    arcs are visibly small post-relax.

    `comp_first_a` / `comp_first_b` are accepted for API symmetry with
    the geometry helper but aren't used in this scalar-magnitude form.
    """
    del n_a, comp_first_a, comp_first_b
    visual_length = max(base_count - 1, 1) * BDNA_RISE_PER_BP
    chord_mag = float(np.linalg.norm(p_b - p_a))
    half_residual = abs(visual_length - chord_mag) * 0.5
    return half_residual, half_residual


def _optimize_angle(moving_anchor: np.ndarray, moving_normal: np.ndarray | None,
                    fixed_anchor: np.ndarray, fixed_normal: np.ndarray | None,
                    moving_is_a: bool,
                    axis_origin: np.ndarray, axis_dir: np.ndarray,
                    base_count: int,
                    comp_first_a: bool, comp_first_b: bool,
                    theta_min: float = -np.pi,
                    theta_max: float = +np.pi) -> float:
    """Brent-bounded search for θ ∈ [theta_min, theta_max] minimizing the
    sum-of-squares boundary-gap residuals (gap_A)² + (gap_B)² (target = 0).

    *theta_min* / *theta_max* (radians) come from the joint's mechanical
    limits (`ClusterJoint.min_angle_deg` / `max_angle_deg`). Both the
    coarse grid sweep and the per-bracket Brent refinement are clipped to
    this window, so the returned θ is always physically reachable.

    The moving anchor's base_normal also rotates with the cluster, so the
    frame's preferred-normal seed is rotated too — otherwise the linker
    tube would shift its rotational alignment in a way the renderer doesn't.
    """
    def chord_loss(theta: float) -> float:
        """Pure chord-magnitude loss (NO θ regularizer) — used inside each
        local-minimum bracket so refinement converges on the actual chord
        minimum, not a regularizer-shifted point."""
        R = _rot_axis_angle(axis_dir, theta)
        p_moving = R @ (moving_anchor - axis_origin) + axis_origin
        n_moving = R @ moving_normal if moving_normal is not None else None
        if moving_is_a:
            p_a, n_a, p_b = p_moving, n_moving, fixed_anchor
        else:
            p_a, n_a, p_b = fixed_anchor, fixed_normal, p_moving
        chord_a, chord_b = _arc_chord_lengths(p_a, n_a, p_b, base_count,
                                              comp_first_a, comp_first_b)
        return (chord_a - _ARC_TARGET_NM) ** 2 + (chord_b - _ARC_TARGET_NM) ** 2

    # Periodic, multimodal: a 1-DOF cluster rotation can put chord at the
    # target visualLength at TWO θ values per period (chord descends through
    # target on one side, ascends through it on the other). One of them
    # often clashes with neighbouring geometry. Find ALL local minima on a
    # coarse grid (restricted to the joint's mechanical range), refine
    # each, then prefer the one with the smallest |θ| among those that
    # achieve near-zero chord residual.
    #
    # When the range collapses to a point (min == max), no optimization is
    # possible; return the only allowed θ. The caller should not normally
    # request this, but it keeps the math well-defined.
    if theta_max <= theta_min + 1e-9:
        return float(0.5 * (theta_min + theta_max))
    # Sample at 5° resolution within the allowed window; always include the
    # window endpoints so the boundary loss is considered alongside
    # interior local minima.
    step = (5.0 * np.pi / 180.0)
    n_grid = max(3, int(np.ceil((theta_max - theta_min) / step)) + 1)
    grid = np.linspace(theta_min, theta_max, n_grid)
    losses = [chord_loss(t) for t in grid]
    # Local minimum = strictly lower than both neighbours (interior). At
    # the window endpoints, a minimum is the boundary itself if its only
    # interior neighbour is strictly higher. Unlike the previous unbounded
    # implementation, the window does NOT wrap — clamping to mechanical
    # limits intentionally cuts the periodic search.
    candidate_idxs: list[int] = []
    n = len(grid)
    for i in range(n):
        if i == 0:
            if n > 1 and losses[i] < losses[i + 1]:
                candidate_idxs.append(i)
        elif i == n - 1:
            if losses[i] < losses[i - 1]:
                candidate_idxs.append(i)
        else:
            if losses[i] < losses[i - 1] and losses[i] < losses[i + 1]:
                candidate_idxs.append(i)
    if not candidate_idxs:                  # flat/degenerate — fall back
        candidate_idxs = [int(np.argmin(losses))]

    # Refine each candidate in a small bracket around it, clipped to the
    # window so we never sample disallowed θ.
    refined: list[tuple[float, float]] = []  # (theta, chord_loss)
    for i in candidate_idxs:
        lo = grid[max(0, i - 2)]
        hi = grid[min(n - 1, i + 2)]
        if hi <= lo + 1e-9:
            refined.append((float(grid[i]), float(losses[i])))
            continue
        res = minimize_scalar(chord_loss, bounds=(lo, hi), method="bounded",
                              options={"xatol": 1e-5})
        refined.append((float(res.x), float(res.fun)))

    # Among the refined minima, keep those whose chord residual is within
    # a small tolerance of the best-found minimum. Then break ties by |θ|.
    best_chord = min(c for _, c in refined)
    tol = 1e-6                              # nm² — generous; both real minima sit at ~0
    near_best = [(t, c) for t, c in refined if c <= best_chord + tol]
    near_best.sort(key=lambda tc: abs(tc[0]))
    return near_best[0][0]


# ── Cluster transform composition ────────────────────────────────────────────
def _composed_transform(cluster, axis_origin: np.ndarray, axis_dir: np.ndarray,
                        theta: float) -> tuple[list[float], list[float]]:
    """Return (rotation_quat, translation) for the cluster after composing an
    additional rotation by *theta* around (axis_origin, axis_dir).

    Pivot is unchanged. Derivation:
      Existing transform: p' = R(p − pivot) + pivot + t
      Joint rotation:     p'' = R_j(p' − O) + O
      ⇒ p'' = (R_j R)(p − pivot) + R_j(pivot + t − O) + O
           = R_new (p − pivot) + pivot + t_new
      where R_new = R_j R, t_new = R_j(pivot + t − O) + O − pivot.
    """
    pivot = np.asarray(cluster.pivot, dtype=float)
    trans = np.asarray(cluster.translation, dtype=float)
    q_existing = np.asarray(cluster.rotation, dtype=float)
    q_joint = _quat_axis_angle(axis_dir, theta)
    q_new = _quat_mul(q_joint, q_existing)
    R_j = _rot_axis_angle(axis_dir, theta)
    t_new = R_j @ (pivot + trans - axis_origin) + axis_origin - pivot
    return q_new.tolist(), t_new.tolist()


# ── Public entry point ───────────────────────────────────────────────────────
def relax_linker(
    design: Design, conn, joint_ids: list[str] | None = None,
) -> tuple[Design, dict[str, Any]]:
    """Apply the relax operation to *design* for *conn*.

    joint_ids:
      None       — auto-pick: requires the 1-DOF case (uses dof_topology).
      [single]   — same single-axis path as 1-DOF.
      [j1, j2…]  — multi-DOF: optimize all angles jointly so the chord lands
                   on the duplex target length. Each joint rotates ITS OWN
                   cluster (joint.cluster_id) around its axis.

    Returns (updated_design, info_dict). info_dict carries per-joint angles,
    final chord length, and target length, for logging / debug.
    """
    topo = dof_topology(design, conn)

    if joint_ids is None:
        if topo["status"] != "ok" or topo["n_dof"] != 1:
            raise ValueError(f"relax_linker: not a 1-DOF case ({topo['status']})")
        # Auto-pick the single joint.
        joint_ids = topo["joints_a"] or topo["joints_b"]

    if not joint_ids:
        raise ValueError("relax_linker: no joints to relax over.")

    # Resolve joint records and validate axes.
    # Joint storage is cluster-local; compose with the cluster's transform
    # to get the world-space axis used by the relaxation kinematics.
    from backend.core.models import _local_to_world_joint
    joints_by_id = {j.id: j for j in design.cluster_joints}
    cts_by_id    = {c.id: c for c in design.cluster_transforms}
    # Per-joint tuple: (joint_id, origin, axis, cluster_id, theta_min, theta_max)
    # Bounds are converted from the joint's stored degrees to radians here so
    # downstream optimizer code stays in radians end-to-end.
    selected: list[tuple[str, np.ndarray, np.ndarray, str, float, float]] = []
    for jid in joint_ids:
        j = joints_by_id.get(jid)
        if j is None:
            raise ValueError(f"relax_linker: joint id {jid!r} not found.")
        ct = cts_by_id.get(j.cluster_id)
        world_origin, world_dir = _local_to_world_joint(
            j.local_axis_origin, j.local_axis_direction, ct,
        )
        axis = np.asarray(world_dir, dtype=float)
        n = np.linalg.norm(axis)
        if n < 1e-9:
            raise ValueError(f"relax_linker: joint {jid!r} axis_direction is degenerate.")
        theta_min = float(j.min_angle_deg) * np.pi / 180.0
        theta_max = float(j.max_angle_deg) * np.pi / 180.0
        selected.append((j.id, np.asarray(world_origin, dtype=float), axis / n,
                         j.cluster_id, theta_min, theta_max))

    # Resolve anchor positions + base_normals in the live geometry frame
    # (cluster transforms already applied).
    from backend.api.crud import _geometry_for_design   # local import to avoid cycles
    nucs = _geometry_for_design(design)
    anchor_a, normal_a = _anchor_pos_and_normal(nucs, conn, conn.overhang_a_id, True)
    anchor_b, normal_b = _anchor_pos_and_normal(nucs, conn, conn.overhang_b_id, False)
    if anchor_a is None or anchor_b is None:
        raise ValueError("relax_linker: could not resolve anchor positions from geometry.")

    # Map anchor → cluster ownership so we know whether each joint rotates
    # anchor_a, anchor_b, both, or neither.
    cluster_of_a = topo["cluster_a"]
    cluster_of_b = topo["cluster_b"]
    base_count = _linker_bp(conn)
    cfa = _comp_first(conn.overhang_a_id, conn.overhang_a_attach)
    cfb = _comp_first(conn.overhang_b_id, conn.overhang_b_attach)

    def _apply(thetas: np.ndarray,
               p_a: np.ndarray, n_a: np.ndarray | None,
               p_b: np.ndarray, n_b: np.ndarray | None):
        """Apply the proposed joint angles to both anchor positions AND their
        base_normals (directions rotate too — needed for the linker frame).
        Each joint rotates only the side whose cluster matches its cluster_id."""
        for (_jid, origin, axis, cluster_id, _tmin, _tmax), theta in zip(selected, thetas):
            R = _rot_axis_angle(axis, theta)
            if cluster_id == cluster_of_a:
                p_a = R @ (p_a - origin) + origin
                if n_a is not None: n_a = R @ n_a
            if cluster_id == cluster_of_b:
                p_b = R @ (p_b - origin) + origin
                if n_b is not None: n_b = R @ n_b
        return p_a, n_a, p_b, n_b

    # ── Optimize ─────────────────────────────────────────────────────────────
    # Loss: sum-of-squares arc-chord residuals around _ARC_TARGET_NM (0.67 nm).
    # The two connector arcs (posA→aStart, posB→bStart) should both read like
    # standard backbone-to-backbone bonds at the target length.
    if len(selected) == 1:
        _jid, origin, axis, cluster_id, theta_min, theta_max = selected[0]
        moving_is_a = (cluster_id == cluster_of_a)
        moving_anchor = anchor_a if moving_is_a else anchor_b
        moving_normal = normal_a if moving_is_a else normal_b
        fixed_anchor  = anchor_b if moving_is_a else anchor_a
        fixed_normal  = normal_b if moving_is_a else normal_a
        theta = _optimize_angle(moving_anchor, moving_normal,
                                fixed_anchor, fixed_normal,
                                moving_is_a, origin, axis, base_count,
                                cfa, cfb,
                                theta_min=theta_min, theta_max=theta_max)
        thetas = np.array([theta])
    else:
        def loss(thetas: np.ndarray) -> float:
            p_a, n_a, p_b, _n_b = _apply(thetas, anchor_a.copy(),
                                          normal_a.copy() if normal_a is not None else None,
                                          anchor_b.copy(),
                                          normal_b.copy() if normal_b is not None else None)
            chord_a, chord_b = _arc_chord_lengths(p_a, n_a, p_b, base_count, cfa, cfb)
            return ((chord_a - _ARC_TARGET_NM) ** 2 + (chord_b - _ARC_TARGET_NM) ** 2
                    + _THETA_REG_LAMBDA * float(np.sum(thetas * thetas)))
        # Per-joint bounds from the joint records — Powell honours bounds
        # in scipy ≥ 1.5 and clips x to lie inside them. The seed is
        # clipped explicitly so it starts inside the feasible region (a
        # legacy joint with bounds excluding 0 would otherwise begin out
        # of bounds).
        bounds = [(tmin, tmax) for (*_rest, tmin, tmax) in selected]
        x0 = np.array([min(max(0.0, tmin), tmax) for (tmin, tmax) in bounds],
                      dtype=float)
        res = minimize(loss, x0, method="Powell", bounds=bounds,
                       options={"xtol": 1e-5, "ftol": 1e-8, "maxiter": 500})
        thetas = np.asarray(res.x, dtype=float)
        # Powell can drift epsilon-outside bounds in some scipy versions;
        # clip defensively so downstream cluster transforms never carry an
        # out-of-range angle.
        for i, (tmin, tmax) in enumerate(bounds):
            thetas[i] = float(min(max(thetas[i], tmin), tmax))

    final_a, final_n_a, final_b, _final_n_b = _apply(
        thetas, anchor_a.copy(),
        normal_a.copy() if normal_a is not None else None,
        anchor_b.copy(),
        normal_b.copy() if normal_b is not None else None,
    )
    final_arc_a, final_arc_b = _arc_chord_lengths(final_a, final_n_a, final_b, base_count, cfa, cfb)
    final_chord = float(np.linalg.norm(final_a - final_b))

    # Apply each joint's rotation to its owning cluster transform. Multiple
    # joints can share a cluster (rare but supported); compose them in order.
    cluster_updates: dict[str, tuple[list[float], list[float]]] = {}   # cluster_id → (rot, trans)
    for (_jid, origin, axis, cluster_id, _tmin, _tmax), theta in zip(selected, thetas):
        cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
        if cluster is None:
            continue
        # Use the latest pending update if this cluster has already been touched;
        # otherwise start from the cluster's stored transform.
        if cluster_id in cluster_updates:
            q_prev, t_prev = cluster_updates[cluster_id]
            staged = cluster.model_copy(update={"rotation": q_prev, "translation": t_prev})
        else:
            staged = cluster
        cluster_updates[cluster_id] = _composed_transform(staged, origin, axis, float(theta))

    new_clusters = []
    for c in design.cluster_transforms:
        if c.id in cluster_updates:
            q_new, t_new = cluster_updates[c.id]
            new_clusters.append(c.model_copy(update={"rotation": q_new, "translation": t_new}))
        else:
            new_clusters.append(c)

    # Append one ClusterOpLogEntry per touched cluster. Truncate any redo tail.
    log = list(design.feature_log)
    if design.feature_log_cursor == -2:
        log = []
    elif design.feature_log_cursor >= 0:
        log = log[:design.feature_log_cursor + 1]
    for c in new_clusters:
        if c.id in cluster_updates:
            log.append(ClusterOpLogEntry(
                cluster_id=c.id,
                translation=list(c.translation),
                rotation=list(c.rotation),
                pivot=list(c.pivot),
                source="relax",
            ))

    updated = design.copy_with(
        cluster_transforms=new_clusters,
        feature_log=log,
        feature_log_cursor=-1,
    )
    return updated, {
        "joint_ids": [jid for (jid, *_rest) in selected],
        "thetas_rad": [float(t) for t in thetas],
        "moved_cluster_ids": list(cluster_updates.keys()),
        "final_chord_nm": final_chord,
        "final_arc_a_nm": final_arc_a,
        "final_arc_b_nm": final_arc_b,
        "target_arc_nm": _ARC_TARGET_NM,
    }


# ── Anchor lookup (mirrors frontend `_linkerAttachAnchor`) ────────────────────
def _is_a_side(conn, ovhg_id: str) -> bool:
    return ovhg_id == conn.overhang_a_id


def _oh_attach_nuc(oh_nucs: list[dict], attach: str) -> dict | None:
    """OH nucleotide at the user-chosen attach end:
       free_end → the strand-terminal (5'/3' marked) nuc  (= OH's free tip)
       root     → the OH nuc farthest in bp from the tip  (= OH's bonded end)

    Returns None when the OH has no nucs in geometry yet."""
    if not oh_nucs:
        return None
    tip = next((n for n in oh_nucs if n.get("is_five_prime") or n.get("is_three_prime")), oh_nucs[0])
    if attach != "root" or len(oh_nucs) < 2:
        return tip
    tip_bp = tip.get("bp_index") or 0
    return max(oh_nucs, key=lambda n: abs((n.get("bp_index") or 0) - tip_bp))


def _anchor_pos_and_normal(nucs: list[dict], conn, ovhg_id: str, is_a_side: bool):
    """Returns (pos, base_normal) for the linker anchor on this side:
       the COMPLEMENT nuc on the OH's helix at the OH's `attach`-end bp.

    Per the user-facing rule:
       attach=root     → bridge bonds at OH crossover bp = OH-bonded-end bp
       attach=free_end → bridge bonds at OPPOSITE end       = OH-free-tip bp

    In both cases the complement nuc to anchor against is the antiparallel
    partner sitting at the SAME helix and SAME bp as the OH's attach-end
    nuc. (Direct lookup, not a "farthest from tip" heuristic.)

    Strand-id source by linker type:
      ds → per-side ``__lnk__<conn>__a`` / ``__b``.
      ss → single bridge strand ``__lnk__<conn>__s`` (carries both
            complements on real OH helices + the bridge nucs on the
            virtual helix; the helix-id filter below drops the bridge nucs).
    """
    side   = "a" if is_a_side else "b"
    attach = conn.overhang_a_attach if is_a_side else conn.overhang_b_attach
    if getattr(conn, "linker_type", "ds") == "ss":
        candidate_strand_ids = [f"__lnk__{conn.id}__s"]
    else:
        candidate_strand_ids = [f"__lnk__{conn.id}__{side}"]
    linker_nucs = [n for n in nucs
                   if n.get("strand_id") in candidate_strand_ids
                   and not (n.get("helix_id") or "").startswith("__lnk__")]
    oh_nucs = [n for n in nucs if n.get("overhang_id") == ovhg_id]
    attach_nuc = _oh_attach_nuc(oh_nucs, attach)

    chosen = None
    if linker_nucs and attach_nuc is not None:
        target_helix = attach_nuc.get("helix_id")
        target_bp    = attach_nuc.get("bp_index")
        chosen = next((n for n in linker_nucs
                       if n.get("helix_id") == target_helix
                       and n.get("bp_index") == target_bp), None)

    if chosen is None:
        # Fallback for synthetic fixtures: attach to the OH attach-end nuc
        # itself (OH backbone, not complement) — keeps the anchor on the
        # right structural end even when complement geometry is missing.
        chosen = attach_nuc
    if chosen is None:
        return None, None

    pos = chosen.get("backbone_position") or chosen.get("base_position")
    bn  = chosen.get("base_normal")
    return (np.asarray(pos, dtype=float) if pos is not None else None,
            np.asarray(bn,  dtype=float) if bn  is not None else None)


def _anchor_position(nucs, conn, ovhg_id, is_a_side):
    """Backwards-compatible wrapper — returns position only."""
    pos, _bn = _anchor_pos_and_normal(nucs, conn, ovhg_id, is_a_side)
    return pos


# ── ssDNA bridge relax ───────────────────────────────────────────────────────
def _ss_target_chord_nm(conn, bin_index: int = 0) -> float:
    """Target chord magnitude for an ss-linker relax (chosen bin's R_ee)."""
    from backend.core import ssdna_fjc
    return float(ssdna_fjc.bin_r_ee(_linker_bp(conn), bin_index))


def _optimize_chord_angle(moving_anchor: np.ndarray,
                          fixed_anchor: np.ndarray,
                          axis_origin: np.ndarray, axis_dir: np.ndarray,
                          target_nm: float,
                          theta_min: float, theta_max: float) -> float:
    """Brent-bounded search for θ minimising (|R(θ)·p_m - p_f| - target_nm)².

    Simpler analog of the ds-linker ``_optimize_angle`` — no
    bridge-boundary radials, just a scalar chord-magnitude target."""
    def loss(theta: float) -> float:
        R = _rot_axis_angle(axis_dir, theta)
        p_m = R @ (moving_anchor - axis_origin) + axis_origin
        diff = float(np.linalg.norm(p_m - fixed_anchor) - target_nm)
        return diff * diff

    if theta_max <= theta_min + 1e-9:
        return float(0.5 * (theta_min + theta_max))

    # Coarse grid → local-minimum picks (same pattern as `_optimize_angle`).
    step = 5.0 * np.pi / 180.0
    n_grid = max(3, int(np.ceil((theta_max - theta_min) / step)) + 1)
    grid = np.linspace(theta_min, theta_max, n_grid)
    losses = [loss(t) for t in grid]
    candidate_idxs: list[int] = []
    n = len(grid)
    for i in range(n):
        if i == 0:
            if n > 1 and losses[i] < losses[i + 1]:
                candidate_idxs.append(i)
        elif i == n - 1:
            if losses[i] < losses[i - 1]:
                candidate_idxs.append(i)
        else:
            if losses[i] < losses[i - 1] and losses[i] < losses[i + 1]:
                candidate_idxs.append(i)
    if not candidate_idxs:
        candidate_idxs = [int(np.argmin(losses))]

    refined: list[tuple[float, float]] = []
    for i in candidate_idxs:
        lo = grid[max(0, i - 2)]
        hi = grid[min(n - 1, i + 2)]
        if hi <= lo + 1e-9:
            refined.append((float(grid[i]), float(losses[i])))
            continue
        res = minimize_scalar(loss, bounds=(lo, hi), method="bounded",
                              options={"xatol": 1e-5})
        refined.append((float(res.x), float(res.fun)))

    best = min(c for _, c in refined)
    tol = 1e-6
    near_best = [(t, c) for t, c in refined if c <= best + tol]
    near_best.sort(key=lambda tc: abs(tc[0]))
    return near_best[0][0]


def fjc_positions_in_design_frame(design: Design, conn) -> list[list[float]]:
    """Pre-baked FJC bead positions mapped onto the live anchor chord.

    The bin index is taken from ``conn.bridge_bin_index`` (the chosen
    R_ee histogram bin's representative shape). Returns an empty list
    when geometry isn't ready or the bp length is out of the lookup range.
    """
    from backend.api.crud import _geometry_for_design
    from backend.core import ssdna_fjc

    n_bp = _linker_bp(conn)
    if not ssdna_fjc.has_entry(n_bp):
        return []
    nucs = _geometry_for_design(design)
    anchor_a, _ = _anchor_pos_and_normal(nucs, conn, conn.overhang_a_id, True)
    anchor_b, _ = _anchor_pos_and_normal(nucs, conn, conn.overhang_b_id, False)
    if anchor_a is None or anchor_b is None:
        return []
    bin_index = int(getattr(conn, "bridge_bin_index", 0) or 0)
    canonical = ssdna_fjc.bin_positions(n_bp, bin_index)
    transformed = ssdna_fjc.transform_to_chord(canonical, anchor_a, anchor_b)
    return [[float(x), float(y), float(z)] for x, y, z in transformed]


def relax_ss_linker(
    design: Design, conn, joint_ids: list[str] | None = None,
    bin_index: int | None = None,
    r_ee_min_nm: float | None = None,
    r_ee_max_nm: float | None = None,
) -> tuple[Design, dict[str, Any]]:
    """ss-linker relax: bring the anchor chord to the chosen FJC bin's R_ee.

    The frontend's interactive linker-config modal picks a specific
    histogram bin (one of ``hist_bins`` along the R_ee axis). Each bin
    has a stored representative shape and R_ee value. The relax targets
    that R_ee; the chosen positions are returned so the renderer can
    place beads at the pre-baked shape.

    ``r_ee_min_nm`` / ``r_ee_max_nm`` are persisted on the connection as
    kinematic limits (used by downstream animation / future hard joint
    clamps); not enforced inside this function.

    Returns ``(updated_design, info_dict)``.
    """
    from backend.core import ssdna_fjc

    if getattr(conn, "linker_type", "ds") != "ss":
        raise ValueError("relax_ss_linker only handles ss linkers; got "
                         f"{conn.linker_type!r}")
    n_bp = _linker_bp(conn)
    if not ssdna_fjc.has_entry(n_bp):
        lo, hi = ssdna_fjc.supported_range()
        raise ValueError(f"relax_ss_linker: bp length {n_bp} outside lookup "
                         f"range {lo}..{hi}. Regenerate the table to extend.")

    topo = dof_topology(design, conn)
    if joint_ids is None:
        if topo["status"] != "ok" or topo["n_dof"] != 1:
            raise ValueError(f"relax_ss_linker: not a 1-DOF case ({topo['status']})")
        joint_ids = topo["joints_a"] or topo["joints_b"]
    if not joint_ids:
        raise ValueError("relax_ss_linker: no joints to relax over.")

    from backend.core.models import _local_to_world_joint
    joints_by_id = {j.id: j for j in design.cluster_joints}
    cts_by_id    = {c.id: c for c in design.cluster_transforms}
    selected: list[tuple[str, np.ndarray, np.ndarray, str, float, float]] = []
    for jid in joint_ids:
        j = joints_by_id.get(jid)
        if j is None:
            raise ValueError(f"relax_ss_linker: joint id {jid!r} not found.")
        ct = cts_by_id.get(j.cluster_id)
        world_origin, world_dir = _local_to_world_joint(
            j.local_axis_origin, j.local_axis_direction, ct,
        )
        axis = np.asarray(world_dir, dtype=float)
        n = float(np.linalg.norm(axis))
        if n < 1e-9:
            raise ValueError(f"relax_ss_linker: joint {jid!r} axis_direction is degenerate.")
        theta_min = float(j.min_angle_deg) * np.pi / 180.0
        theta_max = float(j.max_angle_deg) * np.pi / 180.0
        selected.append((j.id, np.asarray(world_origin, dtype=float), axis / n,
                         j.cluster_id, theta_min, theta_max))

    from backend.api.crud import _geometry_for_design
    nucs = _geometry_for_design(design)
    anchor_a, _normal_a = _anchor_pos_and_normal(nucs, conn, conn.overhang_a_id, True)
    anchor_b, _normal_b = _anchor_pos_and_normal(nucs, conn, conn.overhang_b_id, False)
    if anchor_a is None or anchor_b is None:
        raise ValueError("relax_ss_linker: could not resolve anchor positions from geometry.")

    cluster_of_a = topo["cluster_a"]
    cluster_of_b = topo["cluster_b"]

    # Pick which pre-simulated bin to apply. The frontend modal sends an
    # explicit `bin_index`; otherwise keep the connection's current index
    # (relaxed) or fall back to the ensemble-mean bin (unrelaxed). The
    # actual bin used may differ from the requested one when the requested
    # bin is empty (loader walks to the nearest occupied bin).
    n_bins = ssdna_fjc.num_bins(n_bp)
    if bin_index is not None:
        requested_bin = int(bin_index) % n_bins
    elif getattr(conn, "bridge_relaxed", False):
        requested_bin = int(getattr(conn, "bridge_bin_index", 0) or 0) % n_bins
    else:
        requested_bin = ssdna_fjc.default_bin_index(n_bp)
    next_bin_index = ssdna_fjc.resolve_bin_index(n_bp, requested_bin)
    target_nm = float(ssdna_fjc.bin_r_ee(n_bp, next_bin_index))

    def _apply(thetas: np.ndarray, p_a: np.ndarray, p_b: np.ndarray):
        for (_jid, origin, axis, cluster_id, _tmin, _tmax), theta in zip(selected, thetas):
            R = _rot_axis_angle(axis, theta)
            if cluster_id == cluster_of_a:
                p_a = R @ (p_a - origin) + origin
            if cluster_id == cluster_of_b:
                p_b = R @ (p_b - origin) + origin
        return p_a, p_b

    if len(selected) == 1:
        _jid, origin, axis, cluster_id, theta_min, theta_max = selected[0]
        moving_is_a = (cluster_id == cluster_of_a)
        moving = anchor_a if moving_is_a else anchor_b
        fixed  = anchor_b if moving_is_a else anchor_a
        theta = _optimize_chord_angle(moving, fixed, origin, axis,
                                      target_nm, theta_min, theta_max)
        thetas = np.array([theta])
    else:
        def loss(thetas: np.ndarray) -> float:
            p_a, p_b = _apply(thetas, anchor_a.copy(), anchor_b.copy())
            diff = float(np.linalg.norm(p_b - p_a) - target_nm)
            return diff * diff + _THETA_REG_LAMBDA * float(np.sum(thetas * thetas))

        bounds = [(tmin, tmax) for (*_rest, tmin, tmax) in selected]
        x0 = np.array([min(max(0.0, tmin), tmax) for (tmin, tmax) in bounds], dtype=float)
        res = minimize(loss, x0, method="Powell", bounds=bounds,
                       options={"xtol": 1e-5, "ftol": 1e-8, "maxiter": 500})
        thetas = np.asarray(res.x, dtype=float)
        for i, (tmin, tmax) in enumerate(bounds):
            thetas[i] = float(min(max(thetas[i], tmin), tmax))

    final_a, final_b = _apply(thetas, anchor_a.copy(), anchor_b.copy())
    final_chord = float(np.linalg.norm(final_b - final_a))

    # Compose new cluster transforms. Identical logic to the ds path.
    cluster_updates: dict[str, tuple[list[float], list[float]]] = {}
    for (_jid, origin, axis, cluster_id, _tmin, _tmax), theta in zip(selected, thetas):
        cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
        if cluster is None:
            continue
        if cluster_id in cluster_updates:
            q_prev, t_prev = cluster_updates[cluster_id]
            staged = cluster.model_copy(update={"rotation": q_prev, "translation": t_prev})
        else:
            staged = cluster
        cluster_updates[cluster_id] = _composed_transform(staged, origin, axis, float(theta))

    new_clusters = []
    for c in design.cluster_transforms:
        if c.id in cluster_updates:
            q_new, t_new = cluster_updates[c.id]
            new_clusters.append(c.model_copy(update={"rotation": q_new, "translation": t_new}))
        else:
            new_clusters.append(c)

    log = list(design.feature_log)
    if design.feature_log_cursor == -2:
        log = []
    elif design.feature_log_cursor >= 0:
        log = log[:design.feature_log_cursor + 1]
    for c in new_clusters:
        if c.id in cluster_updates:
            log.append(ClusterOpLogEntry(
                cluster_id=c.id,
                translation=list(c.translation),
                rotation=list(c.rotation),
                pivot=list(c.pivot),
                source="relax",
            ))

    # Flip `bridge_relaxed=True` and persist the chosen bin index + any
    # kinematic R_ee limits set by the user in the modal.
    conn_update = {
        "bridge_relaxed": True,
        "bridge_bin_index": next_bin_index,
    }
    if r_ee_min_nm is not None:
        conn_update["bridge_r_ee_min_nm"] = float(r_ee_min_nm)
    if r_ee_max_nm is not None:
        conn_update["bridge_r_ee_max_nm"] = float(r_ee_max_nm)
    new_conns = [
        c.model_copy(update=conn_update) if c.id == conn.id else c
        for c in design.overhang_connections
    ]

    updated = design.copy_with(
        cluster_transforms=new_clusters,
        overhang_connections=new_conns,
        feature_log=log,
        feature_log_cursor=-1,
    )

    # Compute world-frame FJC bead positions on the (now relaxed) design.
    relaxed_conn = next((c for c in updated.overhang_connections if c.id == conn.id), conn)
    fjc_positions = fjc_positions_in_design_frame(updated, relaxed_conn)
    entry = ssdna_fjc.entry(n_bp)
    return updated, {
        "joint_ids": [jid for (jid, *_rest) in selected],
        "thetas_rad": [float(t) for t in thetas],
        "moved_cluster_ids": list(cluster_updates.keys()),
        "final_chord_nm": final_chord,
        "target_chord_nm": target_nm,
        "fjc_n_bp": n_bp,
        "fjc_n_kuhn": int(entry["n_kuhn"]),
        "fjc_rg_nm": float(ssdna_fjc.bin_rg(n_bp, next_bin_index)),
        "fjc_wall_separation_nm": float(entry.get("wall_separation_nm", target_nm)),
        "fjc_saw_radius_nm": float(entry.get("saw_radius_nm", 0.6)),
        "fjc_bin_index": next_bin_index,
        "fjc_n_bins": n_bins,
        "fjc_r_ee_min_nm": r_ee_min_nm,
        "fjc_r_ee_max_nm": r_ee_max_nm,
        "fjc_positions": fjc_positions,
    }

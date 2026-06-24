"""Cluster OBB + edge-alignment solver — backend/core/cluster_obb.py (AF-15 Phase 2).

The OBB is the shared geometric foundation for the kinematic-cluster items
(AF-15 edge alignment here, AF-14 revolute-joint ROM later).  Two properties make
it trustworthy:

  * **containment + tightness** — the box really bounds the cluster's helix axes,
    snugly (it touches the extremes on every face);
  * **equivariance** — ``OBB(g · design) = g · OBB(design)`` for a rigid pose ``g``.
    This is the load-bearing pin: it is what lets a named edge refer to the *same
    physical edge* before and after the alignment solver moves the cluster, so the
    ``assert_edges_collinear`` oracle (which recomputes the OBB on the posed design)
    measures the edge the solver intended.

The solver itself (``align_edge_transform`` / the ``hb.align_cluster_edge`` wrapper)
is pinned by ``assert_edges_collinear``: after the solved pose the chosen edge is
collinear with the target edge / world line.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.cluster_obb import (
    OBB,
    _obb_intersect,
    align_edge_transform,
    cluster_obb,
    cluster_range_of_motion,
    grubler_mobility,
    hull_prism_axis,
    obb_sweep_rom,
    rank_joint_candidates,
    recommend_hinge_joints,
)
from backend.core.deformation import deformed_helix_axes
from backend.core.models import LatticeType
from tests.automation_harness import (
    assert_edges_collinear,
    assert_joint_on_hull_corner,
    assert_range_of_motion,
    assert_recommended_hinge,
    headless_coverage_report,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _square_grid(rows: int, cols: int, length_bp: int = 32):
    """Create a rows×cols SQUARE bundle in the active scratch session; return the design."""
    hb.create_bundle(
        [(r, c) for r in range(rows) for c in range(cols)],
        length_bp, lattice=LatticeType.SQUARE, name="grid",
    )
    return design_state.get_or_404()


def _helix_ids_in_cols(design, col_lo: int, col_hi: int):
    return [h.id for h in design.helices
            if h.grid_pos and col_lo <= h.grid_pos[1] <= col_hi]


def _add_cluster(name, helix_ids) -> str:
    hb.add_cluster(name, helix_ids)
    return design_state.get_or_404().cluster_transforms[-1].id


def _bar_design():
    """One whole-bar cluster over a 2×6 rectangular grid; return (design, cluster_id)."""
    d = _square_grid(2, 6)
    cid = _add_cluster("bar", [h.id for h in d.helices])
    return design_state.get_or_404(), cid


def _two_bar_design():
    """Two 2×3 clusters (cols 0-2 = A, cols 3-5 = B) in one 2×6 grid; return (A_id, B_id)."""
    d = _square_grid(2, 6)
    a = _add_cluster("barA", _helix_ids_in_cols(d, 0, 2))
    b = _add_cluster("barB", _helix_ids_in_cols(d, 3, 5))
    return a, b


# ── OBB: containment + tightness ──────────────────────────────────────────────

def test_obb_contains_cluster_geometry_snugly():
    """Every cluster helix-axis endpoint is inside the OBB, and the box touches the
    extreme on every one of its 6 faces (tight, not loose)."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        obb = cluster_obb(design, cid)
        cluster = next(c for c in design.cluster_transforms if c.id == cid)
        hids = set(cluster.helix_ids)
        axes = {a["helix_id"]: a for a in deformed_helix_axes(design)}
        pts = []
        for hid in hids:
            pts.append(np.asarray(axes[hid]["start"], float))
            pts.append(np.asarray(axes[hid]["end"], float))
        pts = np.asarray(pts)
        # coords in the OBB frame relative to centre
        coords = (pts - obb.center) @ obb.axes.T
        # containment: |coord| ≤ half on each axis
        assert np.all(np.abs(coords) <= obb.half + 1e-6), "a helix endpoint escapes the OBB"
        # tightness: each axis's extreme reaches the face (max |coord| == half)
        reach = np.abs(coords).max(axis=0)
        assert np.allclose(reach, obb.half, atol=1e-6), (
            f"OBB is loose — reach {np.round(reach,3)} vs half {np.round(obb.half,3)}"
        )


def test_obb_axes_are_right_handed_orthonormal():
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        obb = cluster_obb(design, cid)
        # orthonormal
        assert np.allclose(obb.axes @ obb.axes.T, np.eye(3), atol=1e-9)
        # right-handed: u × v == w
        u, v, w = obb.axes
        assert np.allclose(np.cross(u, v), w, atol=1e-9)


def test_obb_rejects_degenerate_clusters():
    with hb.scratch_session(LatticeType.SQUARE):
        d = _square_grid(1, 4)
        # single-helix cluster → no cross-section / <2 helices
        cid_single = _add_cluster("one", [d.helices[0].id])
        with pytest.raises(ValueError, match="≥2 helices"):
            cluster_obb(design_state.get_or_404(), cid_single)
    with hb.scratch_session(LatticeType.SQUARE):
        # square footprint (2×2) → ambiguous u/v
        d = _square_grid(2, 2)
        cid_sq = _add_cluster("sq", [h.id for h in d.helices])
        with pytest.raises(ValueError, match="too symmetric"):
            cluster_obb(design_state.get_or_404(), cid_sq)


# ── OBB: equivariance (the load-bearing pin) ──────────────────────────────────

@pytest.mark.parametrize("rotvec,translation", [
    ([0.0, 0.0, 0.0], [3.0, -4.0, 5.0]),                       # pure translation
    ([0.0, 0.0, np.pi / 5], [0.0, 0.0, 0.0]),                  # rotation about Z
    (list(np.array([1.0, 2.0, 3.0]) / np.linalg.norm([1, 2, 3]) * 0.7),
     [2.0, -1.0, 4.0]),                                        # general screw
])
def test_obb_is_equivariant(rotvec, translation):
    """OBB(g·design) = g·OBB(design): half unchanged, axes rotate, centre moves with g.

    This is what makes edge keys track the cluster through the alignment transform.
    """
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        obb0 = cluster_obb(design, cid)

        Rg = Rotation.from_rotvec(rotvec)
        quat = Rg.as_quat().tolist()
        pivot = [0.0, 0.0, 0.0]
        hb.transform_cluster(cid, translation=translation, rotation=quat, pivot=pivot)
        obb1 = cluster_obb(design_state.get_or_404(), cid)

        T = np.asarray(translation, float)
        # half-extents preserved by a rigid motion
        assert np.allclose(obb1.half, obb0.half, atol=1e-3), "OBB extents changed under a rigid pose"
        # axes rotate with g
        for i in range(3):
            assert np.allclose(obb1.axes[i], Rg.apply(obb0.axes[i]), atol=1e-3), (
                f"OBB axis {i} did not rotate with the cluster (frame not equivariant)"
            )
        # centre: Rg·(c0 − pivot) + pivot + T  (pivot = 0)
        expected_c = Rg.apply(obb0.center) + T
        assert np.allclose(obb1.center, expected_c, atol=1e-3)


# ── edge-alignment solver ─────────────────────────────────────────────────────

def test_align_two_parallel_bars_snaps_edge_onto_edge():
    """Align bar A's axial edge onto bar B's axial edge (already parallel → mostly a
    translation): afterwards the two edges are collinear and the midpoints coincide."""
    with hb.scratch_session(LatticeType.SQUARE):
        a, b = _two_bar_design()
        src = ("w", 1, 1)
        tgt = ("w", -1, 1)
        hb.align_cluster_edge(a, src, target_edge=(b, tgt))
        d = design_state.get_or_404()
        assert_edges_collinear(d, a, src, target_edge=(b, tgt))
        # full-snap: the src edge midpoint coincides with the target edge midpoint
        obb_a = cluster_obb(d, a)
        obb_b = cluster_obb(d, b)
        pa0, pa1 = obb_a.edge_endpoints(src)
        pb0, pb1 = obb_b.edge_endpoints(tgt)
        assert np.allclose((pa0 + pa1) / 2, (pb0 + pb1) / 2, atol=1e-3), "midpoints not snapped"


def test_align_edge_to_angled_world_line_rotates_and_snaps():
    """Align an axial (≈Z) edge onto a world line at 45° in XZ: a real rotation, then
    a midpoint snap onto the line's point."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        src = ("w", 1, 1)
        point = [5.0, 5.0, 5.0]
        direction = [1.0, 0.0, 1.0]  # 45° from Z in the XZ plane
        quat, _, _ = align_edge_transform(design, cid, src, target_line=(point, direction))
        # the rotation is non-trivial (not identity)
        ang = Rotation.from_quat(quat).magnitude()
        assert ang > np.radians(20), "expected a real rotation onto the angled line"
        hb.align_cluster_edge(cid, src, target_line=(point, direction))
        d = design_state.get_or_404()
        assert_edges_collinear(d, cid, src, target_line=(point, direction))
        # midpoint snapped onto the line's point
        pa0, pa1 = cluster_obb(d, cid).edge_endpoints(src)
        assert np.allclose((pa0 + pa1) / 2, point, atol=1e-3)


def test_align_to_rotated_bar_exercises_full_rotation():
    """Pre-rotate bar B 90° about X (its axial edge now runs along Y), then align A's
    axial edge onto it — A must really turn 90° to become collinear."""
    with hb.scratch_session(LatticeType.SQUARE):
        a, b = _two_bar_design()
        # B: 90° about X about its own centre region
        b_obb = cluster_obb(design_state.get_or_404(), b)
        q = Rotation.from_rotvec([np.pi / 2, 0.0, 0.0]).as_quat().tolist()
        hb.transform_cluster(b, translation=[0.0, 0.0, 0.0], rotation=q,
                             pivot=b_obb.center.tolist())
        src = ("w", 1, 1)
        tgt = ("w", 1, 1)
        hb.align_cluster_edge(a, src, target_edge=(b, tgt))
        d = design_state.get_or_404()
        assert_edges_collinear(d, a, src, target_edge=(b, tgt))


def test_align_auto_flips_to_minimal_rotation():
    """Target direction pointing opposite the src edge → auto-flip picks the ≤90°
    rotation (antiparallel sense), and the oracle (direction-agnostic) still passes."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        src = ("w", 1, 1)
        # src edge runs ≈ +Z; target line direction ≈ −Z (opposite)
        point = [4.0, 0.0, 0.0]
        direction = [0.0, 0.0, -1.0]
        quat, _, _ = align_edge_transform(design, cid, src, target_line=(point, direction))
        ang = Rotation.from_quat(quat).magnitude()
        assert ang < np.radians(1.0), "auto-flip should make this a ~zero rotation, not 180°"
        hb.align_cluster_edge(cid, src, target_line=(point, direction))
        d = design_state.get_or_404()
        assert_edges_collinear(d, cid, src, target_line=(point, direction))


# ── AF-14 Phase 1: hull_prism_axis (named OBB feature → world revolute axis) ───

def test_hull_prism_axis_edge_runs_along_the_obb_edge():
    """edge mode: origin = edge midpoint, direction = the edge line."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        obb = cluster_obb(design, cid)
        edge = ("w", 1, 1)
        p_lo, p_hi = obb.edge_endpoints(edge)
        origin, direction = hull_prism_axis(design, cid, edge=edge)
        assert np.allclose(origin, (p_lo + p_hi) / 2.0, atol=1e-6)
        edge_dir = (p_hi - p_lo) / np.linalg.norm(p_hi - p_lo)
        # parallel (collinear with the edge); unit length
        assert abs(abs(float(np.dot(direction, edge_dir))) - 1.0) < 1e-6
        assert abs(np.linalg.norm(direction) - 1.0) < 1e-9


def test_hull_prism_axis_corner_pivots_at_corner_along_face_normal():
    """corner mode: origin = corner, direction = the named face's outward normal."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        obb = cluster_obb(design, cid)
        origin, direction = hull_prism_axis(design, cid, corner=(1, 1, 1), face=("w", 1))
        assert np.allclose(origin, obb.corner(1, 1, 1), atol=1e-6)
        normal = obb.face_normal(("w", 1))
        assert abs(abs(float(np.dot(direction, normal / np.linalg.norm(normal)))) - 1.0) < 1e-6


def test_hull_prism_axis_rejections():
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        with pytest.raises(ValueError, match="exactly one"):
            hull_prism_axis(design, cid)  # neither edge nor corner
        with pytest.raises(ValueError, match="neither corner nor face"):
            hull_prism_axis(design, cid, edge=("w", 1, 1), face=("w", 1))
        with pytest.raises(ValueError, match="requires a face"):
            hull_prism_axis(design, cid, corner=(1, 1, 1))  # corner without face
        with pytest.raises(ValueError, match="does not lie on face"):
            hull_prism_axis(design, cid, corner=(1, 1, 1), face=("w", -1))


# ── AF-14 Phase 1: place_cluster_joint (anchored revolute joint) ───────────────

def test_place_cluster_joint_on_edge_lands_on_that_edge():
    """A joint placed on an OBB edge has a world axis collinear with that edge."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        edge = ("w", 1, 1)
        hb.place_cluster_joint(cid, edge=edge, name="hinge")
        d = design_state.get_or_404()
        jid = d.cluster_joints[-1].id
        assert_joint_on_hull_corner(d, jid, edge=edge)


def test_place_cluster_joint_on_corner_passes_through_corner():
    """A joint placed at an OBB corner has a world axis through that corner along the
    named face normal."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        hb.place_cluster_joint(cid, corner=(1, 1, 1), face=("w", 1), name="pivot")
        d = design_state.get_or_404()
        jid = d.cluster_joints[-1].id
        assert_joint_on_hull_corner(d, jid, corner=(1, 1, 1), face=("w", 1))


def test_place_cluster_joint_on_posed_cluster_round_trips_local_frame():
    """Pose the cluster (translate + rotate) BEFORE placing the joint: the route stores
    the axis in the cluster's LOCAL frame, and the oracle (re-deriving world via
    _local_to_world_joint on the recomputed posed OBB) still finds it on the named edge —
    proving the world→local→world round-trip is consistent on a posed body."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        obb = cluster_obb(design, cid)
        q = Rotation.from_rotvec([0.0, 0.0, np.pi / 4]).as_quat().tolist()
        hb.transform_cluster(cid, translation=[5.0, -3.0, 2.0], rotation=q,
                             pivot=obb.center.tolist())
        edge = ("w", 1, 1)
        hb.place_cluster_joint(cid, edge=edge)
        d = design_state.get_or_404()
        jid = d.cluster_joints[-1].id
        assert_joint_on_hull_corner(d, jid, edge=edge)


def test_place_cluster_joint_flips_add_joint_to_covered():
    """place_cluster_joint drives the real add_joint handler (function-identity) →
    coverage 34 → 35 (the first coverage flip since AF-15 Phase 1)."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert "add_joint" in covered


# ── AF-14 Phase 2: swept-OBB range of motion ──────────────────────────────────

def _box(center, half, axes=None) -> OBB:
    """A synthetic axis-aligned OBB for the pure swept-collision tests."""
    if axes is None:
        axes = np.eye(3)
    return OBB(center=np.asarray(center, float),
               axes=np.asarray(axes, float),
               half=np.asarray(half, float))


def test_obb_intersect_overlap_and_separation():
    """SAT: two unit boxes overlap when their centres are < 2·half apart, separate
    when farther — on a face axis and on a diagonal."""
    a = _box([0, 0, 0], [1, 1, 1])
    assert _obb_intersect(a, _box([1.5, 0, 0], [1, 1, 1]))      # overlapping in x
    assert not _obb_intersect(a, _box([2.5, 0, 0], [1, 1, 1]))  # separated in x
    assert _obb_intersect(a, _box([1.2, 1.2, 0], [1, 1, 1]))    # overlapping on diagonal
    assert not _obb_intersect(a, _box([3, 3, 3], [1, 1, 1]))    # far away


def test_obb_sweep_rom_double_wall_matches_analytic():
    """A thin rod hinged at the origin about Z, with symmetric walls at y=±Y0: the rod's
    far corner reaches the wall after a closed-form angle, so the two-sided ROM is
    2·(asin(Y0/√(L²+w²)) − atan2(w, L)) — an INDEPENDENT derivation, not the SAT sweep."""
    L, w, Y0 = 4.0, 0.2, 2.0
    rod = _box([L / 2, 0, 0], [L / 2, w, w])
    top = _box([0, Y0 + 0.5, 0], [6, 0.5, 2])     # lower face at y = Y0
    bottom = _box([0, -(Y0 + 0.5), 0], [6, 0.5, 2])  # upper face at y = −Y0
    rom = obb_sweep_rom(rod, [top, bottom], [0, 0, 0], [0, 0, 1],
                        pad=0.0, step_deg=0.5)
    theta_plus = math.degrees(math.asin(Y0 / math.hypot(L, w)) - math.atan2(w, L))
    assert abs(rom - 2 * theta_plus) < 1.0, (
        f"swept ROM {rom:.2f}° ≠ analytic {2 * theta_plus:.2f}°"
    )


def test_obb_sweep_rom_no_obstacle_is_full_limit():
    """No obstacle → free swing to the joint's angular limit (max − min)."""
    rod = _box([2, 0, 0], [2, 0.2, 0.2])
    assert abs(obb_sweep_rom(rod, [], [0, 0, 0], [0, 0, 1]) - 360.0) < 1e-6
    assert abs(obb_sweep_rom(rod, [], [0, 0, 0], [0, 0, 1],
                             min_deg=-90, max_deg=90) - 180.0) < 1e-6


def test_cluster_range_of_motion_no_obstacle_full_swing():
    """A lone cluster (no other clusters) swings the full angular limit about any edge."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        axis = hull_prism_axis(design, cid, edge=("w", 1, 1))
        assert abs(cluster_range_of_motion(design, cid, axis) - 360.0) < 2.0
        assert abs(cluster_range_of_motion(
            design, cid, axis, min_angle_deg=-90, max_angle_deg=90) - 180.0) < 2.0


def _near_w_edge(obb_a, target_center):
    """The cluster's vertical (axial-‘w’) OBB edge whose midpoint is NEAREST
    ``target_center`` — the contact-interface hinge, where one swing sense drives A's
    body straight into the neighbour so the ROM is sensitive to the gap."""
    best, best_d = None, 1e30
    for key in [("w", s1, s2) for s1 in (-1, 1) for s2 in (-1, 1)]:
        p_lo, p_hi = obb_a.edge_endpoints(key)
        d = float(np.linalg.norm((p_lo + p_hi) / 2 - target_center))
        if d < best_d:
            best, best_d = key, d
    return best


def test_cluster_range_of_motion_obstacle_reduces_and_is_monotonic():
    """Two bars: hinging A about its interface edge swings A's body into B → ROM < 360,
    and moving B closer strictly shrinks it (the can-go-red 'obstacle reduces' property)."""
    with hb.scratch_session(LatticeType.SQUARE):
        a, b = _two_bar_design()
        d = design_state.get_or_404()
        sep = cluster_obb(d, b).center - cluster_obb(d, a).center
        sep_u = sep / np.linalg.norm(sep)

        # B farther: a wide rest gap → more swing before contact.
        hb.transform_cluster(b, translation=(sep_u * 4).tolist(),
                             rotation=[0, 0, 0, 1], pivot=[0, 0, 0])
        d_far = design_state.get_or_404()
        obb_a = cluster_obb(d_far, a)
        edge = _near_w_edge(obb_a, cluster_obb(d_far, b).center)
        axis_far = hull_prism_axis(d_far, a, edge=edge)
        rom_far = cluster_range_of_motion(d_far, a, axis_far)

        # B closer (still a rest gap) → less swing room.
        hb.transform_cluster(b, translation=(sep_u * 1).tolist(),
                             rotation=[0, 0, 0, 1], pivot=[0, 0, 0])
        d_near = design_state.get_or_404()
        axis_near = hull_prism_axis(d_near, a, edge=edge)
        rom_near = cluster_range_of_motion(d_near, a, axis_near)

        assert rom_far < 360.0, "B should block some of A's swing"
        assert 0.0 < rom_near < rom_far, (
            f"moving B closer should shrink ROM ({rom_near:.1f}° vs {rom_far:.1f}°)"
        )


def test_rank_joint_candidates_orders_by_rom_and_door_jamb():
    """Ranking returns all 12 edges sorted by ROM; with a neighbour present the ROM
    varies across edges (the door-jamb principle: an edge facing away swings free, one
    driving the bulk in scores low), and a target filter keeps only the qualifying ones."""
    with hb.scratch_session(LatticeType.SQUARE):
        a, b = _two_bar_design()
        d = design_state.get_or_404()
        sep = cluster_obb(d, b).center - cluster_obb(d, a).center
        sep_u = sep / np.linalg.norm(sep)
        hb.transform_cluster(b, translation=(sep_u * 2).tolist(),
                             rotation=[0, 0, 0, 1], pivot=[0, 0, 0])
        d2 = design_state.get_or_404()

        ranked = rank_joint_candidates(d2, a)
        assert len(ranked) == 12
        roms = [c["rom_deg"] for c in ranked]
        assert roms == sorted(roms, reverse=True), "candidates not sorted by ROM"
        assert roms[0] - roms[-1] > 5.0, "B should make some hinges much freer than others"

        # the door-jamb: the best hinge is freer than the worst, which drives A into B
        worst = ranked[-1]
        assert worst["rom_deg"] < 360.0

        # target filter: only candidates meeting the bar pass through, still sorted
        target = (roms[0] + roms[-1]) / 2
        filt = rank_joint_candidates(d2, a, target_rom_deg=target)
        assert filt and all(c["rom_deg"] >= target for c in filt)
        assert len(filt) < 12


def test_assert_range_of_motion_oracle_and_red(  # the harness oracle on real clusters
):
    """assert_range_of_motion passes on the lone-cluster full swing and goes red on a
    wrong expected angle (the load-bearing can-go-red guard)."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        axis = hull_prism_axis(design, cid, edge=("w", 1, 1))
        assert_range_of_motion(design, cid, axis, 360.0)
        with pytest.raises(AssertionError, match="expected"):
            assert_range_of_motion(design, cid, axis, 180.0)


# ── AF-14 Phase 3: hinge-joint recommender (non-axial, longest, corner-anchored) ──

def test_recommend_hinge_picks_longest_non_axial_corner_anchored():
    """On a 2×6 bar the recommender's #1 hinge is the wide cross-section (u) edge — the
    longest edge NOT parallel to the helical axis — anchored at a face corner."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        recs = recommend_hinge_joints(design, cid)
        assert len(recs) == 12  # all edges returned, axial ones demoted to the tail
        top = recs[0]
        # the wide cross-section direction is u (6 cols) > v (2 rows) > nothing axial.
        assert top["edge"][0] == "u", f"top hinge {top['edge']} is not the wide u-edge"
        assert not top["is_axial"]
        # the oracle pins non-axial + longest-non-axial + corner-anchored together.
        assert_recommended_hinge(design, cid)


def test_recommend_hinge_demotes_axial_w_edges():
    """The 4 axial (w) edges — barrel-rolls about the helical axis — sort AFTER every
    cross-section edge, and are flagged is_axial."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        recs = recommend_hinge_joints(design, cid)
        axials = [c for c in recs if c["edge"][0] == "w"]
        assert len(axials) == 4 and all(c["is_axial"] for c in axials)
        # every non-axial edge outranks every axial one → axials are the last 4.
        assert all(c["edge"][0] == "w" for c in recs[-4:])
        assert all(c["angle_to_axis_deg"] < 1.0 for c in axials)  # exactly along w
        # cross-section edges are perpendicular to w.
        for c in recs[:8]:
            assert abs(c["angle_to_axis_deg"] - 90.0) < 1.0


def test_recommend_hinge_corner_vs_midpoint_anchor():
    """anchor='corner' stores an edge endpoint; anchor='midpoint' the edge centre — same
    hinge line (direction), only the recorded point differs."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        corner = recommend_hinge_joints(design, cid, anchor="corner")[0]
        mid = recommend_hinge_joints(design, cid, anchor="midpoint")[0]
        assert corner["edge"] == mid["edge"]
        # same line direction
        assert np.allclose(corner["axis_direction"], mid["axis_direction"], atol=1e-9)
        obb = cluster_obb(design, cid)
        p_lo, p_hi = obb.edge_endpoints(corner["edge"])
        o_corner = np.asarray(corner["axis_origin"])
        o_mid = np.asarray(mid["axis_origin"])
        # corner anchor coincides with an endpoint; midpoint with the centre.
        assert min(np.linalg.norm(o_corner - p_lo),
                   np.linalg.norm(o_corner - p_hi)) < 1e-6
        assert np.linalg.norm(o_mid - (p_lo + p_hi) / 2.0) < 1e-6
        # they are genuinely different points (the edge has real length).
        assert np.linalg.norm(o_corner - o_mid) > 1.0


def test_recommend_hinge_target_rom_filter():
    """A target-ROM filter keeps only candidates meeting it (door-jamb tiebreaker)."""
    with hb.scratch_session(LatticeType.SQUARE):
        a, b = _two_bar_design()
        d = design_state.get_or_404()
        sep = cluster_obb(d, b).center - cluster_obb(d, a).center
        hb.transform_cluster(b, translation=(sep / np.linalg.norm(sep) * 2).tolist(),
                             rotation=[0, 0, 0, 1], pivot=[0, 0, 0])
        d2 = design_state.get_or_404()
        roms = [c["rom_deg"] for c in recommend_hinge_joints(d2, a)]
        target = (max(roms) + min(roms)) / 2
        filt = recommend_hinge_joints(d2, a, target_rom_deg=target)
        assert filt and all(c["rom_deg"] >= target for c in filt) and len(filt) < 12


def test_place_cluster_joint_corner_anchor_stays_on_edge():
    """Placing a joint with anchor='corner' puts the stored anchor at a corner yet the
    joint axis is still collinear with the same edge (corner moves the point, not the
    line), so assert_joint_on_hull_corner (edge mode) still passes."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        edge = recommend_hinge_joints(design, cid)[0]["edge"]
        hb.place_cluster_joint(cid, edge=edge, anchor="corner", name="hinge")
        d = design_state.get_or_404()
        jid = d.cluster_joints[-1].id
        assert_joint_on_hull_corner(d, jid, edge=edge)  # axis line still on the edge


def test_recommend_hinge_rejects_bad_anchor():
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        with pytest.raises(ValueError, match="anchor"):
            recommend_hinge_joints(design, cid, anchor="centroid")


def test_recommend_hinge_adds_no_coverage():
    """recommend_hinge_joints is a pure selector + place_cluster_joint's anchor reuses the
    already-covered add_joint route — no NEW route wrapped, so coverage is unchanged."""
    before = headless_coverage_report()["covered"]
    with hb.scratch_session(LatticeType.SQUARE):
        design, cid = _bar_design()
        recommend_hinge_joints(design, cid)
    assert headless_coverage_report()["covered"] == before


# ── Grübler / Kutzbach planar mobility ────────────────────────────────────────

def test_grubler_four_bar_is_one_dof():
    """4 links (one grounded) + 4 revolute joints = a 1-DOF planar mechanism."""
    assert grubler_mobility(4, revolute=4) == 1


def test_grubler_known_mechanisms():
    """Textbook planar cases: 5-bar/6-joint = 0 (structure), prismatic counts as a
    lower pair, a higher pair removes only 1, a lone link has 0 DOF (it's the ground)."""
    assert grubler_mobility(5, revolute=6) == 0          # over-constrained structure
    assert grubler_mobility(4, revolute=3, prismatic=1) == 1  # slider-crank
    assert grubler_mobility(4, revolute=3, higher=2) == 1     # 3 lower + 2 higher pairs
    assert grubler_mobility(1) == 0                       # ground alone


def test_grubler_rejects_bad_input():
    with pytest.raises(ValueError, match="n_links"):
        grubler_mobility(0, revolute=2)
    with pytest.raises(ValueError, match="non-negative"):
        grubler_mobility(4, revolute=-1)


# ── coverage: a construction-sugar item (wraps no new route) ──────────────────

def test_align_cluster_edge_adds_no_coverage():
    """align_cluster_edge composes transform_cluster (already covered) + a pure solver —
    it wraps no NEW route, so headless coverage is unchanged (the oracle is the
    deliverable, not a coverage flip)."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert "update_cluster" in covered  # what align_cluster_edge drives
    # AF-14 Phase 1's place_cluster_joint flipped add_joint → covered (34 → 35);
    # the full_sequence feature later flipped assign_staple_sequences (35 → 36);
    # the periodic straggler flipped polymerize_periodic_assembly (36 → 37);
    # AF-25's seek_features flipped /design/features/seek (37 → 38);
    # AF-26's return_to_latest flipped /design/loadouts/{id}/select (38 → 39).
    assert rep["covered"] == 39

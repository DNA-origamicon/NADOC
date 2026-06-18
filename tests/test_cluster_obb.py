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

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.cluster_obb import align_edge_transform, cluster_obb
from backend.core.deformation import deformed_helix_axes
from backend.core.models import LatticeType
from tests.automation_harness import assert_edges_collinear, headless_coverage_report


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


# ── coverage: a construction-sugar item (wraps no new route) ──────────────────

def test_align_cluster_edge_adds_no_coverage():
    """align_cluster_edge composes transform_cluster (already covered) + a pure solver —
    it wraps no NEW route, so headless coverage is unchanged (the oracle is the
    deliverable, not a coverage flip)."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert "update_cluster" in covered  # what align_cluster_edge drives
    assert rep["covered"] == 34

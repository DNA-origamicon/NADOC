"""The headless 4-bar parallelogram — the first headless kinematic mechanism (AF capstone).

Composes the kinematic-cluster pieces built across AF-14 + AF-15 into one mechanism,
entirely without a browser:

  * extrude rigid bars (``hb.create_bundle``), one rigid-body cluster each
    (``hb.add_cluster``, AF-15 P1);
  * arrange them into a parallelogram by OBB-**edge alignment** onto the four sides of a
    rhombus (``hb.align_cluster_edge``, AF-15 P2) — so adjacent bars meet at a shared
    OBB corner (the hinge point) and opposite bars stay parallel;
  * hinge each bar with a revolute **cluster joint** on that shared side-edge
    (``hb.place_cluster_joint``, AF-14 P1);
  * validate the assembled mechanism with ``assert_parallelogram_linkage`` — closed
    quadrilateral + opposite-sides-parallel-and-equal + Grübler mobility 1 + every hinge
    movable (nonzero ROM vs. the non-pinned bar, via AF-14 P2's swept-OBB ROM).

Nothing before this validated an *assembled multi-cluster mechanism*; the individual
construction steps each have their own AF oracle (``assert_edges_collinear``,
``assert_joint_on_hull_corner``, ``assert_range_of_motion``), and this pins their
composition into a working 1-DOF linkage.
"""

from __future__ import annotations

import math

import numpy as np

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.cluster_obb import cluster_obb
from backend.core.models import LatticeType

# The OBB-edge used both as the alignment edge (→ a parallelogram side) and the hinge
# edge (the revolute axis runs along it, through the two shared corners).
_SIDE_EDGE = ("w", 1, 1)


def build_parallelogram(
    *,
    interior_angle_deg: float = 70.0,
    length_bp: int = 32,
    place_joints: bool = True,
):
    """Build a 4-bar parallelogram in the ACTIVE scratch session; return ids.

    Caller owns the ``hb.scratch_session(LatticeType.SQUARE)`` context.  Returns
    ``(design, bar_ids, joint_ids)`` — four bar clusters in cyclic loop order and (if
    ``place_joints``) the four revolute hinges anchored on the shared side-edges.
    """
    # One 2×12 SQUARE grid, carved into four 2×3 rectangular bars (square footprints are
    # rejected by cluster_obb — the bars must be non-square so the u/v frame is stable).
    hb.create_bundle(
        [(r, c) for r in range(2) for c in range(12)],
        length_bp, lattice=LatticeType.SQUARE, name="grid",
    )
    d = design_state.get_or_404()
    bar_ids = []
    for i, (lo, hi) in enumerate([(0, 2), (3, 5), (6, 8), (9, 11)]):
        hids = [h.id for h in d.helices if h.grid_pos and lo <= h.grid_pos[1] <= hi]
        hb.add_cluster(f"bar{i}", hids)
        d = design_state.get_or_404()
        bar_ids.append(d.cluster_transforms[-1].id)

    # Rhombus sides of length L = the bar's axial edge length, in the XY plane.
    L = 2.0 * float(cluster_obb(d, bar_ids[0]).half[2])
    th = math.radians(interior_angle_deg)
    a = L * np.array([1.0, 0.0, 0.0])
    b = L * np.array([math.cos(th), math.sin(th), 0.0])
    corners = [np.zeros(3), a, a + b, b]
    sides = [(corners[k], corners[(k + 1) % 4]) for k in range(4)]

    for bid, (p, q) in zip(bar_ids, sides):
        mid = (p + q) / 2.0
        direction = (q - p) / np.linalg.norm(q - p)
        hb.align_cluster_edge(
            bid, _SIDE_EDGE, target_line=(mid.tolist(), direction.tolist()),
        )

    joint_ids = []
    if place_joints:
        for bid in bar_ids:
            hb.place_cluster_joint(bid, edge=_SIDE_EDGE, name="hinge")
            joint_ids.append(design_state.get_or_404().cluster_joints[-1].id)

    return design_state.get_or_404(), bar_ids, joint_ids


def test_headless_parallelogram_is_a_one_dof_linkage():
    """The full capstone: build the mechanism headlessly and assert it is a closed,
    parallel, 1-DOF four-bar linkage with every hinge movable."""
    from tests.automation_harness import assert_parallelogram_linkage

    with hb.scratch_session(LatticeType.SQUARE):
        design, bar_ids, joint_ids = build_parallelogram()
        result = assert_parallelogram_linkage(design, bar_ids, joint_ids=joint_ids)
        assert result["mobility"] == 1
        assert len(result["joint_roms"]) == 4
        assert all(rom > 0.0 for rom in result["joint_roms"].values())


def test_each_hinge_sits_on_its_shared_corner_edge():
    """Each placed joint's world axis is collinear with the bar's side-edge (the line
    through the two shared corners) — the per-joint AF-14 P1 oracle on the assembly."""
    from tests.automation_harness import assert_joint_on_hull_corner

    with hb.scratch_session(LatticeType.SQUARE):
        design, bar_ids, joint_ids = build_parallelogram()
        for jid in joint_ids:
            assert_joint_on_hull_corner(design, jid, edge=_SIDE_EDGE)


def test_adjacent_bars_share_exact_corners():
    """Each adjacent bar pair meets at a single shared OBB corner (the closed loop) and
    opposite bars are parallel — the geometric parallelogram, independent of the oracle."""
    with hb.scratch_session(LatticeType.SQUARE):
        design, bar_ids, _ = build_parallelogram(place_joints=False)
        obbs = [cluster_obb(design, b) for b in bar_ids]

        def corners(o):
            return [o.corner(su, sv, sw)
                    for su in (-1, 1) for sv in (-1, 1) for sw in (-1, 1)]

        for k in range(4):
            ci, cj = corners(obbs[k]), corners(obbs[(k + 1) % 4])
            dmin = min(np.linalg.norm(x - y) for x in ci for y in cj)
            assert dmin < 1e-3, f"bars {k},{(k + 1) % 4} don't share a corner ({dmin:.3f})"

        for k in (0, 1):
            w1, w2 = obbs[k].axes[2], obbs[k + 2].axes[2]
            ang = math.degrees(math.acos(min(1.0, abs(float(w1 @ w2)))))
            assert ang < 1.0, f"opposite bars {k},{k + 2} not parallel ({ang:.2f}°)"


def test_parallelogram_wraps_no_new_route():
    """The capstone is pure composition of already-covered wrappers
    (create_bundle / add_cluster / update_cluster / add_joint) — it flips no coverage."""
    from tests.automation_harness import headless_coverage_report

    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert {"create_bundle", "add_cluster", "update_cluster", "add_joint"} <= covered

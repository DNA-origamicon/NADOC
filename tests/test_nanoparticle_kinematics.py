import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.nanoparticle_kinematics import solve_closed_loop_pose


def _pose(translation=(0, 0, 0), rotvec=(0, 0, 0)):
    out = np.eye(4)
    out[:3, :3] = Rotation.from_rotvec(rotvec).as_matrix()
    out[:3, 3] = translation
    return out


@pytest.mark.parametrize("count", [1, 2, 3])
def test_closed_loop_solver_converges_for_n_anchors(count):
    local = np.array([[2, 0, 0], [0, 2, 0], [0, 0, 2]], dtype=float)[:count]
    target = _pose((3, -2, 1), (0.15, -0.1, 0.2))
    sites = local @ target[:3, :3].T + target[:3, 3]
    directions = np.array([[1, 1, 0], [-1, 0.5, 1], [0.5, -1, 1]], dtype=float)[:count]
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    radii = np.full(count, 8.0)
    roots = sites - directions * radii[:, None]
    initial = target.copy()
    initial[:3, 3] += [0.3, -0.2, 0.15]

    solved, report = solve_closed_loop_pose(
        initial, local, roots, radii, np.empty((0, 3)), 0.0,
    )

    assert report["converged"] is True
    assert report["max_joint_error_nm"] < 0.01
    solved_sites = local @ solved[:3, :3].T + solved[:3, 3]
    assert np.abs(np.linalg.norm(solved_sites - roots, axis=1) - radii).max() < 0.01


def test_closed_loop_solver_is_anchor_order_independent():
    local = np.array([[2, 0, 0], [0, 2, 0], [0, 0, 2]], dtype=float)
    roots = np.array([[-6, 0, 0], [0, -6, 0], [0, 0, -6]], dtype=float)
    radii = np.full(3, 8.0)
    initial = _pose((0.25, -0.1, 0.2), (0.03, -0.02, 0.01))
    a, ra = solve_closed_loop_pose(initial, local, roots, radii, np.empty((0, 3)), 0)
    order = np.array([2, 0, 1])
    b, rb = solve_closed_loop_pose(
        initial, local[order], roots[order], radii[order], np.empty((0, 3)), 0,
    )
    assert ra["converged"] and rb["converged"]
    assert a == pytest.approx(b, abs=1e-7)


def test_closed_loop_solver_reports_infeasible_without_distorting_links():
    # Both constraints address the same NP-local point, but their radius-one
    # root spheres are disjoint; no rigid pose can satisfy both.
    local = np.zeros((2, 3))
    roots = np.array([[0, 0, 0], [10, 0, 0]], dtype=float)
    radii = np.ones(2)
    _solved, report = solve_closed_loop_pose(
        np.eye(4), local, roots, radii, np.empty((0, 3)), 0,
    )
    assert report["converged"] is False
    assert report["max_joint_error_nm"] > 1.0


def test_closed_loop_solver_projects_nanoparticle_clearance():
    local = np.array([[2.0, 0, 0]])
    roots = np.array([[-8.0, 0, 0]])
    radii = np.array([10.0])
    obstacle = np.array([[0.0, 0, 0]])
    solved, report = solve_closed_loop_pose(
        np.eye(4), local, roots, radii, obstacle, 4.0,
    )
    assert np.linalg.norm(solved[:3, 3] - obstacle[0]) >= 3.95
    assert report["max_penetration_nm"] <= 0.05

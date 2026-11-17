"""Independent geometric oracles for the isolated collision benchmark."""
import numpy as np

from experiments.flexible_collision_benchmark import capsule_gaps, segment_distances


def test_segment_distance_crossing_parallel_endpoint_and_points():
    p = np.array([[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=float)
    q = np.array([[2, 0, 0], [2, 0, 0], [1, 0, 0], [0, 0, 0]], dtype=float)
    r = np.array([[1, -1, 0], [1, 3, 0], [2, 1, 0], [0, 3, 4]], dtype=float)
    s = np.array([[1, 1, 0], [3, 3, 0], [2, 2, 0], [0, 3, 4]], dtype=float)
    expected = [0, 3, np.sqrt(2), 5]
    np.testing.assert_allclose(segment_distances(p, q, r, s), expected)
    np.testing.assert_allclose(segment_distances(s, r, q, p), expected)


def test_segment_distance_invariant_under_common_rigid_motion():
    from scipy.spatial.transform import Rotation
    rng = np.random.default_rng(481)
    points = rng.normal(size=(4, 100, 3))
    rotation = Rotation.from_rotvec([.7, -.4, 1.2])
    moved = np.array([rotation.apply(p)+[10, -30, 5] for p in points])
    np.testing.assert_allclose(segment_distances(*points), segment_distances(*moved), atol=1e-12)


def test_segment_distances_against_independent_bounded_minimization():
    from scipy.optimize import minimize
    rng = np.random.default_rng(482)
    points = rng.normal(size=(4, 20, 3))
    expected = []
    for p, q, r, s in zip(*points):
        result = minimize(lambda x: np.sum((p+x[0]*(q-p)-r-x[1]*(s-r))**2),
                          [.5, .5], bounds=[(0, 1), (0, 1)], method='L-BFGS-B',
                          options={'ftol': 1e-14, 'gtol': 1e-10})
        expected.append(np.sqrt(result.fun))
    np.testing.assert_allclose(segment_distances(*points), expected, atol=1e-6)


def test_broad_phase_preserves_all_penetrations_and_feasible_pairs():
    rng = np.random.default_rng(483)
    points = rng.normal(size=(4, 200, 3))*5
    exact = segment_distances(*points)-2
    accelerated = capsule_gaps(*points, 2)
    np.testing.assert_allclose(np.minimum(accelerated, 0), np.minimum(exact, 0))
    np.testing.assert_array_equal(accelerated >= 0, exact >= 0)


def test_expansion_separates_bodies_without_scaling_them_or_moving_root():
    from experiments.flexible_collision_benchmark import Problem, expanded_seed
    problem = Problem.__new__(Problem)
    problem.ids = ['fixed', 'moving']
    problem.p = np.array([[0., 0., 0.], [.8, 0., 0.]])
    problem.q = problem.p + [0., 0., 2.]
    problem.owners = np.array([0, 1])
    problem.centers = (problem.p+problem.q)/2
    problem.pa, problem.pb = problem.p[:1], problem.p[1:]
    problem.ea, problem.eb = np.array([0]), np.array([1])
    problem.ia, problem.ib = np.array([0]), np.array([1])
    problem.contour = np.array([1.])
    problem.broad_phase = False
    before = problem.p.copy()
    x, factor = expanded_seed(problem)
    assert factor == 3.
    p = problem.move(problem.p, problem.owners, x)
    q = problem.move(problem.q, problem.owners, x)
    np.testing.assert_array_equal(p[0], before[0])
    np.testing.assert_allclose(q-p, problem.q-problem.p)
    np.testing.assert_array_equal(problem.p, before)
    assert problem.metrics(x)['capsule_overlaps'] == 0
    # Expansion alone is not an acceptable final relaxation: tether is stretched.
    assert not problem.metrics(x)['accepted']

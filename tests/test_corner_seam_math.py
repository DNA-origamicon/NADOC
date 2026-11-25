"""Acceleration must retain the exact arithmetic order of the approved fit."""

import numpy as np

from backend.core.corner_seam_math import cross, scatter_add, clearance_gradient


def test_accumulation_and_cross_products_match_numpy_bit_for_bit():
    rng = np.random.default_rng(414)
    indices = rng.integers(0, 17, 5000)
    values = rng.normal(size=(5000, 3)) * 10.**rng.integers(-12, 12, (5000, 3))
    expected = np.zeros((17, 3))
    actual = expected.copy()
    np.add.at(expected, indices, values)
    scatter_add(actual, indices, values)
    np.testing.assert_array_equal(actual, expected)
    a, b = rng.normal(size=(2, 100, 3))
    np.testing.assert_array_equal(cross(a, b), np.cross(a, b))
    np.testing.assert_array_equal(cross(a[0], b[0]), np.cross(a[0], b[0]))


def test_compiled_bridge_preserves_scalar_powers_norms_and_gradients():
    from backend.core.atomistic_helpers import _backbone_bridge_cost_grad
    from backend.core.corner_seam_bridge_math import bridge_cost_grad

    rng = np.random.default_rng(481)
    samples = [*rng.normal(size=(1500, 5, 3)), np.zeros((5, 3)),
               np.full((5, 3), 1e-14)]
    for points in samples:
        expected = _backbone_bridge_cost_grad(*points)
        actual = bridge_cost_grad(*points)
        assert actual[0] == expected[0]
        np.testing.assert_array_equal(actual[1:], expected[1:])


def test_pair_clearance_preserves_norms_reduction_and_scatter_order():
    rng = np.random.default_rng(441)
    xyz = rng.normal(size=(200, 3)) * .1
    pairs = rng.integers(0, 200, (20000, 2))
    expected = rng.normal(size=xyz.shape)
    actual = expected.copy()
    i, j = pairs.T
    delta = xyz[i]-xyz[j]
    distance = np.linalg.norm(delta, axis=1)
    penetration = np.minimum(distance-.20, 0.)
    g = (2*penetration/np.maximum(distance, 1e-12))[:, None]*delta
    np.add.at(expected, i, g)
    np.add.at(expected, j, -g)
    result = clearance_gradient(xyz, pairs, actual)
    np.testing.assert_array_equal(result, penetration)
    np.testing.assert_array_equal(actual, expected)


def test_seed_bridge_cost_matches_native_finite_difference_objective_exactly():
    from backend.core.atomistic_helpers import _backbone_bridge_cost
    from backend.core.corner_seam_bridge_math import bridge_cost

    rng = np.random.default_rng(821)
    samples = [*rng.normal(size=(2000, 5, 3)), np.zeros((5, 3)),
               np.full((5, 3), 1e-14)]
    for points in samples:
        assert bridge_cost(*points) == _backbone_bridge_cost(*points)
        # Exercise the actual perturbation scale used by the seed fit too.
        points[1, 0] += 1e-8
        assert bridge_cost(*points) == _backbone_bridge_cost(*points)

"""Check the gradient driving chirality constraints before native preparation."""

import numpy as np

from experiments.cpd_anti_additive.chiral_constraints import SignedVolumes, volumes_and_derivatives


def test_volume_derivative_matches_independent_central_differences():
    x = np.array([[.2, .3, -.1], [1.4, -.1, .2], [-.4, 1.7, .5], [.3, .6, 1.8]])
    volume, gradient = volumes_and_derivatives(x)
    assert volume > 0
    numerical = np.empty_like(x)
    step = 1e-6
    for i in range(4):
        for axis in range(3):
            p, m = x.copy(), x.copy()
            p[i, axis] += step; m[i, axis] -= step
            # Homogeneous determinant is independent of the analytic cross-product formula.
            def determinant(z):
                return -np.linalg.det(np.column_stack((z, np.ones(4))))
            numerical[i, axis] = (determinant(p)-determinant(m))/(2*step)
    np.testing.assert_allclose(gradient, numerical, atol=2e-9, rtol=2e-9)
    np.testing.assert_allclose(gradient.sum(axis=0), 0, atol=1e-14)


def test_mobile_mapping_retains_fixed_atoms_and_detects_reflection():
    x = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.], [5., 6., 7.]])
    mobile = [3, 1]
    constraint = SignedVolumes(x, mobile, [[0, 1, 2, 3]], [1])
    flat = x[mobile].ravel()
    np.testing.assert_allclose(constraint.values(flat), [1])
    np.testing.assert_allclose(constraint.jacobian(flat).toarray(), [[0, 0, 1, 1, 0, 0]])
    reflected = flat.copy(); reflected[2] = -1
    assert constraint.values(reflected)[0] == -1
    np.testing.assert_array_equal(constraint.positions(reflected)[[0, 2, 4]], x[[0, 2, 4]])

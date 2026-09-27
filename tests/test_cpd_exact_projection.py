from types import SimpleNamespace

import numpy as np
import pytest

from experiments.cpd_anti_additive.exact_constraint_projection import exact_gradient_projection


class MovingNormal:
    def derivative(self, xyz):
        return 2*np.asarray(xyz)


def test_projection_uses_current_geometry_and_preserves_tangent_gradient():
    internals = SimpleNamespace(rigid=False, Prims=SimpleNamespace(cPrims=[MovingNormal()]))
    xyz = np.array([[1., 2., 3.], [-2., 1., .5]])
    tangent = np.array([[2., -1., 0.], [1., 2., 0.]])
    normal = 2*xyz
    gradient = tangent+3.7*normal
    projected = exact_gradient_projection(internals, xyz.ravel(), gradient.ravel())
    np.testing.assert_allclose(projected, tangent.ravel(), atol=2e-15)
    displaced = xyz.copy(); displaced[0, 0] += .7
    updated = exact_gradient_projection(internals, displaced.ravel(), gradient.ravel())
    assert not np.allclose(updated, projected)
    assert abs(updated @ displaced.ravel()) < 1e-13


def test_unsupported_or_degenerate_constraints_fail_closed():
    for rigid, primitives in [(True, [MovingNormal()]), (False, []), (False, [MovingNormal(), MovingNormal()])]:
        with pytest.raises(ValueError):
            exact_gradient_projection(SimpleNamespace(rigid=rigid, Prims=SimpleNamespace(cPrims=primitives)),
                                      np.ones(6), np.ones(6))
    with pytest.raises(ValueError, match='Degenerate'):
        exact_gradient_projection(SimpleNamespace(rigid=False, Prims=SimpleNamespace(cPrims=[MovingNormal()])),
                                  np.zeros(6), np.ones(6))

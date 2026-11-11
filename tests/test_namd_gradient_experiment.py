"""Pure checks for the isolated graded-shell pilot (no native simulations)."""

import numpy as np
import pytest
from experiments.namd_submodel_gradient.run import ramp


def test_gradient_has_zero_inner_slope_and_saturates_before_fixed_outer_layer():
    x = np.linspace(0, 3, 301)
    k = ramp(x)
    assert k[0] == 0 and k[-1] == 0.5
    assert np.all(np.diff(k) >= -1e-15)
    assert np.all(k[x >= 2.7] == 0.5)
    assert ramp([1e-5])[0] < 1e-10
    assert 0.5 - ramp([2.7 - 1e-5])[0] < 1e-10
    np.testing.assert_allclose(ramp([1.35]), [0.25])


def test_invalid_gradient_width_is_rejected():
    with pytest.raises(ValueError):
        ramp([0, 1], width=0.3, fixed_layer=0.3)

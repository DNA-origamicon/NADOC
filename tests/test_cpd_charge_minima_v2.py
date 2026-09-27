"""Numerical edge cases for the water-minimum fitting objective."""

import numpy as np
import pytest

from experiments.cpd_anti_additive.charge_fit_v2 import minimum


def test_subgrid_minimum_recovers_energy_and_distance():
    x = np.arange(1.1, 5.01, .02)
    r, e, bracketed = minimum(x, 7.3*(x-2.713)**2-4.812)
    assert bracketed
    assert r == pytest.approx(2.713, abs=1e-10)
    assert e == pytest.approx(-4.812, abs=1e-10)


def test_boundary_minimum_is_not_accepted_as_bracketed():
    x = np.arange(1.1, 5.01, .02)
    _, _, bracketed = minimum(x, -x)
    assert not bracketed

"""Analytic and symmetry checks of the independent literature reference."""
import math

import numpy as np
import pytest

from tools.oxdna_peg.chudoba_reference import (
    bonded_energy, chain_energy, finite_difference_forces,
    pair_energy_derivative, parameters,
)


@pytest.mark.parametrize('temperature', [294, 320, 347, 371, 396,
    math.log(8/54)/math.log(.9943)])
def test_pair_force_and_mie_limit(temperature):
    for r in [.35, .41, .5, .69, .82, .899]:
        energy, derivative = pair_energy_derivative(r, temperature)
        h = 1e-6
        fd = (pair_energy_derivative(r+h, temperature)[0]
              - pair_energy_derivative(r-h, temperature)[0])/(2*h)
        assert derivative == pytest.approx(fd, rel=2e-7, abs=1e-7)
        p = parameters(temperature)
        n, m = p['n'], p['m']
        if abs(n-m) > 1e-6:
            literal = n/(n-m)*(n/m)**(m/(n-m))*p['epsilon']*((p['sigma']/r)**n-(p['sigma']/r)**m)
            literal += p['gamma']*math.exp(-((r-p['mu'])/p['delta'])**2)
            assert energy == pytest.approx(literal, abs=1e-10)
        else:
            assert energy == pytest.approx(pair_energy_derivative(r, temperature+1e-5)[0], rel=2e-6)
    assert pair_energy_derivative(.9, temperature) == (0, 0)


def test_chain_rigid_motion_and_force_symmetry():
    xyz = np.array([[0,0,0], [.33,0,0], [.51,.27,0], [.7,.36,.25], [.91,.18,.4]])
    q, _ = np.linalg.qr(np.random.default_rng(7).normal(size=(3,3)))
    assert chain_energy(xyz,294) == pytest.approx(chain_energy(xyz@q + 5,294))
    forces = finite_difference_forces(xyz,294)
    assert np.linalg.norm(forces.sum(axis=0)) < 1e-6
    assert np.linalg.norm(np.cross(xyz,forces).sum(axis=0)) < 1e-6
    assert np.allclose(finite_difference_forces(xyz@q,294), forces@q, atol=1e-6)


def test_equilibrium_bond_and_angle():
    assert bonded_energy([[0,0,0],[.33,0,0]]) == pytest.approx(0)
    t = math.radians(50)
    xyz = [[0,0,0],[.33,0,0],[.33+.33*math.cos(t),.33*math.sin(t),0]]
    assert bonded_energy(xyz) == pytest.approx(0, abs=1e-20)

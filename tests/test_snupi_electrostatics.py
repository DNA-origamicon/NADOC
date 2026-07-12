"""Unit tests for the SNUPI Debye–Hückel electrostatics module (SI S6/S7).

Proves the physics by finite differences (force = −∇Π, stiffness = ∇²Π) and pins the
characteristic values against SNUPI's cited numbers (λ_D, q, r_cut, l_B).  Pure module —
no solver, no topology.
"""
from __future__ import annotations

import math

import numpy as np

from backend.physics import snupi_electrostatics as es


def test_characteristic_values_match_snupi_si():
    # SI S7: q = 0.7 e at 20 mM MgCl₂, r_cut = 2.5 nm; Bjerrum ≈ 0.71 nm (water, 300 K).
    assert abs(es.bjerrum_length_nm(300.0) - 0.714) < 0.01
    # Debye length at 20 mM MgCl₂ (I = 3·0.02 = 0.06 M) ≈ 1.24 nm.
    lam = es.debye_length_nm(es.ionic_strength_mgcl2_M(0.02))
    assert abs(lam - 1.24) < 0.05
    assert es.ionic_strength_mgcl2_M(0.02) == 0.06
    prm = es.ESParams.for_conditions(mgcl2_M=0.02, q_eff=0.7)
    assert prm.r_cut == 2.5
    assert abs(prm.lambda_d - lam) < 1e-9
    # 100 mM has a shorter screening length than 20 mM.
    assert es.debye_length_nm(es.ionic_strength_mgcl2_M(0.1)) < lam


def test_energy_is_positive_repulsive_and_decays():
    prm = es.ESParams.for_conditions()
    e1, e2 = es.pair_energy(1.5, prm), es.pair_energy(2.5, prm)
    assert e1 > e2 > 0                      # repulsive, decays with distance
    # Beyond a few Debye lengths it is negligible vs near-contact.
    assert es.pair_energy(2.5, prm) < 0.5 * es.pair_energy(1.5, prm)


def test_force_equals_negative_energy_gradient_finite_difference():
    """f_j = −∂Π/∂x_j, verified against a central finite difference of Π(|x_j−x_i|)."""
    prm = es.ESParams.for_conditions()
    xi = np.array([0.0, 0.0, 0.0])
    xj = np.array([2.0, 0.6, -0.3])        # generic separation ~2.13 nm < r_cut
    f_j, _ = es.pair_force_stiffness(xj - xi, prm)
    h = 1e-6
    grad = np.zeros(3)
    for d in range(3):
        p, m = xj.copy(), xj.copy()
        p[d] += h; m[d] -= h
        grad[d] = (es.pair_energy(np.linalg.norm(p - xi), prm)
                   - es.pair_energy(np.linalg.norm(m - xi), prm)) / (2 * h)
    assert np.allclose(f_j, -grad, atol=1e-4)
    # Repulsion points from i toward j (outward).
    assert np.dot(f_j, (xj - xi) / np.linalg.norm(xj - xi)) > 0


def test_stiffness_equals_force_jacobian_finite_difference():
    """K_jj = ∂²Π/∂x_j² = −∂f_j/∂x_j, verified by differencing the force."""
    prm = es.ESParams.for_conditions()
    xi = np.array([0.0, 0.0, 0.0])
    xj = np.array([1.8, 0.4, 0.5])
    _, K = es.pair_force_stiffness(xj - xi, prm)
    h = 1e-6
    Jac = np.zeros((3, 3))                  # ∂f_j / ∂x_j
    for d in range(3):
        p, m = xj.copy(), xj.copy()
        p[d] += h; m[d] -= h
        fp, _ = es.pair_force_stiffness(p - xi, prm)
        fm, _ = es.pair_force_stiffness(m - xi, prm)
        Jac[:, d] = (fp - fm) / (2 * h)
    # K is the energy Hessian = −∂f/∂x.
    assert np.allclose(K, -Jac, atol=1e-3)
    assert np.allclose(K, K.T, atol=1e-9)   # symmetric


def test_inter_helix_pairs_exclude_same_helix_and_respect_cutoff():
    # Two parallel helices 2.0 nm apart, 3 nodes each along x; same-helix spacing 0.34 nm.
    pos = []
    hid = []
    for k in range(3):
        pos.append([0.34 * k, 0.0, 0.0]); hid.append("h0")
        pos.append([0.34 * k, 2.0, 0.0]); hid.append("h1")
    pos = np.array(pos)
    pairs = es.inter_helix_pairs(hid, pos, r_cut=2.5)
    # Every returned pair is cross-helix and within cutoff; no same-helix pair.
    for i, j in pairs:
        assert hid[i] != hid[j]
        assert np.linalg.norm(pos[i] - pos[j]) <= 2.5 + 1e-9
    # The 3 directly-facing pairs (2.0 nm) are included; a 3.0 nm gap would be excluded.
    assert len(pairs) >= 3
    pos_far = pos.copy(); pos_far[1::2, 1] = 3.0     # push h1 to 3.0 nm
    assert es.inter_helix_pairs(hid, pos_far, r_cut=2.5) == []


def test_assemble_scale_zero_is_empty_and_force_balances():
    prm = es.ESParams.for_conditions()
    hid = ["h0", "h1"]
    pos = np.array([[0.0, 0.0, 0.0], [0.0, 2.0, 0.0]])
    rows, cols, vals, f = es.assemble_electrostatics(hid, pos, prm, scale=0.0)
    assert not rows and not cols and not vals and not np.any(f)
    # scale=1: equal-and-opposite forces (Newton's third law) → net force zero.
    _, _, _, f1 = es.assemble_electrostatics(hid, pos, prm, scale=1.0)
    net = f1.reshape(-1, 6)[:, :3].sum(axis=0)
    assert np.allclose(net, 0.0, atol=1e-9)
    # The two nodes are pushed apart along +y / −y.
    assert f1[6 + 1] > 0 and f1[1] < 0

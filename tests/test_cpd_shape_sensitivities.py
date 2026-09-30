"""Analytic counterexamples for the diagnostic minimax parameter proposal."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.review_shape_sensitivities_v1 import gate_values, propose


def problem():
    # 23 relative energies, one Cartesian shape block, 23 proper maxima,
    # and six representative maxima. Unused gates are safely zero.
    blocks = [slice(0, 23), slice(23, 26)]
    return np.zeros(55), np.zeros((55, 1)), blocks, slice(26, 49), slice(49, 55)


def test_tradeoff_known_solution():
    r, jac, blocks, torsions, reps = problem()
    # Opposing energy errors are 2+x and 4-x. Their minimax solution is x=1,
    # with max-energy/2=1.5; the RMS energy constraint is less restrictive.
    r[:2] = np.array([2., 4.]) / np.sqrt(23)
    jac[:2, 0] = np.array([1., -1.]) / np.sqrt(23)
    result = propose(r, jac, np.zeros(1), 3., blocks, torsions, reps)
    assert result['success']
    assert result['parameters'][0] == pytest.approx(1., abs=1e-6)
    assert result['predicted_max_gate_ratio'] == pytest.approx(1.5, abs=1e-6)


def test_original_baseline_bound_not_reset_at_new_center():
    r, jac, blocks, torsions, reps = problem()
    r[23] = 2. / np.sqrt(23)
    jac[23, 0] = -1. / np.sqrt(23)
    result = propose(r, jac, np.array([4.9]), 3., blocks, torsions, reps)
    assert result['success']
    assert result['parameters'][0] == pytest.approx(5., abs=1e-7)
    assert result['predicted_max_gate_ratio'] == pytest.approx(1.9, abs=1e-6)


def test_each_gate_can_block_a_small_total_energy_error():
    r, _, blocks, torsions, reps = problem()
    r[23] = 1.01 / np.sqrt(23)
    assert max(gate_values(r, blocks, torsions, reps)) == pytest.approx(1.01)
    r[:] = 0
    r[49] = 1.03 / np.sqrt(3)
    assert max(gate_values(r, blocks, torsions, reps)) == pytest.approx(1.03)

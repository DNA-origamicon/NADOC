import math
import numpy as np
from experiments.cpd_anti_additive.readiness_fit_v3 import layout, gate_values, propose


def fixture():
    blocks, torsions, reps = layout([{'elements': ['C', 'H']}] * 24)
    return blocks, torsions, reps, np.zeros(reps.stop)


def test_added_target_does_not_hide_legacy_energy_failure():
    blocks, torsions, reps, residual = fixture()
    residual[:23] = 1.01 / math.sqrt(24)
    ratios = gate_values(residual, blocks, torsions, reps)
    assert ratios[0] < 1 < ratios[1]


def test_all_six_representative_limits_are_included():
    blocks, torsions, reps, residual = fixture()
    assert reps.stop - reps.start == 6
    residual[reps.stop - 1] = 1.2 / math.sqrt(3)
    assert np.isclose(max(gate_values(residual, blocks, torsions, reps)), 1.2)


def test_proposal_includes_last_representative_limit():
    blocks, torsions, reps, residual = fixture()
    residual[reps.stop - 1] = 1.2 / math.sqrt(3)
    jac = np.zeros((len(residual), 22))
    jac[-1, 0] = 1 / math.sqrt(3)
    result = propose(residual, jac, np.zeros(22), .5, blocks, torsions, reps)
    assert result['success']
    assert result['predicted_max_gate_ratio'] <= 1
    assert result['parameters'][0] < -.19

"""Check scan derivative units and reject malformed quantum results."""

import numpy as np
import pytest
from experiments.cpd_drude_recovery.assess_h6_scan import qm_values


def test_directional_derivative_converts_bohr_to_angstrom():
    gradient = np.zeros((36, 3))
    gradient[0, 0] = 1
    direction = np.zeros((36, 3))
    direction[0, 0] = 0.25
    energy, projected = qm_values(
        {"energy_hartree": 1, "gradient_hartree_bohr": gradient.tolist()}, direction
    )
    assert energy == pytest.approx(627.5094740631)
    assert projected == pytest.approx(0.25 * 627.5094740631 / 0.529177210903)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_reject_nonfinite_energy(value):
    with pytest.raises(ValueError):
        qm_values(
            {
                "energy_hartree": value,
                "gradient_hartree_bohr": np.zeros((36, 3)).tolist(),
            },
            np.zeros((36, 3)),
        )


def test_reject_wrong_gradient_shape():
    with pytest.raises(ValueError):
        qm_values(
            {"energy_hartree": 0, "gradient_hartree_bohr": np.zeros((35, 3)).tolist()},
            np.zeros((36, 3)),
        )

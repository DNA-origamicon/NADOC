import math
from pathlib import Path

import numpy as np
import pytest

from backend.parameterization.photoproduct_nonbonded_fit import (
    _constraint_matrix,
    _hypothesis_fit_summary,
    _quadratic_grid_minimum,
    _solve_constrained_least_squares,
    parse_charmm_nonbonded,
)


def test_parse_charmm_nonbonded_stops_before_nbfix(tmp_path: Path):
    path = tmp_path / "test.prm"
    path.write_text(
        "BONDS\nC H 100 1.0\n"
        "NONBONDED nbxmod 5\n"
        "CUTNB 14.0\n"
        "CT 0.0 -0.0320 2.0000\n"
        "HT 0.0 -0.0450 1.3400 0.0 -0.0200 1.2500 ! comment\n"
        "NBFIX\nCT OT -0.1 3.0\n"
    )
    parsed = parse_charmm_nonbonded(path)
    assert parsed == {
        "CT": {"epsilon_kcal_mol": -0.032, "rmin_half_angstrom": 2.0},
        "HT": {
            "epsilon_kcal_mol": -0.045,
            "rmin_half_angstrom": 1.34,
            "epsilon_14_kcal_mol": -0.02,
            "rmin_half_14_angstrom": 1.25,
        },
    }


def test_constrained_solver_enforces_redundant_charge_equalities():
    atom_map = ["1:A", "2:A", "1:B", "2:B"]
    constraints, values = _constraint_matrix(
        atom_map,
        {
            "total_charge": {"atoms": atom_map, "value_e": 0.0},
            "neutral_n1_methyl_caps": [
                {"atoms": ["1:A", "1:B"], "value_e": 0.0},
                {"atoms": ["2:A", "2:B"], "value_e": 0.0},
            ],
            "equal_charge_groups": [["1:A", "2:A"], ["1:B", "2:B"]],
        },
    )
    design = np.eye(4)
    charges, diagnostics = _solve_constrained_least_squares(
        design, np.asarray([0.2, 0.3, -0.1, -0.4]), constraints, values
    )
    assert np.max(np.abs(constraints @ charges - values)) < 1e-10
    assert charges[0] == pytest.approx(charges[1])
    assert charges[2] == pytest.approx(charges[3])
    assert charges[0] == pytest.approx(-charges[2])
    assert diagnostics["independent_charge_variables"] == 1


def test_quadratic_grid_minimum_recovers_subgrid_vertex():
    distance, energy = _quadratic_grid_minimum(
        np.asarray([1.8, 2.0, 2.2]),
        np.asarray([-3.96, -4.0, -3.96]),
    )
    assert distance == pytest.approx(2.0)
    assert energy == pytest.approx(-4.0)


def test_hypothesis_summary_separates_training_and_held_out_without_selection():
    result = {
        "hypothesis_id": "candidate-a",
        "maximum_charge_change_e": 0.12,
        "dipole_vector_error_debye": 1.5,
        "esp_validation": {"rmse_atomic_unit": 0.01},
        "solver": {"nonlinear_refinement": {"cost": 4.0}},
        "water_metrics": [
            {
                "split": "training",
                "energy_error_kcal_mol": 0.3,
                "distance_error_angstrom": -0.1,
            },
            {
                "split": "training",
                "energy_error_kcal_mol": -0.4,
                "distance_error_angstrom": 0.1,
            },
            {
                "split": "held_out",
                "energy_error_kcal_mol": 0.2,
                "distance_error_angstrom": 0.05,
            },
        ],
    }

    summary = _hypothesis_fit_summary(result)

    assert summary["hypothesis_id"] == "candidate-a"
    assert summary["water"]["training"]["energy_rmse_kcal_mol"] == pytest.approx(
        math.sqrt(0.125)
    )
    assert summary["water"]["training"]["maximum_absolute_energy_error_kcal_mol"] == 0.4
    assert summary["water"]["held_out"]["site_count"] == 1

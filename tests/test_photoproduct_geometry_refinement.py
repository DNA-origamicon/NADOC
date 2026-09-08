from __future__ import annotations

import numpy as np
import pytest

from backend.parameterization.photoproduct_geometry_refinement import (
    _aligned_difference,
    geometry_variable_indices,
)


def _parameters() -> list[dict]:
    return [
        {
            "name": "bond-r2",
            "group_id": "bond:a-b",
            "category": "bonds",
            "basis": "r^2",
            "lower_bound": 0.0,
            "upper_bound": 300.0,
        },
        {
            "name": "bond-r",
            "group_id": "bond:a-b",
            "category": "bonds",
            "basis": "r",
            "lower_bound": -1200.0,
            "upper_bound": 0.0,
        },
        {
            "name": "angle-q",
            "group_id": "angle:a-b-c",
            "category": "angles",
            "basis": "theta^2",
            "lower_bound": 0.0,
            "upper_bound": 300.0,
        },
        {
            "name": "angle-l",
            "group_id": "angle:a-b-c",
            "category": "angles",
            "basis": "theta",
            "lower_bound": -1200.0,
            "upper_bound": 0.0,
        },
        {
            "name": "torsion",
            "group_id": "dihedral:a-b-c-d",
            "category": "dihedrals",
            "basis": "cos(1*phi)",
            "lower_bound": -20.0,
            "upper_bound": 20.0,
        },
        {
            "name": "improper",
            "group_id": "improper:b",
            "category": "impropers",
            "basis": "wrapped_delta^2",
            "lower_bound": 0.0,
            "upper_bound": 200.0,
        },
    ]


def test_geometry_variables_hold_curvatures_and_impropers_fixed() -> None:
    parameters = _parameters()
    coefficients = np.asarray([100.0, -300.0, 50.0, -100.0, 2.0, 20.0])
    indices, lower, upper = geometry_variable_indices(parameters, coefficients)
    assert indices.tolist() == [1, 3, 4]
    assert lower.tolist() == [-600.0, pytest.approx(-100.0 * np.pi), -20.0]
    assert upper.tolist() == [-100.0, pytest.approx(-0.001), 20.0]


def test_geometry_variables_reject_nonphysical_selected_equilibrium() -> None:
    parameters = _parameters()
    coefficients = np.asarray([100.0, -10.0, 50.0, -100.0, 2.0, 20.0])
    with pytest.raises(ValueError, match="outside physical"):
        geometry_variable_indices(parameters, coefficients)


def test_alignment_uses_proper_rotation_without_reflection() -> None:
    reference = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0]])
    rotation = np.asarray([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    moved = reference @ rotation + np.asarray([4.0, -3.0, 2.0])
    assert np.max(np.abs(_aligned_difference(reference, moved))) < 1.0e-12
    reflected = moved.copy()
    reflected[:, 2] *= -1.0
    reflected[2, 2] = 1.0
    assert np.linalg.norm(_aligned_difference(reference, reflected)) > 0.1

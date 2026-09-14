import pytest

from backend.parameterization.photoproduct_openmm_fit_basis import (
    enumerate_linear_fit_parameters,
)


def _fit_plan():
    return {
        "uncovered_parameter_groups": [
            {
                "id": "angles:A-B-C",
                "category": "angles",
                "occurrences": [{"atoms": ["1:A", "1:B", "1:C"]}],
                "variables": {
                    "k_kcal_mol_rad2": None,
                    "theta0_degrees": None,
                    "urey_bradley_k_kcal_mol_a2": None,
                    "urey_bradley_s0_angstrom": None,
                },
            },
            {
                "id": "dihedrals:A-B-C-D",
                "category": "dihedrals",
                "occurrences": [{"atoms": ["1:A", "1:B", "1:C", "1:D"]}],
                "variables": {"fourier_terms": None},
            },
        ],
        "stereochemical_impropers": [
            {
                "stereocenter": "1:B",
                "ordered_atoms_candidate": ["1:B", "1:A", "1:C", "1:D"],
                "observed_improper_degrees": -145.0,
                "status": "ordering_and_parameters_require_product_review",
            }
        ],
    }


def test_linear_fit_parameter_basis_is_explicit_and_zero_valued():
    records = enumerate_linear_fit_parameters(
        _fit_plan(), torsion_periodicities=(1, 2, 3)
    )

    assert len(records) == 4 + 3 + 2
    assert len({record["name"] for record in records}) == len(records)
    assert all(record["default"] == 0.0 for record in records)
    assert [
        record["periodicity"]
        for record in records
        if record["category"] == "dihedrals"
    ] == [1, 2, 3]
    improper = [record for record in records if record["category"] == "impropers"]
    assert {record["basis"] for record in improper} == {
        "wrapped_delta",
        "wrapped_delta^2",
    }
    assert {record["reference_degrees"] for record in improper} == {-145.0}


def test_linear_fit_parameter_basis_rejects_assigned_values_and_bad_periodicities():
    plan = _fit_plan()
    plan["uncovered_parameter_groups"][0]["variables"]["theta0_degrees"] = 110.0
    with pytest.raises(ValueError, match="assigned or malformed"):
        enumerate_linear_fit_parameters(plan)

    with pytest.raises(ValueError, match="between 1 and 6"):
        enumerate_linear_fit_parameters(_fit_plan(), torsion_periodicities=(1, 7))


def test_fixed_qm_reference_improper_uses_positive_curvature_basis_only():
    plan = _fit_plan()
    plan["stereochemical_impropers"][0]["expected_signed_volume"] = "negative"

    records = enumerate_linear_fit_parameters(
        plan,
        torsion_periodicities=(1,),
        improper_equilibrium_mode="fixed_qm_reference",
    )

    improper = [record for record in records if record["category"] == "impropers"]
    assert len(improper) == 1
    assert improper[0]["basis"] == "wrapped_delta^2"
    assert improper[0]["reference_degrees"] == -145.0
    assert improper[0]["expected_signed_volume"] == "negative"


def test_angle_basis_can_explicitly_omit_urey_bradley_coordinates():
    records = enumerate_linear_fit_parameters(
        _fit_plan(),
        torsion_periodicities=(1,),
        angle_urey_bradley_mode="omit",
    )

    angle_basis = {
        record["basis"] for record in records if record["category"] == "angles"
    }
    assert angle_basis == {"theta^2", "theta"}

"""Reject misleading completion records without running quantum calculations."""

import pytest

from experiments.cpd_drude_recovery.audit_water_results import audit_output


def example():
    energies = [-76.0, -985.0, -1061.005]
    occupations = [(1, 5, 4), (20, 74, 54), (21, 79, 58)]
    text = "Counterpoise Corrected (CP) energies\n"
    for energy, (frozen, occupied, active) in zip(energies, occupations):
        text += (
            "Energy and wave function converged.\nBlend: CC-PVQZ\n"
            f"NBF = 1695\nPAIRS {frozen} {occupied} {active} 100 100 0\n"
            f"Total Energy = {energy} [Eh]\n"
            "SCS Total Energy = -777.0 [Eh]\n"
        )
    cp = energies[2] - energies[0] - energies[1]
    result = {
        "cp_interaction_hartree": cp,
        "cp_interaction_kcal_mol": cp * 627.5094740631,
        "variables": {
            "N-BODY (2)@(1, 2) TOTAL ENERGY": energies[0],
            "N-BODY (1)@(1, 2) TOTAL ENERGY": energies[1],
            "N-BODY (1, 2)@(1, 2) TOTAL ENERGY": energies[2],
            "CP-CORRECTED INTERACTION ENERGY": cp,
        },
    }
    return text, result


def test_reconstruct_cp_without_using_scs_energy():
    text, result = example()
    assert audit_output(text, result)["reconstructed_cp_hartree"] == pytest.approx(
        -0.005
    )


@pytest.mark.parametrize(
    "defect", ["arithmetic", "basis", "convergence", "frozen_core", "nan"]
)
def test_reject_false_completion(defect):
    text, result = example()
    if defect == "arithmetic":
        result["cp_interaction_hartree"] *= 1.16
    elif defect == "basis":
        text = text.replace("NBF = 1695", "NBF = 100", 1)
    elif defect == "convergence":
        text = text.replace("Energy and wave function converged.", "SCF failed", 1)
    elif defect == "frozen_core":
        text = text.replace("PAIRS 20 74 54", "PAIRS 0 74 74")
    else:
        result["cp_interaction_kcal_mol"] = float("nan")
    with pytest.raises(ValueError):
        audit_output(text, result)


def test_triple_zeta_requires_explicit_basis_and_correct_dimension():
    text, result = example()
    text = text.replace("CC-PVQZ", "CC-PVTZ").replace("NBF = 1695", "NBF = 882")
    with pytest.raises(ValueError):
        audit_output(text, result)
    assert audit_output(text, result, orbital_basis="cc-pVTZ")[
        "reconstructed_cp_hartree"
    ] == pytest.approx(-0.005)
    with pytest.raises(ValueError):
        audit_output(
            text.replace("NBF = 882", "NBF = 1695", 1), result, orbital_basis="cc-pVTZ"
        )

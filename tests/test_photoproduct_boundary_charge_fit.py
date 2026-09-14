import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import backend.parameterization.photoproduct_boundary_charge_fit as module
from backend.parameterization.photoproduct_boundary_charge_fit import (
    fit_boundary_charges,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def test_full_boundary_fit_keeps_35_fixed_atoms_and_uses_held_out_selection(
    tmp_path: Path, monkeypatch
):
    variable_map = [
        "1:N1",
        "1:C2",
        "1:O2",
        "1:N3",
        "1:H3",
        "1:C4",
        "1:O4",
        "1:C5",
        "1:C7",
        "1:C6",
        "1:H51",
        "1:H52",
        "1:H53",
        "1:H6",
        "2:N1",
        "2:C2",
        "2:O2",
        "2:N3",
        "2:H3",
        "2:C4",
        "2:O4",
        "2:C5",
        "2:C7",
        "2:C6",
        "2:H51",
        "2:H52",
        "2:H53",
        "2:H6",
    ]
    fixed_map = [f"boundary:{index}" for index in range(35)]
    atom_map = variable_map + fixed_map
    coordinates = np.asarray(
        [[float(index % 9), float((index // 9) % 7), float(index // 63)] for index in range(63)]
    )
    xyz = tmp_path / "optimized.xyz"
    xyz.write_text(
        "63\nfixture\n"
        + "\n".join(
            f"C {x:.8f} {y:.8f} {z:.8f}" for x, y, z in coordinates
        )
        + "\n"
    )
    model = tmp_path / "model_manifest.json"
    model.write_text(
        json.dumps(
            {
                "product_id": "tt-cpd-trans-anti-i",
                "model_id": "boundary-test",
                "atom_map": atom_map,
                "outputs": {"xyz": _source(xyz)},
            }
        )
        + "\n"
    )
    cgenff = tmp_path / "cgenff.prm"
    cgenff.write_text("fixture\n")
    nucleic = tmp_path / "nucleic.prm"
    nucleic.write_text("fixture\n")
    references = tmp_path / "references.json"
    references.write_text(
        json.dumps(
            {"base_forcefield": {"parameters": {"sha256": _sha256(nucleic)}}}
        )
        + "\n"
    )
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-boundary-nonbonded-policy.v1",
                "version": "1.1.0",
                "fit_hyperparameter_grid": {
                    "esp_sigma_atomic_unit": [0.01],
                    "water_energy_sigma_kcal_mol": [0.2],
                    "water_distance_sigma_angstrom": [0.1],
                    "dipole_component_sigma_debye": [1.0],
                    "initial_charge_restraint_sigma_e": [0.1],
                    "qm_dipole_scale": 1.0,
                    "water_distance_target_offset_angstrom": -0.2,
                    "esp_group_normalization": "fixture",
                    "water_group_normalization": "fixture",
                    "regularization_group_normalization": "fixture",
                },
                "selection": {"held_out_score": "fixture"},
            }
        )
        + "\n"
    )
    fixed_records = [
        {
            "atom": key,
            "charge_e": -1.0 if index == 0 else 0.0,
            "atom_type": "FIX",
        }
        for index, key in enumerate(fixed_map)
    ]
    specification = tmp_path / "specification.json"
    specification.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-boundary-nonbonded-specification.v1",
                "status": "fit_specification_complete_not_fitted",
                "gate_effect": "none",
                "simulation_ready": False,
                "product_id": "tt-cpd-trans-anti-i",
                "model_id": "boundary-test",
                "atom_map": atom_map,
                "candidate_hypothesis_id": "charmm36-hybrid-cyclobutane-v1",
                "variable_atoms": [
                    {
                        "atom": key,
                        "initial_charge_e": 0.0,
                        "candidate_type": "VAR",
                    }
                    for key in variable_map
                ],
                "fixed_atoms": fixed_records,
                "charge_audit": {
                    "equal_charge_groups": [
                        ["1:H51", "1:H52", "1:H53"],
                        ["2:H51", "2:H52", "2:H53"],
                    ]
                },
                "evidence_partition": {
                    "water_training_site_suffixes": ["h3-donor", "o2-acceptor"],
                    "water_held_out_site_suffixes": ["o4-acceptor"],
                },
                "acceptance": {
                    "water_energy_rmse_kcal_mol": 0.2,
                    "water_distance_rmse_angstrom": 0.1,
                    "charge_sum_tolerance_e": 1e-6,
                    "maximum_charge_change_e": 0.2,
                    "dipole_vector_error_debye": 2.5,
                },
                "sources": {
                    "model_manifest": _source(model),
                    "policy": _source(policy),
                    "reference_manifest": _source(references),
                    "cgenff_parameters": _source(cgenff),
                },
            }
        )
        + "\n"
    )
    esp_audit = tmp_path / "esp_audit.json"
    esp_audit.write_text("{}\n")
    water_audits = []
    for index in range(6):
        path = tmp_path / f"water-{index}.json"
        path.write_text("{}\n")
        water_audits.append(path)

    monkeypatch.setattr(
        module,
        "_load_parameter_types",
        lambda *_args: {
            "VAR": {"epsilon_kcal_mol": -0.1, "rmin_half_angstrom": 1.5},
            "FIX": {"epsilon_kcal_mol": -0.1, "rmin_half_angstrom": 1.5},
        },
    )
    grid = np.asarray(
        [[-10.0 + index * 0.05, 20.0, 30.0] for index in range(300)]
    )
    held_out = np.arange(300) % 5 == 0
    initial = np.zeros(63)
    initial[28] = -1.0
    target_charges = initial.copy()
    target_charges[0] = 0.01
    target_charges[1] = -0.01
    inverse = 0.529177210903 / np.linalg.norm(
        grid[:, None, :] - coordinates[None, :, :], axis=2
    )
    qm_potential = inverse @ target_charges
    qm_dipole_debye = target_charges @ coordinates * module._E_ANGSTROM_TO_DEBYE
    monkeypatch.setattr(
        module,
        "_validate_esp",
        lambda **_kwargs: (
            grid,
            qm_potential,
            held_out,
            {
                "dipole": {
                    "vector": (qm_dipole_debye / module._AU_DIPOLE_TO_DEBYE).tolist()
                }
            },
        ),
    )

    def fake_curves(**_kwargs):
        result = {}
        zero_row = np.zeros(63)
        for endpoint in (1, 2):
            for suffix in ("h3-donor", "o2-acceptor", "o4-acceptor"):
                result[f"endpoint{endpoint}-{suffix}"] = {
                    "split": "held_out" if suffix == "o4-acceptor" else "training",
                    "minimum_index": 2,
                    "points": [
                        {
                            "distance_angstrom": distance,
                            "qm_target_kcal_mol": 0.0,
                            "charge_row": zero_row,
                            "lj_energy_kcal_mol": (distance - 1.8) ** 2,
                        }
                        for distance in (1.6, 1.8, 2.0, 2.2, 2.4)
                    ],
                }
        return result

    monkeypatch.setattr(module, "_load_water_curves", fake_curves)

    report = fit_boundary_charges(
        specification_path=specification,
        esp_audit_path=esp_audit,
        water_audit_paths=water_audits,
        cgenff_parameters_path=cgenff,
        nucleic_parameters_path=nucleic,
        output_path=tmp_path / "fit.json",
    )

    assert report["status"] == "candidate_selected_passed_preregistered_metrics"
    assert report["comparison"]["selected_passed_acceptance"] is True
    assert len(report["comparison"]["summaries"]) == 1
    candidate = report["results"][0]
    assert len(candidate["charges_e"]) == 63
    assert candidate["charges_e"]["boundary:0"] == -1.0
    assert sum(candidate["charges_e"][key] for key in variable_map) == pytest.approx(0.0)
    assert all(candidate["charges_e"][key] == 0.0 for key in fixed_map[1:])
    assert candidate["esp_validation"]["held_out_point_count"] == 60

import json

import pytest

from backend.parameterization.photoproduct_charge_fit import build_charge_target_bundle


def _write(path, payload):
    path.write_text(json.dumps(payload))
    return path


def _fixture(tmp_path):
    atom_map = []
    for endpoint in (1, 2):
        atom_map.extend(
            [
                f"{endpoint}:CM",
                f"{endpoint}:HCM1",
                f"{endpoint}:HCM2",
                f"{endpoint}:HCM3",
                f"{endpoint}:H51",
                f"{endpoint}:H52",
                f"{endpoint}:H53",
            ]
        )
    atom_map_path = _write(tmp_path / "atom_map.json", atom_map)
    initial = _write(
        tmp_path / "initial.json",
        {
            "schema": "nadoc.photoproduct-initial-charge-guess.v1",
            "status": "initial_guess_not_fitted",
            "product_id": "p",
            "model_id": "m",
            "initial_total_charge": 0.0,
            "atoms": [
                {"model_atom": atom, "initial_charge": 0.0} for atom in atom_map
            ],
        },
    )
    electrostatic = _write(
        tmp_path / "electrostatic.json",
        {
            "schema": "nadoc.photoproduct-electrostatic-properties-audit.v1",
            "status": "complete_candidate",
            "passed": True,
            "product_id": "p",
            "model_id": "m",
            "dipole_au": [1.0, 2.0, 3.0],
        },
    )
    calibration = _write(
        tmp_path / "calibration.json",
        {
            "schema": "nadoc.photoproduct-water-scf-calibration-audit.v1",
            "passed": True,
        },
    )
    water = []
    for endpoint in (1, 2):
        for site, target, probe in (
            ("o2-acceptor", "O2", "H1"),
            ("o4-acceptor", "O4", "H1"),
            ("h3-donor", "H3", "O"),
        ):
            site_id = f"endpoint{endpoint}-{site}"
            water.append(
                _write(
                    tmp_path / f"{site_id}.json",
                    {
                        "schema": "nadoc.photoproduct-water-interaction-series-audit.v1",
                        "status": "complete_candidate",
                        "passed": True,
                        "identity": {
                            "product_id": "p",
                            "model_id": "m",
                            "probe_id": site_id,
                            "target_atom": f"{endpoint}:{target}",
                            "probe_atom": probe,
                        },
                        "points": [{"e": 1}, {"e": 0}, {"e": 1}],
                        "minimum_point_index": 1,
                    },
                )
            )
    symmetry_pairs = [
        [key, f"2:{key.split(':', 1)[1]}"]
        for key in atom_map
        if key.startswith("1:")
    ]
    stereo = _write(
        tmp_path / "stereo.json",
        {
            "schema": "nadoc.tt-cpd-stereo-candidate-audit.v1",
            "status": "passed_candidate",
            "candidates": [
                {
                    "product_id": "p",
                    "passed": True,
                    "graph_audit": {
                        "endpoint_exchange_graph_symmetry_ignoring_chirality": True,
                        "charge_symmetry_pairs": symmetry_pairs,
                    },
                }
            ],
        },
    )
    return electrostatic, water, calibration, stereo, initial, atom_map_path


def test_charge_target_bundle_is_complete_but_fit_blocked(tmp_path):
    electrostatic, water, calibration, stereo, initial, atom_map = _fixture(tmp_path)
    report = build_charge_target_bundle(
        electrostatic_audit_path=electrostatic,
        water_audit_paths=water,
        scf_calibration_audit_path=calibration,
        stereo_candidate_audit_path=stereo,
        initial_charge_guess_path=initial,
        atom_map_path=atom_map,
        output_path=tmp_path / "bundle.json",
    )
    assert report["status"] == "targets_complete_fit_blocked"
    assert len(report["targets"]["water_interaction_curves"]) == 6
    assert len(report["constraints"]["equal_charge_groups"]) == 11
    assert len(report["targets"]["proposed_split"]["training_sites"]) == 3
    assert "Lennard-Jones" in report["scientific_warning"]


def test_charge_target_bundle_rejects_incomplete_site_coverage(tmp_path):
    electrostatic, water, calibration, stereo, initial, atom_map = _fixture(tmp_path)
    with pytest.raises(ValueError, match="must cover"):
        build_charge_target_bundle(
            electrostatic_audit_path=electrostatic,
            water_audit_paths=water[:-1],
            scf_calibration_audit_path=calibration,
            stereo_candidate_audit_path=stereo,
            initial_charge_guess_path=initial,
            atom_map_path=atom_map,
            output_path=tmp_path / "bundle.json",
        )


def test_charge_target_bundle_rejects_mismatched_optional_esp(tmp_path):
    electrostatic, water, calibration, stereo, initial, atom_map = _fixture(tmp_path)
    esp = _write(
        tmp_path / "esp.json",
        {
            "schema": "nadoc.photoproduct-esp-audit.v1",
            "status": "complete_candidate",
            "passed": True,
            "product_id": "different",
            "model_id": "m",
        },
    )
    with pytest.raises(ValueError, match="ESP target audit"):
        build_charge_target_bundle(
            electrostatic_audit_path=electrostatic,
            water_audit_paths=water,
            scf_calibration_audit_path=calibration,
            stereo_candidate_audit_path=stereo,
            esp_audit_path=esp,
            initial_charge_guess_path=initial,
            atom_map_path=atom_map,
            output_path=tmp_path / "bundle.json",
        )

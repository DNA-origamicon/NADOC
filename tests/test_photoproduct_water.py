import hashlib
import json

import numpy as np
import pytest

from backend.parameterization.photoproduct_water import (
    build_water_probe_series,
    place_tip3p_probe,
)


def test_tip3p_acceptor_and_donor_geometry_is_exact():
    acceptor, acceptor_probe = place_tip3p_probe(
        target=(1, 0, 0),
        axis_anchor=(0, 0, 0),
        plane_point=(1, 1, 0),
        role="acceptor",
        distance_angstrom=2.0,
    )
    assert acceptor_probe == "H1"
    assert np.linalg.norm(np.array(acceptor[1][1:]) - (1, 0, 0)) == pytest.approx(2.0)
    assert np.linalg.norm(np.array(acceptor[0][1:]) - acceptor[1][1:]) == pytest.approx(
        0.9572
    )

    donor, donor_probe = place_tip3p_probe(
        target=(1, 0, 0),
        axis_anchor=(0, 0, 0),
        plane_point=(1, 1, 0),
        role="donor",
        distance_angstrom=1.8,
    )
    assert donor_probe == "O"
    assert np.linalg.norm(np.array(donor[0][1:]) - (1, 0, 0)) == pytest.approx(1.8)


def test_tip3p_azimuth_rotation_preserves_axis_geometry():
    zero, _ = place_tip3p_probe(
        target=(1, 0, 0),
        axis_anchor=(0, 0, 0),
        plane_point=(1, 1, 0),
        role="acceptor",
        distance_angstrom=2.0,
    )
    rotated, _ = place_tip3p_probe(
        target=(1, 0, 0),
        axis_anchor=(0, 0, 0),
        plane_point=(1, 1, 0),
        role="acceptor",
        distance_angstrom=2.0,
        azimuth_degrees=120.0,
    )
    assert rotated[:2] == pytest.approx(zero[:2])
    oxygen = np.asarray(zero[0][1:])
    zero_side = np.asarray(zero[2][1:]) - oxygen
    rotated_side = np.asarray(rotated[2][1:]) - oxygen
    zero_perpendicular = zero_side.copy()
    rotated_perpendicular = rotated_side.copy()
    zero_perpendicular[0] = 0.0
    rotated_perpendicular[0] = 0.0
    cosine = float(
        np.dot(zero_perpendicular, rotated_perpendicular)
        / np.linalg.norm(zero_perpendicular)
        / np.linalg.norm(rotated_perpendicular)
    )
    assert cosine == pytest.approx(-0.5)


def test_reviewed_water_plan_builds_hash_linked_series(tmp_path):
    model = tmp_path / "model.xyz"
    model.write_text("4\nmodel\nO 1 0 0\nC 0 0 0\nN 1 1 0\nH 2 1 0\n")
    parent = tmp_path / "optimized_model_audit.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "test-product",
                "model_id": "test-model",
                "optimized_xyz": {
                    "sha256": hashlib.sha256(model.read_bytes()).hexdigest()
                },
            }
        )
    )
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-water-probe-plan.v1",
                "status": "reviewed",
                "product_id": "test-product",
                "model_id": "test-model",
                "reviewed_by": "unit-test reviewer",
                "review_rationale": "synthetic carbonyl direction",
                "atom_map": ["O", "C", "N", "H"],
                "sites": [
                    {
                        "id": "acceptor-o",
                        "role": "acceptor",
                        "target_atom": "O",
                        "axis_anchor_atom": "C",
                        "plane_atom": "N",
                        "distances_angstrom": [1.6, 1.8, 2.0, 2.2, 2.4],
                    }
                ],
            }
        )
    )
    series = build_water_probe_series(
        plan_path=plan,
        model_xyz_path=model,
        parent_manifest_path=parent,
        output_dir=tmp_path / "series",
        memory_gib=2,
        threads=2,
    )
    assert series["status"] == "generated_not_run"
    assert series["gate_effect"] == "none"
    assert len(series["jobs"]) == 5
    child = json.loads(
        (tmp_path / "series/acceptor-o/p00-1.600A/job_manifest.json").read_text()
    )
    assert child["probe_atom"] == "H1"
    assert child["target_probe_distance_angstrom"] == pytest.approx(1.6)


def test_unreviewed_water_plan_fails_closed(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"schema": "nadoc.photoproduct-water-probe-plan.v1"}))
    with pytest.raises(ValueError, match="reviewed or quantitatively screened"):
        build_water_probe_series(
            plan_path=plan,
            model_xyz_path=tmp_path / "missing.xyz",
            parent_manifest_path=tmp_path / "missing.json",
            output_dir=tmp_path / "series",
        )

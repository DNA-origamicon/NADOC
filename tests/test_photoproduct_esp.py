import hashlib
import json
from pathlib import Path

import pytest

from backend.parameterization.photoproduct_esp import (
    audit_esp_job,
    build_esp_grid,
    generate_esp_job,
)


ROOT = Path(__file__).resolve().parents[1]
ESP_PROTOCOL_V1_6 = (
    ROOT / "backend/data/forcefield/photoproduct_qm_protocol_v1.6.0.json"
)


def test_esp_grid_is_deterministic_and_excludes_buried_points():
    atoms = [("C", 0.0, 0.0, 0.0), ("O", 1.2, 0.0, 0.0)]
    first = build_esp_grid(atoms, radius_scales=[1.4, 1.8], directions_per_atom=20)
    second = build_esp_grid(atoms, radius_scales=[1.4, 1.8], directions_per_atom=20)
    assert first == second
    assert 8 <= len(first) < 80


def test_generate_esp_job_requires_matching_passed_parent(tmp_path):
    xyz = tmp_path / "model.xyz"
    xyz.write_text("2\nmodel\nC 0 0 0\nO 1.2 0 0\n")
    parent = tmp_path / "parent.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "p",
                "model_id": "m",
                "optimized_xyz": {
                    "sha256": hashlib.sha256(xyz.read_bytes()).hexdigest()
                },
            }
        )
    )
    manifest = generate_esp_job(
        product_id="p",
        model_id="m",
        xyz_path=xyz,
        atom_map=["C", "O"],
        parent_manifest_path=parent,
        output_dir=tmp_path / "job",
        memory_gib=2,
        threads=2,
    )
    assert manifest["job_kind"] == "electrostatic_potential"
    assert manifest["expected_outputs"] == ["output.dat", "grid_esp.dat"]
    assert manifest["grid"]["point_count"] > 8


def test_protocol_1_6_combines_grid_esp_and_dipole(tmp_path):
    xyz = tmp_path / "model.xyz"
    xyz.write_text("2\nmodel\nC 0 0 0\nO 1.2 0 0\n")
    parent = tmp_path / "parent.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "p",
                "model_id": "m",
                "optimized_xyz": {
                    "sha256": hashlib.sha256(xyz.read_bytes()).hexdigest()
                },
            }
        )
    )
    job_dir = tmp_path / "job"
    manifest = generate_esp_job(
        product_id="p",
        model_id="m",
        xyz_path=xyz,
        atom_map=["C", "O"],
        parent_manifest_path=parent,
        output_dir=job_dir,
        protocol_path=ESP_PROTOCOL_V1_6,
    )

    assert manifest["protocol_version"] == "1.6.0"
    assert manifest["properties"] == ["GRID_ESP", "DIPOLE"]
    assert manifest["dipole_units"] == "atomic_unit_e_bohr"
    rendered = (job_dir / "input.dat").read_text()
    assert "oeprop(wavefunction, 'GRID_ESP', 'DIPOLE')" in rendered
    assert "NADOC_DIPOLE_AU" in rendered


def test_esp_audit_requires_declared_dipole_and_preserves_it(tmp_path):
    xyz = tmp_path / "model.xyz"
    xyz.write_text("2\nmodel\nC 0 0 0\nO 1.2 0 0\n")
    parent = tmp_path / "parent.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "p",
                "model_id": "m",
                "optimized_xyz": {
                    "sha256": hashlib.sha256(xyz.read_bytes()).hexdigest()
                },
            }
        )
    )
    job_dir = tmp_path / "job"
    generate_esp_job(
        product_id="p",
        model_id="m",
        xyz_path=xyz,
        atom_map=["C", "O"],
        parent_manifest_path=parent,
        output_dir=job_dir,
        protocol_path=ESP_PROTOCOL_V1_6,
    )
    point_count = len((job_dir / "grid.dat").read_text().splitlines())
    (job_dir / "grid_esp.dat").write_text("\n".join(["0.01"] * point_count) + "\n")
    (job_dir / "output.dat").write_text(
        "NADOC_DIPOLE_AU -0.500000000000 0.250000000000 0.000000000000\n"
    )
    manifest_path = job_dir / "job_manifest.json"
    outputs = {}
    for name in ("output.dat", "grid_esp.dat"):
        path = job_dir / name
        outputs[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (job_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "completed_unreviewed",
                "job_manifest_sha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
                "outputs": outputs,
            }
        )
    )

    audit = audit_esp_job(job_dir)

    assert audit["passed"] is True
    assert audit["dipole"]["required"] is True
    assert audit["dipole"]["vector"] == [-0.5, 0.25, 0.0]


def test_esp_grid_rejects_unknown_bondi_element():
    with pytest.raises(ValueError, match="Bondi radii"):
        build_esp_grid(
            [("Xe", 0.0, 0.0, 0.0)],
            radius_scales=[1.4],
            directions_per_atom=20,
        )

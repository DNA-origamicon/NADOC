import hashlib
import json

import pytest

from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.parameterization.photoproduct_hessian import build_hessian_target_bundle


def _write_evidence(tmp_path):
    definition = load_chemical_definition("TT-CPD", "cis-syn")
    atom_map = sorted(
        {
            atom
            for bond in definition["precursor_local_connectivity"]["bonds"]
            for atom in bond
        }
    )
    xyz = tmp_path / "optimized.xyz"
    xyz.write_text(
        "\n".join(
            [str(len(atom_map)), "synthetic hash-chain fixture"]
            + [f"C {index * 0.1} 0.0 0.0" for index in range(len(atom_map))]
        )
        + "\n"
    )
    dimension = 3 * len(atom_map)
    hessian = tmp_path / "hessian_hartree_per_bohr2.txt"
    hessian.write_text(
        "\n".join(
            " ".join("1.0" if i == j else "0.0" for j in range(dimension))
            for i in range(dimension)
        )
        + "\n"
    )
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "test-model",
        "job_kind": "frequency",
        "atom_count": len(atom_map),
        "atom_map": atom_map,
        "source_xyz": {
            "path": str(xyz),
            "sha256": hashlib.sha256(xyz.read_bytes()).hexdigest(),
        },
    }
    (tmp_path / "job_manifest.json").write_text(json.dumps(job))
    audit = {
        "schema": "nadoc.photoproduct-frequency-audit.v1",
        "status": "passed_harmonic_minimum",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "test-model",
        "cartesian_hessian": {
            "status": "passed",
            "units": "hartree/bohr^2",
            "sha256": hashlib.sha256(hessian.read_bytes()).hexdigest(),
        },
    }
    (tmp_path / "frequency_audit.json").write_text(json.dumps(audit))
    return hessian


def test_hessian_bundle_retains_raw_coupled_response_and_stable_identity(tmp_path):
    _write_evidence(tmp_path)
    report = build_hessian_target_bundle(
        frequency_job_dir=tmp_path, output_path=tmp_path / "targets.json"
    )
    assert report["status"] == "complete_candidate_evidence"
    assert report["gate_effect"] == "none"
    assert report["coordinate_targets"]["bonds"]
    assert report["coordinate_targets"]["angles"]
    assert report["cartesian_hessian"]["maximum_symmetry_error"] == 0.0
    assert "No diagonal projection" in report["fit_policy"]


def test_hessian_bundle_rejects_hash_mismatch(tmp_path):
    hessian = _write_evidence(tmp_path)
    hessian.write_text("changed\n")
    with pytest.raises(ValueError, match="hash-link"):
        build_hessian_target_bundle(
            frequency_job_dir=tmp_path, output_path=tmp_path / "targets.json"
        )


def test_hessian_bundle_uses_only_manifested_byte_identical_relocation(tmp_path):
    _write_evidence(tmp_path)
    source = tmp_path / "optimized.xyz"
    job = json.loads((tmp_path / "job_manifest.json").read_text())
    original_declared = tmp_path / "old" / "optimized.xyz"
    job["source_xyz"]["path"] = str(original_declared)
    (tmp_path / "job_manifest.json").write_text(json.dumps(job))
    provenance = tmp_path / "provenance"
    provenance.mkdir()
    relocated = provenance / "source_geometry.xyz"
    relocated.write_bytes(source.read_bytes())
    source.unlink()
    (tmp_path / "frequency_job_provenance.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-frequency-job-provenance-copy.v1",
                "status": "materialized_byte_identical",
                "gate_effect": "none",
                "frequency_job_manifest": {
                    "sha256": hashlib.sha256(
                        (tmp_path / "job_manifest.json").read_bytes()
                    ).hexdigest()
                },
                "references": {
                    "source_xyz": {
                        "original_path": str(original_declared),
                        "sha256": job["source_xyz"]["sha256"],
                        "copy": {
                            "path": "provenance/source_geometry.xyz",
                            "sha256": job["source_xyz"]["sha256"],
                        },
                    }
                },
            }
        )
    )

    report = build_hessian_target_bundle(
        frequency_job_dir=tmp_path, output_path=tmp_path / "relocated-targets.json"
    )

    assert report["source_geometry"]["relocated"] is True
    assert report["source_geometry"]["path"] == str(relocated.resolve())


def test_hessian_bundle_allows_partial_base_model_but_excludes_boundary_terms(tmp_path):
    _write_evidence(tmp_path)
    job_path = tmp_path / "job_manifest.json"
    job = json.loads(job_path.read_text())
    keep = [atom for atom in job["atom_map"] if not atom.endswith(":C1'")]
    xyz = tmp_path / "optimized.xyz"
    xyz.write_text(
        "\n".join(
            [str(len(keep)), "base-only model"]
            + [f"C {index * 0.1} 0.0 0.0" for index in range(len(keep))]
        )
        + "\n"
    )
    job["atom_map"] = keep
    job["atom_count"] = len(keep)
    job["source_xyz"]["sha256"] = hashlib.sha256(xyz.read_bytes()).hexdigest()
    job_path.write_text(json.dumps(job))
    dimension = 3 * len(keep)
    hessian = tmp_path / "hessian_hartree_per_bohr2.txt"
    hessian.write_text(
        "\n".join(
            " ".join("1.0" if i == j else "0.0" for j in range(dimension))
            for i in range(dimension)
        )
        + "\n"
    )
    audit_path = tmp_path / "frequency_audit.json"
    audit = json.loads(audit_path.read_text())
    audit["cartesian_hessian"]["sha256"] = hashlib.sha256(
        hessian.read_bytes()
    ).hexdigest()
    audit_path.write_text(json.dumps(audit))

    report = build_hessian_target_bundle(
        frequency_job_dir=tmp_path, output_path=tmp_path / "partial-targets.json"
    )

    assert report["status"] == "partial_candidate_evidence_boundary_model_required"
    assert report["coordinate_target_coverage"]["angles"]["excluded"] > 0
    assert report["coordinate_target_coverage"]["bonds"]["covered"] > 0
    assert all(
        "C1'" in missing
        for category in report["excluded_coordinate_targets"].values()
        for record in category
        for missing in record["missing_model_atoms"]
    )

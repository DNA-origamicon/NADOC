from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.run_local_photoproduct_response import (
    _validate_existing_response_audit,
    _validate_fixed_job_copy,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixed_job_copy_requires_matching_kind_and_immutable_bytes(
    tmp_path: Path,
) -> None:
    job_dir = tmp_path / "fixed"
    job_dir.mkdir()
    manifest = job_dir / "job_manifest.json"
    input_path = job_dir / "input.dat"
    manifest.write_text('{"job_kind":"fixed_geometry_hessian"}\n')
    input_path.write_text("immutable fixed input\n")
    plan = {
        "job_kind": "fixed_geometry_hessian",
        "fixed_geometry_hessian_job": {
            "path": str(manifest),
            "sha256": _sha256(manifest),
            "input_sha256": _sha256(input_path),
        },
    }

    record = _validate_fixed_job_copy(plan=plan, job_dir=job_dir)

    assert record["relocated"] is False
    input_path.write_text("changed\n")
    with pytest.raises(ValueError, match="byte-identical copy"):
        _validate_fixed_job_copy(plan=plan, job_dir=job_dir)
    with pytest.raises(ValueError, match="fixed-geometry plan"):
        _validate_fixed_job_copy(plan={**plan, "job_kind": "frequency"}, job_dir=job_dir)


def test_existing_response_audit_reopens_every_derivative_hash(tmp_path: Path) -> None:
    job_dir = tmp_path / "fixed"
    job_dir.mkdir()
    paths = {
        "job": job_dir / "job_manifest.json",
        "run": job_dir / "run_manifest.json",
        "gradient": job_dir / "gradient_hartree_per_bohr.txt",
        "hessian": job_dir / "hessian_hartree_per_bohr2.txt",
    }
    for label, path in paths.items():
        path.write_text(f"{label}\n")
    plan = {
        "product_id": "tt-cpd-test",
        "model_id": "model",
        "conformer": {"id": "conformer-001", "partition": "validation"},
    }
    audit_path = job_dir / "fixed_geometry_hessian_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-fixed-geometry-hessian-audit.v1",
                "status": "passed_candidate_response_evidence",
                "simulation_ready": False,
                "gate_effect": "none",
                "product_id": plan["product_id"],
                "model_id": plan["model_id"],
                "conformer_id": plan["conformer"]["id"],
                "partition": plan["conformer"]["partition"],
                "source_geometry": {"sha256": "5" * 64},
                "electronic_energy": {
                    "value": -150.0,
                    "units": "hartree",
                    "geometry_sha256": "5" * 64,
                },
                "qm_job": {"sha256": _sha256(paths["job"])},
                "effective_run_record": {"sha256": _sha256(paths["run"])},
                "cartesian_gradient": {"sha256": _sha256(paths["gradient"])},
                "cartesian_hessian": {"sha256": _sha256(paths["hessian"])},
            }
        )
        + "\n"
    )

    result = _validate_existing_response_audit(job_dir=job_dir, plan=plan)

    assert result["status"] == "passed_candidate_response_evidence"
    saved_audit = audit_path.read_text()
    missing_energy = json.loads(saved_audit)
    missing_energy.pop("electronic_energy")
    audit_path.write_text(json.dumps(missing_energy) + "\n")
    with pytest.raises(ValueError, match="stale or mismatched"):
        _validate_existing_response_audit(job_dir=job_dir, plan=plan)
    audit_path.write_text(saved_audit)
    paths["gradient"].write_text("changed\n")
    with pytest.raises(ValueError, match="stale or mismatched"):
        _validate_existing_response_audit(job_dir=job_dir, plan=plan)

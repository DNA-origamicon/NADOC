from __future__ import annotations

import hashlib
import json

import pytest

from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_qm_release import (
    ACCEPTANCE_POLICY_PATH,
    build_boundary_qm_release_audits,
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path):
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _campaigns(tmp_path):
    registry = photoproduct_registry()
    optimization = tmp_path / "optimization"
    frequency = tmp_path / "frequency"
    opt_products = []
    freq_products = []
    for entry in registry["products"]:
        product_id = entry["id"]
        model_id = f"{product_id}-dtpdt-test"
        atom_map = [f"atom-{index:02d}" for index in range(63)]
        definition_path = (
            ACCEPTANCE_POLICY_PATH.parent
            / entry["assets"]["chemical_definition"]["path"]
        )
        definition = json.loads(definition_path.read_text())

        opt_job_dir = optimization / "bundle/cases" / product_id / "job"
        opt_job_dir.mkdir(parents=True)
        opt_job = opt_job_dir / "job_manifest.json"
        opt_job.write_text(
            json.dumps(
                {
                    "schema": "nadoc.photoproduct-qm-job.v1",
                    "job_kind": "geometry_optimization",
                    "product_id": product_id,
                    "model_id": model_id,
                    "atom_count": 63,
                    "charge": -1,
                    "multiplicity": 1,
                    "atom_map": atom_map,
                }
            )
        )
        opt_run = opt_job_dir / "run_manifest.json"
        opt_run.write_text('{"schema":"nadoc.photoproduct-qm-run.v1"}\n')
        optimized = opt_job_dir / "optimized.xyz"
        optimized.write_text("63\ntest only\n")
        opt_audit = opt_job_dir / "optimized_model_audit.json"
        opt_payload = {
            "schema": "nadoc.photoproduct-optimized-model-audit.v1",
            "status": "passed_identity_and_chirality",
            "product_id": product_id,
            "model_id": model_id,
            "atom_count": 63,
            "atom_map_unique": True,
            "coordinates_finite": True,
            "final_energy_hartree": -1000.0,
            "chirality_audit": {
                "passed": True,
                "centers": [{"passed": True} for _ in range(4)],
            },
            "product_ring_bond_distances": [
                {
                    "category": category,
                    "atom_1": bond["atom_1"],
                    "atom_2": bond["atom_2"],
                    "distance_angstrom": 1.55,
                }
                for category in ("bonds_added", "bonds_retained")
                for bond in definition["graph_delta"][category]
            ],
            "effective_run_record": _record(opt_run),
            "optimized_xyz": _record(optimized),
        }
        opt_audit.write_text(json.dumps(opt_payload))
        opt_products.append(
            {
                "product_id": product_id,
                "status": "passed_identity_and_chirality",
                "optimized_model_audit": _record(opt_audit),
            }
        )

        freq_job_dir = frequency / "bundle/cases" / product_id / "job"
        freq_job_dir.mkdir(parents=True)
        freq_job = freq_job_dir / "job_manifest.json"
        freq_job.write_text(
            json.dumps(
                {
                    "schema": "nadoc.photoproduct-qm-job.v1",
                    "job_kind": "frequency",
                    "product_id": product_id,
                    "model_id": model_id,
                    "atom_count": 63,
                    "charge": -1,
                    "multiplicity": 1,
                    "atom_map": atom_map,
                }
            )
        )
        freq_run = freq_job_dir / "run_manifest.json"
        freq_run.write_text('{"schema":"nadoc.photoproduct-qm-run.v1"}\n')
        freq_output = freq_job_dir / "output.dat"
        freq_output.write_text("test-only frequency output\n")
        hessian = freq_job_dir / "hessian_hartree_per_bohr2.txt"
        hessian.write_text("test-only audited Hessian\n")
        freq_audit = freq_job_dir / "frequency_audit.json"
        freq_payload = {
            "schema": "nadoc.photoproduct-frequency-audit.v1",
            "status": "passed_harmonic_minimum",
            "product_id": product_id,
            "model_id": model_id,
            "atom_count": 63,
            "expected_mode_count": 183,
            "parsed_mode_count": 183,
            "frequency_table_complete": True,
            "imaginary_mode_count": 0,
            "lowest_frequency_cm_inverse": 12.5,
            "cartesian_hessian": {
                **_record(hessian),
                "status": "passed",
                "dimension": 189,
                "finite": True,
            },
            "effective_run_record": _record(freq_run),
            "output": _record(freq_output),
            "parent_optimized_model_audit": _record(opt_audit),
        }
        freq_audit.write_text(json.dumps(freq_payload))
        freq_products.append(
            {
                "product_id": product_id,
                "status": "passed_harmonic_minimum",
                "frequency_audit": _record(freq_audit),
            }
        )

    opt_collection = optimization / "collection_report.json"
    opt_collection.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-alpine-boundary-optimization-collection.v1",
                "status": "passed_import_and_identity_audit",
                "gate_effect": "none",
                "simulation_ready": False,
                "product_count": 8,
                "passed_product_count": 8,
                "products": opt_products,
            }
        )
    )
    freq_collection = frequency / "collection_report.json"
    freq_collection.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-alpine-boundary-frequency-collection.v1",
                "status": "passed_harmonic_minimum_audits",
                "gate_effect": "none",
                "simulation_ready": False,
                "product_count": 8,
                "passed_product_count": 8,
                "products": freq_products,
            }
        )
    )
    return optimization, frequency, freq_products


def test_build_all_form_boundary_qm_release_audits(tmp_path):
    optimization, frequency, _records = _campaigns(tmp_path)
    output = tmp_path / "release"
    result = build_boundary_qm_release_audits(
        optimization_campaign_roots=[optimization],
        frequency_campaign_root=frequency,
        output_root=output,
    )

    assert result["status"] == "passed"
    assert result["product_count"] == 8
    for item in result["products"]:
        report = json.loads((output / item["product_id"] / "qm_reference_report.json").read_text())
        assert report["passed"] is True
        assert all(report["checks"].values())
        assert report["observations"]["cartesian_hessian_dimension"] == 189


def test_boundary_qm_release_rejects_hidden_imaginary_mode(tmp_path):
    optimization, frequency, records = _campaigns(tmp_path)
    audit_path = records[0]["frequency_audit"]["path"]
    audit = json.loads(open(audit_path).read())
    audit["imaginary_mode_count"] = 1
    with open(audit_path, "w") as handle:
        json.dump(audit, handle)
    records[0]["frequency_audit"]["sha256"] = _sha256(
        frequency / "bundle/cases" / records[0]["product_id"] / "job/frequency_audit.json"
    )
    (frequency / "collection_report.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-alpine-boundary-frequency-collection.v1",
                "status": "passed_harmonic_minimum_audits",
                "gate_effect": "none",
                "simulation_ready": False,
                "product_count": 8,
                "passed_product_count": 8,
                "products": records,
            }
        )
    )

    with pytest.raises(ValueError, match="optimized_minimum_has_no_imaginary_modes"):
        build_boundary_qm_release_audits(
            optimization_campaign_roots=[optimization],
            frequency_campaign_root=frequency,
            output_root=tmp_path / "rejected",
        )

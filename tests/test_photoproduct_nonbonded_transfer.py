from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import backend.parameterization.photoproduct_nonbonded_transfer as transfer
from backend.parameterization.photoproduct_nonbonded_transfer import (
    audit_joint_nonbonded_candidate,
    summarize_transfer_metrics,
)


def _write(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_transfer_summary_uses_preregistered_rmse_targets() -> None:
    summary = summarize_transfer_metrics(
        [
            {"energy_error_kcal_mol": 0.1, "distance_error_angstrom": 0.05},
            {"energy_error_kcal_mol": -0.1, "distance_error_angstrom": -0.05},
        ]
    )

    assert summary["energy_rmse_kcal_mol"] == 0.1
    assert summary["distance_rmse_angstrom"] == 0.05
    assert summary["passed"] is True


def test_transfer_summary_reports_failure_without_relaxing_targets() -> None:
    summary = summarize_transfer_metrics(
        [{"energy_error_kcal_mol": 0.3, "distance_error_angstrom": 0.11}]
    )

    assert summary["targets"] == {
        "energy_rmse_kcal_mol": 0.2,
        "distance_rmse_angstrom": 0.1,
    }
    assert summary["passed"] is False


def test_independent_validation_rejects_training_collection_by_hash(
    tmp_path: Path,
) -> None:
    source_fit = tmp_path / "source-fit.json"
    source_hash = _write(
        source_fit,
        {"schema": "nadoc.photoproduct-nonbonded-hypothesis-fit.v1"},
    )
    collection = tmp_path / "collection.json"
    collection_hash = _write(
        collection,
        {
            "schema": "nadoc.photoproduct-alpine-water-collection.v1",
            "status": "passed_import_and_curve_audits",
            "gate_effect": "none",
        },
    )
    candidate = tmp_path / "candidate.json"
    _write(
        candidate,
        {
            "schema": "nadoc.photoproduct-joint-nonbonded-fit.v1",
            "simulation_ready": False,
            "gate_effect": "none",
            "sources": {
                "water_collection": {
                    "path": str(collection),
                    "sha256": collection_hash,
                },
                "source_fit": {"path": str(source_fit), "sha256": source_hash},
            },
        },
    )

    with pytest.raises(ValueError, match="identical to candidate training"):
        audit_joint_nonbonded_candidate(
            candidate_path=candidate,
            validation_collection_path=collection,
            cgenff_parameters_path=tmp_path / "unused-cgenff.prm",
            nucleic_parameters_path=tmp_path / "unused-nucleic.prm",
            output_path=tmp_path / "audit.json",
        )


def test_independent_validation_records_separate_evidence_and_never_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_fit = tmp_path / "source-fit.json"
    source_hash = _write(
        source_fit,
        {
            "schema": "nadoc.photoproduct-nonbonded-hypothesis-fit.v1",
            "objective": {"water_distance_target_offset_angstrom": -0.2},
        },
    )
    training = tmp_path / "training.json"
    training_hash = _write(training, {"different": "training evidence"})
    validation = tmp_path / "validation.json"
    _write(
        validation,
        {
            "schema": "nadoc.photoproduct-alpine-water-collection.v1",
            "status": "passed_import_and_curve_audits",
            "gate_effect": "none",
        },
    )
    candidate = tmp_path / "candidate.json"
    _write(
        candidate,
        {
            "schema": "nadoc.photoproduct-joint-nonbonded-fit.v1",
            "status": "candidate_passed_heldout_water_targets",
            "simulation_ready": False,
            "gate_effect": "none",
            "product_ids": ["tt-cpd-trans-syn-i"],
            "atom_types": {"1:C5": "CG2RC0"},
            "charges_e": {"1:C5": -0.1},
            "sources": {
                "water_collection": {
                    "path": str(training),
                    "sha256": training_hash,
                },
                "source_fit": {"path": str(source_fit), "sha256": source_hash},
            },
        },
    )
    cgenff = tmp_path / "cgenff.prm"
    nucleic = tmp_path / "nucleic.prm"
    cgenff.write_text("pinned")
    nucleic.write_text("pinned")
    monkeypatch.setattr(
        transfer,
        "_pinned_nonbonded",
        lambda *_: {"CG2RC0": {"epsilon": -0.1, "rmin_half": 2.0}},
    )
    metrics = {
        "passed": True,
        "site_count": 6,
        "energy_rmse_kcal_mol": 0.1,
        "distance_rmse_angstrom": 0.05,
    }
    monkeypatch.setattr(
        transfer,
        "_evaluate_charge_model_against_collection",
        lambda **_: (
            [
                {
                    "product_id": "tt-cpd-trans-syn-i",
                    "metrics": metrics,
                    "sites": [],
                }
            ],
            metrics,
        ),
    )

    output = tmp_path / "audit.json"
    report = audit_joint_nonbonded_candidate(
        candidate_path=candidate,
        validation_collection_path=validation,
        cgenff_parameters_path=cgenff,
        nucleic_parameters_path=nucleic,
        output_path=output,
    )

    assert report["passed"] is True
    assert report["simulation_ready"] is False
    assert report["gate_effect"] == "none"
    assert report["sources"]["candidate_training_collection"]["sha256"] != report[
        "sources"
    ]["validation_collection"]["sha256"]
    assert json.loads(output.read_text()) == report


def test_joint_fit_rejects_duplicate_training_collections(tmp_path: Path) -> None:
    source_fit = tmp_path / "source-fit.json"
    source_fit.write_text("{}\n")
    collection = tmp_path / "collection.json"
    collection.write_text("{}\n")
    with pytest.raises(ValueError, match="hash-distinct"):
        transfer.fit_joint_nonbonded_transfer(
            source_fit_path=source_fit,
            water_collection_path=collection,
            additional_water_collection_paths=[collection],
            frequency_root=tmp_path,
            cgenff_parameters_path=tmp_path / "cgenff.prm",
            nucleic_parameters_path=tmp_path / "na.prm",
            hypothesis_id="hypothesis",
            output_path=tmp_path / "output.json",
        )

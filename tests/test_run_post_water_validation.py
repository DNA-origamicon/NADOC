from __future__ import annotations

from argparse import Namespace
import hashlib
import json
from pathlib import Path

import pytest

import scripts.run_post_water_validation as workflow


def _write(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(path: Path, products: list[str]) -> None:
    _write(
        path,
        {
            "schema": "nadoc.photoproduct-joint-nonbonded-fit.v1",
            "status": "candidate_passed_heldout_water_targets",
            "simulation_ready": False,
            "gate_effect": "none",
            "product_ids": products,
        },
    )


def _args(tmp_path: Path) -> Namespace:
    storage = tmp_path / "archive"
    collection = storage / "campaign" / "collection_report.json"
    _write(
        collection,
        {
            "schema": "nadoc.photoproduct-alpine-water-collection.v1",
            "status": "passed_import_and_curve_audits",
            "gate_effect": "none",
            "product_count": 2,
            "products": [
                {"product_id": "tt-cpd-one"},
                {"product_id": "tt-cpd-two"},
            ],
        },
    )
    one = storage / "fits" / "one.json"
    two = storage / "fits" / "two.json"
    _candidate(one, ["tt-cpd-one"])
    _candidate(two, ["tt-cpd-two"])
    cgenff = tmp_path / "cgenff.prm"
    nucleic = tmp_path / "nucleic.prm"
    cgenff.write_text("cgenff")
    nucleic.write_text("nucleic")
    return Namespace(
        storage_root=storage,
        validation_collection=collection,
        candidate=[one, two],
        cgenff_parameters=cgenff,
        nucleic_parameters=nucleic,
        output_root=storage / "validation",
    )


def test_post_water_validation_requires_exact_product_partition(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    _candidate(args.candidate[1], ["tt-cpd-one"])

    with pytest.raises(ValueError, match="claimed by both"):
        workflow.run(args)


def test_post_water_validation_runs_and_reuses_hash_matched_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _args(tmp_path)
    calls = []

    def fake_audit(**kwargs):
        calls.append(kwargs["candidate_path"])
        candidate = json.loads(kwargs["candidate_path"].read_text())
        report = {
            "schema": "nadoc.photoproduct-independent-nonbonded-validation.v1",
            "status": "candidate_passed_independent_water_targets",
            "passed": True,
            "simulation_ready": False,
            "gate_effect": "none",
            "product_ids": candidate["product_ids"],
            "sources": {
                "candidate": workflow._source(kwargs["candidate_path"]),
                "validation_collection": workflow._source(
                    kwargs["validation_collection_path"]
                ),
            },
        }
        _write(kwargs["output_path"], report)
        return report

    monkeypatch.setattr(workflow, "audit_joint_nonbonded_candidate", fake_audit)
    first = workflow.run(args)
    second = workflow.run(args)

    assert first["status"] == "passed_all_independent_nonbonded_targets"
    assert first["product_count"] == 2
    assert first["candidate_count"] == 2
    assert len(calls) == 2
    assert second == first
    assert json.loads(
        (args.output_root / "post_water_validation_summary.json").read_text()
    ) == first

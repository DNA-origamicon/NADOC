from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts/alpine_qm_local_fragment_campaign"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_handoff_starts_at_frequency_submission(tmp_path):
    module = _module("test_evaluate_handoff", SCRIPTS / "evaluate_handoff.py")
    report = module.evaluate(tmp_path)
    assert report["status"] == "wait_D1"
    assert report["checks"]["D1-frequency-hessian"] is False


def test_handoff_rejects_gate_without_hash_pinned_assessment(tmp_path):
    module = _module("test_evaluate_handoff_bad", SCRIPTS / "evaluate_handoff.py")
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "frequency_cohort.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-alpine-stage-trigger.v1",
                "stage": "D1-frequency-hessian",
                "status": "passed",
                "gate_effect": "none",
                "simulation_ready": False,
                "assessment": {"path": str(tmp_path / "missing.json"), "sha256": "x"},
            }
        )
    )
    assert module.evaluate(tmp_path)["status"] == "wait_D1"


def test_frequency_collector_accepts_single_case_stage(tmp_path):
    module = _module(
        "test_single_frequency_collector", SCRIPTS / "collect_frequency_campaign.py"
    )
    case = tmp_path / "bundle/frequency-cases/frequency-one"
    case.mkdir(parents=True)
    case_path = case / "case_manifest.json"
    case_path.write_text("{}\n")
    case_hash = hashlib.sha256(case_path.read_bytes()).hexdigest()
    (tmp_path / "campaign_manifest.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-alpine-local-fragment-campaign.v1",
                "queued_frequency_count": 1,
                "queued_frequencies": [
                    {
                        "id": "frequency-one",
                        "case_manifest_sha256": case_hash,
                    }
                ],
                "retained_local_frequencies": [],
                "stage_id": "D2-missing-reused-core-frequency",
                "next_stage": "D2-reused-core-frequency-inventory",
                "trigger_file": "missing_reused_core_frequency.json",
            }
        )
    )
    remote = tmp_path / "remote"
    remote.mkdir()
    report = module.collect(campaign_root=tmp_path, remote_results=remote)
    assert report["scoped_frequency_count"] == 1
    assert report["status"] == "incomplete_or_failed"
    gate = json.loads(
        (tmp_path / "gates/missing_reused_core_frequency.json").read_text()
    )
    assert gate["stage"] == "D2-missing-reused-core-frequency"
    assert gate["status"] == "hold"

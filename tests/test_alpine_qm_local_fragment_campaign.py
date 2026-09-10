from __future__ import annotations

import importlib.util
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

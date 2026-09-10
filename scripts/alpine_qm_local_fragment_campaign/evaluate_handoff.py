#!/usr/bin/env python3
"""Evaluate durable stage triggers for the Alpine fragment continuation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_gate(path: Path, *, stage: str) -> bool:
    if not path.is_file():
        return False
    gate = json.loads(path.read_text())
    assessment = gate.get("assessment") or {}
    assessment_path = Path(str(assessment.get("path") or ""))
    return (
        gate.get("schema") == "nadoc.photoproduct-alpine-stage-trigger.v1"
        and gate.get("stage") == stage
        and gate.get("status") == "passed"
        and gate.get("gate_effect") == "none"
        and gate.get("simulation_ready") is False
        and assessment_path.is_file()
        and _sha256(assessment_path) == assessment.get("sha256")
    )


def evaluate(root: Path) -> dict[str, object]:
    root = root.resolve()
    frequency = _valid_gate(
        root / "gates/frequency_cohort.json", stage="D1-frequency-hessian"
    )
    reused = _valid_gate(
        root / "gates/reused_core_frequency_inventory.json",
        stage="D2-reused-core-frequency-inventory",
    )
    targets = _valid_gate(
        root / "gates/training_targets.json",
        stage="D3-charge-nonbonded-torsion-targets",
    )
    frozen = _valid_gate(
        root / "gates/primary_fit_freeze.json", stage="D4-primary-fit-freeze"
    )
    heldout = _valid_gate(
        root / "gates/heldout_transfer.json", stage="C-heldout-transfer"
    )
    if not frequency:
        state, action = "wait_D1", "submit/collect/audit the six Alpine frequency jobs"
    elif not reused:
        state, action = "ready_D2", "reconcile reused-core frequency evidence on Alpine"
    elif not targets:
        state, action = "ready_D3", "scope and run charge, nonbonded and torsion targets on Alpine"
    elif not frozen:
        state, action = "ready_D4", "fit and freeze primary parameters and transfer metrics on Alpine"
    elif not heldout:
        state, action = "ready_C", "release the sealed held-out payload to Alpine"
    else:
        state, action = "ready_E", "assess existing Alpine full-boundary evidence"
    return {
        "schema": "nadoc.photoproduct-alpine-handoff-evaluation.v1",
        "status": state,
        "gate_effect": "none",
        "simulation_ready": False,
        "checks": {
            "D1-frequency-hessian": frequency,
            "D2-reused-core-frequency-inventory": reused,
            "D3-charge-nonbonded-torsion-targets": targets,
            "D4-primary-fit-freeze": frozen,
            "C-heldout-transfer": heldout,
        },
        "next_action": action,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.campaign_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage-specific, hash-pinned authorization for the preliminary anti campaign."""

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path

from experiments.cpd_anti_additive.validation_gate import checked, read, source

REPO = Path(__file__).resolve().parents[2]
POLICY = Path(__file__).with_name("preliminary_policy_v2.json")
STATE = REPO / ".development-artifacts/cpd-anti-preliminary-v2"
PAUSE = REPO / ".development-artifacts/cpd-anti-validation-v1/campaign_pause.json"


def require(stage, state=None):
    state = Path(state or STATE)
    if read(PAUSE).get("paused"):
        raise RuntimeError("CPD campaign paused")
    active = read(state / "activation.json")
    if active.get("user_authorized_resume") is not True:
        raise RuntimeError("Missing explicit campaign resume")
    checked(active["policy"])
    if active["policy"] != source(POLICY):
        raise RuntimeError("Preliminary policy changed after activation")
    if stage not in ("optimizer", "electrostatics", "conformational", "engine"):
        raise ValueError("Unknown preliminary stage")
    lock = read(state / f"{stage}_input_lock.json")
    if lock["activation"] != source(state / "activation.json") or lock["policy"] != source(POLICY):
        raise RuntimeError("Stage inputs belong to another activation/policy")
    receipt = read(checked(lock["receipt"]))
    if receipt.get("stage") != stage or receipt.get("ready") is not True:
        raise RuntimeError(f"{stage} inputs are incomplete")
    if not receipt.get("artifacts") or not receipt.get("case_ids"):
        raise RuntimeError("Empty input receipt")
    for item in receipt["artifacts"]:
        checked(item)
    if (state / f"{stage}_candidate_lock.json").exists():
        raise RuntimeError("Candidate locked; fitting would consume validation")
    return read(POLICY), receipt


def lock_inputs(stage, receipt_path, state=None):
    """Freeze a stage's independently prepared inputs without mutating activation."""
    state = Path(state or STATE)
    receipt = read(receipt_path)
    if receipt.get("stage") != stage or receipt.get("ready") is not True:
        raise RuntimeError("Cannot freeze incomplete stage inputs")
    if not receipt.get("case_ids") or not receipt.get("artifacts"):
        raise RuntimeError("Cannot freeze empty stage inputs")
    for artifact in receipt["artifacts"]:
        checked(artifact)
    with (state / f"{stage}_input_lock.json").open("x") as handle:
        json.dump(dict(activation=source(state/"activation.json"), policy=source(POLICY),
                       receipt=source(receipt_path)), handle, indent=2)


def begin_round(stage, output, state=None):
    state = Path(state or STATE)
    policy, receipt = require(stage, state)
    if stage not in ("electrostatics", "conformational"):
        raise ValueError("Only fitting stages have fit rounds")
    with (state / f"{stage}_rounds.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        ledger = state / f"{stage}_rounds.json"
        records = read(ledger) if ledger.exists() else []
        if len(records) >= policy[stage]["max_fit_rounds"]:
            raise RuntimeError("Declared fit-round budget exhausted")
        if records:
            decision = read(state / f"{stage}_second_round_review.json")
            checked(decision["prior_result"])
            if decision.get("authorized") is not True or not decision.get("rationale"):
                raise RuntimeError("Second round requires an explicit residual review")
        if Path(output).exists():
            raise FileExistsError(output)
        records.append(dict(round=len(records)+1, output=str(Path(output).resolve()),
            policy=source(POLICY), at=datetime.now(timezone.utc).isoformat()))
        temporary = ledger.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, indent=2)+"\n")
        temporary.replace(ledger)
    return policy, receipt, len(records)

"""Activate the reviewed preliminary protocol and launch one changed-method test."""

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked, source, write
from experiments.cpd_anti_additive.geometric_pilot import screen
from experiments.cpd_anti_additive.preliminary_protocol import POLICY, STATE, PAUSE, require, lock_inputs

ART = REPO / ".development-artifacts"
QM_ROOT = ART / "cpd-anti-default-constraint-v2"


def prepare():
    STATE.mkdir(exist_ok=False)
    parent = ART / "cpd-anti-lower-profile-restart-v1"
    audit_path = ART / "cpd-anti-resume-step-audit-v1/assessment.json"
    audit = json.loads(audit_path.read_text())
    proposed = next(r for r in audit["proposed_steps"] if r["conmethod"] == 0)
    assert proposed["small_step_linear_change_kcal"] < 0
    assert proposed["constraint_error_deg"] < .01
    for key in ("parent", "cached_progress", "runtime", "source"):
        checked(audit[key])
    old = json.loads((parent/"plan.json").read_text())
    first = parent / "evaluation-001/result.json"
    result = json.loads(first.read_text())
    x = np.load(checked(result["geometry"]))
    checked(result["native"])
    plan = copy.deepcopy(old)
    for key in ("input", "neighbor", "original_reference"):
        plan.pop(key, None)
    plan.update(reference=None, geometry_bohr=x.tolist(), replay_sources=[source(first)],
        max_evaluations=41, max_new_evaluations=40,
        scratch_dir=str(Path("/home/jojo/.cache/nadoc-qm")/QM_ROOT.name),
        scope="One changed-constraint-method test after cached step audit; no continuation or parameter promotion",
        policy=source(POLICY), method_selection_audit=source(audit_path))
    plan["optimizer"].update(conmethod=0, enforce=.1, trust=.002, tmax=.02, maxiter=40)
    geometry = screen(x, plan)
    assert geometry["passed"]
    QM_ROOT.mkdir(exist_ok=False)
    write(QM_ROOT/"plan.json", plan)
    write(QM_ROOT/"seed_screen.json", geometry)
    worker = REPO / "experiments/cpd_anti_additive/geometric_pilot.py"
    write(STATE/"optimizer_inputs.json", dict(stage="optimizer", ready=True,
        case_ids=[plan["record"]["label"]], artifacts=[source(audit_path),
        source(QM_ROOT/"plan.json"), source(first), source(worker)],
        worker=source(worker), planned_output=str(QM_ROOT.resolve()),
        scientific_status="Unresolved until independently audited native convergence"))
    shutil.copyfile(PAUSE, STATE/"prior_pause.json")
    activation = dict(policy=source(POLICY), historical_policy=source(
        REPO/"experiments/cpd_anti_additive/validation_policy_v1.json"),
        user_authorized_resume=True,
        user_instruction="Begin next steps. Then resume the campaign to get to NAMD testable cis-anti CPDs.",
        activated_at=datetime.now(timezone.utc).isoformat(),
        previous_pause=source(STATE/"prior_pause.json"),
        legacy_automatic_triggers_reenabled=False, simulation_ready=False)
    write(STATE/"activation.json", activation)
    lock_inputs("optimizer", STATE/"optimizer_inputs.json")
    pause = json.loads(PAUSE.read_text())
    pause.update(paused=False, resumed_at=activation["activated_at"],
                 resume_authorization=source(STATE/"activation.json"))
    write(PAUSE, pause)
    print(json.dumps(dict(state=str(STATE.resolve()), qm_plan=str(QM_ROOT.resolve()),
                          activated=True, launched=False), indent=2))


def launch():
    from experiments.cpd_anti_additive.launch import launch as submit
    policy, receipt = require("optimizer")
    plan = json.loads((QM_ROOT/"plan.json").read_text())
    assert plan["max_new_evaluations"] == policy["optimizer"]["max_new_gradients"]
    assert receipt["planned_output"] == str(QM_ROOT.resolve())
    checked(receipt["worker"])
    with (STATE/"optimizer_launch.json").open("x") as handle:
        json.dump(dict(plan=source(QM_ROOT/"plan.json"), at=datetime.now(timezone.utc).isoformat(),
                       automatic_continuations_remaining=0), handle, indent=2)
    submit(ART/"cpd-anti-default-constraint-service-v2", "nadoc-cpd-anti-default-constraint-v2",
        ["/home/jojo/miniforge3/envs/nadoc-qm/bin/python", str(checked(receipt["worker"])),
         "run", str(QM_ROOT.resolve())], expected_seconds=policy["optimizer"]["expected_seconds"],
        memory_gib=10, threads=4, hours=policy["optimizer"]["hard_hours"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "launch"])
    args = parser.parse_args()
    globals()[args.action]()

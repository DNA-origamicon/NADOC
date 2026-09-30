"""A separate bounded gate-directed development attempt using Sella geometries.

The exhausted v2.2 state is read-only. No old round or recovery entry point is
reopened. Proposals minimize the largest existing gate ratio in a local residual
model. Actual relaxed results, including every failed target, determine success.
"""
import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get("NADOC_REPO_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive import shape_fit_v2 as frozen
from experiments.cpd_anti_additive.shape_fit_isolated_recovery_v1 import assemble
from experiments.cpd_anti_additive.review_shape_sensitivities_v1 import layout, gate_values, propose
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import now, save

ART = REPO / ".development-artifacts"
ROOT = ART / "cpd-anti-shape-gate-refinement-v1"


def prepare():
    ROOT.mkdir(exist_ok=False)
    parent = ART / "cpd-anti-shape-inputs-v2-r2/receipt.json"
    plan = read(parent)
    selected = ART / "cpd-anti-shape-fit-recovery-v1/model-061"
    review = ART / "cpd-anti-shape-sensitivity-review-v1"
    paths = [parent, selected / "assessment.json", selected / "residual.npy",
             selected / "candidate.prm", review / "assessment.json", review / "jacobian-047.npy",
             ART / "cpd-anti-shape-closeout-v2-r2/assessment.json",
             ART / "cpd-anti-shape-state-v2-r2/conformational_rounds.json"]
    paths += [REPO / "experiments/cpd_anti_additive" / name for name in
              ["shape_fit_v2.py", "shape_fit_isolated_recovery_v1.py", "review_shape_sensitivities_v1.py",
               "conformational_fit_v2.py", "sella_pilot.py", "validation_gate.py", "prepare_engine_v2.py"]]
    shutil.copyfile(__file__, ROOT / "worker.py")
    paths.append(ROOT / "worker.py")
    receipt = dict(at=now(), revision="shape-gate-refinement-v1", parent_plan=source(parent),
                   initial_assessment=source(selected / "assessment.json"), initial_residual=source(selected / "residual.npy"),
                   initial_jacobian=source(review / "jacobian-047.npy"), sources=[source(p) for p in paths],
                   user_direction="Resolve the remaining cis-anti shape work, be cautious that the mismatch is not an unfounded expectation from prior work, and treat Sella as the better method moving forward.",
                   authorization_scope="New isolated local development attempt under the current user direction; no reuse or reset of the exhausted v2.2 budget or ledger.",
                   max_new_models=12, wall_seconds=600, automatic_restarts=0, max_steps_per_fragment=400,
                   max_evaluations_per_fragment=600, cpu_affinity=[4, 5, 6, 7],
                   versions=plan["versions"], coefficient_bounds=[-5., 5.], bound_reference=plan["bound_reference"],
                   objective="Minimize largest normalized per-case gate ratio, including energy RMS/max, all 23 heavy RMSDs/proper errors, and all three representative bond/angle maxima.",
                   proposal="Use saved center47 Jacobian at model61 initially; after each completed trial make a residual Broyden secant update. Start infinity-norm trust radius 2 kcal/mol; halve after a poor prediction, grow at most to 3 after a good boundary step; select actual lowest maximum gate ratio.",
                   derivative_caveat="Initial Jacobian is evaluated .02 kcal/mol from model61; all proposals require new full Sella evaluation.",
                   acceptance="All original numerical, chemistry, energy, shape and representative gates; any incomplete or numerically invalid vector cannot pass.",
                   fixed="All 23 exposed targets, original references, all 22 parameter identities and their original baseline/bounds. All other potential terms stay fixed.",
                   stop="First actual complete development pass, 12 new models, 600 seconds, failed child, or unsuccessful proposal. No automatic continuation.",
                   qualification="Development only; no prospective validation, minimum certificate, engine transfer, MD or application promotion.")
    save(ROOT / "plan.json", receipt)
    print("Registered independent 12-vector / 600-second development attempt.", flush=True)


def validate():
    receipt = read(ROOT / "plan.json")
    for ref in receipt["sources"]:
        checked(ref)
    plan = read(checked(receipt["parent_plan"]))
    for ref in plan["artifacts"]:
        checked(ref)
    for name, version in receipt["versions"].items():
        assert metadata.version(name) == version
    return receipt, plan


def child(path):
    from openmm import app
    receipt, plan = validate()
    request = read(path)
    folder = path.parent
    assert folder.parent.resolve() == ROOT.resolve()
    parameters = np.array(request["parameters"])
    assert parameters.shape == (22,) and np.max(abs(parameters)) <= 5 + 1e-12
    frozen.export_parameters(checked(plan["baseline_parameters"]), folder / "candidate.prm", plan["variables"], parameters)
    par = frozen.parameters(folder / "candidate.prm")
    points = read(checked(plan["points"])) + read(checked(plan["representatives"]))
    psfs = {p["endpoint"]: app.CharmmPsfFile(str(Path(plan["parent"]) / f"endpoint-{p['endpoint']}" / "fragment.psf")) for p in points}
    systems = {e: psf.createSystem(par, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False) for e, psf in psfs.items()}
    deadline = time.monotonic() + max(0., request["deadline_epoch"] - time.time())
    results, coordinates = [], []
    for p in points:
        if time.monotonic() >= deadline:
            raise RuntimeError("Declared wall limit reached")
        result, x = frozen.relax_point(folder / p["case_id"], p, systems[p["endpoint"]], plan, deadline)
        results.append(result)
        coordinates.append(x)
        save(folder / "progress.json", results)
    report, residual = assemble(folder, request["number"], parameters, plan, results, coordinates, psfs)
    np.save(folder / "residual.npy", residual)
    save(folder / "assessment.json", report)


def run():
    receipt, plan = validate()
    assert not (ROOT / "started.json").exists()
    start = time.time()
    deadline = start + receipt["wall_seconds"]
    save(ROOT / "started.json", dict(at=now(), deadline_epoch=deadline, plan=source(ROOT / "plan.json")))
    points = read(checked(plan["points"]))
    blocks, torsions, reps = layout(points)
    report = read(checked(receipt["initial_assessment"]))
    x = np.array(report["parameters"])
    residual = np.load(checked(receipt["initial_residual"]))
    jac = np.load(checked(receipt["initial_jacobian"]))
    score = float(max(gate_values(residual, blocks, torsions, reps)))
    best = dict(assessment=receipt["initial_assessment"], maximum_gate_ratio=score, number=0)
    history = []
    radius = 2.
    termination = "Declared model cap reached"
    try:
        for number in range(1, receipt["max_new_models"] + 1):
            if time.time() >= deadline:
                termination = "Declared wall cap reached"
                break
            proposal = propose(residual, jac, x, radius, blocks, torsions, reps)
            if not proposal["success"] or proposal["minimum_constraint_slack"] < -1e-7:
                termination = "Linear proposal did not converge; no automatic restart"
                break
            folder = ROOT / f"model-{number:03d}"
            folder.mkdir(exist_ok=False)
            request = dict(at=now(), number=number, parameters=proposal["parameters"], deadline_epoch=deadline, proposal=proposal)
            save(folder / "request.json", request)
            with (folder / "native.log").open("w") as log:
                process = subprocess.run([sys.executable, str(ROOT / "worker.py"), "child", str(folder / "request.json")],
                                         cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                                         timeout=max(.001, deadline - time.time()))
            if process.returncode:
                termination = f"Child {number} failed with exit {process.returncode}; no automatic restart"
                break
            report = read(folder / "assessment.json")
            observed = np.load(folder / "residual.npy")
            observed_score = float(max(gate_values(observed, blocks, torsions, reps)))
            valid = report["numerically_valid"]
            accept = valid and observed_score < score
            record = dict(number=number, assessment=source(folder / "assessment.json"),
                          maximum_gate_ratio=observed_score, predicted_maximum_gate_ratio=proposal["predicted_max_gate_ratio"],
                          numerically_valid=valid, accepted=accept, shape_failures=report["shape_failures"],
                          development_parameter_passed=report["development_parameter_passed"])
            history.append(record)
            if accept:
                best = record
            save(ROOT / "progress.json", dict(at=now(), history=history, best=best))
            print(dict(model=number, max_gate=observed_score, predicted=proposal["predicted_max_gate_ratio"],
                       shapes=len(report["shape_failures"]), accepted=accept, passed=report["development_parameter_passed"]), flush=True)
            if report["development_parameter_passed"]:
                best = record
                termination = "First complete actual development pass"
                break
            step = np.array(proposal["parameters"]) - x
            if step @ step < 1e-16:
                termination = "No resolvable proposal step"
                break
            if valid:
                jac += np.outer(observed - residual - jac @ step, step) / (step @ step)
            expected = score - proposal["predicted_max_gate_ratio"]
            ratio = (score - observed_score) / max(expected, 1e-12)
            if ratio < .25 or not valid:
                radius *= .5
            elif ratio > .75 and np.max(abs(step)) > .9 * radius:
                radius = min(3., radius * 1.5)
            if accept:
                x, residual, score = np.array(proposal["parameters"]), observed, observed_score
    except subprocess.TimeoutExpired:
        termination = "Child terminated at declared wall limit"
    except Exception as exc:
        termination = repr(exc)
        save(ROOT / "failure.json", dict(at=now(), error=repr(exc), traceback=traceback.format_exc()))
    chosen = read(checked(best["assessment"]))
    save(ROOT / "assessment.json", dict(at=now(), plan=source(ROOT / "plan.json"), history=history, selected=best,
                                       candidate=chosen["candidate"], termination=termination, elapsed_seconds=time.time() - start,
                                       energy=chosen["energy"], shape_failures=chosen["shape_failures"],
                                       representative_geometry=chosen["representative_geometry"],
                                       development_parameter_passed=chosen["development_parameter_passed"],
                                       prospective_validation_complete=False, minimum_certified=False, simulation_ready=False))
    validate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "child"])
    parser.add_argument("request", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "child":
        child(args.request)
    else:
        globals()[args.action]()

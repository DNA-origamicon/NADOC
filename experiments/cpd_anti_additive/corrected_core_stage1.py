"""Bounded, gate-neutral corrected cis-anti-I core pilot and optimization.

The pilot and optimization are separately launched jobs. No Hessian, fitting,
registry mutation, MD, continuation, or cloud execution is implemented here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import resource
import shutil
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get("NADOC_REPO_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
BOHR = 0.529177210903
HARTREE_EV = 27.211386245988
FORCE_FACTOR = HARTREE_EV / BOHR
CENTERS = ["1:C5", "1:C6", "2:C5", "2:C6"]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def pin(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def checked(ref):
    path = Path(ref["path"])
    if pin(path)["sha256"] != ref["sha256"]:
        raise ValueError(f"Changed source: {path}")
    return path


def metrics(gradient):
    gradient = np.asarray(gradient, float)
    if gradient.ndim != 2 or gradient.shape[1] != 3 or not np.isfinite(gradient).all():
        raise ValueError("Invalid gradient")
    norms = np.linalg.norm(gradient, axis=1)
    return {"max_atom_gradient_au": float(norms.max()),
            "rms_atom_gradient_au": float(np.sqrt(np.mean(norms**2)))}


def stationary(values):
    return (values["max_atom_gradient_au"] < 1.5e-5 and
            values["rms_atom_gradient_au"] < 1e-5)


def admission(attempts, cap, remaining, measured_seconds):
    if attempts >= cap:
        raise RuntimeError("New-gradient allocation exhausted")
    reserve = max(60., 1.5 * max(measured_seconds, default=0.))
    if remaining <= reserve + 30:
        raise RuntimeError("Insufficient boundary time for another gradient and checkpoint")


def geometry_audit(x_bohr, plan):
    from rdkit import Chem
    x = np.asarray(x_bohr, float) * BOHR
    keys = plan["atom_keys"]
    if x.shape != (len(keys), 3) or not np.isfinite(x).all():
        raise ValueError("Invalid geometry or atom count")
    coords = dict(zip(keys, x))
    definition = read(checked(plan["definition"]))
    records = definition["product_stereocenters"]
    if [c["atom"] for c in records] != CENTERS:
        raise ValueError("Unexpected ordered stereocenters")
    volumes = []
    for center in records:
        vectors = [coords[k] - coords[center["atom"]]
                   for k in center["signed_volume_reference_atoms"]]
        value = float(np.linalg.det(vectors))
        sign = 1 if center["expected_signed_volume"] == "positive" else -1
        volumes.append({"atom": center["atom"], "volume_A3": value,
                        "passed": value * sign > .05})
    molecule = Chem.MolFromMolFile(str(checked(plan["sdf"])), removeHs=False)
    if molecule is None or molecule.GetNumAtoms() != len(keys):
        raise ValueError("Invalid pinned molecular graph")
    conf = molecule.GetConformer()
    for i, pos in enumerate(x):
        conf.SetAtomPosition(i, tuple(pos))
    expected_tags = [molecule.GetAtomWithIdx(keys.index(k)).GetChiralTag() for k in CENTERS]
    Chem.AssignAtomChiralTagsFromStructure(molecule, replaceExistingTags=True)
    actual_tags = [molecule.GetAtomWithIdx(keys.index(k)).GetChiralTag() for k in CENTERS]
    radii = {"H": .31, "C": .76, "N": .71, "O": .66}
    ratios = []
    bonds = set()
    for bond in molecule.GetBonds():
        i, j = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        bonds.add(tuple(sorted((i, j))))
        ratios.append(float(np.linalg.norm(x[i] - x[j]) /
                            (radii[plan["elements"][i]] + radii[plan["elements"][j]])))
    contacts = [float(np.linalg.norm(x[i] - x[j]) /
                      (radii[plan["elements"][i]] + radii[plan["elements"][j]]))
                for i in range(len(x)) for j in range(i+1, len(x)) if (i, j) not in bonds]
    passed = (all(v["passed"] for v in volumes) and expected_tags == actual_tags and
              .7 < min(ratios) and max(ratios) < 1.3 and min(contacts) > .65)
    return {"passed": bool(passed), "signed_centers": volumes,
            "coordinate_chiral_tags_match": expected_tags == actual_tags,
            "covalent_ratio_range": [min(ratios), max(ratios)],
            "minimum_nonbonded_covalent_ratio": min(contacts)}


def native_audit(text, energy, gradient):
    if "Energy and wave function converged." not in text:
        raise ValueError("Native SCF convergence evidence absent")
    residuals = [float(v) for v in re.findall(r"CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)", text)]
    if not residuals or max(residuals) > 1e-10:
        raise ValueError("Native MP2 response convergence failed")
    if not np.isfinite(energy):
        raise ValueError("Nonfinite energy")
    return {"scf_converged": True, "response_residuals": residuals, **metrics(gradient)}


def validate(root):
    authorization = read(root/"authorization.json")
    if (authorization.get("user_instruction") != "Ok, proceed with the first stage." or
            not authorization.get("user_authorized")):
        raise ValueError("Missing stage-one authorization")
    checked(authorization["approved_proposal"])
    plan = read(checked(authorization["execution_plan"]))
    if checked(authorization["worker"]) != Path(__file__).resolve():
        raise ValueError("Worker changed")
    for item in plan["sources"]:
        checked(item)
    for name, version in plan["versions"].items():
        if metadata.version(name) != version:
            raise ValueError(f"Runtime version changed: {name}")
    if plan["phase"] not in ("pilot", "optimization"):
        raise ValueError("Unsupported phase")
    expected = (3600, 1) if plan["phase"] == "pilot" else (14400, 60)
    if (plan["hard_seconds"], plan["max_new_gradients"]) != expected:
        raise ValueError("Unapproved budget")
    if plan["phase"] == "optimization":
        decision = read(checked(plan["pilot_continuation_decision"]))
        review = read(checked(decision["pilot_review"]))
        if not decision["proceed"] or not review["passed"]:
            raise ValueError("Pilot was not admitted for continuation")
        checked(review["last_result"])
    pause = Path(plan["campaign_root"])/"pause.json"
    if pause.exists() and read(pause).get("paused"):
        raise RuntimeError("Campaign paused")
    return plan


def xyz(elements, x_bohr, comment):
    return "\n".join([str(len(elements)), comment] +
                     [el + " " + " ".join(f"{v:.14f}" for v in pos * BOHR)
                      for el, pos in zip(elements, np.asarray(x_bohr))]) + "\n"


def review(root):
    """Reopen pinned native results and recompute identity and full forces."""
    plan = validate(root)
    rows = read(root/"progress.json")["evaluations"]
    if not rows:
        raise ValueError("No completed native evaluations")
    for row in rows:
        result = read(checked(row["result"]))
        inp = read(checked(result["input"]))
        x = np.load(checked(result["geometry"]))
        if not np.array_equal(x, np.array(inp["geometry_bohr"])):
            raise ValueError("Input/result geometry mismatch")
        if inp["options"] != plan["options"] or inp["method"] != "mp2":
            raise ValueError("Input method changed")
        audit = geometry_audit(x, plan)
        if not audit["passed"]:
            raise ValueError("Geometry failed independent audit")
        native = native_audit(checked(result["native"]).read_text(),
                             result["energy_hartree"], result["gradient_hartree_bohr"])
    outcome = read(root/"assessment.json") if (root/"assessment.json").exists() else {}
    passed = outcome.get("error") is None and outcome.get("native_task_completed") is True
    if plan["phase"] == "optimization":
        passed = passed and outcome.get("optimizer_converged") is True and stationary(native)
    report = {"reviewed_at": now(), "passed": bool(passed), "phase": plan["phase"],
              "evaluations_verified": len(rows), "last_result": rows[-1]["result"],
              "geometry_audit": audit, "native_audit": native,
              "independent_stationarity_passed": stationary(native),
              "max_gradient_wall_seconds": max(read(checked(r["result"]))["wall_seconds"] for r in rows),
              "peak_rss_bytes": outcome.get("peak_rss_bytes"),
              "minimum_certified": False, "simulation_ready": False}
    save(root/"independent_review.json", report)
    return report


def run(root):
    import psi4
    plan = validate(root)
    if psi4.__version__ != plan["psi4_version"]:
        raise ValueError("Psi4 version changed")
    with (root/"started.json").open("x") as stream:
        json.dump({"started_at": now(), "pid": os.getpid()}, stream)
    os.chdir(root)
    scratch = Path(plan["scratch"])
    scratch.mkdir(exist_ok=False)
    if shutil.disk_usage(scratch).free < 20*1024**3:
        raise RuntimeError("Insufficient Archive scratch")
    psi4.set_memory("4 GiB")
    psi4.set_num_threads(4)
    psi4.core.IOManager.shared_object().set_default_path(str(scratch))
    psi4.set_options(plan["options"])
    start = time.monotonic()
    launch = read(root/"launch_receipt.json")
    remaining = launch["deadline_epoch"] - time.time() - 30
    deadline = start + max(0., min(remaining, plan["hard_seconds"] - 60))
    rows, durations = [], []
    attempts = 0
    reused = None
    if plan["phase"] == "optimization":
        reused = read(checked(plan["seed_gradient"]))
        durations.append(reused["wall_seconds"])
    save(root/"progress.json", {"evaluations": rows, "attempts": 0})

    def evaluate(x):
        nonlocal attempts
        pause = Path(plan["campaign_root"])/"pause.json"
        if pause.exists() and read(pause).get("paused"):
            raise RuntimeError("Campaign paused at gradient boundary")
        admission(attempts, plan["max_new_gradients"], deadline-time.monotonic(), durations)
        audit = geometry_audit(x, plan)
        if not audit["passed"]:
            save(root/"rejected_trial.json", {"geometry_bohr": x.tolist(), "audit": audit})
            raise RuntimeError("Trial chemistry failed before QM")
        attempts += 1
        folder = root/f"evaluation-{attempts:03d}"
        folder.mkdir(exist_ok=False)
        np.save(folder/"geometry_bohr.npy", x)
        save(folder/"input.json", {"geometry_bohr": x.tolist(), "elements": plan["elements"],
             "method": "mp2", "options": plan["options"], "charge": 0, "multiplicity": 1,
             "scratch": str(scratch), "started_at": now(), "geometry_audit": audit})
        save(root/"progress.json", {"evaluations": rows, "attempts": attempts,
             "in_flight_input": pin(folder/"input.json"), "minimum_certified": False})
        psi4.set_output_file(str(folder/"output.dat"), False)
        lines = "\n".join(el + " " + " ".join(f"{v:.15f}" for v in pos)
                          for el, pos in zip(plan["elements"], x))
        molecule = psi4.geometry("0 1\n" + lines + "\nunits bohr\nsymmetry c1\nno_com\nno_reorient")
        before = time.monotonic()
        gradient, wfn = psi4.gradient("mp2", molecule=molecule, return_wfn=True)
        energy = float(wfn.energy())
        gradient = np.asarray(gradient)
        if gradient.shape != x.shape or np.max(abs(np.asarray(wfn.molecule().geometry())-x)) > 1e-10:
            raise ValueError("QM atom frame or gradient shape changed")
        psi4.core.flush_outfile()
        evidence = native_audit((folder/"output.dat").read_text(), energy, gradient)
        elapsed = time.monotonic()-before
        result = {"energy_hartree": energy, "gradient_hartree_bohr": gradient.tolist(),
                  "wall_seconds": elapsed, "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  "input": pin(folder/"input.json"), "geometry": pin(folder/"geometry_bohr.npy"),
                  "native": pin(folder/"output.dat"), "native_audit": evidence,
                  "scratch_path": psi4.core.IOManager.shared_object().get_default_path(),
                  "scratch_bytes_before_clean": sum(p.stat().st_size for p in scratch.rglob('*') if p.is_file()),
                  "completed_at": now()}
        save(folder/"result.json", result)
        rows.append({"result": pin(folder/"result.json"), **metrics(gradient)})
        durations.append(elapsed)
        save(root/"progress.json", {"evaluations": rows, "attempts": attempts,
             "elapsed_seconds": time.monotonic()-start, "minimum_certified": False})
        (root/"last_evaluated.xyz").write_text(xyz(plan["elements"], x, "Evaluated; not minimum certified"))
        psi4.core.clean()
        print(json.dumps({"evaluation": attempts, "wall_seconds": elapsed, **metrics(gradient)}), flush=True)
        return energy, gradient

    error, native_done, optimizer_converged = None, False, False
    try:
        if plan["phase"] == "pilot":
            evaluate(np.array(plan["geometry_bohr"]))
            native_done = True
        else:
            from ase import Atoms
            from ase.calculators.calculator import Calculator, all_changes
            from sella import Sella

            class Psi4Calculator(Calculator):
                implemented_properties = ["energy", "forces"]

                def calculate(self, atoms=None, properties=("energy", "forces"), system_changes=all_changes):
                    super().calculate(atoms, properties, system_changes)
                    x = self.atoms.positions/BOHR
                    seed = np.load(checked(reused["geometry"]))
                    if attempts == 0 and np.allclose(x, seed, atol=1e-12, rtol=0):
                        energy, grad = reused["energy_hartree"], np.array(reused["gradient_hartree_bohr"])
                        if not (root/"seed_gradient_reuse.json").exists():
                            save(root/"seed_gradient_reuse.json", {"source": plan["seed_gradient"],
                                 "reason": "Exact same geometry/method; avoid duplicate pilot gradient"})
                            rows.append({"result": plan["seed_gradient"], "reused": True, **metrics(grad)})
                            save(root/"progress.json", {"evaluations": rows, "attempts": attempts})
                    else:
                        energy, grad = evaluate(x)
                    self.results = {"energy": energy*HARTREE_EV, "forces": -grad*FORCE_FACTOR}

            atoms = Atoms(plan["elements"], positions=np.array(plan["geometry_bohr"])*BOHR)
            atoms.calc = Psi4Calculator()

            class AuditedSella(Sella):
                def converged(self, forces=None):
                    native = bool(super().converged(forces))
                    grad = -atoms.get_forces(apply_constraint=False)/FORCE_FACTOR
                    values = metrics(grad)
                    audit = geometry_audit(atoms.positions/BOHR, plan)
                    save(root/"latest_convergence.json", {"native_converged": native,
                         "independent_stationarity_passed": stationary(values), **values,
                         "geometry_audit": audit, "new_evaluations": attempts})
                    return native and stationary(values) and audit["passed"]

            optimizer = AuditedSella(atoms, order=0, internal=True, eig=False, delta0=.1,
                          refine_initial_hessian=False, max_cpu_threads=1,
                          logfile=str(root/"sella.log"), trajectory=str(root/"sella.traj"))

            def accepted_checkpoint():
                x = atoms.positions/BOHR
                audit = geometry_audit(x, plan)
                if not audit["passed"]:
                    raise RuntimeError("Accepted optimizer geometry failed identity")
                matches = [r["result"] for r in rows
                           if np.allclose(np.load(checked(read(checked(r["result"]))["geometry"])),
                                          x, atol=1e-12, rtol=0)]
                if not matches:
                    raise RuntimeError("Accepted checkpoint lacks a matching evaluated gradient")
                target = root/f"accepted-{optimizer.nsteps:03d}.xyz"
                target.write_text(xyz(plan["elements"], x, "Accepted geometry; restart with fresh optimizer history"))
                save(root/"restart_checkpoint.json", {"geometry": pin(target),
                     "step": optimizer.nsteps, "evaluated_source": matches[-1],
                     "optimizer_state_restorable": False, "minimum_certified": False})

            optimizer.attach(accepted_checkpoint, interval=1)
            optimizer_converged = bool(optimizer.run(fmax=1.5e-5*FORCE_FACTOR, steps=60))
            native_done = optimizer_converged
            if not optimizer_converged:
                raise RuntimeError("Optimizer stopped without joint convergence")
            (root/"optimized.xyz").write_text(xyz(plan["elements"], atoms.positions/BOHR,
                                                  "Stationary candidate; Hessian not computed"))
    except Exception as exc:
        error = repr(exc)
        (root/"failure_traceback.txt").write_text(traceback.format_exc())
    finally:
        psi4.core.flush_outfile()
        psi4.core.clean()
        save(root/"assessment.json", {"finished_at": now(), "error": error,
             "native_task_completed": native_done, "optimizer_converged": optimizer_converged,
             "new_gradients": attempts, "completed_result_count": len(rows),
             "wall_seconds": time.monotonic()-start,
             "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
             "minimum_certified": False, "simulation_ready": False})
        try:
            review(root)
        except Exception:
            (root/"review_failure.txt").write_text(traceback.format_exc())
            error = error or "Independent review failed"
    return 1 if error else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "review"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.action == "run":
        sys.exit(run(args.root.resolve()))
    print(json.dumps(review(args.root.resolve()), indent=2))

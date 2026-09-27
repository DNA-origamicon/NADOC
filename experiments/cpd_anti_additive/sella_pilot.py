"""One explicitly authorized Sella/Psi4 attempt; no fitting or minimum claims."""

import argparse
from datetime import datetime, timezone
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get("NADOC_REPO_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from backend.parameterization.photoproduct_qm import _dihedral_degrees
from experiments.cpd_anti_additive.validation_gate import checked, read, source

BOHR = 0.529177210903
HARTREE_EV = 27.211386245988
FORCE_FACTOR = HARTREE_EV / BOHR


def save(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def projected_metrics(x, gradient, indices, h=1e-5):
    """Current Cartesian normal, independently finite-differenced in bohr."""
    x, gradient = np.asarray(x, float), np.asarray(gradient, float)
    if x.shape != gradient.shape or x.ndim != 2 or x.shape[1] != 3:
        raise ValueError("Coordinate/gradient shape mismatch")
    if not np.isfinite([x, gradient]).all():
        raise ValueError("Nonfinite coordinates/gradient")
    normal = np.zeros(x.shape)
    for atom in indices:
        for axis in range(3):
            plus, minus = x.copy(), x.copy()
            plus[atom, axis] += h
            minus[atom, axis] -= h
            difference = (_dihedral_degrees(*plus[indices]) -
                          _dihedral_degrees(*minus[indices]) + 180) % 360 - 180
            normal[atom, axis] = difference / (2 * h)
    denominator = float(np.sum(normal**2))
    if denominator < 1e-20:
        raise ValueError("Degenerate torsion normal")
    tangent = gradient - normal * float(np.sum(normal * gradient)) / denominator
    norms = np.linalg.norm(tangent, axis=1)
    return dict(max_projected_atom_gradient=float(norms.max()),
                rms_projected_atom_gradient=float(np.sqrt(np.mean(norms**2))))


def geometry_audit(x, plan, graph):
    x = np.asarray(x, float)
    seed = np.asarray(plan["geometry_bohr"])
    if x.shape != seed.shape or not np.isfinite(x).all():
        raise ValueError("Invalid geometry")
    neighbors = {i: [] for i in range(len(x))}
    radii = {"H": .31, "C": .76, "N": .71, "O": .66}
    ratios = []
    for bond in graph["bonds"]:
        i, j = bond["indices"]
        neighbors[i].append(j)
        neighbors[j].append(i)
        ratios.append(float(np.linalg.norm(x[i] - x[j]) * BOHR /
                            (radii[plan["elements"][i]] + radii[plan["elements"][j]])))
    volumes = []
    for atom, n in neighbors.items():
        if len(n) != 4:
            continue
        def volume(pos):
            a, b, c, d = pos[n]
            return float(np.dot(b-a, np.cross(c-a, d-a)))
        before, after = volume(seed), volume(x)
        volumes.append(dict(atom=graph["atoms"][atom]["key"],
                            preserved=bool(before*after > 0 and abs(after) > 1e-8)))
    torsion = _dihedral_degrees(*x[plan["record"]["torsion_indices"]])
    error = abs((torsion-plan["record"]["target_degrees"]+180) % 360-180)
    chemistry = bool(.7 < min(ratios) and max(ratios) < 1.3 and
                     all(v["preserved"] for v in volumes))
    return dict(chemistry_passed=chemistry, tetrahedral_sites=volumes,
                covalent_ratio_range=[min(ratios), max(ratios)],
                torsion_degrees=torsion, torsion_error_deg=error,
                constraint_passed=bool(error < plan["limits"]["torsion_error_deg"]))


def force_pass(metrics, limits):
    return (metrics["max_projected_atom_gradient"] < limits["max_gradient"] and
            metrics["rms_projected_atom_gradient"] < limits["rms_gradient"])


def xyz_text(elements, coordinates_bohr, comment):
    lines = [str(len(elements)), comment]
    lines.extend(el + " " + " ".join(f"{v:.14f}" for v in pos*BOHR)
                 for el, pos in zip(elements, np.asarray(coordinates_bohr)))
    return "\n".join(lines) + "\n"


def review(root):
    """Reread every completed evaluation and independently audit the last one."""
    plan = read(root / "plan.json")
    graph = read(checked(plan["record"]["model_graph"]))
    rows = read(root / "progress.json")["evaluations"]
    for row in rows:
        result = read(checked(row["result"]))
        x = np.load(checked(result["geometry"]))
        inputs = read(checked(result["input"]))
        if not np.array_equal(x, np.asarray(inputs["geometry_bohr"])):
            raise ValueError("Input/result coordinate mismatch")
        native = checked(result["native"]).read_text()
        response = [float(v) for v in re.findall(r"CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)", native)]
        if not response or max(response) > plan["options"]["solver_convergence"]:
            raise ValueError("Native electronic response failure")
        audit = geometry_audit(x, plan, graph)
        if not audit["chemistry_passed"]:
            raise ValueError("Evaluated chemistry failed")
    report = dict(evaluations_verified=len(rows), minimum_certified=False,
                  simulation_ready=False, reviewed_at=now())
    if rows:
        metrics = [projected_metrics(x, result["gradient"], plan["record"]["torsion_indices"], h)
                   for h in (1e-4, 1e-5, 1e-6)]
        passed = all(force_pass(m, plan["limits"]) for m in metrics) and audit["constraint_passed"]
        report.update(last_evaluated_result=rows[-1]["result"],
                      energy_hartree=result["energy"], geometry_audit=audit,
                      projection_checks=metrics, independent_stationarity_passed=passed)
    save(root / "independent_review.json", report)
    return report


def validate_authorization(root):
    authorization = read(root / "authorization.json")
    if (authorization.get("user_authorized") is not True or
            authorization.get("user_instruction") !=
            "Ok, do a from scratch attempt to push the cis-anti CPD through Sella and see what we get."):
        raise RuntimeError("Missing specific Sella authorization")
    plan = read(checked(authorization["plan"]))
    if checked(authorization["worker"]) != Path(__file__).resolve():
        raise RuntimeError("Not running the frozen worker")
    if read(REPO / ".development-artifacts/cpd-anti-validation-v1/campaign_pause.json").get("paused"):
        raise RuntimeError("Campaign paused")
    if plan["max_new_gradients"] != 60 or plan["max_continuations"] != 0:
        raise RuntimeError("Unexpected Sella budget")
    for ref in plan["sources"] + plan["runtime_sources"]:
        checked(ref)
    for name, version in plan["versions"].items():
        if metadata.version(name) != version:
            raise RuntimeError(f"Runtime changed: {name}")
    return plan


def run(root):
    from ase import Atoms
    from ase.calculators.calculator import Calculator, all_changes
    from sella import Sella, Constraints
    import psi4

    plan = validate_authorization(root)
    if psi4.__version__ != plan["psi4_version"]:
        raise RuntimeError("Psi4 version changed")
    with (root / "started.json").open("x") as handle:
        json.dump(dict(started_at=now(), pid=os.getpid(), plan=source(root/"plan.json")), handle)
    os.chdir(root)
    graph = read(checked(plan["record"]["model_graph"]))
    scratch = Path(plan["scratch_dir"])
    scratch.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(scratch).free < 15 * 1024**3:
        raise RuntimeError("Insufficient local scratch")
    psi4.set_num_threads(plan["threads"])
    psi4.set_memory(f"{plan['memory_gib']} GiB")
    psi4.core.IOManager.shared_object().set_default_path(str(scratch))
    psi4.set_options(plan["options"])
    rows, convergence = [], []
    attempts = 0
    start = time.monotonic()
    save(root / "progress.json", dict(evaluations=rows, started_at=now()))

    class Psi4Calculator(Calculator):
        implemented_properties = ["energy", "forces"]

        def calculate(self, atoms=None, properties=("energy", "forces"), system_changes=all_changes):
            nonlocal attempts
            super().calculate(atoms, properties, system_changes)
            if attempts >= plan["max_new_gradients"]:
                raise RuntimeError("Declared new-gradient budget exhausted")
            if time.monotonic()-start >= plan["wall_seconds"]:
                raise RuntimeError("Declared wall-time budget exhausted")
            x = self.atoms.positions / BOHR
            audit = geometry_audit(x, plan, graph)
            if not audit["chemistry_passed"]:
                save(root/"rejected_trial.json", dict(geometry_bohr=x.tolist(), audit=audit))
                raise RuntimeError("Trial chemistry screen failed before QM")
            attempts += 1
            folder = root / f"evaluation-{attempts:03d}"
            folder.mkdir(exist_ok=False)
            np.save(folder / "geometry_bohr.npy", x)
            save(folder / "input.json", dict(elements=plan["elements"], geometry_bohr=x.tolist(),
                 method=plan["method"], options=plan["options"], charge=0, multiplicity=1,
                 attempt=attempts, started_at=now(), geometry_audit=audit))
            psi4.set_output_file(str(folder / "output.dat"), False)
            geometry = "\n".join(el + " " + " ".join(f"{v:.15f}" for v in pos)
                                 for el, pos in zip(plan["elements"], x))
            molecule = psi4.geometry("0 1\n" + geometry +
                                    "\nunits bohr\nsymmetry c1\nno_com\nno_reorient")
            evaluated_at = time.monotonic()
            gradient, wfn = psi4.gradient(plan["method"], molecule=molecule, return_wfn=True)
            energy, gradient = float(wfn.energy()), np.array(gradient)
            if np.max(abs(np.array(wfn.molecule().geometry())-x)) > 1e-10:
                raise RuntimeError("QM atom frame changed")
            psi4.core.flush_outfile()
            psi4.core.clean()
            native = (folder / "output.dat").read_text()
            residuals = [float(v) for v in re.findall(r"CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)", native)]
            if not residuals or max(residuals) > plan["options"]["solver_convergence"]:
                raise RuntimeError("Electronic response did not meet fixed limit")
            if gradient.shape != x.shape or not np.isfinite(gradient).all() or not np.isfinite(energy):
                raise RuntimeError("Nonfinite or malformed QM result")
            metrics = projected_metrics(x, gradient, plan["record"]["torsion_indices"])
            save(folder / "result.json", dict(energy=energy, gradient=gradient.tolist(),
                 input=source(folder/"input.json"), geometry=source(folder/"geometry_bohr.npy"),
                 native=source(folder/"output.dat"), reused=False, audit=audit,
                 independent_projection=metrics, elapsed_seconds=time.monotonic()-evaluated_at))
            rows.append(dict(result=source(folder/"result.json"), energy=energy, **metrics))
            save(root / "progress.json", dict(evaluations=rows, attempts=attempts,
                 elapsed_seconds=time.monotonic()-start, minimum_certified=False))
            (root/"last_evaluated.xyz").write_text(xyz_text(plan["elements"], x, "Evaluated; not a certified minimum"))
            self.results = dict(energy=energy*HARTREE_EV, forces=-gradient*FORCE_FACTOR)
            print(json.dumps(dict(evaluation=attempts, energy=energy, **metrics)), flush=True)

    atoms = Atoms(plan["elements"], positions=np.array(plan["geometry_bohr"])*BOHR)
    atoms.calc = Psi4Calculator()
    constraints = Constraints(atoms)
    # Freeze the measured seed angle; compare signed convention independently in preflight.
    constraints.fix_dihedral(tuple(plan["record"]["torsion_indices"]))

    class AuditedSella(Sella):
        def converged(self, forces=None):
            native = bool(super().converged(forces))
            x = atoms.positions / BOHR
            raw_gradient = -atoms.get_forces(apply_constraint=False) / FORCE_FACTOR
            metrics = projected_metrics(x, raw_gradient, plan["record"]["torsion_indices"])
            audit = geometry_audit(x, plan, graph)
            independent = force_pass(metrics, plan["limits"]) and audit["constraint_passed"] and audit["chemistry_passed"]
            convergence.append(dict(native_converged=native, independent_passed=independent,
                                    evaluations=attempts, **metrics, torsion_error_deg=audit["torsion_error_deg"]))
            save(root/"convergence_checks.json", convergence)
            return native and independent

    native = False
    error = None
    try:
        optimizer = AuditedSella(atoms, constraints=constraints,
                    logfile=str(root/"sella.log"), trajectory=str(root/"sella.traj"),
                    **plan["optimizer"])
        native = bool(optimizer.run(fmax=plan["limits"]["max_gradient"]*FORCE_FACTOR,
                                    steps=plan["max_new_gradients"]))
        if native:
            (root/"optimized.xyz").write_text(xyz_text(plan["elements"], atoms.positions/BOHR,
                                         "Sella constrained stationary candidate; no Hessian certification"))
        else:
            error = "Sella step cap reached without joint convergence"
    except Exception as exc:
        error = repr(exc)
        (root/"failure_traceback.txt").write_text(traceback.format_exc())
    finally:
        psi4.core.flush_outfile()
        psi4.core.clean()
        save(root/"assessment.json", dict(joint_optimizer_converged=native, error=error,
             evaluations=len(rows), attempted_gradients=attempts, finished_at=now(),
             elapsed_seconds=time.monotonic()-start, minimum_certified=False, simulation_ready=False))
        try:
            independent = review(root)
        except Exception as exc:
            save(root/"independent_review_failure.json", dict(error=repr(exc), traceback=traceback.format_exc()))
            raise
    if not native or not independent.get("independent_stationarity_passed"):
        raise RuntimeError(error or "Independent stationarity review failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "review"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    globals()[args.action](args.root.resolve())

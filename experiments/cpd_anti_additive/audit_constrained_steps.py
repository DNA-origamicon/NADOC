"""Review cached optimizer steps and proposed coordinate steps without native QM."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
RUNTIME = REPO / ".development-artifacts/cpd-geometric-runtime-v1"
sys.path.insert(0, str(RUNTIME))

from experiments.cpd_anti_additive.core_baseline import checked, source, write
from geometric.internal import DelocalizedInternalCoordinates
from geometric.molecule import Molecule
from geometric.prepare import parse_constraints
from geometric.step import get_delta_prime_trm

BOHR = 0.529177210903
HARTREE = 627.5094740631


def audit(parent, output):
    output.mkdir(parents=True, exist_ok=False)
    plan = json.loads((parent / "plan.json").read_text())
    graph = json.loads(checked(plan["record"]["model_graph"]).read_text())
    records = []
    for item in json.loads((parent / "progress.json").read_text())["evaluations"]:
        result = json.loads(checked(item["result"]).read_text())
        checked(result["native"])
        records.append((np.load(checked(result["geometry"])),
                        np.asarray(result["gradient"]), result["energy"]))
    x0, g0, e0 = records[0]
    steps = []
    for i, (x, g, energy) in enumerate(records[1:], 2):
        dx = x - x0
        actual = (energy - e0) * HARTREE
        integral = float(np.sum(dx * (g0 + g) / 2)) * HARTREE
        steps.append(dict(evaluation=i, energy_change_kcal=actual,
                          linear_change_kcal=float(np.sum(dx * g0)) * HARTREE,
                          trapezoid_change_kcal=integral,
                          trapezoid_residual_kcal=actual-integral,
                          max_displacement_A=float(np.linalg.norm(dx, axis=1).max())*BOHR))
    proposed = []
    for method in (0, 1):
        molecule = Molecule()
        molecule.elem = plan["elements"]
        molecule.xyzs = [x0 * BOHR]
        molecule.bonds = [tuple(b["indices"]) for b in graph["bonds"]]
        molecule.top_settings["read_bonds"] = True
        molecule.build_topology(force_bonds=False)
        constraints, values = parse_constraints(molecule, (parent / "constraints.txt").read_text())
        ic = DelocalizedInternalCoordinates(molecule, build=True, connect=False,
                addcart=False, constraints=constraints, cvals=values[0], conmethod=method)
        flat = x0.ravel()
        gradient = ic.calcGrad(flat, g0.ravel())
        hessian = ic.guess_hessian(flat)
        delta, expected, _ = get_delta_prime_trm(0, flat, gradient, hessian, ic)
        trial = ic.newCartesian_withConstraint(flat, delta, thre=.1)
        scale = min(1., .002 / (BOHR * np.linalg.norm((trial-flat).reshape(-1, 3), axis=1).max()))
        trial = ic.newCartesian_withConstraint(flat, delta*scale, thre=.1)
        displacement = trial-flat
        normal = constraints[0].derivative(x0).ravel()
        projected = g0.ravel()-normal*np.dot(normal, g0.ravel())/np.dot(normal, normal)
        cosine = -float(np.dot(projected, displacement))/(np.linalg.norm(projected)*np.linalg.norm(displacement))
        error = float(np.max(np.abs(ic.calcConstraintDiff(trial))))*180/np.pi
        proposed.append(dict(conmethod=method, guess_expected_hartree=float(expected),
            small_step_linear_change_kcal=float(np.dot(g0.ravel(), displacement))*HARTREE,
            small_step_max_displacement_A=float(np.linalg.norm(displacement.reshape(-1, 3), axis=1).max())*BOHR,
            constraint_error_deg=error, descent_cosine=cosine,
            native_energy_evaluated=False))
    report = dict(parent=source(parent/"plan.json"), cached_progress=source(parent/"progress.json"),
        runtime=source(RUNTIME/"geometric/internal.py"), source=source(Path(__file__)),
        cached_steps=steps, proposed_steps=proposed,
        interpretation=[
            "Early energy increases are consistent with endpoint-gradient line integrals; linear descent alone ignores curvature.",
            "Step 4 is accepted despite uphill energy because the energy increment meets the optimizer energy criterion.",
            "Subsequent vanishing steps do not establish stationarity.",
            "conmethod=0 with exact constraint enforcement is the runtime's documented, more extensively tested default path.",
            "A coordinate-step audit is not a native energy test or convergence proof.",
        ], simulation_ready=False)
    write(output/"assessment.json", report)
    print(json.dumps(dict(cached_steps=len(steps), proposed_steps=proposed), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.parent.resolve(), args.output.resolve())

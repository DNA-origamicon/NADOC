"""Constrained relaxed-MM predictions for the frozen ring pilot; no QM output reads."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import unit as u
from scipy.optimize import minimize, NonlinearConstraint, root as solve_root

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import (
    AdiabaticNonbonded,
    checked,
    source,
    write,
)
from backend.parameterization.photoproduct_bonded_fit_plan import _dihedral
from backend.parameterization.photoproduct_openmm_linear_response import (
    mass_weighted_rigid_body_projector,
)


def main(root, plan_path, recovery, fits):
    root.mkdir(exist_ok=False)
    snapshot = root / "source_snapshot.py"
    snapshot.write_text(Path(__file__).read_text())
    plan = json.loads(plan_path.read_text())
    policy = {
        "simulation_ready": False,
        "gate_effect": "none",
        "qm_scan_outputs_read": False,
        "plan": source(plan_path),
        "fits": [source(f) for f in fits],
        "code": source(snapshot),
        "optimizer": {
            "method": "trust-constr",
            "initial_tr_radius_angstrom": 0.02,
            "gtol": 1e-6,
            "xtol": 1e-10,
            "maxiter": 500,
        },
        "force_refinement": "KKT root solve after trust-constr; finite-difference torsion derivative, unchanged force tolerance",
        "scope": "Local constrained MM stationary candidates from identical QM reference starts; no global-minimum or validation claim. All numerical failures retained.",
    }
    write(root / "policy.json", policy)
    xyz = np.array(
        [
            [float(v) for v in l.split()[1:]]
            for l in plan["molecule"].splitlines()
            if len(l.split()) == 4
        ]
    )
    projector, rank = mass_weighted_rigid_body_projector(xyz, np.ones(len(xyz)))
    assert rank == 6
    eig, vec = np.linalg.eigh(projector)
    basis = vec[:, eig > 0.5]
    origin = xyz.ravel()
    indices = plan["indices_zero_based"]
    cases = [
        {"id": "reference", "target_degrees": plan["reference_dihedral_degrees"]},
        *plan["cases"],
    ]
    records = []
    for fit_record in policy["fits"]:
        path = checked(fit_record)
        stage = path.parent
        fit = json.loads(path.read_text())
        fp = json.loads((stage / "policy.json").read_text())
        model = AdiabaticNonbonded(recovery, checked(fp["electrostatics"]))
        system_path = stage / "basis/linear_fit_system.xml"
        system = mm.XmlSerializer.deserialize(system_path.read_text())
        integrator = mm.VerletIntegrator(0.001)
        context = mm.Context(
            system, integrator, mm.Platform.getPlatformByName("Reference")
        )
        for p in fit["parameters"]:
            context.setParameter(p["name"], p["coefficient"])

        def coords(x):
            return (origin + basis @ x).reshape(-1, 3)

        def objective(x, model=model, context=context):
            points = coords(x)
            energy, gradient = model.energy_gradient(points)
            context.setPositions(points * u.angstrom)
            state = context.getState(getEnergy=True, getForces=True)
            energy += state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
            gradient = (
                np.asarray(gradient).ravel()
                - np.asarray(
                    state.getForces(asNumpy=True).value_in_unit(
                        u.kilocalorie_per_mole / u.angstrom
                    )
                ).ravel()
            )
            return float(energy), basis.T @ gradient

        def angle(x):
            return np.radians(_dihedral(*coords(x)[indices]))

        for case in cases:
            write(
                root / "progress.json",
                {
                    "state": "running",
                    "fit": str(path),
                    "case_id": case["id"],
                    "simulation_ready": False,
                },
            )
            target = np.radians(case["target_degrees"])
            try:
                result = minimize(
                    objective,
                    np.zeros(basis.shape[1]),
                    jac=True,
                    method="trust-constr",
                    constraints=[
                        NonlinearConstraint(angle, target, target, jac="3-point")
                    ],
                    options={
                        "initial_tr_radius": 0.02,
                        "gtol": 1e-6,
                        "xtol": 1e-10,
                        "maxiter": 500,
                    },
                )

                def angle_gradient(x):
                    gradient = np.empty(len(x))
                    step = 1e-5
                    for j in range(len(x)):
                        plus, minus = x.copy(), x.copy()
                        plus[j] += step
                        minus[j] -= step
                        gradient[j] = (angle(plus) - angle(minus)) / (2 * step)
                    return gradient

                def kkt(z):
                    x, multiplier = z[:-1], z[-1]
                    return np.r_[
                        objective(x)[1] + multiplier * angle_gradient(x),
                        angle(x) - target,
                    ]

                polished = solve_root(
                    kkt,
                    np.r_[result.x, float(result.v[0][0])],
                    method="hybr",
                    options={"xtol": 1e-9, "eps": 1e-8, "maxfev": 3000},
                )
                residual = kkt(polished.x)
                result.x = polished.x[:-1]
                result.lagrangian_grad = residual[:-1]
                result.constr_violation = abs(residual[-1])
                e, g = objective(result.x)
                record = {
                    "fit": fit_record,
                    "case_id": case["id"],
                    "optimizer_success": bool(result.success),
                    "stationary_solver_success": bool(polished.success),
                    "stationary_solver_message": str(polished.message),
                    "message": str(result.message),
                    "iterations": int(result.nit),
                    "energy_kcal_mol": e,
                    "geometry_angstrom": coords(result.x).tolist(),
                    "final_angle_degrees": float(np.degrees(angle(result.x))),
                    "constraint_error_degrees": float(
                        np.degrees(angle(result.x)) - case["target_degrees"]
                    ),
                    "lagrangian_gradient_max": float(abs(result.lagrangian_grad).max()),
                    "constraint_violation_radians": float(result.constr_violation),
                    "stationarity_checked": bool(
                        abs(result.lagrangian_grad).max() <= 1e-5
                        and abs(np.degrees(angle(result.x)) - case["target_degrees"])
                        <= 0.001
                    ),
                    "bonded_system": source(system_path),
                    "electrostatics": fp["electrostatics"],
                }
            except ValueError as error:
                record = {
                    "fit": fit_record,
                    "case_id": case["id"],
                    "status": "numerical_or_domain_failure",
                    "reason": str(error),
                    "stationarity_checked": False,
                }
            records.append(record)
            write(
                root / "predictions.json",
                {
                    "simulation_ready": False,
                    "gate_effect": "none",
                    "qm_scan_outputs_read": False,
                    "policy": source(root / "policy.json"),
                    "records": records,
                },
            )
        del context, integrator, model
    write(
        root / "progress.json",
        {"state": "completed", "records": len(records), "simulation_ready": False},
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for n in ("root", "plan", "recovery"):
        p.add_argument("--" + n, type=Path, required=True)
    p.add_argument("--fit", type=Path, action="append", required=True)
    a = p.parse_args()
    main(
        a.root.resolve(),
        a.plan.resolve(),
        a.recovery.resolve(),
        [f.resolve() for f in a.fit],
    )

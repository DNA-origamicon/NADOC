"""Fixed-torsion tangent-space Lagrangian curvature and stereo audit."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import unit as u
from scipy.linalg import null_space

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import (
    AdiabaticNonbonded,
    checked,
    source,
    write,
)
from experiments.cpd_drude_recovery.audit_relaxed_ring import geometry_checks
from backend.parameterization.photoproduct_openmm_linear_response import (
    mass_weighted_rigid_body_projector,
)
from backend.parameterization.photoproduct_bonded_fit_plan import _dihedral


def main(predictions, recovery, root):
    root.mkdir(exist_ok=False)
    (root / "source_snapshot.py").write_text(Path(__file__).read_text())
    data = json.loads(predictions.read_text())
    policy = json.loads(checked(data["policy"]).read_text())
    plan = json.loads(checked(policy["plan"]).read_text())
    reference = np.array(
        [
            [float(v) for v in l.split()[1:]]
            for l in plan["molecule"].splitlines()
            if len(l.split()) == 4
        ]
    )
    target = {c["id"]: c["target_degrees"] for c in plan["cases"]}
    target["reference"] = plan["reference_dihedral_degrees"]
    constraint_system = mm.System()
    for _ in range(36):
        constraint_system.addParticle(1)
    torsion = mm.CustomTorsionForce("theta")
    torsion.addTorsion(*plan["indices_zero_based"], [])
    constraint_system.addForce(torsion)
    ci = mm.VerletIntegrator(0.001)
    cc = mm.Context(constraint_system, ci, mm.Platform.getPlatformByName("Reference"))

    def constraint(xyz):
        cc.setPositions(xyz * u.angstrom)
        s = cc.getState(getEnergy=True, getForces=True)
        return float(
            s.getPotentialEnergy().value_in_unit(u.kilojoule_per_mole)
        ), -np.asarray(
            s.getForces(asNumpy=True).value_in_unit(u.kilojoule_per_mole / u.angstrom)
        ).ravel()

    records = []
    for fit_record in policy["fits"]:
        fit_path = checked(fit_record)
        stage = fit_path.parent
        fit = json.loads(fit_path.read_text())
        fp = json.loads((stage / "policy.json").read_text())
        model = AdiabaticNonbonded(recovery, checked(fp["electrostatics"]))
        system = mm.XmlSerializer.deserialize(
            (stage / "basis/linear_fit_system.xml").read_text()
        )
        integ = mm.VerletIntegrator(0.001)
        context = mm.Context(system, integ, mm.Platform.getPlatformByName("Reference"))
        for p in fit["parameters"]:
            context.setParameter(p["name"], p["coefficient"])
        fit_plan = json.loads((stage / "bonded_fit_plan.json").read_text())

        def gradient(xyz, model=model, context=context):
            _, g = model.energy_gradient(xyz)
            context.setPositions(xyz * u.angstrom)
            f = np.asarray(
                context.getState(getForces=True)
                .getForces(asNumpy=True)
                .value_in_unit(u.kilocalorie_per_mole / u.angstrom)
            ).ravel()
            return np.asarray(g).ravel() - f

        for row in data["records"]:
            if row["fit"] != fit_record:
                continue
            assert row["stationarity_checked"]
            checked(row["bonded_system"])
            checked(row["electrostatics"])
            xyz = np.array(row["geometry_angstrom"])
            q, gc = constraint(xyz)
            assert (
                abs(np.degrees(q) - _dihedral(*xyz[plan["indices_zero_based"]])) < 1e-8
            )
            projector, rank = mass_weighted_rigid_body_projector(xyz, np.ones(36))
            assert rank == 6
            vals, vec = np.linalg.eigh(projector)
            internal = vec[:, vals > 0.5]
            normal = internal.T @ gc
            tangent = internal @ null_space(normal.reshape(1, -1))
            assert tangent.shape == (108, 101)
            g = gradient(xyz)
            multiplier = -float(normal @ (internal.T @ g)) / (normal @ normal)
            lagrangian = g + multiplier * gc
            hessians = []
            for step in (1e-4, 5e-5):
                h = np.empty((101, 101))
                for j in range(101):
                    move = tangent[:, j].reshape(36, 3) * step
                    plus, minus = xyz + move, xyz - move
                    gp = gradient(plus) + multiplier * constraint(plus)[1]
                    gm = gradient(minus) + multiplier * constraint(minus)[1]
                    h[:, j] = tangent.T @ (gp - gm) / (2 * step)
                hessians.append((h + h.T) / 2)
            eigenvalues = [float(np.linalg.eigvalsh(h).min()) for h in hessians]
            relative = float(
                np.linalg.norm(hessians[0] - hessians[1]) / np.linalg.norm(hessians[1])
            )
            geom = geometry_checks(
                xyz,
                reference,
                model.d.ATOM_NAMES,
                model.d._bonds(),
                fit_plan["stereochemical_impropers"],
                plan["indices_zero_based"],
                target[row["case_id"]],
            )
            force = float(abs(internal.T @ lagrangian).max())
            records.append(
                {
                    "fit": fit_record,
                    "case_id": row["case_id"],
                    "lagrangian_gradient_max": force,
                    "constraint_multiplier_kcal_mol_radian": multiplier,
                    "minimum_tangent_curvatures_kcal_mol_angstrom2": eigenvalues,
                    "hessian_halving_relative_error": relative,
                    "geometry": geom,
                    "local_constrained_minimum_checks_passed": bool(
                        force <= 1e-5
                        and min(eigenvalues) > 0
                        and relative <= 0.001
                        and geom["constraint_satisfied"]
                        and geom["all_stereo_preserved"]
                    ),
                }
            )
            write(
                root / "assessment.json",
                {
                    "simulation_ready": False,
                    "gate_effect": "none",
                    "qm_scan_outputs_read": False,
                    "scope": "Local constrained minimum check, 101 tangent directions after removing rigid motion and torsion constraint. Lagrangian Hessian includes multiplier times torsion Hessian. Not global or QM agreement.",
                    "predictions": source(predictions),
                    "script": source(root / "source_snapshot.py"),
                    "records": records,
                },
            )
        del context, integ, model
    print(
        "Checked",
        len(records),
        "passed",
        sum(r["local_constrained_minimum_checks_passed"] for r in records),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for n in ("predictions", "recovery", "root"):
        p.add_argument("--" + n, type=Path, required=True)
    a = p.parse_args()
    main(a.predictions.resolve(), a.recovery.resolve(), a.root.resolve())

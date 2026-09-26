"""Bounded equilibrium-angle refinement; explicitly a training fit, not validation."""

import json
from pathlib import Path
import sys
import argparse
import numpy as np
import openmm as mm
from openmm import app, unit as u
from scipy.optimize import minimize, least_squares

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.local_benchmarks import checked, angle
from experiments.cpd_published_comparator.reconstruct import write, source


def main(root, emphasize_outliers=False):
    from experiments.cpd_anti_additive.validation_gate import require_fit_ready
    require_fit_ready()
    root.mkdir(exist_ok=False)
    base = Path(".development-artifacts/cpd-anti-additive-core-baseline-v1").resolve()
    from experiments.cpd_drude_recovery.campaign import OLD

    campaign = json.loads(
        (
            OLD / "bundle/results/response_campaign/response_campaign_manifest.json"
        ).read_text()
    )
    manifest = json.loads(
        checked(campaign["training_datasets"][0]["response_manifest"]).read_text()
    )
    names = [
        a["stable_atom_key"]
        for a in json.loads(checked(manifest["sources"]["stable_atom_map"]).read_text())
    ]
    xyz = np.array(
        [
            list(map(float, l.split()[1:]))
            for l in checked(manifest["sources"]["target_geometry"])
            .read_text()
            .splitlines()[2:]
            if l.strip()
        ]
    )
    psf = app.CharmmPsfFile(str(base / "core.psf"))
    system = mm.XmlSerializer.deserialize((base / "last_system.xml").read_text())
    af = next(f for f in system.getForces() if isinstance(f, mm.HarmonicAngleForce))
    records = []
    groups = {}
    for i in range(af.getNumAngles()):
        a, b, c, t, k = af.getAngleParameters(i)
        types = tuple(psf.atom_list[j].attype for j in (a, b, c))
        key = min(types, types[::-1])
        groups.setdefault(key, len(groups))
        records.append((a, b, c, float(t.value_in_unit(u.radian)), k, groups[key]))
    target = np.array([angle(xyz, r[:3]) for r in records])
    bonds = [(b.atom1.idx, b.atom2.idx) for b in psf.bond_list]
    target_bonds = np.array([np.linalg.norm(xyz[a] - xyz[b]) for a, b in bonds])
    write(
        root / "plan.json",
        {
            "product_id": "tt-cpd-cis-anti-i",
            "scope": "Isolated core diagnostic only; do not export shared types to DNA. Joint CPD-specific core/sugar refit required.",
            "status": "training_refinement",
            "angle_groups": len(groups),
            "shift_bound_deg": 6,
            "emphasize_outliers": emphasize_outliers,
            "max_optimizer_evaluations": 50,
            "unchanged": ["force constants", "charges", "torsions", "nonbonded"],
            "criteria": {"max_angle_error_deg": 3, "max_bond_error_A": 0.03},
            "sources": [source(base / "last_system.xml"), source(Path(__file__))],
        },
    )
    (root / "executed_source.py").write_text(Path(__file__).read_text())
    integrator = mm.VerletIntegrator(0.001)
    context = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
    initial = np.loadtxt(base / "last_minimum_A.txt")
    history = []

    def fit_geometry(shifts):
        for i, (a, b, c, t, k, g) in enumerate(records):
            af.setAngleParameters(i, a, b, c, t + np.radians(shifts[g]), k)
        af.updateParametersInContext(context)

        def objective(flat):
            context.setPositions(flat.reshape(-1, 3) * u.angstrom)
            s = context.getState(getEnergy=True, getForces=True)
            return s.getPotentialEnergy().value_in_unit(
                u.kilocalorie_per_mole
            ), -np.asarray(
                s.getForces(asNumpy=True).value_in_unit(
                    u.kilocalorie_per_mole / u.angstrom
                )
            ).ravel()

        sol = minimize(
            objective,
            initial.ravel(),
            jac=True,
            method="L-BFGS-B",
            options={"maxiter": 2500, "ftol": 1e-15, "gtol": 1e-7, "maxls": 40},
        )
        x = sol.x.reshape(-1, 3)
        ae = np.array([angle(x, r[:3]) for r in records]) - target
        be = np.array([np.linalg.norm(x[a] - x[b]) for a, b in bonds]) - target_bonds
        return x, ae, be, float(np.max(np.abs(objective(sol.x)[1])))

    def residual(shifts):
        x, ae, be, force = fit_geometry(shifts)
        history.append(
            {
                "max_angle_error": float(max(abs(ae))),
                "max_bond_error": float(max(abs(be))),
                "max_force": force,
            }
        )
        ordinary = np.r_[ae / 3, be / 0.03, shifts / 6 * 0.15]
        return (
            np.r_[ordinary, 2 * np.maximum(np.abs(ae) - 2.8, 0)]
            if emphasize_outliers
            else ordinary
        )

    # Explicit finite-difference step avoids minimizer noise at machine-epsilon steps.
    def jac(shifts):
        h = 0.02
        cols = []
        for i in range(len(shifts)):
            plus = shifts.copy()
            minus = shifts.copy()
            plus[i] += h
            minus[i] -= h
            cols.append((residual(plus) - residual(minus)) / (2 * h))
        return np.array(cols).T

    result = least_squares(
        residual,
        np.zeros(len(groups)),
        jac=jac,
        bounds=(-6, 6),
        max_nfev=50,
        ftol=1e-5,
        xtol=1e-5,
        gtol=1e-5,
    )
    x, ae, be, force = fit_geometry(result.x)
    np.savetxt(root / "minimum_A.txt", x)
    (root / "candidate.xml").write_text(mm.XmlSerializer.serialize(system))
    write(
        root / "assessment.json",
        {
            "status": "training_fit_only",
            "simulation_ready": False,
            "max_angle_error_deg": float(max(abs(ae))),
            "max_bond_error_A": float(max(abs(be))),
            "max_force": force,
            "optimizer_success": bool(result.success),
            "optimizer_message": result.message,
            "angle_changes": [
                {"types": key, "delta_deg": float(result.x[g])}
                for key, g in groups.items()
            ],
            "angles": [
                {"atoms": [names[i] for i in r[:3]], "error_deg": float(e)}
                for r, e in zip(records, ae)
            ],
            "history": history,
        },
    )
    print("max angle", max(abs(ae)), "max bond", max(abs(be)), "max force", force)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--emphasize-outliers", action="store_true")
    args = p.parse_args()
    main(args.root.resolve(), args.emphasize_outliers)

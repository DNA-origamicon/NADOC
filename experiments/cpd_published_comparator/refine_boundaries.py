"""Shared, bounded glycosidic geometry training fit; isolated from production."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u
from scipy.optimize import least_squares, minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.local_benchmarks import angle, checked, volume
from experiments.cpd_published_comparator.reconstruct import BASE, FF, source, write

BASELINE = Path(".development-artifacts/cpd-sugar-boundary-validation-v2").resolve()
CORE = Path(".development-artifacts/cpd-angle-native-v1").resolve()


def main(root, guard_collateral=False):
    root.mkdir(exist_ok=False)
    shutil.copyfile(__file__, root / "executed_source.py")
    cases, groups = [], {}
    for endpoint in (1, 2):
        folder = BASELINE / f"endpoint-{endpoint}"
        report = json.loads((folder / "assessment.json").read_text())
        manifest = json.loads(checked(report["sources"][1]).read_text())
        names = manifest["atom_map"]
        xyz = np.array(
            [
                list(map(float, line.split()[1:]))
                for line in checked(report["sources"][0]).read_text().splitlines()[2:]
                if line.strip()
            ]
        )
        psf = app.CharmmPsfFile(str(folder / "fragment.psf"))
        system = mm.XmlSerializer.deserialize((folder / "system.xml").read_text())
        bond = next(
            f for f in system.getForces() if isinstance(f, mm.HarmonicBondForce)
        )
        angles = next(
            f for f in system.getForces() if isinstance(f, mm.HarmonicAngleForce)
        )
        glyco = {names.index(f"{endpoint}:N1"), names.index(f"{endpoint}:C1'")}
        records = []
        for force, count, getter, kind in [
            (bond, bond.getNumBonds(), bond.getBondParameters, "bond"),
            (angles, angles.getNumAngles(), angles.getAngleParameters, "angle"),
        ]:
            for i in range(count):
                args = getter(i)
                ids = tuple(int(v) for v in args[:-2])
                if not glyco.issubset(ids):
                    continue
                types = tuple(psf.atom_list[j].attype for j in ids)
                key = (kind, min(types, types[::-1]))
                groups.setdefault(key, len(groups))
                records.append((force, i, args, groups[key], kind))
        assert len(records) == 6
        integrator = mm.VerletIntegrator(0.001)
        ctx = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
        all_angles = [(a.atom1.idx, a.atom2.idx, a.atom3.idx) for a in psf.angle_list]
        all_bonds = [(b.atom1.idx, b.atom2.idx) for b in psf.bond_list]
        cases.append(
            dict(
                endpoint=endpoint,
                report=report,
                names=names,
                xyz=xyz,
                psf=psf,
                system=system,
                integrator=integrator,
                ctx=ctx,
                records=records,
                initial=np.loadtxt(folder / "minimum_A.txt"),
                all_angles=all_angles,
                all_bonds=all_bonds,
            )
        )
    assert len(groups) == 6, (
        "One shared bond plus five shared angle parameters required"
    )
    write(
        root / "plan.json",
        dict(
            scope="training fit on both sugar endpoints",
            simulation_ready=False,
            bounds={"bond_equilibrium_shift_A": 0.03, "angle_equilibrium_shift_deg": 6},
            unchanged=[
                "force constants",
                "charges",
                "torsions",
                "nonbonded",
                "capped core",
            ],
            criteria={"bond_error_A": 0.03, "angle_error_deg": 3},
            guard_collateral=guard_collateral,
            sources=[
                source(BASELINE / "assessment.json"),
                source(CORE / "comparator_last.prm"),
                source(Path(__file__)),
            ],
        ),
    )

    def geometry(case, shifts):
        for force, i, args, g, kind in case["records"]:
            delta = shifts[g] * (0.03 * u.angstrom if kind == "bond" else 6 * u.degree)
            setter = (
                force.setBondParameters if kind == "bond" else force.setAngleParameters
            )
            setter(i, *args[:-2], args[-2] + delta, args[-1])
        for force in {r[0] for r in case["records"]}:
            force.updateParametersInContext(case["ctx"])

        def objective(flat):
            case["ctx"].setPositions(flat.reshape(-1, 3) * u.angstrom)
            state = case["ctx"].getState(getEnergy=True, getForces=True)
            return state.getPotentialEnergy().value_in_unit(
                u.kilocalorie_per_mole
            ), -np.asarray(
                state.getForces(asNumpy=True).value_in_unit(
                    u.kilocalorie_per_mole / u.angstrom
                )
            ).ravel()

        sol = minimize(
            objective,
            case["initial"].ravel(),
            jac=True,
            method="L-BFGS-B",
            options={"maxiter": 4000, "ftol": 1e-15, "gtol": 1e-7, "maxls": 40},
        )
        x = sol.x.reshape(-1, 3)
        errors = []
        for _, _, args, _, kind in case["records"]:
            ids = list(args[:-2])
            if kind == "bond":
                a, b = ids
                errors.append(
                    (
                        np.linalg.norm(x[a] - x[b])
                        - np.linalg.norm(case["xyz"][a] - case["xyz"][b])
                    )
                    / 0.03
                )
            else:
                errors.append((angle(x, ids) - angle(case["xyz"], ids)) / 3)
        return x, np.asarray(errors), float(np.max(np.abs(objective(sol.x)[1]))), sol

    history = []

    def residual(shifts):
        results = [geometry(c, shifts) for c in cases]
        errors = np.concatenate([r[1] for r in results])
        history.append(
            dict(
                max_normalized_error=float(max(abs(errors))),
                max_force=max(r[2] for r in results),
            )
        )
        if len(history) % 20 == 0:
            print("evaluations", len(history), history[-1], flush=True)
        collateral = []
        if guard_collateral:
            for c, (x, _, _, _) in zip(cases, results):
                for ids in c["all_angles"]:
                    before = abs(angle(c["initial"], ids) - angle(c["xyz"], ids))
                    after = abs(angle(x, ids) - angle(c["xyz"], ids))
                    collateral.append(
                        50 * max(after - 2.95, 0) / 3 if before <= 3 else 0
                    )
                for a, b in c["all_bonds"]:
                    target = np.linalg.norm(c["xyz"][a] - c["xyz"][b])
                    before = abs(
                        np.linalg.norm(c["initial"][a] - c["initial"][b]) - target
                    )
                    after = abs(np.linalg.norm(x[a] - x[b]) - target)
                    collateral.append(
                        50 * max(after - 0.0299, 0) / 0.03 if before <= 0.03 else 0
                    )
        return np.r_[
            errors, 2 * np.maximum(abs(errors) - 0.9, 0), shifts * 0.1, collateral
        ]

    def jac(shifts):
        h = 0.005
        cols = []
        for i in range(len(shifts)):
            plus, minus = shifts.copy(), shifts.copy()
            plus[i] += h
            minus[i] -= h
            cols.append((residual(plus) - residual(minus)) / (2 * h))
        return np.array(cols).T

    fit = least_squares(
        residual,
        np.zeros(len(groups)),
        jac=jac,
        bounds=(-1, 1),
        max_nfev=35,
        ftol=1e-5,
        xtol=1e-5,
        gtol=1e-5,
    )
    changes = [
        dict(
            kind=kind,
            types=types,
            delta=float(fit.x[g]) * (0.03 if kind == "bond" else 6),
        )
        for (kind, types), g in groups.items()
    ]
    results = []
    for c in cases:
        x, errors, max_force, sol = geometry(c, fit.x)
        out = root / f"endpoint-{c['endpoint']}"
        out.mkdir()
        for file in ["fragment.psf", "fragment.rtf"]:
            shutil.copyfile(BASELINE / out.name / file, out / file)
        np.savetxt(out / "minimum_A.txt", x)
        (out / "system.xml").write_text(mm.XmlSerializer.serialize(c["system"]))
        report = dict(c["report"])
        report.update(
            evidence_role="training",
            optimizer_success=bool(sol.success),
            max_force=max_force,
        )
        report["boundary_bond_error_A"] = float(errors[0] * 0.03)
        for a in report["angles"]:
            ids = [c["names"].index(n) for n in a["atoms"]]
            a["mm_deg"] = angle(x, ids)
            a["error_deg"] = a["mm_deg"] - a["qm_deg"]
        report["max_boundary_angle_error_deg"] = max(
            abs(a["error_deg"]) for a in report["angles"]
        )
        orders = {
            f"{c['endpoint']}:{center}": [f"{c['endpoint']}:{n}" for n in seq]
            for center, seq in [
                ("C1'", ["O4'", "C2'", "N1", "H1'"]),
                ("C3'", ["C2'", "C4'", "O3'", "H3'"]),
                ("C4'", ["O4'", "C3'", "C5'", "H4'"]),
            ]
        }
        for r in (1, 2):
            orders[f"{r}:C5"] = [f"{r}:C4", f"{r}:C6", f"{r}:C7", f"{3 - r}:C5"]
            orders[f"{r}:C6"] = [f"{r}:N1", f"{r}:C5", f"{r}:H6", f"{3 - r}:C6"]
        for center in report["centers"]:
            center["mm"] = volume(
                x, [c["names"].index(n) for n in orders[center["center"]]]
            )
            center["preserved"] = center["qm"] * center["mm"] > 0
        report["stereochemistry_passed"] = all(
            v["preserved"] for v in report["centers"]
        )
        report["boundary_geometry_passed"] = (
            abs(report["boundary_bond_error_A"]) <= 0.03
            and report["max_boundary_angle_error_deg"] <= 3
        )
        # Record all off-target changes rather than hiding geometric coupling.
        report["all_angles"] = [
            dict(
                atoms=[c["names"][i] for i in ids],
                before_error_deg=angle(c["initial"], ids) - angle(c["xyz"], ids),
                error_deg=angle(x, ids) - angle(c["xyz"], ids),
            )
            for ids in c["all_angles"]
        ]
        report["all_bonds"] = [
            dict(
                atoms=[c["names"][i] for i in ids],
                before_error_A=float(
                    np.linalg.norm(c["initial"][ids[0]] - c["initial"][ids[1]])
                    - np.linalg.norm(c["xyz"][ids[0]] - c["xyz"][ids[1]])
                ),
                error_A=float(
                    np.linalg.norm(x[ids[0]] - x[ids[1]])
                    - np.linalg.norm(c["xyz"][ids[0]] - c["xyz"][ids[1]])
                ),
            )
            for ids in c["all_bonds"]
        ]
        write(out / "assessment.json", report)
        results.append(report)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pars = app.CharmmParameterSet(
            str(BASE / "top_all36_na.rtf"),
            str(BASE / "par_all36_na.prm"),
            str(FF / "top_all36_cgenff.rtf"),
            str(FF / "par_all36_cgenff.prm"),
            str(CORE / "comparator_last.prm"),
        )
    prm = (CORE / "comparator_last.prm").read_text().rsplit("END", 1)[0]
    for kind, heading in [("bond", "BONDS"), ("angle", "ANGLES")]:
        prm += "\n" + heading + "\n"
        for row in changes:
            if row["kind"] != kind:
                continue
            key = tuple(row["types"])
            p = (pars.bond_types if kind == "bond" else pars.angle_types)[key]
            value = (p.req if kind == "bond" else p.theteq) + row["delta"]
            prm += " ".join(key) + f" {p.k:.12g} {value:.12g}"
            if kind == "angle":
                ub = pars.urey_bradley_types.get(key)
                if ub is not None and ub.k not in (None, 0):
                    prm += f" {ub.k:.12g} {ub.req:.12g}"
            prm += "\n"
    (root / "comparator_last.prm").write_text(prm + "END\n")
    shutil.copyfile(CORE / "comparator.rtf", root / "comparator.rtf")
    write(
        root / "assessment.json",
        dict(
            simulation_ready=False,
            evidence_role="training",
            optimizer_success=bool(fit.success),
            optimizer_message=fit.message,
            parameter_changes=changes,
            records=results,
            history=history,
        ),
    )
    print(
        json.dumps(
            {
                "changes": changes,
                "endpoints": [
                    {
                        k: r[k]
                        for k in [
                            "endpoint",
                            "boundary_bond_error_A",
                            "max_boundary_angle_error_deg",
                            "stereochemistry_passed",
                            "max_force",
                        ]
                    }
                    for r in results
                ],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--guard-collateral", action="store_true")
    args = parser.parse_args()
    main(args.root.resolve(), args.guard_collateral)

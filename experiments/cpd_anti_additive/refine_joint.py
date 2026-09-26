"""Joint three-compound geometry training. Experimental overlay, never production."""

import argparse
import copy
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
from experiments.cpd_published_comparator.local_benchmarks import (
    checked,
    angle,
    volume,
)
from experiments.cpd_published_comparator.reconstruct import BASE, FF, source, write

ART = Path(".development-artifacts").resolve()
PARENT = ART / "cpd-published-comparator-v1"


def load_cases():
    from experiments.cpd_anti_additive.prepare_anti_types import (
        load_cases as base_cases,
    )
    from experiments.cpd_drude_recovery.campaign import OLD

    cases = base_cases()
    campaign = json.loads(
        (
            OLD / "bundle/results/response_campaign/response_campaign_manifest.json"
        ).read_text()
    )
    manifest = json.loads(
        checked(campaign["training_datasets"][0]["response_manifest"]).read_text()
    )
    for c in cases:
        e = 0 if c["id"] == "core" else int(c["id"][-1])
        c["endpoint"] = e
        folder = c["psf_path"].parent
        c["minimum"] = folder / ("last_minimum_A.txt" if e == 0 else "minimum_A.txt")
        c["system_path"] = folder / ("last_system.xml" if e == 0 else "system.xml")
        c["rtf_path"] = folder / ("core.rtf" if e == 0 else "fragment.rtf")
        if e:
            report = json.loads((folder / "assessment.json").read_text())
            c["report"] = report
            c["target"] = checked(report["sources"][0])
        else:
            c["target"] = checked(manifest["sources"]["target_geometry"])
        c["qm"] = np.array(
            [
                list(map(float, l.split()[1:]))
                for l in c["target"].read_text().splitlines()[2:]
                if l.strip()
            ]
        )
        c["psf"] = app.CharmmPsfFile(str(c["psf_path"]))
        c["angles"] = [
            (a.atom1.idx, a.atom2.idx, a.atom3.idx) for a in c["psf"].angle_list
        ]
        c["bonds"] = [(b.atom1.idx, b.atom2.idx) for b in c["psf"].bond_list]
    return sorted(cases, key=lambda c: c["endpoint"] or 3)


def main(
    root, all_angles, typed_input=None, warm_start=None, all_bonds=False, max_nfev=40
):
    from experiments.cpd_anti_additive.validation_gate import require_fit_ready
    require_fit_ready()
    root.mkdir(exist_ok=False)
    shutil.copy2(__file__, root / "executed_source.py")
    assert typed_input is not None, "Anti refinement requires isolated role aliases"
    cases = load_cases()
    parent_parameters = PARENT / "comparator_last.prm"
    if typed_input:
        parent_parameters = typed_input / "comparator_last.prm"
        for c in cases:
            c["psf_path"] = typed_input / c["id"] / "fragment.psf"
            c["system_path"] = typed_input / c["id"] / "system.xml"
            c["psf"] = app.CharmmPsfFile(str(c["psf_path"]))
            c["system"] = mm.XmlSerializer.deserialize(c["system_path"].read_text())
            c["angles"] = [
                (a.atom1.idx, a.atom2.idx, a.atom3.idx) for a in c["psf"].angle_list
            ]
            c["bonds"] = [(b.atom1.idx, b.atom2.idx) for b in c["psf"].bond_list]
    selected = set()
    for c in cases:
        for ids in c["angles"]:
            if all_angles or abs(angle(c["initial"], ids) - angle(c["qm"], ids)) > 2.5:
                types = tuple(c["psf"].atom_list[i].attype for i in ids)
                selected.add(("angle", min(types, types[::-1])))
    for c in cases[:2]:
        e = c["endpoint"]
        types = tuple(
            c["psf"].atom_list[c["names"].index(n)].attype
            for n in (f"{e}:C1'", f"{e}:N1")
        )
        selected.add(("bond", min(types, types[::-1])))
    if all_bonds:
        for c in cases:
            for ids in c["bonds"]:
                types = tuple(c["psf"].atom_list[i].attype for i in ids)
                selected.add(("bond", min(types, types[::-1])))
    groups = {key: i for i, key in enumerate(sorted(selected))}
    for c in cases:
        c["records"] = []
        forces = c["system"].getForces()
        primary_bonds = next(f for f in forces if isinstance(f, mm.HarmonicBondForce))
        for force in forces:
            if isinstance(force, mm.HarmonicAngleForce):
                kind, getter, count = (
                    "angle",
                    force.getAngleParameters,
                    force.getNumAngles(),
                )
            elif isinstance(force, mm.HarmonicBondForce):
                if force is not primary_bonds:
                    continue
                kind, getter, count = (
                    "bond",
                    force.getBondParameters,
                    force.getNumBonds(),
                )
            else:
                continue
            for i in range(count):
                args = getter(i)
                types = tuple(c["psf"].atom_list[int(j)].attype for j in args[:-2])
                key = (kind, min(types, types[::-1]))
                if key in groups:
                    c["records"].append((force, i, args, groups[key], kind))
        c["integrator"] = mm.VerletIntegrator(0.001)
        c["ctx"] = mm.Context(
            c["system"], c["integrator"], mm.Platform.getPlatformByName("Reference")
        )
    write(
        root / "plan.json",
        dict(
            simulation_ready=False,
            scope="Joint training of core and two sugar fragments",
            no_production_export=True,
            standard_sugar_overrides_require_CPD_specific_typing=True,
            groups=[dict(kind=k[0], types=k[1]) for k in groups],
            max_nfev=max_nfev,
            warm_start=source(warm_start / "assessment.json") if warm_start else None,
            angle_shift_bound_deg=6,
            bond_shift_bound_A=0.01,
            acceptance={"all_angles_deg": 3, "all_bonds_A": 0.03},
            sources=[
                source(c[k])
                for c in cases
                for k in ["target", "psf_path", "system_path", "minimum"]
            ],
        ),
    )
    print("Shared parameter groups", len(groups), flush=True)

    def set_parameters(c, shifts):
        for force, i, args, g, kind in c["records"]:
            setter = (
                force.setAngleParameters if kind == "angle" else force.setBondParameters
            )
            setter(
                i,
                *args[:-2],
                args[-2]
                + shifts[g] * (6 * u.degree if kind == "angle" else 0.01 * u.angstrom),
                args[-1],
            )
        for f in {r[0] for r in c["records"]}:
            f.updateParametersInContext(c["ctx"])

    def relax(c, shifts):
        set_parameters(c, shifts)

        def objective(flat):
            c["ctx"].setPositions(flat.reshape(-1, 3) * u.angstrom)
            s = c["ctx"].getState(getEnergy=True, getForces=True)
            return s.getPotentialEnergy().value_in_unit(
                u.kilocalorie_per_mole
            ), -np.asarray(
                s.getForces(asNumpy=True).value_in_unit(
                    u.kilocalorie_per_mole / u.angstrom
                )
            ).ravel()

        result = minimize(
            objective,
            c["initial"].ravel(),
            jac=True,
            method="L-BFGS-B",
            options={"maxiter": 4000, "ftol": 1e-15, "gtol": 1e-7, "maxls": 40},
        )
        x = result.x.reshape(-1, 3)
        ae = np.array([angle(x, ids) - angle(c["qm"], ids) for ids in c["angles"]])
        be = np.array(
            [
                np.linalg.norm(x[a] - x[b]) - np.linalg.norm(c["qm"][a] - c["qm"][b])
                for a, b in c["bonds"]
            ]
        )
        return x, ae, be, float(max(abs(objective(result.x)[1])))

    history = []

    def residual(shifts):
        results = [relax(c, shifts) for c in cases]
        normalized = np.concatenate([np.r_[a / 3, b / 0.03] for _, a, b, _ in results])
        history.append([float(max(abs(a))) for _, a, _, _ in results])
        if len(history) % 50 == 0:
            print("eval", len(history), "max angles", history[-1], flush=True)
        return np.r_[
            normalized * 0.15, 10 * np.maximum(abs(normalized) - 0.96, 0), shifts * 0.08
        ]

    def jac(shifts):
        # Differentiate stationary geometry via its internal Cartesian Hessian.
        # This avoids hundreds of independent minimizations per optimizer step.
        blocks = []
        values = []
        for c in cases:
            x, ae, be, _ = relax(c, shifts)
            n = x.size

            def gradient(pos):
                c["ctx"].setPositions(pos * u.angstrom)
                return -np.asarray(
                    c["ctx"]
                    .getState(getForces=True)
                    .getForces(asNumpy=True)
                    .value_in_unit(u.kilocalorie_per_mole / u.angstrom)
                ).ravel()

            step = 1e-4
            hessian = np.empty((n, n))
            for i in range(n):
                a, b = x.ravel().copy(), x.ravel().copy()
                a[i] += step
                b[i] -= step
                hessian[:, i] = (
                    gradient(a.reshape(-1, 3)) - gradient(b.reshape(-1, 3))
                ) / (2 * step)
            centered = x - x.mean(axis=0)
            rigid = np.column_stack(
                [np.tile(v, (len(x), 1)).ravel() for v in np.eye(3)]
                + [
                    np.cross(np.tile(v, (len(x), 1)), centered).ravel()
                    for v in np.eye(3)
                ]
            )
            basis = np.linalg.svd(rigid, full_matrices=True)[0][:, 6:]
            internal = basis.T @ ((hessian + hessian.T) / 2) @ basis
            assert np.linalg.eigvalsh(internal).min() > 0, (
                "Response requires a true internal minimum"
            )
            dg = np.zeros((n, len(groups)))
            for g in {r[3] for r in c["records"]}:
                a, b = shifts.copy(), shifts.copy()
                a[g] += 0.001
                b[g] -= 0.001
                set_parameters(c, a)
                ga = gradient(x)
                set_parameters(c, b)
                gb = gradient(x)
                dg[:, g] = (ga - gb) / 0.002
            set_parameters(c, shifts)
            dx = -basis @ np.linalg.solve(internal, basis.T @ dg)
            block = np.empty((len(ae) + len(be), len(groups)))

            def measures(pos):
                return np.r_[
                    [angle(pos, ids) / 3 for ids in c["angles"]],
                    [np.linalg.norm(pos[a] - pos[b]) / 0.03 for a, b in c["bonds"]],
                ]

            for g in range(len(groups)):
                delta = dx[:, g].reshape(-1, 3) * 1e-4
                block[:, g] = (measures(x + delta) - measures(x - delta)) / 2e-4
            blocks.append(block)
            values.extend(np.r_[ae / 3, be / 0.03])
        raw = np.vstack(blocks)
        values = np.asarray(values)
        print("response max normalized error", float(max(abs(values))), flush=True)
        return np.vstack(
            [
                raw * 0.15,
                raw * (10 * np.sign(values) * (abs(values) > 0.96))[:, None],
                np.eye(len(groups)) * 0.08,
            ]
        )

    initial_shifts = np.zeros(len(groups))
    if warm_start:
        prior = json.loads((warm_start / "assessment.json").read_text())
        for row in prior["parameter_changes"]:
            key = (row["kind"], tuple(row["types"]))
            if key in groups:
                initial_shifts[groups[key]] = row["delta"] / (
                    6 if row["kind"] == "angle" else 0.01
                )
    fit = least_squares(
        residual,
        initial_shifts,
        jac=jac,
        bounds=(-1, 1),
        max_nfev=max_nfev,
        ftol=1e-5,
        xtol=1e-5,
        gtol=1e-5,
    )
    write(
        root / "optimizer.json",
        dict(success=bool(fit.success), message=fit.message, shifts=fit.x.tolist()),
    )
    reports = []
    for c in cases:
        out = root / c["id"]
        out.mkdir()
        x, ae, be, force = relax(c, fit.x)
        np.savetxt(out / "minimum_A.txt", x)
        (out / "system.xml").write_text(mm.XmlSerializer.serialize(c["system"]))
        if c["endpoint"] == 0:
            shutil.copy2(out / "system.xml", out / "candidate.xml")
        shutil.copy2(c["psf_path"], out / "fragment.psf")
        if c["endpoint"]:
            shutil.copy2(c["rtf_path"], out / "fragment.rtf")
        r = copy.deepcopy(c.get("report", {}))
        r.update(
            endpoint=c["endpoint"],
            evidence_role="training",
            simulation_ready=False,
            max_force=force,
            max_angle_error_deg=float(max(abs(ae))),
            max_bond_error_A=float(max(abs(be))),
            all_angles=[
                dict(
                    atoms=[c["names"][i] for i in ids],
                    error_deg=float(v),
                    before_error_deg=angle(c["initial"], ids) - angle(c["qm"], ids),
                )
                for ids, v in zip(c["angles"], ae)
            ],
            all_bonds=[
                dict(
                    atoms=[c["names"][i] for i in ids],
                    error_A=float(v),
                    before_error_A=float(
                        np.linalg.norm(c["initial"][ids[0]] - c["initial"][ids[1]])
                        - np.linalg.norm(c["qm"][ids[0]] - c["qm"][ids[1]])
                    ),
                )
                for ids, v in zip(c["bonds"], be)
            ],
        )
        orders = {}
        for e in (1, 2):
            orders[f"{e}:C5"] = [f"{e}:C4", f"{e}:C6", f"{e}:C7", f"{3 - e}:C6"]
            orders[f"{e}:C6"] = [f"{e}:N1", f"{e}:C5", f"{e}:H6", f"{3 - e}:C5"]
        if c["endpoint"]:
            e = c["endpoint"]
            for center, seq in [
                ("C1'", ["O4'", "C2'", "N1", "H1'"]),
                ("C3'", ["C2'", "C4'", "O3'", "H3'"]),
                ("C4'", ["O4'", "C3'", "C5'", "H4'"]),
            ]:
                orders[f"{e}:{center}"] = [f"{e}:{n}" for n in seq]
            glyco = {f"{e}:N1", f"{e}:C1'"}
            r["angles"] = [
                dict(
                    a,
                    mm_deg=angle(x, [c["names"].index(n) for n in a["atoms"]]),
                    error_deg=angle(x, [c["names"].index(n) for n in a["atoms"]])
                    - a["qm_deg"],
                )
                for a in r["angles"]
            ]
            r["boundary_bond_error_A"] = next(
                b["error_A"] for b in r["all_bonds"] if set(b["atoms"]) == glyco
            )
            r["max_boundary_angle_error_deg"] = max(
                abs(a["error_deg"]) for a in r["angles"]
            )
            r["boundary_geometry_passed"] = (
                abs(r["boundary_bond_error_A"]) <= 0.03
                and r["max_boundary_angle_error_deg"] <= 3
            )
        r["centers"] = []
        for center, seq in orders.items():
            ids = [c["names"].index(n) for n in seq]
            v0, v1 = volume(c["qm"], ids), volume(x, ids)
            r["centers"].append(
                dict(center=center, qm=v0, mm=v1, preserved=v0 * v1 > 0)
            )
        r["stereochemistry_passed"] = all(v["preserved"] for v in r["centers"])
        r["all_geometry_passed"] = bool(max(abs(ae)) <= 3 and max(abs(be)) <= 0.03)
        write(out / "assessment.json", r)
        reports.append(r)
    changes = [
        dict(
            kind=kind,
            types=types,
            delta=float(fit.x[g]) * (6 if kind == "angle" else 0.01),
        )
        for (kind, types), g in groups.items()
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pars = app.CharmmParameterSet(
            str(BASE / "top_all36_na.rtf"),
            str(BASE / "par_all36_na.prm"),
            str(FF / "top_all36_cgenff.rtf"),
            str(FF / "par_all36_cgenff.prm"),
            str(parent_parameters),
        )
    prm = parent_parameters.read_text().rsplit("END", 1)[0]
    for kind, heading in [("angle", "ANGLES"), ("bond", "BONDS")]:
        prm += "\n" + heading + "\n"
        for row in changes:
            if row["kind"] != kind:
                continue
            key = tuple(row["types"])
            p = (pars.angle_types if kind == "angle" else pars.bond_types)[key]
            prm += (
                " ".join(key)
                + f" {p.k:.12g} {(p.theteq if kind == 'angle' else p.req) + row['delta']:.12g}"
            )
            if kind == "angle":
                ub = pars.urey_bradley_types.get(key)
                if ub is not None and ub.k not in (None, 0):
                    prm += f" {ub.k:.12g} {ub.req:.12g}"
            prm += "\n"
    (root / "comparator_last.prm").write_text(prm + "END\n")
    if typed_input:
        shutil.copy2(typed_input / "assessment.json", root / "typing_manifest.json")
        shutil.copy2(typed_input / "aliases.rtf", root / "aliases.rtf")
    else:
        shutil.copy2(PARENT / "comparator.rtf", root / "comparator.rtf")
    write(
        root / "assessment.json",
        dict(
            simulation_ready=False,
            evidence_role="joint training",
            optimizer_success=bool(fit.success),
            parameter_changes=changes,
            records=reports[:2],
            core=reports[2],
            history=history,
        ),
    )
    print(
        "Final",
        [
            (
                r["endpoint"],
                r["max_angle_error_deg"],
                r["max_bond_error_A"],
                r["stereochemistry_passed"],
            )
            for r in reports
        ],
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--all-angles", action="store_true")
    p.add_argument("--all-bonds", action="store_true")
    p.add_argument("--max-nfev", type=int, default=40)
    p.add_argument("--typed-input", type=Path)
    p.add_argument("--warm-start", type=Path)
    args = p.parse_args()
    main(
        args.root.resolve(),
        args.all_angles,
        args.typed_input.resolve() if args.typed_input else None,
        args.warm_start.resolve() if args.warm_start else None,
        args.all_bonds,
        args.max_nfev,
    )

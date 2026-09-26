"""Fresh fixed-geometry glycosidic energy/gradient probes, no parameter fitting."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked, source, write

ART = REPO / ".development-artifacts"
BOHR_A = 0.529177210903
EH_KCAL = 627.5094740631


def prepare(root, angle=15.0):
    root.mkdir(exist_ok=False)
    shutil.copyfile(__file__, root / "executed_source.py")
    cases = []
    references = []
    options = None
    for e in (1, 2):
        prior = ART / (
            "cpd-anti-endpoint1-soft-mode-v1"
            if e == 1
            else "cpd-anti-endpoint2-soft-mode-v1"
        )
        old = json.loads((prior / "plan.json").read_text())
        options = old["electronic_options"]
        ref = json.loads((prior / "reference/result.json").read_text())
        for k in ["plan", "native", "input"]:
            checked(ref[k])
        data = json.loads(checked(ref["input"]).read_text())
        x = np.array(data["geometry_bohr"])
        model = json.loads(
            (
                ART / f"cpd-repaired-anti-fragments-v1/endpoint-{e}/model_manifest.json"
            ).read_text()
        )
        names = model["atom_map"]
        graph = json.loads(checked(model["outputs"]["model_graph"]).read_text())
        bonds = [tuple(b["indices"]) for b in graph["bonds"]]
        idx = {n: i for i, n in enumerate(names)}
        origin = x[idx[f"{e}:N1"]]
        axis = x[idx[f"{e}:C1'"]] - origin
        axis /= np.linalg.norm(axis)
        sugar = [i for i, n in enumerate(names) if n.startswith(f"{e}:") and "'" in n]
        assert len(sugar) == 17
        neighbors = {i: [] for i in range(49)}
        for a, b in bonds:
            neighbors[a].append(b)
            neighbors[b].append(a)
        references.append(
            dict(
                endpoint=e,
                input=source(prior / "reference/input.json"),
                result=source(prior / "reference/result.json"),
                names=names,
                sugar=sugar,
                axis=axis.tolist(),
                origin=origin.tolist(),
            )
        )
        for degree in [-angle, angle]:
            label = f"endpoint-{e}-{degree:+g}"
            out = root / label
            out.mkdir()
            theta = np.radians(degree)
            pos = x.copy()
            v = x[sugar] - origin
            pos[sugar] = (
                origin
                + v * np.cos(theta)
                + np.cross(axis, v) * np.sin(theta)
                + np.outer(v @ axis, axis) * (1 - np.cos(theta))
            )
            maxbond = max(
                abs(np.linalg.norm(pos[a] - pos[b]) - np.linalg.norm(x[a] - x[b]))
                * BOHR_A
                for a, b in bonds
            )
            assert maxbond < 1e-8
            stereo = []
            for i, ns in neighbors.items():
                if len(ns) != 4:
                    continue

                def volume(coords):
                    a, b, c, d = coords[ns]
                    return float(np.dot(b - a, np.cross(c - a, d - a)))

                before, after = volume(x), volume(pos)
                assert before * after > 0
                stereo.append(names[i])
            cov = {"C": 0.76, "N": 0.71, "O": 0.66}
            bondset = {tuple(sorted(b)) for b in bonds}
            heavy = [i for i, el in enumerate(data["elements"]) if el != "H"]
            ratios = [
                np.linalg.norm(pos[i] - pos[j])
                * BOHR_A
                / (cov[data["elements"][i]] + cov[data["elements"][j]])
                for i, j in itertools.combinations(heavy, 2)
                if (i, j) not in bondset
            ]
            contact = float(min(ratios))
            assert contact > 1.0
            write(
                out / "input.json",
                dict(
                    label=label, elements=data["elements"], geometry_bohr=pos.tolist()
                ),
            )
            cases.append(
                dict(
                    label=label,
                    endpoint=e,
                    rotation_deg=degree,
                    input=source(out / "input.json"),
                    maximum_bond_length_change_A=maxbond,
                    preserved_tetrahedral_centers=stereo,
                    minimum_nonbonded_heavy_covalent_ratio=contact,
                )
            )
    write(
        root / "plan.json",
        dict(
            cases=cases,
            references=references,
            electronic_options=options,
            threads=4,
            memory_gib=3,
            method="mp2",
            native_worker=source(
                REPO / "experiments/cpd_anti_additive/soft_mode_check.py"
            ),
            scope=f"Fixed-geometry ±{angle:g} degree sugar rotations about N1-C1; fresh energy and projected torque diagnostics, no relaxed profile or minimum claim; no fitting to these probes",
            simulation_ready=False,
        ),
    )


def run(root):
    os.sched_setaffinity(0, set(range(16)))
    plan = json.loads((root / "plan.json").read_text())
    worker = checked(plan["native_worker"])

    def one(case):
        with (root / case["label"] / "run.log").open("w") as log:
            subprocess.run(
                [
                    sys.executable,
                    str(worker),
                    "worker",
                    str(root),
                    "--label",
                    case["label"],
                ],
                cwd=REPO,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, plan["cases"]))
    compare(root)


def compare(root):
    import openmm as mm
    from openmm import unit as u

    plan = json.loads((root / "plan.json").read_text())
    records = []
    for ref in plan["references"]:
        e = ref["endpoint"]
        rd = json.loads(checked(ref["input"]).read_text())
        r = json.loads(checked(ref["result"]).read_text())
        reference = np.array(rd["geometry_bohr"])
        origin = np.array(ref["origin"])
        axis = np.array(ref["axis"])
        sugar = ref["sugar"]
        for label, folder in [("baseline", ART / "cpd-anti-ordered-fit-v1")] + [
            (f"charge-{n}", ART / f"cpd-anti-ordered-coupled-v1/geometry-{n}")
            for n in [1, 10, 100]
        ]:
            sp = folder / f"endpoint-{e}/system.xml"
            system = mm.XmlSerializer.deserialize(sp.read_text())
            it = mm.VerletIntegrator(0.001)
            ctx = mm.Context(system, it, mm.Platform.getPlatformByName("Reference"))

            def evaluate(pos, ctx=ctx):
                ctx.setPositions(pos * BOHR_A * u.angstrom)
                st = ctx.getState(getEnergy=True, getForces=True)
                return st.getPotentialEnergy().value_in_unit(
                    u.kilocalorie_per_mole
                ), -np.asarray(
                    st.getForces(asNumpy=True).value_in_unit(
                        u.kilocalorie_per_mole / u.angstrom
                    )
                )

            re, _ = evaluate(reference)
            for case in plan["cases"]:
                if case["endpoint"] != e:
                    continue
                result_path = root / case["label"] / "result.json"
                qm = json.loads(result_path.read_text())
                for k in ["input", "plan", "native"]:
                    checked(qm[k])
                pos = np.asarray(
                    json.loads(checked(qm["input"]).read_text())["geometry_bohr"]
                )
                energy, gradient = evaluate(pos)
                tangent = np.cross(axis, pos[sugar] - origin)
                qdelta = (qm["energy_hartree"] - r["energy_hartree"]) * EH_KCAL
                mdelta = energy - re
                qt = float(
                    np.sum(np.asarray(qm["gradient_au"])[sugar] * tangent) * EH_KCAL
                )
                mt = float(np.sum(gradient[sugar] * tangent) * BOHR_A)
                records.append(
                    dict(
                        endpoint=e,
                        candidate=label,
                        rotation_deg=case["rotation_deg"],
                        qm_relative_energy_kcal_mol=qdelta,
                        mm_relative_energy_kcal_mol=mdelta,
                        relative_energy_error_kcal_mol=mdelta - qdelta,
                        qm_dE_dtheta_kcal_mol_rad=qt,
                        mm_dE_dtheta_kcal_mol_rad=mt,
                        torque_derivative_error_kcal_mol_rad=mt - qt,
                        system=source(sp),
                        qm_result=source(result_path),
                    )
                )
            del evaluate, ctx, it
    write(
        root / "assessment.json",
        dict(
            records=records,
            simulation_ready=False,
            scope=plan["scope"],
            acceptance="Diagnostic comparison; no retrospectively selected thresholds or refit; fixed geometries are not new minima",
        ),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run", "compare"])
    p.add_argument("root", type=Path)
    p.add_argument("--angle", type=float, default=15.0)
    a = p.parse_args()
    if a.action == "prepare":
        assert 0 < a.angle <= 15
        prepare(a.root.resolve(), a.angle)
    else:
        globals()[a.action](a.root.resolve())

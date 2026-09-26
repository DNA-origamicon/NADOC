"""Charge-to-geometry coupling and retrospective endpoint transfer, isolated."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import warnings
import numpy as np
import openmm as mm
from openmm import app

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.core_baseline import source, checked, write
from experiments.cpd_anti_additive.prepare_anti_types import load_cases

ART = REPO / ".development-artifacts"


def prepare(root, ordered=False):
    root.mkdir(exist_ok=False)
    shutil.copyfile(__file__, root / "executed_source.py")
    chargepath = ART / "cpd-anti-charge-candidates-v1/assessment.json"
    charges = json.loads(chargepath.read_text())
    base = ART / (
        "cpd-anti-ordered-types-v1" if ordered else "cpd-anti-additive-types-v2"
    )
    baseline = ART / ("cpd-anti-ordered-fit-v1" if ordered else "cpd-anti-joint-fit-v2")
    cases = load_cases()
    jobs = []
    for record in charges["records"]:
        strength = record["regularization"]
        folder = root / f"charges-{strength}"
        folder.mkdir()
        shutil.copyfile(base / "comparator_last.prm", folder / "comparator_last.prm")
        shutil.copyfile(base / "aliases.rtf", folder / "aliases.rtf")
        shifts = record["charge_shifts_e"]
        checks = []
        assert record["optimizer_success"] and record["max_constraint_error"] < 1e-8
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            params = app.CharmmParameterSet(str(folder / "comparator_last.prm"))
        for case in cases:
            label = case["id"]
            out = folder / label
            out.mkdir()
            lines = (base / label / "fragment.psf").read_text().splitlines()
            start = next(i for i, l in enumerate(lines) if "!NATOM" in l) + 1
            names = case["names"]
            original = app.CharmmPsfFile(str(base / label / "fragment.psf"))
            q = np.array([a.charge for a in original.atom_list])
            changed = q + np.array([shifts.get(n, 0) for n in names])
            assert abs(changed.sum()) < 1e-8
            for i, n in enumerate(names):
                fields = lines[start + i].split()
                assert int(fields[0]) == i + 1
                fields[6] = f"{changed[i]:.12f}"
                lines[start + i] = " ".join(fields)
            (out / "fragment.psf").write_text("\n".join(lines) + "\n")
            psf = app.CharmmPsfFile(str(out / "fragment.psf"))
            qread = np.array([a.charge for a in psf.atom_list])
            assert np.max(abs(qread - changed)) < 1e-10
            if label != "core":
                target = next(
                    e for e in record["endpoints"] if e["endpoint"] == int(label[-1])
                )
                assert (
                    target["atom_map"] == names
                    and np.max(abs(qread - np.array(target["charges_e"]))) < 1e-10
                )
            assert [(b.atom1.idx, b.atom2.idx) for b in original.bond_list] == [
                (b.atom1.idx, b.atom2.idx) for b in psf.bond_list
            ]
            system = psf.createSystem(
                params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False
            )
            (out / "system.xml").write_text(mm.XmlSerializer.serialize(system))
            checks.append(
                dict(
                    model=label,
                    net_charge=float(qread.sum()),
                    maximum_shift=float(abs(qread - q).max()),
                    fixed_sugar_caps=all(
                        abs(qread[i] - q[i]) < 1e-12
                        for i, n in enumerate(names)
                        if n not in shifts
                    ),
                    unchanged_graph=True,
                )
            )
        write(
            folder / "assessment.json",
            dict(
                records=checks,
                charge_source=source(chargepath),
                regularization=strength,
                simulation_ready=False,
                scope="Isolated charge assignment; original role aliases and parameters; no acceptance",
            ),
        )
        jobs.append(
            dict(
                id=f"geometry-{strength}",
                command=[
                    str(REPO / ".venv/bin/python"),
                    str(REPO / "experiments/cpd_anti_additive/refine_joint.py"),
                    "--root",
                    str(root / f"geometry-{strength}"),
                    "--typed-input",
                    str(folder),
                    "--all-angles",
                    "--all-bonds",
                    "--warm-start",
                    str(baseline),
                    "--max-nfev",
                    "200",
                ],
            )
        )
    for e in () if ordered else (1, 2):
        jobs.append(
            dict(
                id=f"charge-transfer-{e}",
                command=[
                    str(REPO / ".venv/bin/python"),
                    str(
                        REPO / "experiments/cpd_anti_additive/fit_charge_candidates.py"
                    ),
                    "--root",
                    str(root / f"charge-transfer-{e}"),
                    "--train-endpoint",
                    str(e),
                ],
            )
        )
    write(
        root / "plan.json",
        dict(
            jobs=jobs,
            charge_source=source(chargepath),
            baseline=source(baseline / "assessment.json"),
            ordered_endpoints=ordered,
            sources=[
                source(REPO / f"experiments/cpd_anti_additive/{s}.py")
                for s in ["refine_joint", "fit_charge_candidates", "coupled_round"]
            ],
            criteria=dict(
                max_bond_error_A=0.03,
                max_angle_error_deg=3,
                preserve_stereochemistry=True,
            ),
            resources="Three concurrent single-BLAS-thread tasks on physical cores0-15; avoid unnecessary BLAS/SMT oversubscription",
            scope="Same bounded geometry fit for three pre-existing charge hypotheses; retrospective leave-one-endpoint-out charge transfer. All development data.",
            simulation_ready=False,
        ),
    )


def run(root):
    os.sched_setaffinity(0, set(range(16)))
    plan = json.loads((root / "plan.json").read_text())
    for rec in plan["sources"] + [plan["charge_source"], plan["baseline"]]:
        checked(rec)

    def task(job):
        with (root / f"{job['id']}.log").open("w") as log:
            p = subprocess.run(
                job["command"],
                cwd=REPO,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={
                    **os.environ,
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                },
            )
        return dict(
            id=job["id"],
            returncode=p.returncode,
            assessment=source(root / job["id"] / "assessment.json")
            if (root / job["id"] / "assessment.json").exists()
            else None,
        )

    records = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for f in as_completed([pool.submit(task, j) for j in plan["jobs"]]):
            records.append(f.result())
            write(
                root / "progress.json", dict(records=records, total=len(plan["jobs"]))
            )
            print(records[-1], flush=True)
    write(
        root / "assessment.json",
        dict(
            records=records,
            simulation_ready=False,
            scope="Execution status only; scientific review required",
        ),
    )
    if any(r["returncode"] for r in records):
        raise RuntimeError("Some tasks failed; preserved all results")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run"])
    p.add_argument("root", type=Path)
    p.add_argument("--ordered", action="store_true")
    a = p.parse_args()
    if a.action == "prepare":
        prepare(a.root.resolve(), a.ordered)
    else:
        run(a.root.resolve())

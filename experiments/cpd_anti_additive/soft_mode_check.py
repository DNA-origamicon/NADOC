"""Independent directional soft-mode curvature at two steps and tighter response."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_drude_recovery.campaign import source, checked, write


def prepare(root, reference=None, hessian=None):
    base = REPO / ".development-artifacts/cpd-anti-additive-next-v2"
    ref = reference or base / "endpoint1-hessian/tasks/0000-reference/result.json"
    result = json.loads(ref.read_text())
    molecule = result["molecule"]
    x = np.asarray(molecule["geometry"]).reshape(-1, 3)
    masses = np.array(molecule["masses"])
    weights = np.repeat(np.sqrt(masses), 3)
    hp = hessian or base / "endpoint1-frequency/hessian_hartree_per_bohr2.txt"
    h = np.loadtxt(hp)
    d = h / weights[:, None] / weights[None, :]
    centered = x - np.average(x, axis=0, weights=masses)
    rigid = np.column_stack(
        [np.tile(v, (49, 1)).ravel() * weights for v in np.eye(3)]
        + [np.cross(np.tile(v, (49, 1)), centered).ravel() * weights for v in np.eye(3)]
    )
    u, s, _ = np.linalg.svd(rigid, full_matrices=True)
    assert (s > 1e-8).sum() == 6
    basis = u[:, 6:]
    values, vectors = np.linalg.eigh(basis.T @ d @ basis)
    assert values[0] > 0
    direction = (basis @ vectors[:, 0]) / weights
    direction /= np.linalg.norm(direction)
    root.mkdir(exist_ok=False)
    shutil.copy2(__file__, root / "executed_source.py")
    cases = []
    for label, step in [
        ("reference", 0),
        ("plus-004", 0.04),
        ("minus-004", -0.04),
        ("plus-002", 0.02),
        ("minus-002", -0.02),
    ]:
        folder = root / label
        folder.mkdir()
        data = dict(
            label=label,
            displacement_bohr=step,
            elements=molecule["symbols"],
            geometry_bohr=(x + step * direction.reshape(-1, 3)).tolist(),
        )
        write(folder / "input.json", data)
        cases.append(dict(label=label, input=source(folder / "input.json")))
    write(
        root / "plan.json",
        dict(
            cases=cases,
            direction=direction.tolist(),
            original_directional_curvature=float(direction @ h @ direction),
            electronic_options=dict(
                basis="6-31G(d)",
                reference="rhf",
                scf_type="df",
                mp2_type="df",
                freeze_core=True,
                e_convergence=1e-12,
                d_convergence=1e-12,
                solver_convergence=1e-10,
                maxiter=300,
            ),
            thresholds=dict(
                reference_max_force_au=1.5e-5,
                step_halving_relative_difference=0.1,
                positive_curvature=True,
            ),
            method="mp2",
            threads=4,
            memory_gib=3,
            sources=[source(ref), source(hp)],
            scope="Projected softest-mode directional validation, not a second full Hessian or independent validation of all other modes. No refitting or release.",
        ),
    )


def worker(root, label):
    import psi4

    plan = json.loads((root / "plan.json").read_text())
    case = next(c for c in plan["cases"] if c["label"] == label)
    data = json.loads(checked(case["input"]).read_text())
    folder = root / label
    (folder / "scratch").mkdir()
    os.chdir(folder)
    psi4.set_num_threads(plan["threads"])
    psi4.set_memory(f"{plan['memory_gib']} GiB")
    psi4.core.IOManager.shared_object().set_default_path(str(folder / "scratch"))
    psi4.set_output_file(str(folder / "output.dat"), False)
    geom = "\n".join(
        f"{e} {x:.14f} {y:.14f} {z:.14f}"
        for e, (x, y, z) in zip(data["elements"], data["geometry_bohr"])
    )
    mol = psi4.geometry(
        "0 1\n" + geom + "\nunits bohr\nsymmetry c1\nno_com\nno_reorient"
    )
    psi4.set_options(plan["electronic_options"])
    grad, wfn = psi4.gradient("mp2", molecule=mol, return_wfn=True)
    g = np.asarray(grad)
    assert g.shape == (49, 3) and np.isfinite(g).all()
    native = (folder / "output.dat").read_text()
    cutoffs = [
        float(v) for v in re.findall(r"Convergence cutoff\s*=\s*([\d.Ee+-]+)", native)
    ]
    assert cutoffs and max(cutoffs) <= 1.01e-10, cutoffs
    write(
        folder / "result.json",
        dict(
            energy_hartree=float(wfn.energy()),
            gradient_au=g.tolist(),
            input=source(folder / "input.json"),
            plan=source(root / "plan.json"),
            native=source(folder / "output.dat"),
            observed_response_cutoffs=cutoffs,
        ),
    )
    psi4.core.clean()


def run(root):
    plan = json.loads((root / "plan.json").read_text())
    os.sched_setaffinity(0, set(range(12)))

    def task(case):
        folder = root / case["label"]
        with (folder / "run.log").open("w") as log:
            subprocess.run(
                [
                    sys.executable,
                    str(root / "executed_source.py"),
                    "worker",
                    str(root),
                    "--label",
                    case["label"],
                ],
                cwd=REPO,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                env={**os.environ, "PYTHONPATH": str(REPO)},
            )

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(task, plan["cases"]))
    results = {}
    for case in plan["cases"]:
        r = json.loads((root / case["label"] / "result.json").read_text())
        checked(r["input"])
        checked(r["plan"])
        checked(r["native"])
        results[case["label"]] = r
    q = np.asarray(plan["direction"])
    curv = []
    for suffix, step in [("004", 0.04), ("002", 0.02)]:
        gp = np.asarray(results[f"plus-{suffix}"]["gradient_au"]).ravel()
        gm = np.asarray(results[f"minus-{suffix}"]["gradient_au"]).ravel()
        curv.append(float(q @ (gp - gm) / (2 * step)))
    relative = abs(curv[1] - curv[0]) / max(abs(curv[0]), abs(curv[1]), 1e-20)
    force = float(abs(np.asarray(results["reference"]["gradient_au"])).max())
    checks = dict(
        reference_stationary=force <= plan["thresholds"]["reference_max_force_au"],
        positive_directional_curvature=min(curv) > 0,
        step_halving_agreement=relative
        <= plan["thresholds"]["step_halving_relative_difference"],
    )
    write(
        root / "assessment.json",
        dict(
            checks=checks,
            passed=all(checks.values()),
            reference_max_force_au=force,
            directional_curvatures_hartree_per_bohr2=curv,
            step_halving_relative_difference=relative,
            original_hessian_directional_curvature=plan[
                "original_directional_curvature"
            ],
            simulation_ready=False,
            sources=[source(root / c["label"] / "result.json") for c in plan["cases"]],
        ),
    )
    if not all(checks.values()):
        raise RuntimeError("Soft-mode numerical check failed; preserve results")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run", "worker"])
    p.add_argument("root", type=Path)
    p.add_argument("--label")
    p.add_argument("--reference", type=Path)
    p.add_argument("--hessian", type=Path)
    a = p.parse_args()
    root = a.root.resolve()
    if a.action == "worker":
        worker(root, a.label)
    elif a.action == "prepare":
        prepare(root, a.reference, a.hessian)
    else:
        run(root)

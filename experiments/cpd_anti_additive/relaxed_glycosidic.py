"""Bounded constrained relaxation of previously screened glycosidic probes."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked, source, write
from backend.parameterization.photoproduct_qm import (
    generate_torsion_scan_job,
    run_psi4_job,
    parse_xyz,
    _dihedral_degrees,
    _circular_difference_degrees,
)

ART = REPO / ".development-artifacts"
PROTOCOL = REPO / "backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json"


def prepare(root):
    root.mkdir(exist_ok=False)
    shutil.copyfile(__file__, root / "executed_source.py")
    probe = ART / "cpd-anti-glycosidic-probes-v1"
    prior = json.loads((probe / "plan.json").read_text())
    records = []
    for e in (1, 2):
        model = json.loads(
            (
                ART / f"cpd-repaired-anti-fragments-v1/endpoint-{e}/model_manifest.json"
            ).read_text()
        )
        graph = checked(model["outputs"]["model_graph"])
        names = model["atom_map"]
        torsion = [f"{e}:C2", f"{e}:N1", f"{e}:C1'", f"{e}:O4'"]
        indices = [names.index(n) for n in torsion]
        points = []
        for c in prior["cases"]:
            if c["endpoint"] != e:
                continue
            data = json.loads(checked(c["input"]).read_text())
            x = np.asarray(data["geometry_bohr"]) * 0.529177210903
            point_id = c["label"]
            folder = root / point_id
            folder.mkdir()
            xyz = folder / "starting.xyz"
            xyz.write_text(
                "49\nPreviously screened fixed glycosidic probe\n"
                + "\n".join(
                    f"{el} {a:.12f} {b:.12f} {d:.12f}"
                    for el, (a, b, d) in zip(data["elements"], x)
                )
                + "\n"
            )
            angle = _dihedral_degrees(*x[indices])
            points.append(
                dict(
                    id=point_id, target_degrees=angle, xyz_sha256=source(xyz)["sha256"]
                )
            )
        pp = root / f"endpoint-{e}-scan-plan.json"
        write(
            pp,
            dict(
                schema="nadoc.photoproduct-torsion-scan-plan.v2",
                product_id=model["product_id"],
                model_id=model["model_id"],
                reviewed_by="Screened prior probe geometry plus explicit acyclic-bond graph validation",
                review_rationale="Preserve existing ±15 degree seeds; freeze only C2-N1-C1prime-O4prime while relaxing other degrees of freedom. No refitting or minimum certification.",
                atom_map=names,
                torsion_atoms=torsion,
                model_graph=source(graph),
                charge=0,
                multiplicity=1,
                starting_angle_tolerance_degrees=0.01,
                points=points,
            ),
        )
        for point in points:
            folder = root / point["id"]
            job = folder / "qm"
            generate_torsion_scan_job(
                scan_plan_path=pp,
                point_id=point["id"],
                xyz_path=folder / "starting.xyz",
                output_dir=job,
                memory_gib=3,
                threads=4,
                protocol_path=PROTOCOL,
            )
            records.append(
                dict(
                    endpoint=e,
                    label=point["id"],
                    job_dir=str(job),
                    manifest=source(job / "job_manifest.json"),
                    scan_plan=source(pp),
                    seed=source(folder / "starting.xyz"),
                    model_graph=source(graph),
                    torsion_indices=indices,
                    target_degrees=point["target_degrees"],
                )
            )
    write(
        root / "plan.json",
        dict(
            records=records,
            protocol=source(PROTOCOL),
            simulation_ready=False,
            scope="Four constrained-relaxation points; existing registered torsion job generator and default optimizer policy; no unconstrained-minimum or full-profile claim",
        ),
    )


def audit(record):
    folder = Path(record["job_dir"])
    names = json.loads(checked(record["scan_plan"]).read_text())["atom_map"]
    atoms, _ = parse_xyz((folder / "optimized.xyz").read_text())
    start, _ = parse_xyz(checked(record["seed"]).read_text())
    x = np.asarray([a[1:] for a in atoms])
    s = np.asarray([a[1:] for a in start])
    assert [a[0] for a in atoms] == [a[0] for a in start]
    graph = json.loads(checked(record["model_graph"]).read_text())
    neighbors = {i: [] for i in range(len(x))}
    for b in graph["bonds"]:
        i, j = b["indices"]
        neighbors[i].append(j)
        neighbors[j].append(i)
    stereo = []
    for i, ns in neighbors.items():
        if len(ns) != 4:
            continue

        def volume(pos):
            a, b, c, d = pos[ns]
            return float(np.dot(b - a, np.cross(c - a, d - a)))

        v0, v1 = volume(s), volume(x)
        stereo.append(
            dict(center=names[i], preserved=bool(v0 * v1 > 0 and abs(v1) > 1e-8))
        )
    radii = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66}
    ratios = [
        np.linalg.norm(x[b["indices"][0]] - x[b["indices"][1]])
        / (radii[atoms[b["indices"][0]][0]] + radii[atoms[b["indices"][1]][0]])
        for b in graph["bonds"]
    ]
    angle = _dihedral_degrees(*x[record["torsion_indices"]])
    error = _circular_difference_degrees(angle, record["target_degrees"])
    text = (folder / "output.dat").read_text()
    energy = re.findall(r"NADOC_TORSION_ENERGY_HARTREE\s+([-\d.]+)", text)
    assert energy
    report = dict(
        label=record["label"],
        torsion_error_deg=error,
        centers=stereo,
        covalent_ratio_range=[float(min(ratios)), float(max(ratios))],
        energy_hartree=float(energy[-1]),
        passed=bool(
            error <= 0.1
            and all(c["preserved"] for c in stereo)
            and min(ratios) > 0.7
            and max(ratios) < 1.3
        ),
        minimum_certified=False,
        simulation_ready=False,
        scope="Constraint, tetrahedral-sign and covalent-distance screen; not unconstrained harmonic-minimum certification",
        native=source(folder / "output.dat"),
        optimized_xyz=source(folder / "optimized.xyz"),
    )
    write(folder.parent / "geometry_audit.json", report)
    return report


def run(root):
    os.sched_setaffinity(0, set(range(16)))
    plan = json.loads((root / "plan.json").read_text())
    checked(plan["protocol"])

    def task(r):
        checked(r["manifest"])
        folder = Path(r["job_dir"])
        try:
            run_psi4_job(
                job_dir=folder,
                psi4_executable=Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/psi4"),
                scratch_dir=folder / "scratch",
            )
            report = audit(r)
            return dict(label=r["label"], state="audited", audit=report)
        except Exception as exc:
            return dict(label=r["label"], state="failed", error=repr(exc))

    records = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(task, r) for r in plan["records"]]):
            records.append(f.result())
            write(root / "progress.json", dict(records=records, total=4))
            print(records[-1]["label"], records[-1]["state"], flush=True)
    write(root / "assessment.json", dict(records=records, simulation_ready=False))
    if any(r["state"] == "failed" for r in records):
        raise RuntimeError("Constrained jobs failed; preserve native outputs")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run"])
    p.add_argument("root", type=Path)
    a = p.parse_args()
    globals()[a.action](a.root.resolve())

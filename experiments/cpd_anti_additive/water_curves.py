"""Run screened anti water curves after endpoint-specific DF/DIRECT calibration."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.water_calibration import (
    ART,
    PROTOCOL,
    checked,
    source,
    write,
    place_tip3p_probe,
    parse_xyz,
    generate_water_interaction_job,
    run_psi4_job,
)
from backend.parameterization.photoproduct_qm import audit_water_interaction_series


def prepare(root):
    root.mkdir(exist_ok=False)
    shutil.copyfile(__file__, root / "executed_source.py")
    records = []
    prerequisites = []
    for e in (1, 2):
        cp = (
            ART
            / f"cpd-anti-water-calibration-service-v1/endpoint-{e}-independent-calibration-review.json"
        )
        cal = json.loads(cp.read_text())
        assert cal["passed"]
        checked(cal["protocol"])
        pp = ART / f"cpd-anti-water-curve-plans-v1/endpoint-{e}-plan.json"
        p = json.loads(pp.read_text())
        parent = checked(p["parent"])
        xyz = checked(p["xyz"])
        atoms, _ = parse_xyz(xyz.read_text())
        x = {k: np.asarray(a[1:]) for k, a in zip(p["atom_map"], atoms)}
        prerequisites.extend([source(cp), source(pp)])
        for site in p["sites"]:
            for i, distance in enumerate(site["distances_angstrom"]):
                water, probe = place_tip3p_probe(
                    target=x[site["target_atom"]],
                    axis_anchor=x[site["axis_anchor_atom"]],
                    plane_point=x[site["plane_atom"]],
                    role=site["role"],
                    distance_angstrom=distance,
                    azimuth_degrees=site["azimuth_degrees"],
                )
                folder = root / f"endpoint-{e}" / site["id"] / f"p{i:02d}"
                folder.mkdir(parents=True)
                wp = folder / "water.xyz"
                wp.write_text(
                    "3\nScreened anti water-distance point\n"
                    + "\n".join(
                        f"{el} {a:.12f} {b:.12f} {c:.12f}" for el, a, b, c in water
                    )
                    + "\n"
                )
                existing = (
                    ART / f"cpd-anti-water-calibration-v1/endpoint-{e}/{site['id']}/df"
                )
                reuse = False
                if (existing / "job_manifest.json").exists():
                    old = json.loads((existing / "job_manifest.json").read_text())
                    wa, _ = parse_xyz(checked(old["water_xyz"]).read_text())
                    reuse = (
                        old["source_xyz"]["sha256"] == p["xyz"]["sha256"]
                        and old["protocol_sha256"] == source(PROTOCOL)["sha256"]
                        and np.max(
                            abs(
                                np.asarray([a[1:] for a in wa])
                                - np.asarray([a[1:] for a in water])
                            )
                        )
                        < 1e-10
                    )
                if reuse:
                    jobdir = existing
                else:
                    jobdir = folder / "qm"
                    generate_water_interaction_job(
                        product_id=p["product_id"],
                        model_id=p["model_id"],
                        model_xyz_path=xyz,
                        water_xyz_path=wp,
                        parent_manifest_path=parent,
                        atom_map=p["atom_map"],
                        probe_id=site["id"],
                        target_atom=site["target_atom"],
                        probe_atom=probe,
                        output_dir=jobdir,
                        charge=0,
                        multiplicity=1,
                        memory_gib=3,
                        threads=4,
                        protocol_path=PROTOCOL,
                    )
                records.append(
                    dict(
                        endpoint=e,
                        site=site["id"],
                        distance=distance,
                        job_dir=str(jobdir),
                        reused_calibration=bool(reuse),
                        manifest=source(jobdir / "job_manifest.json"),
                    )
                )
    write(
        root / "plan.json",
        dict(
            records=records,
            prerequisites=prerequisites,
            protocol=source(PROTOCOL),
            simulation_ready=False,
            scope="Fixed-orientation water distance curves; charge targets only, no release",
        ),
    )
    print(
        len(records), "points,", sum(r["reused_calibration"] for r in records), "reused"
    )


def run(root):
    os.sched_setaffinity(0, set(range(16)))
    plan = json.loads((root / "plan.json").read_text())
    for r in plan["prerequisites"] + [plan["protocol"]]:
        checked(r)
    records = plan["records"]
    pending = [r for r in records if not r["reused_calibration"]]

    def task(r):
        checked(r["manifest"])
        folder = Path(r["job_dir"])
        run_psi4_job(
            job_dir=folder,
            psi4_executable=Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/psi4"),
            scratch_dir=folder / "scratch",
        )
        return r

    completed = sum(r["reused_calibration"] for r in records)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(task, r) for r in pending]
        for f in as_completed(futures):
            f.result()
            completed += 1
            write(root / "progress.json", dict(completed=completed, total=len(records)))
            print("completed", completed, "/", len(records), flush=True)
    audits = []
    for e, site in sorted({(r["endpoint"], r["site"]) for r in records}):
        a = audit_water_interaction_series(
            [
                Path(r["job_dir"])
                for r in records
                if r["endpoint"] == e and r["site"] == site
            ],
            output_path=root / f"endpoint-{e}" / site / "curve_audit.json",
        )
        audits.append(a)
    write(
        root / "assessment.json",
        dict(
            records=audits,
            all_curves_passed=all(a["passed"] for a in audits),
            simulation_ready=False,
        ),
    )
    print(
        "Curve audits",
        [(a["identity"]["probe_id"], a["status"]) for a in audits],
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run"])
    p.add_argument("root", type=Path)
    a = p.parse_args()
    (prepare if a.action == "prepare" else run)(a.root.resolve())

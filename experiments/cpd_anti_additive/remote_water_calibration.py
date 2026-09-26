"""Local DF/DIRECT calibration on screened additive anti water contacts."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked, source, write
from backend.parameterization.photoproduct_water import place_tip3p_probe
from backend.parameterization.photoproduct_qm import (
    generate_water_interaction_job,
    run_psi4_job,
    audit_water_scf_calibration,
    parse_xyz,
)

ART = REPO / ".development-artifacts"
PROTOCOL = REPO / "backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json"


def prepare(root):
    root.mkdir(exist_ok=False)
    shutil.copyfile(__file__, root / "executed_source.py")
    records = []
    radii = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66}
    for endpoint in (2,):
        esp = ART / f"cpd-anti-remote-esp-v1/endpoint-{endpoint}/job_manifest.json"
        ej = json.loads(esp.read_text())
        parent = checked(ej["parent_manifest"])
        p = json.loads(parent.read_text())
        xyz = checked(p["optimized_xyz"])
        atoms, _ = parse_xyz(xyz.read_text())
        names = p["atom_map"]
        x = np.array([a[1:] for a in atoms])
        idx = {n: i for i, n in enumerate(names)}
        specs = [
            ("1:O2", "1:C2", "1:N3", "acceptor"),
            ("2:O4", "2:C4", "2:C5", "acceptor"),
            (f"{endpoint}:H3", f"{endpoint}:N3", f"{endpoint}:C2", "donor"),
        ]
        for target, anchor, plane, role in specs:
            candidates = []
            for azimuth in (0, 120, 240):
                water, probe = place_tip3p_probe(
                    target=x[idx[target]],
                    axis_anchor=x[idx[anchor]],
                    plane_point=x[idx[plane]],
                    role=role,
                    distance_angstrom=1.9,
                    azimuth_degrees=azimuth,
                )
                ratios = [
                    np.linalg.norm(np.array(w[1:]) - x[i]) / (radii[w[0]] + radii[a[0]])
                    for w in water
                    for i, a in enumerate(atoms)
                    if i != idx[target]
                ]
                candidates.append((min(ratios), azimuth, water, probe))
            ratio, azimuth, water, probe = max(candidates, key=lambda c: c[0])
            assert ratio >= 1.1, (endpoint, target, ratio)
            site = target.replace(":", "-")
            folder = root / f"endpoint-{endpoint}" / site
            folder.mkdir(parents=True)
            wp = folder / "water.xyz"
            wp.write_text(
                "3\nDeterministic TIP3P contact; diagnostic calibration only\n"
                + "\n".join(f"{e} {a:.12f} {b:.12f} {c:.12f}" for e, a, b, c in water)
                + "\n"
            )
            for scf, calrole in [("df", "candidate"), ("direct", "reference")]:
                jobdir = folder / scf
                generate_water_interaction_job(
                    product_id=p["product_id"],
                    model_id=p["model_id"],
                    model_xyz_path=xyz,
                    water_xyz_path=wp,
                    parent_manifest_path=parent,
                    atom_map=names,
                    probe_id=site,
                    target_atom=target,
                    probe_atom=probe,
                    output_dir=jobdir,
                    charge=0,
                    multiplicity=1,
                    memory_gib=3,
                    threads=4,
                    scf_type_override=scf,
                    scf_calibration_role=calrole,
                    protocol_path=PROTOCOL,
                )
                records.append(
                    dict(
                        endpoint=endpoint,
                        job_dir=str(jobdir),
                        manifest=source(jobdir / "job_manifest.json"),
                        target=target,
                        role=role,
                        azimuth_deg=azimuth,
                        minimum_nontarget_covalent_radius_ratio=float(ratio),
                    )
                )
    write(
        root / "plan.json",
        dict(
            records=records,
            scope="Three representative sites at lower-energy endpoint2 conformer; identical-geometry DF/DIRECT calibration; not interaction curves or charge validation",
            screen="Choose best of 0/120/240 degree water azimuths; every non-target intermolecular separation >=1.1 covalent radius sums",
            simulation_ready=False,
        ),
    )


def run(root):
    os.sched_setaffinity(0, set(range(16)))
    records = json.loads((root / "plan.json").read_text())["records"]

    def task(r):
        checked(r["manifest"])
        folder = Path(r["job_dir"])
        return run_psi4_job(
            job_dir=folder,
            psi4_executable=Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/psi4"),
            scratch_dir=folder / "scratch",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(task, records))
    audits = []
    for endpoint in (2,):
        audits.append(
            audit_water_scf_calibration(
                [Path(r["job_dir"]) for r in records if r["endpoint"] == endpoint],
                output_path=root / f"endpoint-{endpoint}/calibration_audit.json",
                protocol_path=PROTOCOL,
            )
        )
    write(root / "assessment.json", dict(records=audits, simulation_ready=False))
    print([a["status"] for a in audits], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run"])
    p.add_argument("root", type=Path)
    a = p.parse_args()
    (prepare if a.action == "prepare" else run)(a.root.resolve())

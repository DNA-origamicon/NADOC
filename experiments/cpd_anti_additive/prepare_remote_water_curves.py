"""Screen prospective anti water-distance grids; do not launch before calibration."""

import json
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_anti_additive.core_baseline import checked, source, write
from backend.parameterization.photoproduct_water import place_tip3p_probe
from backend.parameterization.photoproduct_qm import parse_xyz

art = Path(".development-artifacts").resolve()
root = art / "cpd-anti-remote-water-curve-plans-v1"
root.mkdir(exist_ok=False)
(root / "executed_source.py").write_text(Path(__file__).read_text())
radii = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66}
reports = []
for endpoint in (2,):
    job = json.loads(
        (
            art / f"cpd-anti-remote-esp-v1/endpoint-{endpoint}/job_manifest.json"
        ).read_text()
    )
    parent = checked(job["parent_manifest"])
    a = json.loads(parent.read_text())
    xyz = checked(a["optimized_xyz"])
    atoms, _ = parse_xyz(xyz.read_text())
    names = a["atom_map"]
    x = np.asarray([r[1:] for r in atoms])
    idx = {n: i for i, n in enumerate(names)}
    sites = []
    screens = []
    for residue in (1, 2):
        for atom, anchor, plane, role in [
            ("O2", "C2", "N3", "acceptor"),
            ("O4", "C4", "C5", "acceptor"),
            ("H3", "N3", "C2", "donor"),
        ]:
            target = f"{residue}:{atom}"
            distances = [round(1.5 + i * 0.2, 2) for i in range(7)]
            candidates = []
            for azimuth in (0, 120, 240):
                points = []
                for distance in distances:
                    water, _ = place_tip3p_probe(
                        target=x[idx[target]],
                        axis_anchor=x[idx[f"{residue}:{anchor}"]],
                        plane_point=x[idx[f"{residue}:{plane}"]],
                        role=role,
                        distance_angstrom=distance,
                        azimuth_degrees=azimuth,
                    )
                    ratios = [
                        float(
                            np.linalg.norm(np.asarray(w[1:]) - x[i])
                            / (radii[w[0]] + radii[a[0]])
                        )
                        for w in water
                        for i, a in enumerate(atoms)
                        if i != idx[target]
                    ]
                    points.append(
                        dict(
                            distance_angstrom=distance,
                            minimum_nontarget_covalent_radius_ratio=min(ratios),
                        )
                    )
                candidates.append(
                    dict(
                        azimuth_degrees=azimuth,
                        points=points,
                        minimum_ratio=min(
                            p["minimum_nontarget_covalent_radius_ratio"] for p in points
                        ),
                    )
                )
            selected = max(candidates, key=lambda r: r["minimum_ratio"])
            passed = selected["minimum_ratio"] >= 1.1
            screens.append(
                dict(
                    target=target,
                    candidates=candidates,
                    selected_azimuth=selected["azimuth_degrees"],
                    passed=passed,
                )
            )
            if passed:
                sites.append(
                    dict(
                        id=target.replace(":", "-"),
                        role=role,
                        target_atom=target,
                        axis_anchor_atom=f"{residue}:{anchor}",
                        plane_atom=f"{residue}:{plane}",
                        azimuth_degrees=selected["azimuth_degrees"],
                        distances_angstrom=distances,
                    )
                )
    plan = dict(
        schema="nadoc.photoproduct-water-probe-plan.v1",
        status="quantitatively_screened",
        product_id=a["product_id"],
        model_id=a["model_id"],
        reviewed_by="deterministic intermolecular-distance screen",
        review_rationale="All non-target water/model separations >=1.1 covalent-radius sums at every point; choose least crowded of three registered azimuths. Not orientation optimization. Production requires passed endpoint-specific DF/DIRECT calibration and explicit protocol v1.7.0.",
        atom_map=names,
        sites=sites,
        charge=0,
        multiplicity=1,
        parent=source(parent),
        xyz=source(xyz),
        simulation_ready=False,
        execution_gate="Do not run unless endpoint-specific calibration_audit.json passes; generated jobs must explicitly use protocol v1.7.0, not helper defaults.",
    )
    write(root / f"endpoint-{endpoint}-plan.json", plan)
    write(
        root / f"endpoint-{endpoint}-screen.json",
        dict(sites=screens, all_sites_passed=all(r["passed"] for r in screens)),
    )
    reports.append(
        dict(
            endpoint=endpoint,
            passed_sites=len(sites),
            total_sites=6,
            proposed_points=sum(len(s["distances_angstrom"]) for s in sites),
            jobs_launched=0,
        )
    )
write(root / "assessment.json", dict(records=reports, simulation_ready=False))
print(reports)

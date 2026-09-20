"""Assess a replicated short DNA pilot without claiming solution convergence."""

import argparse
import json
from pathlib import Path
import sys
import warnings

import numpy as np
import MDAnalysis as mda
from MDAnalysis.lib.formats.libdcd import DCDFile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import write, source


def aligned_rmsd(x, y):
    x = x - x.mean(axis=0)
    y = y - y.mean(axis=0)
    a, _, b = np.linalg.svd(x.T @ y)
    sign = np.linalg.det(a @ b)
    rotation = a @ np.diag([1, 1, sign]) @ b
    return float(np.sqrt(np.mean(np.sum((x @ rotation - y) ** 2, axis=1))))


def signed_volume(x, ids):
    a, b, c, d = x[ids]
    return float(np.linalg.det(np.array([a - d, b - d, c - d])))


def analyze_case(folder):
    build = json.loads((folder / "build.json").read_text())
    production_start = build.get("production_start_step", 60000)
    production_steps = build.get("production_steps", 50000)
    expected_frames = build.get("expected_frames", 100)
    completion = json.loads((folder / "completion.json").read_text())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        reference = mda.Universe(str(folder / "system.psf"), str(folder / "system.pdb"))
        trajectory = mda.Universe(
            str(folder / "system.psf"), str(folder / "trajectory.dcd")
        )
    atoms = reference.atoms[:634]
    initial = atoms.positions.copy()
    heavy = atoms.masses > 2
    idx = {(a.segid, int(a.resid), a.name): int(a.index) for a in atoms}
    bonds = [
        tuple(map(int, b.indices))
        for b in reference.bonds
        if all(i < 634 and heavy[i] for i in b.indices)
    ]
    centers = []
    for r in reference.residues[:20]:
        seg, n = r.segid, int(r.resid)
        nitrogen = "N9" if (seg, n, "N9") in idx else "N1"
        for name, seq in [
            ("C1'", ["O4'", "C2'", nitrogen, "H1'"]),
            ("C3'", ["C2'", "C4'", "O3'", "H3'"]),
            ("C4'", ["O4'", "C3'", "C5'", "H4'"]),
        ]:
            ids = [idx[(seg, n, a)] for a in seq]
            centers.append((f"{seg}:{n}:{name}", ids, signed_volume(initial, ids)))
    lesion = []
    if build["system"] == "cpd":
        for n, other in [(15, 16), (16, 15)]:
            for name, seq in [
                ("C5", [(n, "C4"), (n, "C6"), (n, "C5M"), (other, "C5")]),
                ("C6", [(n, "N1"), (n, "C5"), (n, "H6"), (other, "C6")]),
            ]:
                ids = [idx[("B", r, a)] for r, a in seq]
                centers.append((f"B:{n}:{name}", ids, signed_volume(initial, ids)))
        lesion = [(idx[("B", 15, a)], idx[("B", 16, a)]) for a in ["C5", "C6"]]
    contacts = []
    residues = {(r.segid, int(r.resid)): r.resname for r in reference.residues[:20]}
    for a in range(3, 9):
        b = 21 - a
        left, right = residues[("A", a)], residues[("B", b)]
        if (left, right) == ("ADE", "THY"):
            names = [("N6", "O4"), ("N1", "N3")]
        elif (left, right) == ("THY", "ADE"):
            names = [("O4", "N6"), ("N3", "N1")]
        elif (left, right) == ("GUA", "CYT"):
            names = [("O6", "N4"), ("N1", "N3"), ("N2", "O2")]
        elif (left, right) == ("CYT", "GUA"):
            names = [("N4", "O6"), ("N3", "N1"), ("O2", "N2")]
        else:
            raise ValueError("Unexpected duplex complement")
        contacts.extend([(idx[("A", a, x)], idx[("B", b, y)]) for x, y in names])
    header = DCDFile(str(folder / "trajectory.dcd")).header
    metrics = []
    failed_centers = set()
    bond_outliers = []
    max_bond = 0.0
    min_bond = float("inf")
    production_reference = None
    center_volumes = {name: [] for name, _, _ in centers}
    for ts in trajectory.trajectory:
        step = header["istart"] + ts.frame * header["nsavc"]
        x = ts.positions[:634].copy()
        if step <= 10000:
            continue
        lengths = np.array([np.linalg.norm(x[a] - x[b]) for a, b in bonds])
        max_bond = max(max_bond, float(max(lengths)))
        min_bond = min(min_bond, float(min(lengths)))
        for name, ids, v0 in centers:
            v = signed_volume(x, ids)
            center_volumes[name].append(v)
            if v * v0 <= 0:
                failed_centers.add(name)
        for j in np.flatnonzero((lengths < 0.8) | (lengths > 2.1)):
            if len(bond_outliers) < 30:
                bond_outliers.append(
                    dict(
                        step=step,
                        atoms=[str(atoms[i]) for i in bonds[j]],
                        distance_A=float(lengths[j]),
                    )
                )
        if step <= production_start:
            continue
        if production_reference is None:
            production_reference = x.copy()
        metrics.append(
            dict(
                step=int(step),
                production_ps=(step - production_start) * 0.002,
                aligned_heavy_rmsd_initial_A=aligned_rmsd(x[heavy], initial[heavy]),
                aligned_heavy_rmsd_production_start_A=aligned_rmsd(
                    x[heavy], production_reference[heavy]
                ),
                central_contact_fraction=float(
                    np.mean([np.linalg.norm(x[a] - x[b]) < 3.5 for a, b in contacts])
                ),
                lesion_bonds_A=[float(np.linalg.norm(x[a] - x[b])) for a, b in lesion],
            )
        )
    energies = []
    keys = []
    for line in (folder / "run.log").read_text().splitlines():
        if line.startswith("ETITLE:"):
            keys = line.split()[1:]
        if line.startswith("ENERGY:"):
            row = dict(zip(keys, map(float, line.split()[1:])))
            if row["TS"] > production_start:
                energies.append(row)
    assert energies and metrics, "No production samples"
    temperature = float(np.mean([e["TEMP"] for e in energies]))
    density = float(
        np.mean(
            [
                reference.atoms.masses.sum() * 1.66053906660 / e["VOLUME"]
                for e in energies
            ]
        )
    )
    checks = dict(
        native_execution=completion["passed_execution"],
        production_expected_frames=len(metrics) == expected_frames,
        all_stereochemistry_retained=not failed_centers,
        heavy_bond_sanity=0.8 <= min_bond and max_bond <= 2.1,
        mean_temperature=280 <= temperature <= 320,
        mean_density=0.9 <= density <= 1.2,
        finite_observables=all(np.isfinite(v) for e in energies for v in e.values()),
    )
    report = dict(
        system=build["system"],
        replica=build["replica"],
        stage=build.get("stage", "short stability pilot"),
        passed=bool(all(checks.values())),
        checks=checks,
        production_ps=production_steps * 0.002,
        centers_checked=len(centers),
        failed_centers=sorted(failed_centers),
        heavy_bond_min_A=min_bond,
        heavy_bond_max_A=max_bond,
        bond_outliers=bond_outliers,
        temperature_mean_K=temperature,
        density_mean_g_ml=density,
        pressure_mean_bar=float(np.mean([e["PRESSURE"] for e in energies])),
        rmsd_initial_mean_A=float(
            np.mean([m["aligned_heavy_rmsd_initial_A"] for m in metrics])
        ),
        rmsd_production_mean_A=float(
            np.mean([m["aligned_heavy_rmsd_production_start_A"] for m in metrics])
        ),
        central_contact_fraction_mean=float(
            np.mean([m["central_contact_fraction"] for m in metrics])
        ),
        lesion_bond_mean_A=np.mean(
            [m["lesion_bonds_A"] for m in metrics], axis=0
        ).tolist()
        if lesion
        else [],
        metrics=metrics,
        center_volume_ranges={k: [min(v), max(v)] for k, v in center_volumes.items()},
        sources=[
            source(folder / n)
            for n in [
                "run.conf",
                "system.psf",
                "system.pdb",
                "run.log",
                "trajectory.dcd",
                "build.json",
                "completion.json",
            ]
        ],
    )
    return report


def main(root):
    cases = json.loads((root / "builds.json").read_text())["cases"]
    records = []
    for case in cases:
        folder = Path(case["folder"])
        if not (folder / "completion.json").exists():
            continue
        completion = json.loads((folder / "completion.json").read_text())
        if not completion["passed_execution"]:
            records.append(
                dict(
                    system=case["system"],
                    replica=case["replica"],
                    passed=False,
                    checks={"native_execution": False},
                )
            )
            continue
        if (folder / "analysis.json").exists():
            report = json.loads((folder / "analysis.json").read_text())
        else:
            report = analyze_case(folder)
            write(folder / "analysis.json", report)
        records.append(
            {
                k: v
                for k, v in report.items()
                if k not in ["metrics", "sources", "center_volume_ranges"]
            }
        )
    complete = len(records) == 6
    result = dict(
        simulation_ready=False,
        stage="replicated short DNA stability pilot",
        complete=complete,
        passed=complete and all(r["passed"] for r in records),
        completed_replicas=len(records),
        planned_replicas=6,
        records=records,
        limits=json.loads((root / "protocol.json").read_text())["limits"],
        sources=[
            source(root / "protocol.json"),
            source(root / "solvent_parameter_audit.json"),
            source(Path(__file__)),
        ],
    )
    write(root / "assessment.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    main(p.parse_args().root.resolve())

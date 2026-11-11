"""Compare identical core atoms/pairs across isolated damping trials.

Reports per-seed results, not significance from correlated trajectory frames.
RMSD/RMSF remove rigid core motion; topology-authored pairs avoid nearest-neighbor
misassignment. Native input files and trajectories are never modified.
"""

import argparse
import json
from pathlib import Path
from collections import defaultdict

import numpy as np
import MDAnalysis as mda
from scipy.spatial import cKDTree
from backend.core.namd_submodel import sections
from backend.core.md_shell_reprep import read_namd_coor
from backend.core.md_health import build_wc_pairs, wc_frame_metrics


def aligned(x, reference):
    x = x - x.mean(0)
    y = reference - reference.mean(0)
    u, _, vt = np.linalg.svd(x.T @ y)
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    return x @ u @ correction @ vt


def energy_values(log, column):
    labels = None
    values = []
    for line in log.splitlines():
        if line.startswith("ETITLE:"):
            labels = line.split()[1:]
        if line.startswith("ENERGY:") and labels:
            row = dict(zip(labels, map(float, line.split()[1:])))
            values.append(row[column])
    return values


def analyze(root):
    selection = json.loads((root / "selection.json").read_text())
    buffer = json.loads((root / "buffer.json").read_text())
    source_rows = [
        s.split() for s in sections((root / "source.psf").read_text())["NATOM"][1]
    ]
    ideal = np.array(
        [
            [float(s[i : i + 8]) for i in (30, 38, 46)]
            for s in (root / "source.pdb").read_text().splitlines()
            if s.startswith(("ATOM  ", "HETATM"))
        ]
    )
    core_source = [
        i for i in selection["mobile_source_indices"] if float(source_rows[i][7]) > 2
    ]
    core_residues = {tuple(source_rows[i][1:3]) for i in core_source}
    source_index = {tuple(row[1:3] + [row[4]]): i for i, row in enumerate(source_rows)}
    reference = ideal[core_source]
    reference -= reference.mean(0)
    results = []
    traces = {}
    rmsf_profiles = {}
    trials = json.loads((root / "trials.json").read_text())
    experiment = json.loads((root / "experiment.json").read_text())
    conditions = experiment.get(
        "conditions", ["full", "fixed", "gamma_0.1", "gamma_1", "gamma_5"]
    )
    expected = {(condition, seed) for condition in conditions for seed in (77, 177)}
    assert (
        len(trials) == len(expected)
        and {(trial["condition"], trial["seed"]) for trial in trials} == expected
    )
    for trial in trials:
        pkg = Path(trial["package"])
        stem = trial["stem"]
        name = trial["name"]
        rows = [
            s.split() for s in sections((pkg / (stem + ".psf")).read_text())["NATOM"][1]
        ]
        identity = {tuple(row[1:3] + [row[4]]): i for i, row in enumerate(rows)}
        core = [
            identity[tuple(source_rows[i][1:3] + [source_rows[i][4]])]
            for i in core_source
        ]
        core_set = set(core)
        pairs = [
            pair
            for pair in build_wc_pairs(pkg / (stem + ".psf"), pkg / (stem + ".pdb"))
            if all(i in core_set and j in core_set for i, j in pair.atom_pairs)
        ]
        assert pairs, "No topology-defined core pairs"
        pair_registry = json.loads((pkg / (stem + "_wc_pairs.json")).read_text())[
            "pairs"
        ]
        c1pairs = [
            (identity[tuple(p["a"]) + ("C1'",)], identity[tuple(p["b"]) + ("C1'",)])
            for p in pair_registry
            if tuple(p["a"]) in core_residues and tuple(p["b"]) in core_residues
        ]
        # Use native coordinates at the start; all cropped trials share this pose.
        start = read_namd_coor(pkg / "output/common_relax.coor")
        start_core = aligned(start[core], reference)
        water = [
            i for i, row in enumerate(rows) if row[3] == "TIP3" and row[4] == "OH2"
        ]
        dna = [
            i
            for i, row in enumerate(rows)
            if tuple(row[1:3] + [row[4]]) in source_index
        ]
        bonds = (
            np.array(
                list(
                    map(
                        int,
                        " ".join(
                            sections((pkg / (stem + ".psf")).read_text())["NBOND"][1]
                        ).split(),
                    )
                )
            ).reshape(-1, 2)
            - 1
        )
        bonds = np.array(
            [
                (a, b)
                for a, b in bonds
                if (a in core_set or b in core_set)
                and float(rows[a][7]) > 2
                and float(rows[b][7]) > 2
            ]
        )
        bond_ref = np.linalg.norm(start[bonds[:, 0]] - start[bonds[:, 1]], axis=1)
        universe = mda.Universe(
            str(pkg / (stem + ".psf")), str(pkg / "output" / f"{name}.dcd")
        )
        data = []
        frames = []
        gaps = []
        for ts in universe.trajectory:
            xyz = universe.atoms.positions
            assert np.isfinite(xyz).all()
            fit = aligned(xyz[core], reference)
            frames.append(fit)
            wc = wc_frame_metrics(xyz, pairs)
            c1 = np.linalg.norm(
                xyz[np.array(c1pairs)[:, 0]] - xyz[np.array(c1pairs)[:, 1]], axis=1
            )
            strict = []
            for pair in pairs:
                a, b = pair.atom_pairs[0]
                h = pair.h_index
                assert h is not None
                va = xyz[a] - xyz[h]
                vb = xyz[b] - xyz[h]
                cosine = np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb))
                angle = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
                strict.append(np.linalg.norm(xyz[a] - xyz[b]) < 3 and angle > 140)
            lengths = np.linalg.norm(xyz[bonds[:, 0]] - xyz[bonds[:, 1]], axis=1)
            cell = np.array(ts.dimensions[:3], dtype=float)
            tree = cKDTree(np.mod(xyz[core], cell), boxsize=cell)
            distances, _ = tree.query(
                np.mod(xyz[water], cell), distance_upper_bound=5, workers=1
            )
            # Sufficient conservative check for DNA/periodic-image separation.
            gaps.append(float(np.min(cell - np.ptp(xyz[dna], axis=0))))
            data.append(
                {
                    "time_ps": len(data) + 1,
                    "rmsd_ideal_A": float(
                        np.sqrt(np.mean(np.sum((fit - reference) ** 2, axis=1)))
                    ),
                    "rmsd_start_A": float(
                        np.sqrt(np.mean(np.sum((fit - start_core) ** 2, axis=1)))
                    ),
                    "rg_A": float(np.sqrt(np.mean(np.sum(fit**2, axis=1)))),
                    "wc_fraction": wc["absolute_paired_fraction"],
                    "wc_strict_fraction": float(np.mean(strict)),
                    "c1_fraction": float(np.mean(c1 <= 12)),
                    "c1_mean_A": float(c1.mean()),
                    "bond_stretch_p99_A": float(
                        np.percentile(np.abs(lengths - bond_ref), 99)
                    ),
                    "waters_within_5A": int(np.isfinite(distances).sum()),
                }
            )
        frames = np.array(frames)
        tail = frames[len(frames) // 2 :]
        rmsf = np.sqrt(np.mean(np.sum((tail - tail.mean(0)) ** 2, axis=2), axis=0))
        native_final = read_namd_coor(pkg / "output" / f"{name}.coor")
        if trial["condition"] == "full":
            fixed = []
        elif trial["condition"] == "fixed":
            fixed = sorted(
                set(range(buffer["retained_atoms"])) - set(buffer["core_indices"])
            )
        else:
            fixed = buffer["frozen_indices"]
        drift = (
            float(np.linalg.norm(native_final[fixed] - start[fixed], axis=1).max())
            if fixed
            else None
        )
        log = (pkg / (name + ".native.log")).read_text()
        temps = energy_values(log, "TEMP")
        pressures = energy_values(log, "PRESSURE")
        assert len(data) == trial["frames_expected"], (name, len(data))
        assert not fixed or drift < 1e-8, (name, drift)
        assert min(gaps) > 20, (
            name,
            "DNA periodic-image bounding-box gap below twice 10 A cutoff",
            min(gaps),
        )
        means = {
            key: float(np.mean([row[key] for row in data[len(data) // 2 :]]))
            for key in data[0]
            if key != "time_ps"
        }
        result = {
            **trial,
            "core_heavy_atoms": len(core),
            "core_base_pairs": len(pairs),
            "frames": len(data),
            "initial_core_rmsd_to_ideal_A": float(
                np.sqrt(np.mean(np.sum((start_core - reference) ** 2, axis=1)))
            ),
            "last_half_means": means,
            "last_half_core_rmsf_A": float(rmsf.mean()),
            "temperature_mean_K": float(np.mean(temps)),
            "temperature_range_K": [float(min(temps)), float(max(temps))],
            "pressure_mean_bar": float(np.mean(pressures)),
            "minimum_DNA_image_gap_A": min(gaps),
            "fixed_max_drift_A": drift,
        }
        results.append(result)
        traces[name] = data
        rmsf_profiles[name] = rmsf.tolist()
        print(
            name,
            means["rmsd_ideal_A"],
            result["last_half_core_rmsf_A"],
            means["wc_fraction"],
            flush=True,
        )
    counts = {(r["core_heavy_atoms"], r["core_base_pairs"]) for r in results}
    assert len(counts) == 1
    groups = defaultdict(list)
    for result in results:
        groups[result["condition"]].append(result)
    summary = {}
    for name, rows in groups.items():
        metrics = {
            **{
                key: [r["last_half_means"][key] for r in rows]
                for key in rows[0]["last_half_means"]
            },
            "rmsf_A": [r["last_half_core_rmsf_A"] for r in rows],
            "temperature_K": [r["temperature_mean_K"] for r in rows],
            "pressure_bar": [r["pressure_mean_bar"] for r in rows],
        }
        summary[name] = {
            key: {
                "mean": float(np.mean(values)),
                "seeds": values,
                "range": [float(min(values)), float(max(values))],
            }
            for key, values in metrics.items()
        }
    for filename, obj in [
        ("analysis.json", results),
        ("summary.json", summary),
        ("traces.json", traces),
        ("rmsf_profiles.json", rmsf_profiles),
    ]:
        (root / filename).write_text(json.dumps(obj, indent=2))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    colors = dict(zip(groups, plt.get_cmap("tab10").colors))
    for result in results:
        name = result["name"]
        cond = result["condition"]
        data = traces[name]
        color = colors[cond]
        label = cond if result["seed"] == 77 else None
        axes[0, 0].plot(
            [d["time_ps"] for d in data],
            [d["rmsd_ideal_A"] for d in data],
            color=color,
            label=label,
            alpha=0.8,
            ls="-" if result["seed"] == 77 else "--",
        )
        axes[0, 1].plot(
            [d["time_ps"] for d in data],
            [d["wc_fraction"] for d in data],
            color=color,
            alpha=0.8,
            ls="-" if result["seed"] == 77 else "--",
        )
    names = list(summary)
    x = np.arange(len(names))
    for axis, key, title in [
        (axes[1, 0], "rmsf_A", "Core heavy-atom RMSF (Å), last 25 ps"),
        (axes[1, 1], "c1_mean_A", "Mean paired C1′ separation (Å), last 25 ps"),
    ]:
        axis.bar(
            x,
            [summary[n][key]["mean"] for n in names],
            color=[colors[n] for n in names],
            alpha=0.5,
        )
        for i, n in enumerate(names):
            axis.scatter(
                [i] * len(summary[n][key]["seeds"]),
                summary[n][key]["seeds"],
                color="black",
                s=15,
            )
        axis.set_xticks(x, names, rotation=20)
        axis.set_title(title)
    axes[0, 0].set_title("Aligned core RMSD to common ideal structure (Å)")
    axes[0, 0].legend(fontsize=8)
    axes[0, 1].set_title("Designed core pairs: all WC contacts ≤3.6 Å")
    for axis in axes[0]:
        axis.set_xlabel("Production time (ps)")
    fig.suptitle(
        experiment.get(
            "plot_title",
            "Central NAMD submodel: two 50 ps seeds per condition\nSame core identities; restrained buffer k=0.1 kcal/mol/Å²; exploratory, not converged",
        )
    )
    fig.savefig(root / "comparison.png", dpi=180)
    fig.savefig(root / "comparison.pdf")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    analyze(parser.parse_args().output.resolve())

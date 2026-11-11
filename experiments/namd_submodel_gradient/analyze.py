"""Core metrics plus spatial shell response and boundary-strain diagnostics."""

import argparse
import json
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from backend.core.namd_submodel import sections
from backend.core.md_shell_reprep import read_namd_coor
from experiments.namd_submodel_damping.analyze import analyze as core_analysis, aligned
from experiments.namd_submodel_gradient.run import identity, dump


def shell_metrics(root):
    b = json.loads((root / "buffer.json").read_text())
    sel = json.loads((root / "selection.json").read_text())
    source = [
        s.split() for s in sections((root / "source.psf").read_text())["NATOM"][1]
    ]
    retained = sel["retained_source_indices"]
    d = np.array(b["distance_nm"])
    heavy = np.array([float(source[i][7]) > 2 for i in retained])
    core_local = np.array(b["core_indices"])
    core_local = core_local[heavy[core_local]]
    edges = [0, 0.5, 1, 1.5, 2, 2.5, 3, float("inf")]
    shell = np.ones(len(retained), dtype=bool)
    shell[b["core_indices"]] = False
    results = []
    residue_results = {}
    for trial in json.loads((root / "trials.json").read_text()):
        pkg = Path(trial["package"])
        stem = trial["stem"]
        name = trial["name"]
        parsed = sections((pkg / f"{stem}.psf").read_text())
        rows = [s.split() for s in parsed["NATOM"][1]]
        lookup = identity(rows)
        mapping = np.array(
            [lookup[tuple(source[i][1:3] + [source[i][4]])] for i in retained]
        )
        core = mapping[core_local]
        start = read_namd_coor(pkg / "output/common_relax.coor")
        indices = set(mapping[shell])
        retained_set = set(mapping)
        bonds = (
            np.array(list(map(int, " ".join(parsed["NBOND"][1]).split()))).reshape(
                -1, 2
            )
            - 1
        )
        bonds = np.array(
            [
                (a, c)
                for a, c in bonds
                if a in retained_set
                and c in retained_set
                and (a in indices or c in indices)
                and float(rows[a][7]) > 2
                and float(rows[c][7]) > 2
            ]
        )
        lengths = np.linalg.norm(start[bonds[:, 0]] - start[bonds[:, 1]], axis=1)
        u = mda.Universe(str(pkg / f"{stem}.psf"), str(pkg / "output" / f"{name}.dcd"))
        positions = []
        aligned_positions = []
        strains = []
        fixed_drift = 0
        fixed = (
            []
            if trial["condition"] == "full"
            else (
                np.flatnonzero(shell)
                if trial["condition"] == "fixed"
                else b["frozen_indices"]
            )
        )
        for ts in u.trajectory:
            x = u.atoms.positions.astype(float)
            if len(fixed):
                fixed_drift = max(
                    fixed_drift,
                    float(
                        np.linalg.norm(
                            x[mapping[fixed]] - start[mapping[fixed]], axis=1
                        ).max()
                    ),
                )
            positions.append(x[mapping])
            aa = x[core] - x[core].mean(0)
            bb = start[core] - start[core].mean(0)
            left, _, right = np.linalg.svd(aa.T @ bb)
            correction = np.eye(3)
            correction[-1, -1] = np.linalg.det(left @ right)
            aligned_positions.append(
                (x[mapping] - x[core].mean(0)) @ left @ correction @ right
                + start[core].mean(0)
            )
            strains.append(
                float(
                    np.percentile(
                        np.abs(
                            np.linalg.norm(x[bonds[:, 0]] - x[bonds[:, 1]], axis=1)
                            - lengths
                        ),
                        99,
                    )
                )
            )
        assert fixed_drift < 5e-5, (
            name,
            fixed_drift,
        )  # float32 DCD quantization, not native checkpoint precision
        positions = np.array(positions)
        aligned_positions = np.array(aligned_positions)
        tail = aligned_positions[len(positions) // 2 :]
        rmsf = np.sqrt(np.mean(np.sum((tail - tail.mean(0)) ** 2, axis=2), axis=0))
        profiles = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            mask = shell & heavy & (d >= lo) & (d < hi)
            if not mask.any():
                continue
            ids = np.flatnonzero(mask)
            profiles.append(
                dict(
                    inner_nm=lo,
                    outer_nm=hi if np.isfinite(hi) else None,
                    heavy_atoms=len(ids),
                    fixed_heavy_atoms=len(set(ids).intersection(fixed)),
                    mean_reference_distance_nm=float(d[mask].mean()),
                    residues=len({tuple(source[retained[i]][1:3]) for i in ids}),
                    mean_core_aligned_rmsf_A=float(rmsf[mask].mean()),
                    mean_core_aligned_displacement_A=float(
                        np.linalg.norm(
                            tail[:, mask] - start[mapping[mask]], axis=2
                        ).mean()
                    ),
                    mean_lab_displacement_A=float(
                        np.linalg.norm(
                            positions[len(positions) // 2 :, mask]
                            - start[mapping[mask]],
                            axis=2,
                        ).mean()
                    ),
                )
            )
        # U=k*delta^2 for NAMD harmonic constraints; force magnitude proxy 2*k*delta.
        if trial["condition"] == "gradient":
            k = np.array(b["gradient_k"])
        elif trial["condition"] == "uniform":
            k = np.zeros(len(retained))
            k[b["buffer_indices"]] = 0.1
            k[~heavy] = 0
        else:
            k = np.zeros(len(retained))
        delta = np.linalg.norm(positions - start[mapping], axis=2)
        by_residue = {}
        for i, source_i in enumerate(retained):
            if heavy[i]:
                by_residue.setdefault(tuple(source[source_i][1:3]), []).append(i)
        residue_results[name] = [
            dict(
                segment=key[0],
                residue=key[1],
                distance_nm=float(d[ids[0]]),
                region="core"
                if not shell[ids[0]]
                else "fixed"
                if ids[0] in fixed
                else "buffer",
                mean_core_aligned_rmsf_A=float(rmsf[ids].mean()),
                mean_core_aligned_displacement_A=float(
                    np.linalg.norm(tail[:, ids] - start[mapping[ids]], axis=2).mean()
                ),
                mean_lab_displacement_A=float(delta[len(delta) // 2 :, ids].mean()),
                coefficient=float(k[ids[0]]),
            )
            for key, ids in by_residue.items()
        ]
        results.append(
            dict(
                name=name,
                condition=trial["condition"],
                seed=trial["seed"],
                shell_profiles=profiles,
                boundary_bond_count=len(bonds),
                boundary_bond_stretch_p99_A=float(
                    np.mean(strains[len(strains) // 2 :])
                ),
                fixed_max_DCD_drift_A=fixed_drift,
                mean_restraint_energy_proxy_kcal_mol=float(
                    np.mean((delta**2 * k).sum(1))
                ),
                max_restraint_force_proxy_kcal_mol_A=float((2 * delta * k).max()),
                trajectory_bytes=(pkg / "output" / f"{name}.dcd").stat().st_size,
            )
        )
    assert len({r["boundary_bond_count"] for r in results}) == 1
    dump(root / "shell-metrics.json", results)
    dump(root / "residue-profiles.json", residue_results)
    experiment = json.loads((root / "experiment.json").read_text())
    performance = {}
    for path in [
        Path(experiment["prior"]) / "execution.jsonl",
        root / "execution.jsonl",
    ]:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row["success"]:
                performance[row["stage"]] = row
    dump(
        root / "performance.json", {r["name"]: performance[r["name"]] for r in results}
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(14, 4), constrained_layout=True)
    colors = dict(
        zip(["full", "fixed", "uniform", "gradient"], plt.get_cmap("tab10").colors)
    )
    for r in results:
        p = r["shell_profiles"]
        x = [v["mean_reference_distance_nm"] for v in p]
        for ax, key in zip(
            axes[:2], ["mean_core_aligned_rmsf_A", "mean_lab_displacement_A"]
        ):
            ax.plot(
                x,
                [v[key] for v in p],
                color=colors[r["condition"]],
                ls="-" if r["seed"] == 77 else "--",
                label=r["condition"] if r["seed"] == 77 else None,
            )
    axes[0].set_ylabel("Core-aligned shell RMSF (Å)")
    axes[1].set_ylabel("Shell displacement in cell frame (Å)")
    for ax in axes[:2]:
        ax.set_xlabel("Distance outside mobile box (nm)")
    axes[0].legend()
    mobile_mask = heavy & shell
    mobile_mask[b["frozen_indices"]] = False
    axes[2].scatter(
        d[mobile_mask],
        np.array(b["gradient_k"])[mobile_mask],
        s=3,
        label="mobile restraint coefficients",
    )
    fi = np.array(b["frozen_indices"])
    fi = fi[heavy[fi]]
    axes[2].scatter(
        d[fi], np.full(len(fi), 0.55), s=8, marker="x", label="fixed (not finite k)"
    )
    axes[2].set_xlabel("Reference distance outside box (nm)")
    axes[2].set_ylabel("NAMD harmonic coefficient (kcal/mol/Å²)")
    axes[2].legend(fontsize=7)
    fig.suptitle(
        "3 nm shell: spatial response, two 50 ps seeds; static smoothstep restraints"
    )
    fig.savefig(root / "shell-profiles.png", dpi=180)
    fig.savefig(root / "shell-profiles.pdf")
    plt.close(fig)


def verify_shared_start(root):
    packages = json.loads((root / "packages.json").read_text())
    selection = json.loads((root / "selection.json").read_text())
    rows = [s.split() for s in sections((root / "source.psf").read_text())["NATOM"][1]]
    core = [i for i in selection["mobile_source_indices"] if float(rows[i][7]) > 2]
    points = {}
    for key, info in packages.items():
        pkg = Path(info["package"])
        stem = info["stem"]
        lookup = identity(
            [s.split() for s in sections((pkg / f"{stem}.psf").read_text())["NATOM"][1]]
        )
        ids = [lookup[tuple(rows[i][1:3] + [rows[i][4]])] for i in core]
        points[key] = read_namd_coor(pkg / "output/common_relax.coor")[ids]
    reference = points["full"] - points["full"].mean(0)
    delta = aligned(points["crop"], points["full"]) - reference
    error = np.linalg.norm(delta, axis=1)
    assert error.max() < 0.002, error.max()
    dump(
        root / "shared-start-verification.json",
        dict(
            core_heavy_atoms=len(core),
            aligned_core_RMSD_A=float(np.sqrt(np.mean(error**2))),
            maximum_core_atom_error_A=float(error.max()),
            tolerance_A=0.002,
        ),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output", type=Path)
    a = ap.parse_args()
    root = a.output.resolve()
    verify_shared_start(root)
    core_analysis(root)
    shell_metrics(root)


if __name__ == "__main__":
    main()

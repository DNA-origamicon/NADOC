"""Localize existing DNA drift; descriptive diagnostics, no new acceptance gates."""

import argparse
import itertools
import json
from pathlib import Path
import warnings
import numpy as np
import MDAnalysis as mda
from scipy.spatial import cKDTree
from experiments.cpd_published_comparator.analyze_dna_replicas import aligned_rmsd


def fit(x, reference, ids):
    a, b = x[ids].mean(0), reference[ids].mean(0)
    u, _, v = np.linalg.svd((x[ids] - a).T @ (reference[ids] - b))
    rotation = u @ np.diag([1, 1, np.linalg.det(u @ v)]) @ v
    return (x - a) @ rotation + b


def torsion(x):
    b = np.diff(x, axis=0)
    axis = b[1] / np.linalg.norm(b[1])
    v = -b[0] + np.dot(b[0], axis) * axis
    w = b[2] - np.dot(b[2], axis) * axis
    return float(np.degrees(np.arctan2(np.dot(np.cross(axis, v), w), np.dot(v, w))))


def analyze(root, out):
    out.mkdir(exist_ok=False)
    cases = []
    for system in ["cpd", "control"]:
        for replica in range(1, 4):
            folder = root / system / f"replica-{replica}"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ref = mda.Universe(
                    str(folder / "block-1/system.psf"),
                    str(folder / "block-1/system.pdb"),
                )
                u = mda.Universe(
                    str(folder / "block-1/system.psf"),
                    *[str(folder / f"block-{b}/trajectory.dcd") for b in range(1, 6)],
                )
            atoms = ref.atoms[:634]
            initial = atoms.positions.copy()
            heavy = np.flatnonzero(atoms.masses > 2)
            idx = {(a.segid, int(a.resid), a.name): a.index for a in atoms}
            residues = [
                np.array([a.index for a in r.atoms if a.mass > 2])
                for r in ref.residues[:20]
            ]
            labels = [f"{r.segid}:{r.resid}" for r in ref.residues[:20]]
            central = np.concatenate(
                [residues[i] for i in list(range(2, 8)) + list(range(12, 18))]
            )
            lesion = np.array(
                [
                    idx["B", r, n]
                    for r in [15, 16]
                    for n in ["N1", "C2", "N3", "C4", "C5", "C6", "O2", "O4"]
                ]
            )
            sugar = [
                np.array([idx["B", r, n] for n in ["O4'", "C1'", "C2'", "C3'", "C4'"]])
                for r in [15, 16]
            ]
            chi = [
                [idx["B", r, n] for n in ["O4'", "C1'", "N1", "C2"]] for r in [15, 16]
            ]
            pairs = []
            contacts = []
            names = {r.resid: r.resname for r in ref.residues[:20]}
            for a in range(1, 11):
                b = 21 - a
                base_names = ["N1", "C2", "N3", "C4", "C5", "C6"]
                pairs.append(
                    [
                        idx[seg, r, n]
                        for seg, r in [("A", a), ("B", b)]
                        for n in base_names
                    ]
                )
                left = names[a]
                seq = {
                    "ADE": [("N6", "O4"), ("N1", "N3")],
                    "THY": [("O4", "N6"), ("N3", "N1")],
                    "GUA": [("O6", "N4"), ("N1", "N3"), ("N2", "O2")],
                    "CYT": [("N4", "O6"), ("N3", "N1"), ("O2", "N2")],
                }[left]
                contacts.append([(idx["A", a, x], idx["B", b, y]) for x, y in seq])
            frames = []
            for ts in u.trajectory[9::10]:
                x = ts.positions[:634].copy()
                aligned = fit(x, initial, heavy)
                centered = fit(x, initial, central)
                centers = np.array([x[ids].mean(0) for ids in pairs])
                v = centers[3] - centers[0]
                w = centers[9] - centers[6]
                bend = float(
                    np.degrees(
                        np.arccos(
                            np.clip(
                                v @ w / np.linalg.norm(v) / np.linalg.norm(w), -1, 1
                            )
                        )
                    )
                )
                cell = np.array(ts.triclinic_dimensions)
                tree = cKDTree(x[heavy])
                best = (float("inf"), None, None)
                for shift in itertools.product([-1, 0, 1], repeat=3):
                    if shift == (0, 0, 0):
                        continue
                    distances, indices = tree.query(
                        x[heavy] + np.array(shift) @ cell, k=1
                    )
                    j = int(np.argmin(distances))
                    if distances[j] < best[0]:
                        best = (
                            float(distances[j]),
                            [str(atoms[heavy[j]]), str(atoms[heavy[indices[j]]])],
                            shift,
                        )
                frames.append(
                    dict(
                        time_ns=(ts.frame + 1) * 0.002,
                        block=ts.frame // 500 + 1,
                        global_rmsd_A=aligned_rmsd(x[heavy], initial[heavy]),
                        central_rmsd_A=aligned_rmsd(x[central], initial[central]),
                        lesion_local_rmsd_A=aligned_rmsd(x[lesion], initial[lesion]),
                        residue_global_rmsd_A=[
                            float(
                                np.sqrt(
                                    np.mean(
                                        np.sum(
                                            (aligned[ids] - initial[ids]) ** 2, axis=1
                                        )
                                    )
                                )
                            )
                            for ids in residues
                        ],
                        residue_central_fit_rmsd_A=[
                            float(
                                np.sqrt(
                                    np.mean(
                                        np.sum(
                                            (centered[ids] - initial[ids]) ** 2, axis=1
                                        )
                                    )
                                )
                            )
                            for ids in residues
                        ],
                        residue_local_rmsd_A=[
                            aligned_rmsd(x[ids], initial[ids]) for ids in residues
                        ],
                        pair_contacts=[
                            float(
                                np.mean(
                                    [
                                        np.linalg.norm(x[a] - x[b]) < 3.5
                                        for a, b in bonds
                                    ]
                                )
                            )
                            for bonds in contacts
                        ],
                        bend_proxy_deg=bend,
                        chi_deg=[torsion(x[ids]) for ids in chi],
                        sugar_ring_torsions_deg=[
                            [torsion(x[np.roll(ids, -k)[:4]]) for k in range(5)]
                            for ids in sugar
                        ],
                        image_distance_A=best[0],
                        image_pair=best[1],
                        image_shift=best[2],
                    )
                )
            case = dict(system=system, replica=replica, labels=labels, frames=frames)
            (out / f"{system}-{replica}.json").write_text(json.dumps(case) + "\n")
            cases.append(case)
            print(system, replica, "done", flush=True)
    summaries = []
    for c in cases:
        blocks = []
        for b in range(1, 6):
            fs = [f for f in c["frames"] if f["block"] == b]
            fields = [
                "global_rmsd_A",
                "central_rmsd_A",
                "lesion_local_rmsd_A",
                "residue_global_rmsd_A",
                "residue_central_fit_rmsd_A",
                "residue_local_rmsd_A",
                "pair_contacts",
                "bend_proxy_deg",
                "image_distance_A",
            ]
            stats = {
                key: np.mean([f[key] for f in fs], axis=0).tolist() for key in fields
            }
            stats.update(
                block=b,
                image_min_A=min(f["image_distance_A"] for f in fs),
                image_below_cutoff_fraction=float(
                    np.mean([f["image_distance_A"] < 12 for f in fs])
                ),
            )
            blocks.append(stats)
        summaries.append(
            dict(
                system=c["system"],
                replica=c["replica"],
                labels=c["labels"],
                blocks=blocks,
            )
        )
    (out / "summary.json").write_text(
        json.dumps(
            dict(
                stride_ps=20,
                replicas=summaries,
                limits=[
                    "Descriptive diagnostics; no convergence acceptance gate",
                    "Bend is a coarse centerline proxy, not a helical-axis fit",
                    "Contacts use distance only; image distances sampled every 20 ps",
                    "Sugar ring torsions are raw dihedrals, not assigned pseudorotation states",
                ],
            ),
            indent=2,
        )
        + "\n"
    )
    plot(cases, out)


def plot(cases, out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(3, 2, figsize=(12, 10), sharex=True, layout="constrained")
    for c in cases:
        fs = c["frames"]
        x = [f["time_ns"] for f in fs]
        style = "-" if c["system"] == "cpd" else "--"
        color = f"C{c['replica'] - 1}"
        label = f"{c['system']} {c['replica']}"
        for ax, key in zip(
            axs.flat,
            [
                "global_rmsd_A",
                "central_rmsd_A",
                "lesion_local_rmsd_A",
                "bend_proxy_deg",
                "image_distance_A",
                "pair_contacts",
            ],
        ):
            y = [
                np.mean(np.array(f[key])[[0, 1, 8, 9]])
                if key == "pair_contacts"
                else f[key]
                for f in fs
            ]
            ax.plot(x, y, style, color=color, alpha=0.65, lw=0.8, label=label)
    titles = [
        "Whole duplex RMSD (Å)",
        "Central six pairs fitted RMSD (Å)",
        "Two lesion base rings, local fit RMSD (Å)",
        "Centerline bend proxy (degrees)",
        "Nearest translated DNA image (Å)",
        "Terminal two pairs per end, contact fraction",
    ]
    for ax, title in zip(axs.flat, titles):
        ax.set_title(title)
        ax.set_xlabel("Additional sampling (ns)")
        ax.grid(alpha=0.2)
    axs[2, 0].axhline(12, color="black", lw=1, label="12 Å cutoff")
    axs[0, 0].legend(fontsize=8, ncol=2)
    fig.savefig(out / "drift_localization.png", dpi=160)
    fig.savefig(out / "drift_localization.pdf")
    plt.close(fig)
    fig, axs = plt.subplots(2, 3, figsize=(13, 7), layout="constrained")
    for ax, c in zip(axs.flat, cases):
        values = np.array([f["residue_global_rmsd_A"] for f in c["frames"]]).T
        im = ax.imshow(
            values,
            aspect="auto",
            origin="lower",
            extent=[0, 5, 0, 20],
            vmin=0,
            vmax=8,
            cmap="magma",
        )
        ax.set_title(f"{c['system']} {c['replica']}")
        ax.set_yticks(np.arange(20) + 0.5, c["labels"], fontsize=6)
        ax.set_xlabel("Additional sampling (ns)")
    fig.colorbar(im, ax=axs, label="Residue RMSD after whole-duplex fit (Å)")
    fig.savefig(out / "residue_drift.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    analyze(a.root.resolve(), a.out.resolve())

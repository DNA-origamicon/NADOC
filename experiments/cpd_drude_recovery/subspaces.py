"""Diagnose mode mixing and planarity without changing a fit or acceptance gate."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, write


def plane_geometry(x, center, neighbors):
    a, b, c = x[neighbors]
    normal = np.cross(b - a, c - a)
    norm = np.linalg.norm(normal)
    if norm < 1e-10:
        raise ValueError("Degenerate neighbor plane")
    height = float((x[center] - a) @ normal / norm)
    vectors = x[neighbors] - x[center]
    angles = [
        np.arccos(
            np.clip(
                vectors[i]
                @ vectors[j]
                / np.linalg.norm(vectors[i])
                / np.linalg.norm(vectors[j]),
                -1,
                1,
            )
        )
        for i, j in ((0, 1), (1, 2), (2, 0))
    ]
    return {
        "signed_height_angstrom": height,
        "angle_sum_degrees": float(np.degrees(sum(angles))),
    }


def main(root):
    with np.load(root / "normal_modes.npz") as f:
        data = dict(f)
    qf, mf = data["qm_frequencies_cm_inverse"], data["mm_frequencies_cm_inverse"]
    qv, mv = (
        data["qm_mass_weighted_eigenvectors"],
        data["mm_mass_weighted_eigenvectors"],
    )
    names = data["atom_names"].tolist()
    idx = {n: i for i, n in enumerate(names)}
    bands = []
    for lo, hi in ((0, 300), (300, 1000), (1000, 1800), (1800, 2500), (2500, 4000)):
        q = np.flatnonzero((qf >= lo) & (qf < hi))
        m = np.flatnonzero((mf >= lo) & (mf < hi))
        cross = qv[:, q].T @ mv[:, m]
        singular = np.linalg.svd(cross, compute_uv=False)
        bands.append(
            {
                "frequency_interval_cm_inverse": [lo, hi],
                "qm_mode_count": len(q),
                "mm_mode_count": len(m),
                "mean_qm_projection_into_mm_band": float(np.sum(cross**2) / len(q))
                if len(q)
                else None,
                "principal_cosines_squared": (singular**2).tolist(),
            }
        )
    overlap = (qv.T @ mv) ** 2
    qi, mi = linear_sum_assignment(-overlap)
    modes = []
    for i, j in zip(qi, mi):
        atom_weights = (qv[:, i].reshape(-1, 3) ** 2).sum(axis=1)
        modes.append(
            {
                "qm_mode": int(i),
                "matched_mm_mode": int(j),
                "qm_frequency_cm_inverse": float(qf[i]),
                "mm_frequency_cm_inverse": float(mf[j]),
                "frequency_difference_cm_inverse": float(mf[j] - qf[i]),
                "squared_overlap": float(overlap[i, j]),
                "qm_projection_into_mm_within_50_cm_inverse": float(
                    overlap[i, np.abs(mf - qf[i]) <= 50].sum()
                ),
                "hydrogen_mass_weighted_fraction": float(
                    sum(
                        w
                        for n, w in zip(names, atom_weights)
                        if n.split(":")[1].startswith("H")
                    )
                ),
                "largest_atom_weights": [
                    {"atom": names[k], "weight": float(atom_weights[k])}
                    for k in np.argsort(atom_weights)[-5:][::-1]
                ],
            }
        )
    planes = []
    for ring in (1, 2):
        for center, neighbors in [
            ("N1", ("C6", "C2", "CM")),
            ("C4", ("N3", "C5", "O4")),
            ("C2", ("N1", "N3", "O2")),
        ]:
            c = idx[f"{ring}:{center}"]
            n = [idx[f"{ring}:{a}"] for a in neighbors]
            planes.append(
                {
                    "center": f"{ring}:{center}",
                    "neighbors": [f"{ring}:{a}" for a in neighbors],
                    "qm": plane_geometry(data["qm_coordinates_angstrom"], c, n),
                    "mm": plane_geometry(data["mm_coordinates_angstrom"], c, n),
                }
            )
    write(
        root / "subspace_assessment.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "role": "Diagnostic only; fixed frequency bands and 50 cm^-1 windows are not acceptance criteria. Mass-weighted localization is not energy decomposition.",
            "source": source(root / "normal_modes.npz"),
            "code": source(Path(__file__)),
            "bands": bands,
            "planarity": planes,
            "largest_frequency_disagreements": sorted(
                modes,
                key=lambda x: abs(x["frequency_difference_cm_inverse"]),
                reverse=True,
            ),
            "median_projection_within_50_cm_inverse": float(
                np.median(
                    [m["qm_projection_into_mm_within_50_cm_inverse"] for m in modes]
                )
            ),
        },
    )
    print(
        json.dumps(
            {
                "bands": [
                    {k: v for k, v in b.items() if k != "principal_cosines_squared"}
                    for b in bands
                ],
                "planarity": planes,
                "worst_modes": sorted(
                    modes,
                    key=lambda x: abs(x["frequency_difference_cm_inverse"]),
                    reverse=True,
                )[:4],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    main(p.parse_args().root)

"""exp33 — extract a twist profile from an MD trajectory and compare to the oxDNA one.

Reuses `md_trajectory.md_rmsf` (the MD analogue of oxDNA's production_rmsf: pools all DCD frames,
Kabsch-aligns, returns the per-nucleotide mean structure in the SAME `{positions:[{helix_id,
bp_index, direction, backbone_position}]}` shape) and exp31's `profile.compute_twist_profile`, so
the MD twist is measured with the IDENTICAL pipeline as oxDNA — the comparison is apples-to-apples.
"""
from __future__ import annotations

import csv
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.core.md_trajectory import md_rmsf

import profile as _profile  # exp31 sibling on sys.path (compute_twist_profile)


def _locate(job, ws):
    """(psf, pdb, [dcd…]) for a finished MD job — globbed under its package dir (archive-aware
    via job.job_dir)."""
    jd = job.job_dir(pathlib.Path(ws))
    psfs = sorted(jd.rglob("*.psf"))
    stem = job.name_stem
    pdbs = [p for p in jd.rglob(f"{stem}.pdb")] or sorted(jd.rglob("*.pdb"))
    dcds = sorted(jd.rglob("output/*.dcd"))
    return (psfs[0] if psfs else None, pdbs[0] if pdbs else None, dcds)


def md_mean_core_positions(job, ws, design):
    """Per-nucleotide MEAN backbone positions over the MD trajectory (list of
    {helix_id, bp_index, direction, backbone_position}), or [] if nothing is readable yet."""
    psf, pdb, dcds = _locate(job, ws)
    if not (psf and pdb and dcds):
        return []
    segments = [(p.stem, "", str(p)) for p in dcds]
    res = md_rmsf(str(psf), segments, str(pdb), design)
    return res.get("positions", []) if res.get("ready") else []


def differential_profile(core, ref, *, length_bp: int):
    """MD differential twist profile (sim − analytic), identical pipeline to the oxDNA profiles."""
    return _profile.compute_twist_profile(core, ref, length_bp=length_bp)


def save_profile(profile, path) -> None:
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["position_bp", "cum_twist_diff"])
        for p in profile:
            w.writerow([p["position_bp"], p["cum_twist_diff"]])


def _load_ox(csv_path):
    rows = list(csv.DictReader(pathlib.Path(csv_path).open()))
    return [(float(r["position_bp"]), float(r["cum_twist_diff"])) for r in rows]


def compare_and_plot(name, md_profile, ox_csv, png_path) -> float | None:
    """Overlay the MD vs oxDNA twist profile; return the RMSD (deg) between them on a common grid."""
    import numpy as np
    md = [(p["position_bp"], p["cum_twist_diff"]) for p in md_profile]
    ox = _load_ox(ox_csv) if pathlib.Path(ox_csv).exists() else []
    fig, ax = plt.subplots(figsize=(8, 5))
    if md:
        ax.plot([x for x, _ in md], [y for _, y in md], "-o", color="#d62728",
                ms=4, label="atomistic MD")
    if ox:
        ax.plot([x for x, _ in ox], [y for _, y in ox], "-o", color="#1f77b4",
                ms=4, label="oxDNA")
    ax.axhline(0.0, color="0.85", lw=0.7)
    ax.set_xlabel("position along bundle (bp, axis-projected)")
    ax.set_ylabel("cumulative twist (deg, sim − analytic)")
    ax.set_title(f"exp33 — atomistic MD vs oxDNA twist profile: {name}")
    ax.grid(True, alpha=0.25); ax.legend(fontsize=9)
    pathlib.Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(); fig.savefig(png_path, dpi=130); plt.close(fig)

    if not (md and ox):
        return None
    mx = np.array([x for x, _ in md]); my = np.array([y for _, y in md])
    ox_on_md = np.interp(mx, [x for x, _ in ox], [y for _, y in ox])
    return round(float(np.sqrt(np.mean((my - ox_on_md) ** 2))), 2)

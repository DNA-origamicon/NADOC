#!/usr/bin/env python3
"""Measure paired-base orientation drift across NAMD trajectories.

The script reuses NADOC's C1' base-pair identification, then samples one or
more DCD segments and measures how each paired base pair is oriented relative
to its reference PDB geometry.

Typical usage:

  python scripts/analyze_basepair_orientations.py \
    --package workspace/md_jobs/b9f5df08a55e/package/6hb_84bp_namd_solvated \
    --segments 6hb_84bp_03_300K_NPT_ENM_k0p01_p100 6hb_84bp_04_300K_NPT_MGHH_only_p10

Outputs:
  output/basepair_orientation_summary.json
  output/basepair_orientation_timeseries.csv
  output/basepair_orientation_plot.png

Angles are degrees, distances are Angstrom.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.md_health import C1_PAIRED_MAX_DEFAULT, build_wc_pairs  # noqa: E402


PURINE_BASE_ATOMS = ("N9", "C8", "N7", "C5", "C4", "N3", "C2", "N1", "C6")
PYRIMIDINE_BASE_ATOMS = ("N1", "C2", "N3", "C4", "C5", "C6")
BASE_ATOMS_BY_RESNAME = {
    "DA": PURINE_BASE_ATOMS,
    "DG": PURINE_BASE_ATOMS,
    "ADE": PURINE_BASE_ATOMS,
    "GUA": PURINE_BASE_ATOMS,
    "A": PURINE_BASE_ATOMS,
    "G": PURINE_BASE_ATOMS,
    "DT": PYRIMIDINE_BASE_ATOMS,
    "DC": PYRIMIDINE_BASE_ATOMS,
    "THY": PYRIMIDINE_BASE_ATOMS,
    "CYT": PYRIMIDINE_BASE_ATOMS,
    "T": PYRIMIDINE_BASE_ATOMS,
    "C": PYRIMIDINE_BASE_ATOMS,
}
GLYCOSIDIC_ATOM = {
    "DA": "N9",
    "DG": "N9",
    "ADE": "N9",
    "GUA": "N9",
    "A": "N9",
    "G": "N9",
    "DT": "N1",
    "DC": "N1",
    "THY": "N1",
    "CYT": "N1",
    "T": "N1",
    "C": "N1",
}


@dataclass(frozen=True)
class BaseFrame:
    origin: np.ndarray
    normal: np.ndarray
    gly: np.ndarray
    y: np.ndarray


@dataclass(frozen=True)
class PairRef:
    pair_index: int
    res_ix_i: int
    res_ix_j: int
    label_i: str
    label_j: str
    pair_type: str
    ref_c1_dist: float
    ref_normal_angle_abs: float
    ref_propeller_signed: float
    ref_gly_opposition: float


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("zero-length vector")
    return v / n


def _angle_deg(a: np.ndarray, b: np.ndarray, *, abs_dot: bool = False) -> float:
    aa = _unit(a)
    bb = _unit(b)
    dot = float(np.dot(aa, bb))
    if abs_dot:
        dot = abs(dot)
    return float(math.degrees(math.acos(max(-1.0, min(1.0, dot)))))


def _signed_angle_deg(a: np.ndarray, b: np.ndarray, axis: np.ndarray) -> float:
    aa = _unit(a)
    bb = _unit(b)
    ax = _unit(axis)
    x = float(np.dot(aa, bb))
    y = float(np.dot(ax, np.cross(aa, bb)))
    return float(math.degrees(math.atan2(y, x)))


def _res_label(res: Any) -> str:
    return f"{res.segid}:{res.resname}{int(res.resid)}"


def _res_base_atom_indices(res: Any) -> list[int]:
    names = set(BASE_ATOMS_BY_RESNAME.get(res.resname.strip(), ()))
    return [int(a.index) for a in res.atoms if a.name.strip() in names]


def _atom_index(res: Any, name: str) -> int | None:
    for atom in res.atoms:
        if atom.name.strip() == name:
            return int(atom.index)
    return None


def _base_frame_from_positions(u: Any, res: Any, positions: np.ndarray) -> BaseFrame | None:
    c1_idx = _atom_index(res, "C1'") or _atom_index(res, "C1X")
    gly_name = GLYCOSIDIC_ATOM.get(res.resname.strip())
    gly_idx = _atom_index(res, gly_name) if gly_name else None
    base_idx = _res_base_atom_indices(res)
    if c1_idx is None or gly_idx is None or len(base_idx) < 3:
        return None

    pts = positions[base_idx]
    center = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - center, full_matrices=False)
    normal = _unit(vt[-1])
    gly = _unit(positions[gly_idx] - positions[c1_idx])

    # Make the normal sign deterministic for this frame. The base normal is a
    # plane axis, so sign is arbitrary; orient it to the C1' side of the base.
    c1_side = positions[c1_idx] - center
    if float(np.dot(normal, c1_side)) < 0:
        normal = -normal

    y = _unit(np.cross(normal, gly))
    normal = _unit(np.cross(gly, y))
    return BaseFrame(origin=positions[c1_idx], normal=normal, gly=gly, y=y)


def _measure_pair(fi: BaseFrame, fj: BaseFrame) -> dict[str, float]:
    c1_vec = fj.origin - fi.origin
    c1_dist = float(np.linalg.norm(c1_vec))
    if c1_dist < 1e-12:
        c1_axis = fi.gly
    else:
        c1_axis = c1_vec / c1_dist
    return {
        "c1_dist": c1_dist,
        "normal_angle_abs": _angle_deg(fi.normal, fj.normal, abs_dot=True),
        "normal_angle_raw": _angle_deg(fi.normal, fj.normal),
        "propeller_signed": _signed_angle_deg(fi.normal, fj.normal, c1_axis),
        "gly_opposition": _angle_deg(fi.gly, -fj.gly),
        "gly_raw_angle": _angle_deg(fi.gly, fj.gly),
        "c1_axis_vs_gly_i": _angle_deg(c1_axis, fi.gly, abs_dot=True),
        "c1_axis_vs_gly_j": _angle_deg(-c1_axis, fj.gly, abs_dot=True),
    }


def _select_c1(u: Any) -> Any:
    sel = u.select_atoms("name C1'")
    if len(sel) == 0:
        sel = u.select_atoms("name C1X")
    if len(sel) == 0:
        raise RuntimeError("No C1' atoms found.")
    return sel


def _build_pair_refs(u_ref: Any, psf: Path, pdb: Path, paired_max_ang: float) -> list[PairRef]:
    pairs = build_wc_pairs(psf, pdb)
    refs: list[PairRef] = []
    for k, pair in enumerate(pairs):
        atom_i, atom_j = pair.atom_pairs[0]
        res_i = u_ref.atoms[int(atom_i)].residue
        res_j = u_ref.atoms[int(atom_j)].residue
        fi = _base_frame_from_positions(u_ref, res_i, u_ref.atoms.positions)
        fj = _base_frame_from_positions(u_ref, res_j, u_ref.atoms.positions)
        if fi is None or fj is None:
            continue
        m = _measure_pair(fi, fj)
        if m["c1_dist"] > paired_max_ang:
            continue
        pair_type = f"{res_i.resname.strip()}-{res_j.resname.strip()}"
        refs.append(PairRef(
            pair_index=k,
            res_ix_i=int(res_i.ix),
            res_ix_j=int(res_j.ix),
            label_i=_res_label(res_i),
            label_j=_res_label(res_j),
            pair_type=pair_type,
            ref_c1_dist=m["c1_dist"],
            ref_normal_angle_abs=m["normal_angle_abs"],
            ref_propeller_signed=m["propeller_signed"],
            ref_gly_opposition=m["gly_opposition"],
        ))
    if not refs:
        raise RuntimeError("No base pairs had enough atoms for orientation analysis.")
    return refs


def _sample_frame_indices(n_frames: int, stride: int, max_frames: int | None) -> list[int]:
    idxs = list(range(0, n_frames, max(1, stride)))
    if idxs and idxs[-1] != n_frames - 1:
        idxs.append(n_frames - 1)
    if max_frames is not None and len(idxs) > max_frames:
        keep = np.linspace(0, len(idxs) - 1, max_frames).round().astype(int)
        idxs = [idxs[int(i)] for i in keep]
    return sorted(set(idxs))


def _mean(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(np.mean(vals)) if vals else None


def _pct(values: Iterable[float], pct: float) -> float | None:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(np.percentile(vals, pct)) if vals else None


def _resolve_segments(package_dir: Path, explicit: list[str]) -> list[str]:
    if explicit:
        return explicit
    manifest = package_dir / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        names = [s["name"] for s in data.get("segments", []) if (package_dir / "output" / f"{s['name']}.dcd").exists()]
        if names:
            return names
    return sorted(p.stem for p in (package_dir / "output").glob("*.dcd"))


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    import MDAnalysis as mda  # noqa: PLC0415

    package_dir = args.package.resolve()
    psf = args.psf or next(package_dir.glob("*.psf"))
    pdb = args.pdb or next(package_dir.glob("*.pdb"))
    output_dir = args.output_dir or (package_dir / "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    u_ref = mda.Universe(str(psf), str(pdb))
    pair_refs = _build_pair_refs(u_ref, psf, pdb, args.paired_max_ang)
    ref_by_pair = {p.pair_index: p for p in pair_refs}

    timeseries_path = output_dir / args.timeseries_name
    rows: list[dict[str, Any]] = []
    segment_summaries: dict[str, Any] = {}
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)

    segments = _resolve_segments(package_dir, args.segments)
    if not segments:
        raise RuntimeError(f"No DCD segments found under {package_dir / 'output'}")

    for seg in segments:
        dcd = package_dir / "output" / f"{seg}.dcd"
        if not dcd.exists() or dcd.stat().st_size == 0:
            continue
        u = mda.Universe(str(psf), str(pdb), str(dcd))
        frame_indices = _sample_frame_indices(len(u.trajectory), args.stride, args.max_frames_per_segment)
        seg_rows: list[dict[str, Any]] = []

        for frame_idx in frame_indices:
            ts = u.trajectory[frame_idx]
            positions = u.atoms.positions.copy()
            for pref in pair_refs:
                res_i = u.residues[pref.res_ix_i]
                res_j = u.residues[pref.res_ix_j]
                fi = _base_frame_from_positions(u, res_i, positions)
                fj = _base_frame_from_positions(u, res_j, positions)
                if fi is None or fj is None:
                    continue
                m = _measure_pair(fi, fj)
                paired = m["c1_dist"] <= args.paired_max_ang
                row = {
                    "segment": seg,
                    "frame": int(frame_idx),
                    "time_ps": float(getattr(ts, "time", 0.0)),
                    "pair_index": pref.pair_index,
                    "pair_type": pref.pair_type,
                    "res_i": pref.label_i,
                    "res_j": pref.label_j,
                    "paired": int(paired),
                    "c1_dist_ang": m["c1_dist"],
                    "c1_dist_delta_ang": m["c1_dist"] - pref.ref_c1_dist,
                    "normal_angle_abs_deg": m["normal_angle_abs"],
                    "normal_angle_abs_delta_deg": m["normal_angle_abs"] - pref.ref_normal_angle_abs,
                    "propeller_signed_deg": m["propeller_signed"],
                    "propeller_delta_deg": m["propeller_signed"] - pref.ref_propeller_signed,
                    "gly_opposition_deg": m["gly_opposition"],
                    "gly_opposition_delta_deg": m["gly_opposition"] - pref.ref_gly_opposition,
                    "gly_raw_angle_deg": m["gly_raw_angle"],
                    "c1_axis_vs_gly_i_deg": m["c1_axis_vs_gly_i"],
                    "c1_axis_vs_gly_j_deg": m["c1_axis_vs_gly_j"],
                }
                rows.append(row)
                seg_rows.append(row)
                if paired:
                    by_type[pref.pair_type].append(row)

        segment_summaries[seg] = _summarize_rows(seg_rows)

    _write_csv(timeseries_path, rows)
    plot_path = output_dir / args.plot_name
    if rows:
        _write_plot(plot_path, rows)
    summary = {
        "package_dir": str(package_dir),
        "psf": str(psf),
        "pdb": str(pdb),
        "segments": segments,
        "n_reference_pairs": len(pair_refs),
        "paired_max_ang": args.paired_max_ang,
        "stride": args.stride,
        "segment_summaries": segment_summaries,
        "pair_type_summaries": {
            pair_type: _summarize_rows(type_rows)
            for pair_type, type_rows in sorted(by_type.items())
        },
        "suggested_starting_offsets": _suggest_offsets(by_type),
        "outputs": {
            "timeseries_csv": str(timeseries_path),
            "plot_png": str(plot_path) if rows else None,
        },
    }
    summary_path = output_dir / args.summary_name
    summary["outputs"]["summary_json"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, indent=2))
    return summary


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paired_rows = [r for r in rows if r.get("paired")]
    return {
        "n_rows": len(rows),
        "n_paired_rows": len(paired_rows),
        "paired_fraction": (len(paired_rows) / len(rows)) if rows else None,
        "c1_dist_ang_mean": _mean(r["c1_dist_ang"] for r in paired_rows),
        "c1_dist_ang_p90": _pct((r["c1_dist_ang"] for r in paired_rows), 90),
        "normal_angle_abs_deg_mean": _mean(r["normal_angle_abs_deg"] for r in paired_rows),
        "normal_angle_abs_delta_deg_mean": _mean(r["normal_angle_abs_delta_deg"] for r in paired_rows),
        "propeller_signed_deg_mean": _mean(r["propeller_signed_deg"] for r in paired_rows),
        "propeller_delta_deg_mean": _mean(r["propeller_delta_deg"] for r in paired_rows),
        "gly_opposition_deg_mean": _mean(r["gly_opposition_deg"] for r in paired_rows),
        "gly_opposition_delta_deg_mean": _mean(r["gly_opposition_delta_deg"] for r in paired_rows),
        "gly_opposition_delta_deg_p90_abs": _pct((abs(r["gly_opposition_delta_deg"]) for r in paired_rows), 90),
    }


def _suggest_offsets(by_type: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    suggestions = {}
    for pair_type, rows in sorted(by_type.items()):
        max_frame_by_segment: dict[str, int] = {}
        for row in rows:
            seg = str(row["segment"])
            max_frame_by_segment[seg] = max(max_frame_by_segment.get(seg, 0), int(row["frame"]))
        late_rows = [
            row for row in rows
            if int(row["frame"]) >= 0.75 * max(1, max_frame_by_segment.get(str(row["segment"]), 0))
        ]
        # These are not template rotations yet. They are observed mean pair-level
        # deltas that indicate which starting orientation biases to test.
        suggestions[pair_type] = {
            "mean_propeller_delta_deg": _mean(r["propeller_delta_deg"] for r in rows),
            "mean_gly_opposition_delta_deg": _mean(r["gly_opposition_delta_deg"] for r in rows),
            "mean_normal_angle_abs_delta_deg": _mean(r["normal_angle_abs_delta_deg"] for r in rows),
            "late_mean_propeller_delta_deg": _mean(r["propeller_delta_deg"] for r in late_rows),
            "late_mean_gly_opposition_delta_deg": _mean(r["gly_opposition_delta_deg"] for r in late_rows),
            "late_mean_normal_angle_abs_delta_deg": _mean(r["normal_angle_abs_delta_deg"] for r in late_rows),
            "late_n_rows": len(late_rows),
            "interpretation": (
                "Use late_mean_* as the first candidate pair-level starting "
                "orientation bias. A positive propeller delta means sampled MD "
                "prefers a more positive signed normal twist around the C1'-C1' "
                "axis than the starting PDB."
            ),
        }
    return suggestions


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_plot(path: Path, rows: list[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    by_key: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_key[(str(row["segment"]), int(row["frame"]))].append(row)

    frame_records = []
    global_idx = 0
    last_segment = None
    segment_starts: dict[str, int] = {}
    for key in sorted(by_key, key=lambda k: (k[0], k[1])):
        segment, frame = key
        if segment != last_segment:
            segment_starts[segment] = global_idx
            last_segment = segment
        recs = [r for r in by_key[key] if r.get("paired")]
        if not recs:
            continue
        frame_records.append({
            "x": global_idx,
            "segment": segment,
            "frame": frame,
            "paired_fraction": len(recs) / len(by_key[key]),
            "propeller": _mean(r["propeller_delta_deg"] for r in recs),
            "gly": _mean(r["gly_opposition_delta_deg"] for r in recs),
            "normal": _mean(r["normal_angle_abs_delta_deg"] for r in recs),
            "c1": _mean(r["c1_dist_ang"] for r in recs),
        })
        global_idx += 1

    if not frame_records:
        return

    xs = [r["x"] for r in frame_records]
    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    fig.suptitle("Paired Base Orientation Drift", fontsize=14)

    axes[0].plot(xs, [r["propeller"] for r in frame_records], color="#1f77b4", lw=1.8)
    axes[0].axhline(0, color="#777", lw=0.8, alpha=0.7)
    axes[0].set_ylabel("Propeller delta (deg)")

    axes[1].plot(xs, [r["gly"] for r in frame_records], color="#d62728", lw=1.8)
    axes[1].axhline(0, color="#777", lw=0.8, alpha=0.7)
    axes[1].set_ylabel("Gly opposition delta (deg)")

    axes[2].plot(xs, [r["normal"] for r in frame_records], color="#2ca02c", lw=1.8)
    axes[2].axhline(0, color="#777", lw=0.8, alpha=0.7)
    axes[2].set_ylabel("Plane angle delta (deg)")

    axes[3].plot(xs, [r["paired_fraction"] * 100.0 for r in frame_records], color="#9467bd", lw=1.8)
    axes[3].set_ylabel("Paired (%)")
    axes[3].set_xlabel("Sampled frame order")
    axes[3].set_ylim(0, 105)

    for ax in axes:
        ax.grid(True, alpha=0.25)
        for segment, start in segment_starts.items():
            ax.axvline(start, color="#999", lw=0.7, alpha=0.35)

    ymax = axes[0].get_ylim()[1]
    for segment, start in segment_starts.items():
        label = segment.replace("_300K_NPT_", "\n").replace("6hb_84bp_", "")
        axes[0].text(start + 0.2, ymax, label, fontsize=7, va="top", color="#444")

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, required=True, help="NAMD package directory containing PSF/PDB/output")
    ap.add_argument("--psf", type=Path, default=None)
    ap.add_argument("--pdb", type=Path, default=None)
    ap.add_argument("--segments", nargs="*", default=[], help="Segment names without .dcd. Defaults to all DCDs in manifest/output.")
    ap.add_argument("--stride", type=int, default=10, help="Sample every N frames.")
    ap.add_argument("--max-frames-per-segment", type=int, default=80)
    ap.add_argument("--paired-max-ang", type=float, default=C1_PAIRED_MAX_DEFAULT)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--summary-name", default="basepair_orientation_summary.json")
    ap.add_argument("--timeseries-name", default="basepair_orientation_timeseries.csv")
    ap.add_argument("--plot-name", default="basepair_orientation_plot.png")
    args = ap.parse_args()

    summary = analyze(args)
    print(f"Analysed {summary['n_reference_pairs']} reference pairs across {len(summary['segments'])} segment(s).")
    print(f"Summary:    {summary['outputs']['summary_json']}")
    print(f"Timeseries: {summary['outputs']['timeseries_csv']}")
    if summary["outputs"].get("plot_png"):
        print(f"Plot:       {summary['outputs']['plot_png']}")
    print("\nPair-type suggested offsets:")
    for pair_type, rec in summary["suggested_starting_offsets"].items():
        print(
            f"  {pair_type}: late propeller {rec['late_mean_propeller_delta_deg']:+.2f} deg, "
            f"late gly-opposition {rec['late_mean_gly_opposition_delta_deg']:+.2f} deg, "
            f"late normal {rec['late_mean_normal_angle_abs_delta_deg']:+.2f} deg"
        )


if __name__ == "__main__":
    main()

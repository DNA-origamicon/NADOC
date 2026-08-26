#!/usr/bin/env python3
"""Extract and plot 2hb_1xT extra-base slab orientation phase spaces.

The angular observable is derived from the same basis permutation used by the Full
representation's crossoverExtraSlabQuaternion():

    slab basis = [template-y, template-z, template-x]

The directed slab-face normal is therefore template-z (mesh local +Y).  It is expressed
in a per-frame two-helix frame before conversion to spherical angles:

    e_ih   = helix(min id) -> helix(max id)
    e_ax   = increasing-bp helix axis, Gram-Schmidt orthogonal to e_ih
    e_perp = e_ih x e_ax
    azimuth = atan2(n . e_perp, n . e_ih)
    polar   = acos(n . e_ax)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"
PLOTS = HERE / "plots"
CONFIG = HERE / "inventory.json"
EXTRACTOR = ROOT / "experiments/exp46_xb_placement/xb_observables.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _structural_design_sha256(path: Path) -> str:
    """Hash model-normalized scientific content, excluding document metadata.

    The current .nadoc has newer default-valued UI fields and file-identity metadata
    than the archived design.json snapshots.  Model normalization makes those schema
    additions explicit before excluding metadata, so structural identity is not
    confused with byte identity.
    """
    from backend.core.models import Design

    design = Design.model_validate_json(path.read_text()).model_dump(
        mode="json", exclude_defaults=True, exclude_none=True,
    )
    design.pop("metadata", None)
    payload = json.dumps(design, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _config() -> dict:
    return json.loads(CONFIG.read_text())


def _package(source: dict) -> Path:
    job = Path(source["job"])
    meta = json.loads((job / "job.json").read_text())
    return job / meta["package_subdir"]


def _dcd(source: dict) -> Path:
    return _package(source) / "output" / source["dcd"]


def _metrics_path(source: dict) -> Path:
    return DATA / f"{source['id']}__metrics.json"


def scan_archive(config: dict) -> dict:
    """Inventory every archived NAMD package associated with this exact design."""
    archive = Path("/media/jojo/Archive/NADOC_archive")
    canonical = ROOT / config["canonical_design"]
    canonical_hash = _sha256(canonical)
    canonical_structural_hash = _structural_design_sha256(canonical)
    rows = []
    for package in sorted(archive.glob("*/package/2hb_1xT_namd_solvated")):
        job = package.parents[1]
        design = job / "design.json"
        meta_path = job / "job.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        dcds = []
        for path in sorted((package / "output").glob("*.dcd")):
            name = path.name
            free = "production" in name and "k0" in name and "ENM" not in name
            dcds.append({"name": name, "bytes": path.stat().st_size,
                         "free_production": free})
        rows.append({
            "job_id": job.name,
            "status": meta.get("status"),
            "parent_job_id": meta.get("parent_job_id"),
            "design_sha256": _sha256(design) if design.exists() else None,
            "structural_design_sha256": (
                _structural_design_sha256(design) if design.exists() else None
            ),
            "matches_canonical_design": (
                _structural_design_sha256(design) == canonical_structural_hash
                if design.exists() else None
            ),
            "design_snapshot_available": design.exists(),
            "package": str(package),
            "dcds": dcds,
        })
    selected = {Path(source["job"]).name for source in config["sources"]}
    out = {
        "schema": "nadoc.exp55.archive_scan.v1",
        "canonical_design": str(canonical),
        "canonical_design_sha256": canonical_hash,
        "canonical_structural_design_sha256": canonical_structural_hash,
        "selected_jobs": sorted(selected),
        "jobs": rows,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / "archive_inventory.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(path)
    return out


def extract(config: dict, force: bool = False) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for source in config["sources"]:
        dcd = _dcd(source)
        if not dcd.exists():
            raise FileNotFoundError(dcd)
        output = _metrics_path(source)
        signature = output.with_suffix(".signature.json")
        sig = {
            "dcd": str(dcd), "bytes": dcd.stat().st_size,
            "mtime_ns": dcd.stat().st_mtime_ns, "stride": source["stride"],
            "extractor_sha256": _sha256(EXTRACTOR),
        }
        if (not force and output.exists() and signature.exists()
                and json.loads(signature.read_text()) == sig):
            print(output, "cached")
            continue
        command = [
            sys.executable, str(EXTRACTOR), "--job", source["job"],
            "--dcd", str(dcd), "--stride", str(source["stride"]),
            "--out", str(output),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        signature.write_text(json.dumps(sig, indent=2) + "\n")


def _valid_sample(sample: dict, paired: float, cfg: dict) -> tuple[bool, list[str]]:
    checks = (
        (paired >= cfg["global_paired_min"], "global_pairing"),
        (cfg["local_bp_min_A"] <= sample.get("bp_src", math.nan)
         <= cfg["local_bp_max_A"], "source_pairing"),
        (cfg["local_bp_min_A"] <= sample.get("bp_dst", math.nan)
         <= cfg["local_bp_max_A"], "destination_pairing"),
        (cfg["bond_min_A"] <= sample.get("bond_src", math.nan)
         <= cfg["bond_max_A"], "source_bond"),
        (cfg["bond_min_A"] <= sample.get("bond_dst", math.nan)
         <= cfg["bond_max_A"], "destination_bond"),
        (sample.get("pose_rmsd", math.inf) <= cfg["pose_rmsd_max_A"], "pose_fit"),
    )
    reasons = [label for passed, label in checks if not passed]
    return not reasons, reasons


def _stable_mask(valid: list[bool], minimum: int) -> list[bool]:
    stable = [False] * len(valid)
    start = None
    for index, good in enumerate(valid + [False]):
        if good and start is None:
            start = index
        elif not good and start is not None:
            if index - start >= minimum:
                stable[start:index] = [True] * (index - start)
            start = None
    return stable


CSV_FIELDS = (
    "source", "replica", "sample", "frame", "time_ns", "crossover_id",
    "base_index", "bp", "valid", "stable", "failure_reasons", "paired_fraction",
    "slab_face_azimuth_deg", "slab_face_polar_deg", "slab_face_ih", "slab_face_ax",
    "slab_face_perp", "slab_long_azimuth_deg", "slab_long_polar_deg",
    "position_azimuth_deg", "position_polar_deg", "position_radius_A", "pose_rmsd_A",
)


def compile_samples(config: dict) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    failure_counts: Counter = Counter()
    for source in config["sources"]:
        data = json.loads(_metrics_path(source).read_text())
        times_ps = data.get("times_ps")
        if times_ps is None:
            raise ValueError(f"{source['id']} metrics lack times_ps; rerun extraction")
        for insert in data["inserts"]:
            samples = insert["samples"]
            if len(samples) != len(data["frames"]):
                raise ValueError(f"{source['id']} {insert['crossover_id']}: sample mismatch")
            decisions = [
                _valid_sample(sample, data["paired_fraction"][i], config["filters"])
                for i, sample in enumerate(samples)
            ]
            stable = _stable_mask(
                [decision[0] for decision in decisions],
                int(config["filters"]["min_window_samples"]),
            )
            bp = int(insert["src"][1])
            base_index = "bp13" if bp == 13 else "bp14" if bp == 14 else f"bp{bp}"
            for i, sample in enumerate(samples):
                if "slab_face_azimuth_deg" not in sample:
                    raise ValueError(
                        f"{source['id']} metrics lack slab fields; rerun extraction"
                    )
                reasons = decisions[i][1]
                failure_counts.update(reasons)
                rows.append({
                    "source": source["id"], "replica": source["replica"],
                    "sample": i, "frame": data["frames"][i],
                    "time_ns": times_ps[i] / 1000.0 + source["time_offset_ns"],
                    "crossover_id": insert["crossover_id"], "base_index": base_index,
                    "bp": bp, "valid": decisions[i][0], "stable": stable[i],
                    "failure_reasons": ";".join(reasons),
                    "paired_fraction": data["paired_fraction"][i],
                    "slab_face_azimuth_deg": sample["slab_face_azimuth_deg"],
                    "slab_face_polar_deg": sample["slab_face_polar_deg"],
                    "slab_face_ih": sample["slab_face_ih"],
                    "slab_face_ax": sample["slab_face_ax"],
                    "slab_face_perp": sample["slab_face_perp"],
                    "slab_long_azimuth_deg": sample["slab_long_azimuth_deg"],
                    "slab_long_polar_deg": sample["slab_long_polar_deg"],
                    "position_azimuth_deg": sample["position_azimuth_deg"],
                    "position_polar_deg": sample["position_polar_deg"],
                    "position_radius_A": sample["position_radius_A"],
                    "pose_rmsd_A": sample["pose_rmsd"],
                })
    with (DATA / "orientation_samples.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = _summarize(rows)
    summary["filters"] = config["filters"]
    summary["failure_counts"] = dict(sorted(failure_counts.items()))
    (DATA / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(DATA / "orientation_samples.csv")
    print(DATA / "summary.json")
    return rows, summary


def _direction_summary(group: list[dict]) -> dict:
    vectors = np.asarray([
        [row["slab_face_ih"], row["slab_face_ax"], row["slab_face_perp"]]
        for row in group
    ])
    mean = vectors.mean(axis=0)
    resultant = float(np.linalg.norm(mean))
    direction = mean / resultant if resultant > 1e-12 else np.full(3, np.nan)
    return {
        "n": len(group),
        "mean_vector_ih_ax_perp": mean.tolist(),
        "mean_direction_ih_ax_perp": direction.tolist(),
        "mean_azimuth_deg": float(np.degrees(np.arctan2(direction[2], direction[0]))),
        "mean_polar_deg": float(np.degrees(np.arccos(np.clip(direction[1], -1, 1)))),
        "resultant_length": resultant,
        "position_radius_A_mean": float(np.mean([r["position_radius_A"] for r in group])),
        "position_radius_A_sd": float(np.std([r["position_radius_A"] for r in group])),
    }


def _summarize(rows: list[dict]) -> dict:
    stable = [row for row in rows if row["stable"]]
    by_replica_base = defaultdict(list)
    by_base = defaultdict(list)
    for row in stable:
        by_replica_base[(row["replica"], row["base_index"])].append(row)
        by_base[row["base_index"]].append(row)
    by_source_base = defaultdict(list)
    for row in rows:
        by_source_base[(row["source"], row["base_index"])].append(row)

    source_groups = {}
    for (source, base), group in sorted(by_source_base.items()):
        ordered = sorted(group, key=lambda row: row["sample"])
        windows, start = [], None
        for index, row in enumerate(ordered + [None]):
            is_stable = row is not None and row["stable"]
            if is_stable and start is None:
                start = index
            elif not is_stable and start is not None:
                window = ordered[start:index]
                windows.append({
                    "time_start_ns": window[0]["time_ns"],
                    "time_stop_ns": window[-1]["time_ns"],
                    "n_samples": len(window),
                })
                start = None
        source_groups[f"{source}_{base}"] = {
            "n": len(group),
            "n_valid": sum(row["valid"] for row in group),
            "n_stable": sum(row["stable"] for row in group),
            "stable_windows": windows,
        }

    stable_by_key = {
        (row["source"], row["sample"], row["base_index"]): row for row in stable
    }
    pair_angles = defaultdict(list)
    for source, sample in sorted({key[:2] for key in stable_by_key}):
        a = stable_by_key.get((source, sample, "bp13"))
        b = stable_by_key.get((source, sample, "bp14"))
        if a is None or b is None:
            continue
        va = np.asarray([a["slab_face_ih"], a["slab_face_ax"], a["slab_face_perp"]])
        vb = np.asarray([b["slab_face_ih"], b["slab_face_ax"], b["slab_face_perp"]])
        pair_angles[a["replica"]].append(float(np.degrees(
            np.arccos(np.clip(np.dot(va, vb), -1, 1))
        )))

    pair_summary = {}
    for replica, angles in sorted(pair_angles.items()):
        values = np.asarray(angles)
        pair_summary[f"replica_{replica}"] = {
            "n": len(values), "mean_deg": float(values.mean()),
            "sd_deg": float(values.std()), "median_deg": float(np.median(values)),
            "p05_deg": float(np.percentile(values, 5)),
            "p95_deg": float(np.percentile(values, 95)),
        }
    return {
        "schema": "nadoc.exp55.summary.v1",
        "n_rows": len(rows), "n_stable": len(stable),
        "groups": {
            f"replica_{replica}_{base}": _direction_summary(group)
            for (replica, base), group in sorted(by_replica_base.items())
        },
        "pooled_by_base": {
            base: _direction_summary(group) for base, group in sorted(by_base.items())
        },
        "source_quality": source_groups,
        "paired_face_normal_separation": pair_summary,
    }


def _plot_phase_grid(rows: list[dict], x_key: str, y_key: str, stem: str,
                     x_label: str, y_label: str) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    stable = [row for row in rows if row["stable"]]
    replicas, bases = ("A", "B"), ("bp13", "bp14")
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 8.0), sharex=True, sharey=True,
                             constrained_layout=True)
    for row_index, replica in enumerate(replicas):
        for col_index, base in enumerate(bases):
            ax = axes[row_index, col_index]
            group = [r for r in stable if r["replica"] == replica
                     and r["base_index"] == base]
            x = np.asarray([r[x_key] for r in group])
            y = np.asarray([r[y_key] for r in group])
            if len(group):
                ax.hexbin(x, y, gridsize=(45, 30), extent=(-180, 180, 0, 180),
                          mincnt=1, cmap="viridis", norm=LogNorm())
            ax.set_title(f"Replica {replica}, insert {base[2:]} (n={len(group):,})")
            ax.set_xlim(-180, 180)
            ax.set_ylim(0, 180)
            ax.set_xticks([-180, -90, 0, 90, 180])
            ax.set_yticks([0, 45, 90, 135, 180])
            ax.grid(alpha=0.16, linewidth=0.6)
    fig.supxlabel(x_label)
    fig.supylabel(y_label)
    fig.suptitle(stem.replace("_", " ").title() + " — stable, quality-filtered frames")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOTS / f"{stem}.{suffix}", dpi=300 if suffix == "png" else None)
    plt.close(fig)


def _plot_pair_coupling(rows: list[dict]) -> None:
    import matplotlib.pyplot as plt

    stable = [row for row in rows if row["stable"]]
    keyed = {(r["source"], r["sample"], r["base_index"]): r for r in stable}
    pairs = []
    for source, sample, _base in sorted({key[:2] + ("",) for key in keyed}):
        a = keyed.get((source, sample, "bp13"))
        b = keyed.get((source, sample, "bp14"))
        if a is None or b is None:
            continue
        va = np.asarray([a["slab_face_ih"], a["slab_face_ax"], a["slab_face_perp"]])
        vb = np.asarray([b["slab_face_ih"], b["slab_face_ax"], b["slab_face_perp"]])
        angle = float(np.degrees(np.arccos(np.clip(np.dot(va, vb), -1, 1))))
        pairs.append((a["replica"], a["time_ns"], angle))
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.0), constrained_layout=True)
    colors = {"A": "#31688e", "B": "#35b779"}
    for replica in ("A", "B"):
        group = [p for p in pairs if p[0] == replica]
        axes[0].scatter([p[1] for p in group], [p[2] for p in group], s=5,
                        alpha=0.35, color=colors[replica], label=f"Replica {replica}")
        axes[1].hist([p[2] for p in group], bins=np.linspace(0, 180, 46), histtype="step",
                     linewidth=1.8, density=True, color=colors[replica],
                     label=f"Replica {replica} (n={len(group):,})")
    axes[0].set(xlabel="trajectory time (ns)", ylabel="directed face-normal separation (deg)",
                ylim=(0, 180))
    axes[1].set(xlabel="directed face-normal separation (deg)", ylabel="density", xlim=(0, 180))
    for ax in axes:
        ax.grid(alpha=0.16, linewidth=0.6)
        ax.legend(frameon=False)
    fig.suptitle("Coupled orientation of the two reciprocal extra-base slabs")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOTS / f"slab_orientation_pair_coupling.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)


def plot(rows: list[dict]) -> None:
    PLOTS.mkdir(parents=True, exist_ok=True)
    _plot_phase_grid(
        rows, "slab_face_azimuth_deg", "slab_face_polar_deg",
        "slab_orientation_phase_space",
        "azimuth around helix axis from inter-helix axis (deg)",
        "polar angle from +helix axis (deg)",
    )
    _plot_phase_grid(
        rows, "position_azimuth_deg", "position_polar_deg",
        "c1_position_phase_space",
        "C1′ azimuth around helix axis from inter-helix axis (deg)",
        "C1′ polar angle from +helix axis (deg)",
    )
    _plot_pair_coupling(rows)
    print(PLOTS)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="all",
                        choices=("inventory", "extract", "compile", "plot", "all"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    config = _config()
    if args.command in ("inventory", "all"):
        scan_archive(config)
    if args.command in ("extract", "all"):
        extract(config, force=args.force)
    rows = None
    if args.command in ("compile", "all"):
        rows, _summary = compile_samples(config)
    if args.command in ("plot", "all"):
        if rows is None:
            with (DATA / "orientation_samples.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            numeric = set(CSV_FIELDS) - {
                "source", "replica", "crossover_id", "base_index", "failure_reasons",
                "valid", "stable",
            }
            for row in rows:
                row["valid"] = row["valid"] == "True"
                row["stable"] = row["stable"] == "True"
                for key in numeric:
                    row[key] = float(row[key])
        plot(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

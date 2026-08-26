#!/usr/bin/env python3
"""Build crossover-weighted slab-orientation densities for archived 24hb_1xT.

This uses the exp53 metric cache rather than rereading the 181 GB DCD.  The cache stores
both the template rotation in the builder chord frame and coordinates of five landmarks
in that frame and the fixed hop frame.  Those paired coordinates recover the exact frame
rotation; comparison against exp55's direct 2hb extraction agrees within 5e-7 in vector
norm over every tested observation.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_DIR = HERE / "data"
PLOT_DIR = HERE / "plots"
METRICS = (
    ROOT / "experiments/exp53_extra_base_state_refinement/results/"
    "24hb_1xT__large-bundle-single-long__metrics.json"
)
DESIGN = Path("/media/jojo/Archive/NADOC_archive/6950d3b79138/design.json")
TWO_HELIX_SUMMARY = DATA_DIR / "summary.json"
FILTERS = {
    "global_paired_min": 0.90,
    "local_bp_min_A": 8.0,
    "local_bp_max_A": 13.0,
    "bond_min_A": 1.2,
    "bond_max_A": 2.2,
    "pose_rmsd_max_A": 1.5,
    "min_window_samples": 25,
}
PHI_EDGES = np.linspace(-180.0, 180.0, 73)
POLAR_EDGES = np.linspace(0.0, 180.0, 37)
LANDMARKS = ("c1", "base", "P", "C3'", "C5'")
GROUPS = ("all", "reciprocal_lower", "reciprocal_upper", "unpaired")


def _valid(sample: dict, paired: float) -> bool:
    return bool(
        paired >= FILTERS["global_paired_min"]
        and FILTERS["local_bp_min_A"] <= sample.get("bp_src", math.nan)
        <= FILTERS["local_bp_max_A"]
        and FILTERS["local_bp_min_A"] <= sample.get("bp_dst", math.nan)
        <= FILTERS["local_bp_max_A"]
        and FILTERS["bond_min_A"] <= sample.get("bond_src", math.nan)
        <= FILTERS["bond_max_A"]
        and FILTERS["bond_min_A"] <= sample.get("bond_dst", math.nan)
        <= FILTERS["bond_max_A"]
        and sample.get("pose_rmsd", math.inf) <= FILTERS["pose_rmsd_max_A"]
    )


def _stable_mask(valid: list[bool]) -> np.ndarray:
    result = np.zeros(len(valid), dtype=bool)
    start = None
    for index, good in enumerate(valid + [False]):
        if good and start is None:
            start = index
        elif not good and start is not None:
            if index - start >= FILTERS["min_window_samples"]:
                result[start:index] = True
            start = None
    return result


def _reconstruct_faces(samples: list[dict], source_helix: str,
                       helix_pair: tuple[str, str]) -> tuple[np.ndarray, np.ndarray]:
    """Return directed slab-face normals in G=(interhelix, axial, perpendicular)."""
    n = len(samples)
    builder = np.empty((n, 3, len(LANDMARKS)), dtype=float)
    hop = np.empty_like(builder)
    pose = np.empty((n, 3, 3), dtype=float)
    for row, sample in enumerate(samples):
        for column, tag in enumerate(LANDMARKS):
            builder[row, :, column] = [
                sample[f"t_{tag}"], sample[f"bow_{tag}"], sample[f"ax_{tag}"]
            ]
            hop[row, :, column] = [sample[f"h{i}_{tag}"] for i in (1, 2, 3)]
        pose[row] = np.asarray(sample["pose_M"], dtype=float).reshape(3, 3)

    # hop ~= Q @ builder. The overdetermined landmark solution is an exact rotation to
    # floating-point precision; batching avoids 172k small Python SVD calls.
    bt = np.swapaxes(builder, 1, 2)
    q = (hop @ bt) @ np.linalg.inv(builder @ bt)
    residual = np.sqrt(np.mean((hop - q @ builder) ** 2, axis=(1, 2)))

    lo, _hi = sorted(helix_pair)
    sign = 1.0 if source_helix == lo else -1.0
    hop_to_global = np.diag([sign, 1.0, sign])
    template_global = hop_to_global @ q @ pose
    faces = template_global[:, :, 2]  # template +Z = slab mesh +Y face normal
    faces /= np.linalg.norm(faces, axis=1)[:, None]
    return faces, residual


def _classify_inserts(inserts: list[dict], crossovers: dict[str, dict]) -> dict[str, str]:
    records = []
    for insert in inserts:
        xo = crossovers[insert["crossover_id"]]
        pair = tuple(sorted((xo["half_a"]["helix_id"], xo["half_b"]["helix_id"])))
        records.append({
            "id": insert["crossover_id"], "pair": pair,
            "bp": int(xo["half_a"]["index"]), "src": insert["src"][0],
        })
    classification = {record["id"]: "unpaired" for record in records}
    used = set()
    for record in records:
        if record["id"] in used:
            continue
        candidates = [
            other for other in records
            if other["id"] != record["id"] and other["id"] not in used
            and other["pair"] == record["pair"]
            and abs(other["bp"] - record["bp"]) == 1
            and other["src"] != record["src"]
        ]
        if len(candidates) != 1:
            continue
        other = candidates[0]
        lower, upper = sorted((record, other), key=lambda item: item["bp"])
        classification[lower["id"]] = "reciprocal_lower"
        classification[upper["id"]] = "reciprocal_upper"
        used.update((record["id"], other["id"]))
    return classification


def _angles(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    azimuth = np.degrees(np.arctan2(vectors[:, 2], vectors[:, 0]))
    polar = np.degrees(np.arccos(np.clip(vectors[:, 1], -1.0, 1.0)))
    return azimuth, polar


def _density_from_mass(mass: np.ndarray) -> np.ndarray:
    smoothed = gaussian_filter(mass, sigma=(1.25, 1.25), mode=("wrap", "reflect"))
    smoothed /= smoothed.sum()
    dphi = np.diff(np.radians(PHI_EDGES))[None, :]
    solid_angle = (
        np.cos(np.radians(POLAR_EDGES[:-1]))
        - np.cos(np.radians(POLAR_EDGES[1:]))
    )[:, None] * dphi
    return smoothed / solid_angle


def _bootstrap_density(site_mass: np.ndarray, indices: np.ndarray, rng: np.random.Generator,
                       n_bootstrap: int = 300) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    selected = site_mass[indices]
    estimate = _density_from_mass(selected.mean(axis=0))
    boot = np.empty((n_bootstrap,) + estimate.shape, dtype=np.float32)
    probability = np.full(len(selected), 1.0 / len(selected))
    for start in range(0, n_bootstrap, 20):
        stop = min(start + 20, n_bootstrap)
        counts = rng.multinomial(len(selected), probability, size=stop - start)
        masses = (counts @ selected.reshape(len(selected), -1)) / len(selected)
        for offset, mass in enumerate(masses):
            boot[start + offset] = _density_from_mass(mass.reshape(estimate.shape))
    return estimate, np.percentile(boot, 2.5, axis=0), np.percentile(boot, 97.5, axis=0)


def _mean_direction(vectors: np.ndarray) -> dict:
    mean = vectors.mean(axis=0)
    resultant = float(np.linalg.norm(mean))
    direction = mean / resultant
    azimuth, polar = _angles(direction[None, :])
    return {
        "mean_vector_ih_ax_perp": mean.tolist(),
        "mean_direction_ih_ax_perp": direction.tolist(),
        "mean_azimuth_deg": float(azimuth[0]), "mean_polar_deg": float(polar[0]),
        "resultant_length": resultant,
    }


def process() -> tuple[dict, dict[str, np.ndarray], list[dict]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"loading {METRICS} ({METRICS.stat().st_size / 1024**2:.1f} MiB)", flush=True)
    data = json.loads(METRICS.read_text())
    design = json.loads(DESIGN.read_text())
    crossovers = {xo["id"]: xo for xo in design["crossovers"]}
    classification = _classify_inserts(data["inserts"], crossovers)
    class_counts = dict(sorted(defaultdict(int, {
        group: sum(value == group for value in classification.values())
        for group in ("reciprocal_lower", "reciprocal_upper", "unpaired")
    }).items()))
    if class_counts != {"reciprocal_lower": 159, "reciprocal_upper": 159, "unpaired": 20}:
        raise ValueError(f"unexpected reciprocal classification: {class_counts}")

    n_sites = len(data["inserts"])
    site_mass = np.zeros((n_sites, len(POLAR_EDGES) - 1, len(PHI_EDGES) - 1), dtype=float)
    site_rows = []
    all_stable_vectors = []
    group_vectors: dict[str, list[np.ndarray]] = defaultdict(list)
    max_transform_residual = 0.0
    stable_total = 0
    sample_csv = DATA_DIR / "24hb_orientation_samples.csv.gz"
    fields = (
        "crossover_id", "site_class", "source_helix", "destination_helix", "bp",
        "sample", "frame", "time_ns", "azimuth_deg", "polar_deg", "face_ih",
        "face_ax", "face_perp", "site_equal_weight", "paired_fraction", "pose_rmsd_A",
    )
    with gzip.open(sample_csv, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for site_index, insert in enumerate(data["inserts"]):
            xo = crossovers[insert["crossover_id"]]
            helix_pair = (xo["half_a"]["helix_id"], xo["half_b"]["helix_id"])
            samples = insert["samples"]
            valid = [
                _valid(sample, data["paired_fraction"][i])
                for i, sample in enumerate(samples)
            ]
            stable = _stable_mask(valid)
            faces, residual = _reconstruct_faces(samples, insert["src"][0], helix_pair)
            max_transform_residual = max(max_transform_residual, float(residual.max()))
            kept = faces[stable]
            if not len(kept):
                raise ValueError(f"no stable samples for {insert['crossover_id']}")
            azimuth, polar = _angles(kept)
            mass, _, _ = np.histogram2d(polar, azimuth, bins=(POLAR_EDGES, PHI_EDGES))
            site_mass[site_index] = mass / mass.sum()
            label = classification[insert["crossover_id"]]
            group_vectors[label].append(kept)
            all_stable_vectors.append(kept)
            stable_total += len(kept)
            site_result = _mean_direction(kept)
            site_rows.append({
                "crossover_id": insert["crossover_id"], "site_class": label,
                "source_helix": insert["src"][0], "destination_helix": insert["dst"][0],
                "bp": int(xo["half_a"]["index"]), "n_samples": len(samples),
                "n_valid": int(sum(valid)), "n_stable": int(stable.sum()),
                "valid_fraction": float(np.mean(valid)), **site_result,
            })
            weight = 1.0 / int(stable.sum())
            kept_indices = np.flatnonzero(stable)
            for local, sample_index in enumerate(kept_indices):
                face = kept[local]
                writer.writerow({
                    "crossover_id": insert["crossover_id"], "site_class": label,
                    "source_helix": insert["src"][0],
                    "destination_helix": insert["dst"][0],
                    "bp": int(xo["half_a"]["index"]), "sample": int(sample_index),
                    "frame": int(data["frames"][sample_index]),
                    "time_ns": (int(data["frames"][sample_index]) + 1) * 0.020,
                    "azimuth_deg": float(azimuth[local]), "polar_deg": float(polar[local]),
                    "face_ih": float(face[0]), "face_ax": float(face[1]),
                    "face_perp": float(face[2]), "site_equal_weight": weight,
                    "paired_fraction": data["paired_fraction"][sample_index],
                    "pose_rmsd_A": samples[sample_index]["pose_rmsd"],
                })
            if (site_index + 1) % 25 == 0 or site_index + 1 == n_sites:
                print(f"processed {site_index + 1}/{n_sites} crossover inserts", flush=True)

    if max_transform_residual > 1e-5:
        raise ValueError(f"frame reconstruction residual too large: {max_transform_residual}")

    site_fields = (
        "crossover_id", "site_class", "source_helix", "destination_helix", "bp",
        "n_samples", "n_valid", "n_stable", "valid_fraction", "mean_azimuth_deg",
        "mean_polar_deg", "resultant_length", "mean_vector_ih_ax_perp",
        "mean_direction_ih_ax_perp",
    )
    with (DATA_DIR / "24hb_per_crossover_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=site_fields, lineterminator="\n")
        writer.writeheader()
        for row in site_rows:
            writer.writerow({**row,
                "mean_vector_ih_ax_perp": json.dumps(row["mean_vector_ih_ax_perp"]),
                "mean_direction_ih_ax_perp": json.dumps(row["mean_direction_ih_ax_perp"]),
            })

    indices_by_group = {
        "all": np.arange(n_sites),
        **{
            group: np.asarray([i for i, insert in enumerate(data["inserts"])
                               if classification[insert["crossover_id"]] == group])
            for group in ("reciprocal_lower", "reciprocal_upper", "unpaired")
        },
    }
    rng = np.random.default_rng(20260825)
    grids = {}
    density_summary = {}
    for group in GROUPS:
        estimate, low, high = _bootstrap_density(site_mass, indices_by_group[group], rng)
        grids[f"{group}_density_per_sr"] = estimate
        grids[f"{group}_ci95_low_per_sr"] = low
        grids[f"{group}_ci95_high_per_sr"] = high
        vectors = (np.concatenate(all_stable_vectors) if group == "all"
                   else np.concatenate(group_vectors[group]))
        # For the directional mean, give each crossover equal total weight.
        equal_site_mean = np.mean([
            np.asarray(row["mean_vector_ih_ax_perp"])
            for row in site_rows if group == "all" or row["site_class"] == group
        ], axis=0)
        direction = equal_site_mean / np.linalg.norm(equal_site_mean)
        mean_az, mean_pol = _angles(direction[None, :])
        peak = np.unravel_index(np.argmax(estimate), estimate.shape)
        site_subset = [
            row for row in site_rows if group == "all" or row["site_class"] == group
        ]
        site_resultants = np.asarray([row["resultant_length"] for row in site_subset])
        density_summary[group] = {
            "n_crossovers": int(len(indices_by_group[group])),
            "n_stable_observations": int(len(vectors)),
            "equal_crossover_mean_direction_ih_ax_perp": direction.tolist(),
            "equal_crossover_mean_azimuth_deg": float(mean_az[0]),
            "equal_crossover_mean_polar_deg": float(mean_pol[0]),
            "equal_crossover_resultant_length": float(np.linalg.norm(equal_site_mean)),
            "within_crossover_resultant_median": float(np.median(site_resultants)),
            "within_crossover_resultant_p05": float(np.percentile(site_resultants, 5)),
            "within_crossover_resultant_p95": float(np.percentile(site_resultants, 95)),
            "stable_samples_per_crossover_median": float(np.median([
                row["n_stable"] for row in site_subset
            ])),
            "density_peak_azimuth_deg": float(
                0.5 * (PHI_EDGES[peak[1]] + PHI_EDGES[peak[1] + 1])
            ),
            "density_peak_polar_deg": float(
                0.5 * (POLAR_EDGES[peak[0]] + POLAR_EDGES[peak[0] + 1])
            ),
            "peak_enrichment_over_isotropic": float(4 * np.pi * estimate[peak]),
        }

    np.savez_compressed(
        DATA_DIR / "24hb_density_grid.npz", phi_edges_deg=PHI_EDGES,
        polar_edges_deg=POLAR_EDGES, **grids,
    )
    lower_direction = np.asarray(
        density_summary["reciprocal_lower"]["equal_crossover_mean_direction_ih_ax_perp"]
    )
    upper_direction = np.asarray(
        density_summary["reciprocal_upper"]["equal_crossover_mean_direction_ih_ax_perp"]
    )
    directed_separation = float(np.degrees(np.arccos(np.clip(
        np.dot(lower_direction, upper_direction), -1, 1,
    ))))
    summary = {
        "schema": "nadoc.exp55.24hb_orientation_density.v1",
        "source_metrics": str(METRICS), "source_design": str(DESIGN),
        "n_crossovers": n_sites, "classification_counts": class_counts,
        "n_sampled_frames": len(data["frames"]), "n_stable_observations": stable_total,
        "mean_global_pairing": float(np.mean(data["paired_fraction"])),
        "minimum_global_pairing": float(np.min(data["paired_fraction"])),
        "max_frame_reconstruction_rms": max_transform_residual,
        "filters": FILTERS,
        "density_method": (
            "Each crossover contributes unit total mass; 5-degree spherical histogram, "
            "1.25-bin Gaussian smoothing, solid-angle correction, and 300-crossover "
            "bootstrap 95% intervals."
        ),
        "reciprocal_mean_directed_separation_deg": directed_separation,
        "reciprocal_mean_undirected_slab_separation_deg": min(
            directed_separation, 180.0 - directed_separation
        ),
        "groups": density_summary,
    }
    (DATA_DIR / "24hb_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(DATA_DIR / "24hb_orientation_samples.csv.gz")
    print(DATA_DIR / "24hb_per_crossover_summary.csv")
    print(DATA_DIR / "24hb_density_grid.npz")
    print(DATA_DIR / "24hb_summary.json")
    return summary, grids, site_rows


def plot(summary: dict, grids: dict[str, np.ndarray], site_rows: list[dict]) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    titles = {
        "all": "All inserts",
        "reciprocal_lower": "Reciprocal lower-bp side",
        "reciprocal_upper": "Reciprocal higher-bp side",
        "unpaired": "No adjacent reciprocal insert",
    }
    phi_centers = 0.5 * (PHI_EDGES[:-1] + PHI_EDGES[1:])
    polar_centers = 0.5 * (POLAR_EDGES[:-1] + POLAR_EDGES[1:])
    two_helix = json.loads(TWO_HELIX_SUMMARY.read_text())
    markers = {
        "reciprocal_lower": [
            (two_helix["groups"]["replica_A_bp13"], "A", "#ef8a62"),
            (two_helix["groups"]["replica_B_bp13"], "B", "#67a9cf"),
        ],
        "reciprocal_upper": [
            (two_helix["groups"]["replica_A_bp14"], "A", "#ef8a62"),
            (two_helix["groups"]["replica_B_bp14"], "B", "#67a9cf"),
        ],
    }
    enrichment = [4 * np.pi * grids[f"{group}_density_per_sr"] for group in GROUPS]
    vmax = max(float(np.percentile(grid, 99.5)) for grid in enrichment)
    norm = LogNorm(vmin=0.2, vmax=max(10.0, vmax), clip=True)
    density_cmap = plt.get_cmap("magma").copy()
    density_cmap.set_under(density_cmap(0.0))
    density_cmap.set_bad(density_cmap(0.0))
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 8.3), sharex=True, sharey=True,
                             constrained_layout=True)
    mesh = None
    for ax, group, values in zip(axes.flat, GROUPS, enrichment):
        display_values = np.maximum(values, norm.vmin)
        mesh = ax.pcolormesh(PHI_EDGES, POLAR_EDGES, display_values, shading="auto",
                             cmap=density_cmap, norm=norm)
        low_enrichment = 4 * np.pi * grids[f"{group}_ci95_low_per_sr"]
        if np.nanmin(low_enrichment) <= 1 <= np.nanmax(low_enrichment):
            ax.contour(phi_centers, polar_centers, low_enrichment,
                       levels=[1.0], colors="white", linewidths=0.9, linestyles="--")
        points = [row for row in site_rows if group == "all" or row["site_class"] == group]
        ax.scatter([row["mean_azimuth_deg"] for row in points],
                   [row["mean_polar_deg"] for row in points], s=5, c="cyan",
                   alpha=0.24, linewidths=0)
        for marker, label, color in markers.get(group, []):
            ax.scatter(marker["mean_azimuth_deg"], marker["mean_polar_deg"], marker="*",
                       s=130, c=color, edgecolors="white", linewidths=0.7,
                       label=f"2hb replica {label}", zorder=5)
        if group in markers:
            ax.legend(frameon=True, fontsize=8, loc="upper right", facecolor="white",
                      framealpha=0.86, edgecolor="none")
        count = summary["groups"][group]["n_crossovers"]
        ax.set_title(f"{titles[group]} (sites={count})")
        ax.set_xlim(-180, 180); ax.set_ylim(180, 0)
        ax.set_xticks([-180, -90, 0, 90, 180]); ax.set_yticks([0, 45, 90, 135, 180])
        ax.grid(color="white", alpha=0.14, linewidth=0.5)
    fig.supxlabel("slab-face azimuth around helix axis from inter-helix axis (deg)")
    fig.supylabel("polar angle from +helix axis (deg)")
    fig.suptitle("24hb_1xT extra-base slab orientation density\n"
                 "equal crossover weighting; cyan = per-crossover mean")
    cbar = fig.colorbar(mesh, ax=axes, fraction=0.025, pad=0.02)
    cbar.set_label("density enrichment over isotropic")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOT_DIR / f"24hb_orientation_density.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)

    # Independent-unit view: one mean direction per crossover, colored by within-site R.
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.3), sharex=True, sharey=True,
                             constrained_layout=True)
    scatter = None
    for ax, group in zip(axes, ("reciprocal_lower", "reciprocal_upper")):
        points = [row for row in site_rows if row["site_class"] == group]
        scatter = ax.scatter(
            [row["mean_azimuth_deg"] for row in points],
            [row["mean_polar_deg"] for row in points],
            c=[row["resultant_length"] for row in points], s=18,
            cmap="viridis", vmin=0, vmax=1, alpha=0.82, linewidths=0,
        )
        ax.set_title(f"{titles[group]} (n={len(points)})")
        ax.set_xlim(-180, 180); ax.set_ylim(180, 0)
        ax.set_xticks([-180, -90, 0, 90, 180]); ax.set_yticks([0, 45, 90, 135, 180])
        ax.grid(alpha=0.18, linewidth=0.6)
    fig.supxlabel("per-crossover mean azimuth (deg)")
    fig.supylabel("per-crossover mean polar angle (deg)")
    fig.suptitle("24hb_1xT orientation heterogeneity across reciprocal crossovers")
    cbar = fig.colorbar(scatter, ax=axes, fraction=0.035, pad=0.02)
    cbar.set_label("within-crossover resultant length R")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOT_DIR / f"24hb_per_crossover_means.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)
    print(PLOT_DIR)


def main() -> int:
    summary, grids, site_rows = process()
    plot(summary, grids, site_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

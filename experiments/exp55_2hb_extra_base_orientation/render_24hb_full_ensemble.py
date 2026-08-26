#!/usr/bin/env python3
"""Render traversal-aligned 24hb phase densities from every stable observation.

Every frame contributes to its crossover's spherical histogram.  Each crossover histogram
is normalized to unit mass before pooling, retaining the full ensemble while preventing a
site with more valid frames from receiving more statistical weight.
"""
from __future__ import annotations

import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PLOTS = HERE / "plots"
SAMPLES = DATA / "24hb_orientation_samples.csv.gz"
MEMBERSHIP = DATA / "24hb_subpopulation_membership.csv"
TESTS = DATA / "24hb_sequence_association_tests.csv"
PHI_EDGES = np.linspace(-180.0, 180.0, 73)
POLAR_EDGES = np.linspace(0.0, 180.0, 37)
BASES = "ACGT"
SIDES = ("reciprocal_lower", "reciprocal_upper")


def _density(masses: list[np.ndarray]) -> np.ndarray:
    mean_mass = np.mean(masses, axis=0)
    # Array axes are (polar, azimuth): reflect at the poles, wrap at +/-180 azimuth.
    smoothed = gaussian_filter(mean_mass, sigma=(1.25, 1.25), mode=("reflect", "wrap"))
    smoothed /= smoothed.sum()
    solid_angle = (
        np.cos(np.radians(POLAR_EDGES[:-1]))
        - np.cos(np.radians(POLAR_EDGES[1:]))
    )[:, None] * np.diff(np.radians(PHI_EDGES))[None, :]
    return smoothed / solid_angle


def _bootstrap_low(masses: list[np.ndarray], *, seed: int, n_bootstrap: int = 300) -> np.ndarray:
    site_mass = np.asarray(masses)
    rng = np.random.default_rng(seed)
    boot = np.empty((n_bootstrap, len(POLAR_EDGES) - 1, len(PHI_EDGES) - 1), dtype=np.float32)
    probability = np.full(len(site_mass), 1.0 / len(site_mass))
    flat = site_mass.reshape(len(site_mass), -1)
    for start in range(0, n_bootstrap, 20):
        stop = min(start + 20, n_bootstrap)
        counts = rng.multinomial(len(site_mass), probability, size=stop - start)
        for offset, mass in enumerate((counts @ flat) / len(site_mass)):
            boot[start + offset] = _density([mass.reshape(site_mass.shape[1:])])
    return np.percentile(boot, 2.5, axis=0)


def _load_membership() -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    with MEMBERSHIP.open(newline="") as handle:
        members = {row["crossover_id"]: row for row in csv.DictReader(handle)}
    with TESTS.open(newline="") as handle:
        tests = {(row["side"], row["variable"]): row for row in csv.DictReader(handle)}
    return members, tests


def _load_full_ensemble(members: dict[str, dict]) -> tuple[dict[str, dict], int]:
    sites: dict[str, dict] = {}
    output_path = DATA / "24hb_hop_orientation_samples.csv.gz"
    output_fields = (
        "crossover_id", "site_class", "source_helix", "destination_helix", "bp",
        "sample", "frame", "time_ns", "hop_azimuth_deg", "hop_polar_deg",
        "hop_face_source_to_destination", "hop_face_ax", "hop_face_perp",
        "site_equal_weight", "source_base", "destination_base",
        "hop_candidate_cluster", "paired_fraction", "pose_rmsd_A",
    )
    total = 0
    with gzip.open(SAMPLES, "rt", newline="") as source, gzip.open(
        output_path, "wt", newline=""
    ) as destination:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(destination, fieldnames=output_fields, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            crossover_id = row["crossover_id"]
            sign = 1.0 if row["source_helix"] == min(
                row["source_helix"], row["destination_helix"]
            ) else -1.0
            vector = np.asarray([
                sign * float(row["face_ih"]),
                float(row["face_ax"]),
                sign * float(row["face_perp"]),
            ])
            azimuth = float(np.degrees(np.arctan2(vector[2], vector[0])))
            polar = float(np.degrees(np.arccos(np.clip(vector[1], -1.0, 1.0))))
            phi_bin = int(np.clip(np.searchsorted(PHI_EDGES, azimuth, side="right") - 1, 0, 71))
            polar_bin = int(np.clip(np.searchsorted(POLAR_EDGES, polar, side="right") - 1, 0, 35))
            if crossover_id not in sites:
                member = members.get(crossover_id, {})
                sites[crossover_id] = {
                    "site_class": row["site_class"],
                    "source_base": member.get("source_base", ""),
                    "destination_base": member.get("destination_base", ""),
                    "cluster": member.get("hop_candidate_cluster", ""),
                    "mass": np.zeros((36, 72), dtype=float),
                    "n_observations": 0,
                    "vector_sum": np.zeros(3, dtype=float),
                }
            site = sites[crossover_id]
            site["mass"][polar_bin, phi_bin] += 1.0
            site["n_observations"] += 1
            site["vector_sum"] += vector
            total += 1
            writer.writerow({
                "crossover_id": crossover_id,
                "site_class": row["site_class"],
                "source_helix": row["source_helix"],
                "destination_helix": row["destination_helix"],
                "bp": row["bp"], "sample": row["sample"], "frame": row["frame"],
                "time_ns": row["time_ns"], "hop_azimuth_deg": azimuth,
                "hop_polar_deg": polar,
                "hop_face_source_to_destination": vector[0], "hop_face_ax": vector[1],
                "hop_face_perp": vector[2], "site_equal_weight": row["site_equal_weight"],
                "source_base": site["source_base"],
                "destination_base": site["destination_base"],
                "hop_candidate_cluster": site["cluster"],
                "paired_fraction": row["paired_fraction"], "pose_rmsd_A": row["pose_rmsd_A"],
            })
    for site in sites.values():
        site["mass"] /= site["mass"].sum()
        site["mean_vector"] = site["vector_sum"] / site["n_observations"]
    return sites, total


def _select(sites: dict[str, dict], predicate) -> list[dict]:
    return [site for site in sites.values() if predicate(site)]


def _grid(sites: list[dict]) -> np.ndarray:
    if not sites:
        raise ValueError("empty phase-density selection")
    return 4.0 * np.pi * _density([site["mass"] for site in sites])


def _style_axis(ax) -> None:
    ax.set_xlim(-180, 180)
    ax.set_ylim(180, 0)
    ax.set_xticks([-180, -90, 0, 90, 180])
    ax.set_yticks([0, 45, 90, 135, 180])
    ax.grid(color="white", alpha=0.14, linewidth=0.5)


def _draw_density(ax, values: np.ndarray, norm, cmap):
    return ax.pcolormesh(
        PHI_EDGES, POLAR_EDGES, np.maximum(values, norm.vmin),
        shading="auto", norm=norm, cmap=cmap,
    )


def _plot_main(sites: dict[str, dict], summary: dict) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    groups = (
        ("All inserts", lambda site: True),
        ("Reciprocal lower-bp", lambda site: site["site_class"] == "reciprocal_lower"),
        ("Reciprocal higher-bp", lambda site: site["site_class"] == "reciprocal_upper"),
        ("No adjacent reciprocal", lambda site: site["site_class"] == "unpaired"),
    )
    selections = [_select(sites, predicate) for _, predicate in groups]
    grids = [_grid(selected) for selected in selections]
    vmax = max(float(np.percentile(grid, 99.5)) for grid in grids)
    norm = LogNorm(vmin=0.2, vmax=max(10.0, vmax), clip=True)
    cmap = plt.get_cmap("magma").copy()
    cmap.set_under(cmap(0.0))
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 8.3), sharex=True, sharey=True,
                             constrained_layout=True)
    mesh = None
    grid_export = {"phi_edges_deg": PHI_EDGES, "polar_edges_deg": POLAR_EDGES}
    for index, (ax, (title, _), selected, values) in enumerate(
        zip(axes.flat, groups, selections, grids)
    ):
        mesh = _draw_density(ax, values, norm, cmap)
        observations = sum(site["n_observations"] for site in selected)
        ax.set_title(f"{title}\n{len(selected)} sites; {observations:,} observations")
        _style_axis(ax)
        key = ("all", "reciprocal_lower", "reciprocal_upper", "unpaired")[index]
        grid_export[f"{key}_enrichment_over_isotropic"] = values
        peak = np.unravel_index(np.argmax(values), values.shape)
        summary["groups"][key] = {
            "n_crossovers": len(selected), "n_stable_observations": observations,
            "density_peak_azimuth_deg": float((PHI_EDGES[peak[1]] + PHI_EDGES[peak[1] + 1]) / 2),
            "density_peak_polar_deg": float((POLAR_EDGES[peak[0]] + POLAR_EDGES[peak[0] + 1]) / 2),
            "peak_enrichment_over_isotropic": float(values[peak]),
        }
        mean_vector = np.mean([site["mean_vector"] for site in selected], axis=0)
        resultant = float(np.linalg.norm(mean_vector))
        direction = mean_vector / resultant
        summary["groups"][key].update({
            "equal_crossover_mean_direction_hop_ax_perp": direction.tolist(),
            "equal_crossover_mean_azimuth_deg": float(np.degrees(np.arctan2(direction[2], direction[0]))),
            "equal_crossover_mean_polar_deg": float(np.degrees(np.arccos(np.clip(direction[1], -1, 1)))),
            "equal_crossover_resultant_length": resultant,
        })
    fig.supxlabel("slab-face azimuth from chemical 3′ source→5′ destination axis (deg)")
    fig.supylabel("polar angle from +helix axis (deg)")
    fig.suptitle("24hb_1xT full-ensemble extra-base orientation density\n"
                 "all stable frames; equal crossover weighting")
    cbar = fig.colorbar(mesh, ax=axes, fraction=0.025, pad=0.02)
    cbar.set_label("density enrichment over isotropic")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOTS / f"24hb_orientation_density.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)
    np.savez_compressed(DATA / "24hb_hop_density_grid.npz", **grid_export)
    lower = np.asarray(summary["groups"]["reciprocal_lower"]["equal_crossover_mean_direction_hop_ax_perp"])
    upper = np.asarray(summary["groups"]["reciprocal_upper"]["equal_crossover_mean_direction_hop_ax_perp"])
    summary["reciprocal_mean_directed_separation_deg"] = float(np.degrees(np.arccos(
        np.clip(np.dot(lower, upper), -1.0, 1.0)
    )))

    # Replace the former presentation scatter with a full-ensemble two-side density view.
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.3), sharex=True, sharey=True,
                             constrained_layout=True)
    for ax, selected, values, title in zip(axes, selections[1:3], grids[1:3],
                                           ("Lower-bp", "Higher-bp")):
        mesh = _draw_density(ax, values, norm, cmap)
        ax.set_title(f"{title}: {len(selected)} sites; "
                     f"{sum(site['n_observations'] for site in selected):,} observations")
        _style_axis(ax)
    fig.supxlabel("slab-face azimuth from chemical 3′ source→5′ destination axis (deg)")
    fig.supylabel("polar angle from +helix axis (deg)")
    fig.suptitle("24hb_1xT reciprocal-side full-ensemble densities")
    cbar = fig.colorbar(mesh, ax=axes, fraction=0.035, pad=0.02)
    cbar.set_label("density enrichment over isotropic")
    for suffix in ("png", "pdf"):
        for basename in ("24hb_reciprocal_full_ensemble_density", "24hb_per_crossover_means"):
            fig.savefig(PLOTS / f"{basename}.{suffix}",
                        dpi=300 if suffix == "png" else None)
    plt.close(fig)


def _plot_subpopulations(sites: dict[str, dict], subpopulation_summary: dict) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    panels = []
    for side in SIDES:
        for cluster in ("0", "1"):
            selected = _select(
                sites, lambda site, s=side, c=cluster:
                site["site_class"] == s and site["cluster"] == c,
            )
            panels.append((side, cluster, selected, _grid(selected)))
    vmax = max(float(np.percentile(panel[3], 99.5)) for panel in panels)
    norm = LogNorm(vmin=0.2, vmax=max(10.0, vmax), clip=True)
    cmap = plt.get_cmap("magma").copy()
    cmap.set_under(cmap(0.0))
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.2), sharex=True, sharey=True,
                             constrained_layout=True)
    mesh = None
    for ax, (side, cluster, selected, values) in zip(axes.flat, panels):
        mesh = _draw_density(ax, values, norm, cmap)
        detail = subpopulation_summary["sides"][side]["hop_candidate_k2"]
        side_title = "Lower-bp" if side.endswith("lower") else "Higher-bp"
        observations = sum(site["n_observations"] for site in selected)
        ax.set_title(
            f"{side_title}, candidate component {int(cluster) + 1}\n"
            f"{len(selected)} sites; {observations:,} observations; "
            f"silhouette={detail['silhouette']:.2f}"
        )
        _style_axis(ax)
    fig.supxlabel("slab-face azimuth from chemical 3′ source→5′ destination axis (deg)")
    fig.supylabel("polar angle from +helix axis (deg)")
    fig.suptitle("24hb_1xT candidate subpopulation full-ensemble densities\n"
                 "site assignments from crossover means; all stable frames shown")
    cbar = fig.colorbar(mesh, ax=axes, fraction=0.025, pad=0.02)
    cbar.set_label("density enrichment over isotropic")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOTS / f"24hb_orientation_subpopulations.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)


def _plot_sequence(sites: dict[str, dict], tests: dict[tuple[str, str], dict]) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    rows = []
    for side in SIDES:
        for flank in ("source", "destination"):
            row = []
            for base in BASES:
                selected = _select(
                    sites, lambda site, s=side, f=flank, b=base:
                    site["site_class"] == s and site[f"{f}_base"] == b,
                )
                row.append((selected, _grid(selected)))
            rows.append((side, flank, row))
    vmax = max(float(np.percentile(values, 99.5))
               for _, _, row in rows for _, values in row)
    norm = LogNorm(vmin=0.2, vmax=max(10.0, vmax), clip=True)
    cmap = plt.get_cmap("magma").copy()
    cmap.set_under(cmap(0.0))
    fig, axes = plt.subplots(4, 4, figsize=(14.0, 12.8), sharex=True, sharey=True,
                             constrained_layout=True)
    mesh = None
    for row_number, (side, flank, panels) in enumerate(rows):
        test = tests[(side, f"{flank}_base")]
        side_title = "Lower-bp" if side.endswith("lower") else "Higher-bp"
        qvalue = float(test["fdr_q"])
        for column, (base, (selected, values)) in enumerate(zip(BASES, panels)):
            ax = axes[row_number, column]
            mesh = _draw_density(ax, values, norm, cmap)
            observations = sum(site["n_observations"] for site in selected)
            ax.set_title(f"{base}: {len(selected)} sites; {observations:,} obs", fontsize=9)
            _style_axis(ax)
        axes[row_number, 0].set_ylabel(
            f"{side_title} {flank}\nR²={float(test['eta_squared']):.3f}, q={qvalue:.3f}\n"
            "polar angle (deg)"
        )
    fig.supxlabel("slab-face azimuth from chemical 3′ source→5′ destination axis (deg)")
    fig.suptitle("Flanking-sequence full-ensemble orientation densities\n"
                 "all stable frames; equal crossover weighting within each base class")
    cbar = fig.colorbar(mesh, ax=axes, fraction=0.018, pad=0.015)
    cbar.set_label("density enrichment over isotropic")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOTS / f"24hb_flank_sequence_association.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)


def main() -> int:
    PLOTS.mkdir(parents=True, exist_ok=True)
    members, tests = _load_membership()
    sites, total = _load_full_ensemble(members)
    if len(sites) != 338 or total != 160_333:
        raise ValueError(f"unexpected ensemble size: {len(sites)} sites, {total} observations")
    subpopulation_summary = json.loads((DATA / "24hb_subpopulation_summary.json").read_text())
    summary = {
        "schema": "nadoc.exp55.24hb_hop_full_ensemble_density.v1",
        "coordinate_frame": (
            "right-handed chemical-hop frame: +x is 3' source to 5' destination, "
            "+y is increasing-bp helix axis, +z = +x cross +y"
        ),
        "n_crossovers": len(sites), "n_stable_observations": total,
        "density_method": (
            "All stable frame observations enter a 5-degree spherical histogram. Each "
            "crossover is normalized to unit mass before pooling; 1.25-bin Gaussian "
            "smoothing uses polar reflection and azimuthal wrapping, followed by "
            "solid-angle correction."
        ),
        "groups": {},
    }
    _plot_main(sites, summary)
    _plot_subpopulations(sites, subpopulation_summary)
    _plot_sequence(sites, tests)
    (DATA / "24hb_hop_density_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(DATA / "24hb_hop_orientation_samples.csv.gz")
    print(DATA / "24hb_hop_density_grid.npz")
    print(DATA / "24hb_hop_density_summary.json")
    print(PLOTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

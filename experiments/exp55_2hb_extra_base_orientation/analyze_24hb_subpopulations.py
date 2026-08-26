#!/usr/bin/env python3
"""Subpopulation and flanking-sequence analysis for 24hb_1xT crossover inserts.

The independent unit is one crossover.  Apparent modes are checked in both the fixed
helix-ID frame and a chemical-hop frame that always points from the insert's 3' source to
its 5' destination.  Sequence association tests permute labels within lattice-edge ×
helical-phase strata, preventing the dominant structural classes from masquerading as a
base-identity effect.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.stats import fisher_exact

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.atomistic import _build_sequence_map  # noqa: E402
from backend.core.models import Design  # noqa: E402

DATA = HERE / "data"
PLOTS = HERE / "plots"
SITE_CSV = DATA / "24hb_per_crossover_summary.csv"
DESIGN_PATH = Path("/media/jojo/Archive/NADOC_archive/6950d3b79138/design.json")
SIDES = ("reciprocal_lower", "reciprocal_upper")
BASES = "ACGT"
COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}
COLORS = {"A": "#3b82f6", "C": "#22c55e", "G": "#f59e0b", "T": "#ef4444"}


def _unit(vector: np.ndarray) -> np.ndarray:
    return vector / np.linalg.norm(vector)


def _angles(vector: np.ndarray) -> tuple[float, float]:
    return (
        float(np.degrees(np.arctan2(vector[2], vector[0]))),
        float(np.degrees(np.arccos(np.clip(vector[1], -1.0, 1.0)))),
    )


def _spherical_kmeans(X: np.ndarray, k: int, *, seed: int, restarts: int = 40):
    best = None
    for restart in range(restarts):
        rng = np.random.default_rng(seed + restart)
        centers = [X[int(rng.integers(len(X)))]]
        for _ in range(1, k):
            distance = 1.0 - np.max(X @ np.asarray(centers).T, axis=1)
            probability = distance ** 2
            probability /= probability.sum()
            centers.append(X[int(rng.choice(len(X), p=probability))])
        centers = np.asarray(centers)
        for _ in range(100):
            labels = np.argmax(X @ centers.T, axis=1)
            updated = []
            for cluster in range(k):
                if not np.any(labels == cluster):
                    break
                updated.append(_unit(X[labels == cluster].mean(axis=0)))
            if len(updated) != k:
                break
            updated = np.asarray(updated)
            if np.max(np.linalg.norm(updated - centers, axis=1)) < 1e-10:
                centers = updated
                break
            centers = updated
        else:
            labels = np.argmax(X @ centers.T, axis=1)
        if len(centers) != k:
            continue
        labels = np.argmax(X @ centers.T, axis=1)
        inertia = float(np.sum(1.0 - np.sum(X * centers[labels], axis=1)))
        if best is None or inertia < best[0]:
            best = (inertia, labels, centers)
    if best is None:
        raise RuntimeError(f"spherical k-means failed for k={k}")
    return best[1], best[2], best[0]


def _silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    distance = np.arccos(np.clip(X @ X.T, -1.0, 1.0))
    result = np.zeros(len(X), dtype=float)
    unique = np.unique(labels)
    for index in range(len(X)):
        same = labels == labels[index]
        n_same = int(same.sum()) - 1
        if n_same <= 0:
            continue
        within = float(distance[index, same].sum()) / n_same
        between = min(float(distance[index, labels == label].mean())
                      for label in unique if label != labels[index])
        result[index] = (between - within) / max(within, between)
    return float(result.mean())


def _adjusted_rand(a: np.ndarray, b: np.ndarray) -> float:
    _, ai = np.unique(a, return_inverse=True)
    _, bi = np.unique(b, return_inverse=True)
    table = np.zeros((ai.max() + 1, bi.max() + 1), dtype=int)
    np.add.at(table, (ai, bi), 1)
    choose2 = lambda x: np.sum(x * (x - 1) // 2)
    nij = float(choose2(table))
    aa, bb = float(choose2(table.sum(axis=1))), float(choose2(table.sum(axis=0)))
    total = len(a) * (len(a) - 1) / 2
    expected = aa * bb / total
    denominator = 0.5 * (aa + bb) - expected
    return float((nij - expected) / denominator) if denominator else 1.0


def _cluster_stability(X: np.ndarray, reference_labels: np.ndarray,
                       reference_centers: np.ndarray, *, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    aris, maximum_shifts = [], []
    n_subset = int(round(0.8 * len(X)))
    for bootstrap in range(500):
        subset = rng.choice(len(X), n_subset, replace=False)
        _, centers, _ = _spherical_kmeans(
            X[subset], len(reference_centers), seed=seed + 1000 + bootstrap, restarts=10,
        )
        row, column = linear_sum_assignment(-(reference_centers @ centers.T))
        aligned = centers[column[np.argsort(row)]]
        labels = np.argmax(X @ aligned.T, axis=1)
        aris.append(_adjusted_rand(reference_labels, labels))
        shifts = np.degrees(np.arccos(np.clip(
            np.sum(reference_centers * aligned, axis=1), -1.0, 1.0,
        )))
        maximum_shifts.append(float(shifts.max()))
    return {
        "subsample_fraction": 0.8, "n_subsamples": 500,
        "ari_median": float(np.median(aris)), "ari_p05": float(np.percentile(aris, 5)),
        "max_centroid_shift_deg_median": float(np.median(maximum_shifts)),
        "max_centroid_shift_deg_p95": float(np.percentile(maximum_shifts, 95)),
    }


def _eta_squared(X: np.ndarray, labels: list[str] | np.ndarray) -> float:
    labels = np.asarray(labels)
    mean = X.mean(axis=0)
    total = float(np.sum((X - mean) ** 2))
    between = sum(
        int(np.sum(labels == label)) * float(np.sum((X[labels == label].mean(axis=0) - mean) ** 2))
        for label in np.unique(labels)
    )
    return between / total if total > 0 else 0.0


def _stratified_permutation_test(X: np.ndarray, labels: list[str], strata: list[str],
                                 *, seed: int, n_permutations: int = 20_000) -> tuple[float, float]:
    observed = _eta_squared(X, labels)
    labels_array = np.asarray(labels, dtype=object)
    strata_array = np.asarray(strata, dtype=object)
    groups = [np.flatnonzero(strata_array == value) for value in np.unique(strata_array)]
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(n_permutations):
        permuted = labels_array.copy()
        for indices in groups:
            permuted[indices] = rng.permutation(permuted[indices])
        exceed += _eta_squared(X, permuted) >= observed - 1e-15
    return observed, (exceed + 1.0) / (n_permutations + 1.0)


def _bh_qvalues(pvalues: list[float]) -> list[float]:
    p = np.asarray(pvalues, dtype=float)
    order = np.argsort(p)
    ranked = p[order]
    adjusted = ranked * len(p) / np.arange(1, len(p) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result = np.empty_like(adjusted)
    result[order] = np.clip(adjusted, 0, 1)
    return result.tolist()


def _chemistry_bootstrap(rows: list[dict], *, seed: int) -> dict:
    """Upper-side source purine/pyrimidine direction difference, structure-stratified."""
    cells = defaultdict(list)
    for index, row in enumerate(rows):
        cells[(row["structural_stratum"], row["source_chemistry"])].append(index)
    rng = np.random.default_rng(seed)
    polar_differences, separations = [], []
    for _ in range(20_000):
        sampled = np.concatenate([
            rng.choice(indices, len(indices), replace=True) for indices in cells.values()
        ])
        directions = {}
        for chemistry in ("purine", "pyrimidine"):
            subset = [i for i in sampled if rows[i]["source_chemistry"] == chemistry]
            directions[chemistry] = _unit(np.mean(
                [rows[i]["hop_vector"] for i in subset], axis=0,
            ))
        purine = directions["purine"]
        pyrimidine = directions["pyrimidine"]
        polar_differences.append(_angles(purine)[1] - _angles(pyrimidine)[1])
        separations.append(float(np.degrees(np.arccos(np.clip(
            np.dot(purine, pyrimidine), -1, 1,
        )))))
    return {
        "purine_minus_pyrimidine_polar_deg": float(np.mean(polar_differences)),
        "purine_minus_pyrimidine_polar_ci95_deg": np.percentile(
            polar_differences, [2.5, 97.5]
        ).tolist(),
        "mean_direction_separation_deg": float(np.mean(separations)),
        "mean_direction_separation_ci95_deg": np.percentile(
            separations, [2.5, 97.5]
        ).tolist(),
    }


def _load_rows() -> tuple[list[dict], dict]:
    raw_design = json.loads(DESIGN_PATH.read_text())
    design = Design.model_validate(raw_design)
    sequence = _build_sequence_map(design)
    crossovers = {xo.id: xo for xo in design.crossovers}
    grid = {helix["id"]: tuple(helix["grid_pos"]) for helix in raw_design["helices"]}
    records = []
    with SITE_CSV.open(newline="") as handle:
        for source in csv.DictReader(handle):
            if source["site_class"] not in SIDES:
                continue
            crossover = crossovers[source["crossover_id"]]
            halves = (crossover.half_a, crossover.half_b)
            source_half = next(h for h in halves if h.helix_id == source["source_helix"])
            destination_half = next(
                h for h in halves if h.helix_id == source["destination_helix"]
            )
            source_key = (source_half.helix_id, source_half.index, source_half.strand.value)
            destination_key = (
                destination_half.helix_id, destination_half.index,
                destination_half.strand.value,
            )
            opposite = lambda direction: "REVERSE" if direction == "FORWARD" else "FORWARD"
            source_base = sequence[source_key]
            destination_base = sequence[destination_key]
            source_pair = sequence[(source_key[0], source_key[1], opposite(source_key[2]))]
            destination_pair = sequence[
                (destination_key[0], destination_key[1], opposite(destination_key[2]))
            ]
            g_vector = np.asarray(json.loads(source["mean_direction_ih_ax_perp"]), dtype=float)
            lo_to_hi = source["source_helix"] == min(
                source["source_helix"], source["destination_helix"]
            )
            sign = 1.0 if lo_to_hi else -1.0
            hop_vector = np.diag([sign, 1.0, sign]) @ g_vector
            a = grid[crossover.half_a.helix_id]
            b = grid[crossover.half_b.helix_id]
            delta = (b[0] - a[0], b[1] - a[1])
            edge = min(delta, (-delta[0], -delta[1]))
            bp = int(source["bp"])
            records.append({
                **source, "bp": bp, "global_vector": g_vector,
                "hop_vector": hop_vector, "lo_to_hi": lo_to_hi,
                "source_base": source_base, "destination_base": destination_base,
                "dinucleotide_3to5": source_base + destination_base,
                "source_paired_base": source_pair,
                "destination_paired_base": destination_pair,
                "source_chemistry": "purine" if source_base in "AG" else "pyrimidine",
                "destination_chemistry": (
                    "purine" if destination_base in "AG" else "pyrimidine"
                ),
                "lattice_edge": str(edge), "bp_mod21": bp % 21,
                "structural_stratum": f"{edge}:{bp % 21}",
            })
    complement_mismatches = sum(
        COMPLEMENT[row["source_base"]] != row["source_paired_base"]
        or COMPLEMENT[row["destination_base"]] != row["destination_paired_base"]
        for row in records
    )
    return records, {"paired_complement_mismatches": complement_mismatches}


def analyse() -> tuple[dict, list[dict], list[dict]]:
    rows, sequence_checks = _load_rows()
    summary = {
        "schema": "nadoc.exp55.24hb_subpopulations.v1",
        "n_crossovers": len(rows), "sequence_checks": sequence_checks,
        "frame_interpretation": {
            "global": "fixed helix(min id)->helix(max id), axial, perpendicular",
            "hop": "chemical 3' source->5' destination, axial, perpendicular",
        },
        "sides": {},
    }
    association_rows = []
    primary_tests = []
    per_side = {}
    for side_number, side in enumerate(SIDES):
        selected = [row for row in rows if row["site_class"] == side]
        global_vectors = np.asarray([row["global_vector"] for row in selected])
        hop_vectors = np.asarray([row["hop_vector"] for row in selected])

        global_labels, global_centers, _ = _spherical_kmeans(
            global_vectors, 2, seed=100 + side_number,
        )
        # Stable naming: increasing azimuth for the global-frame diagnostic.
        global_order = np.argsort([_angles(center)[0] for center in global_centers])
        global_remap = {int(old): new for new, old in enumerate(global_order)}
        global_labels = np.asarray([global_remap[int(label)] for label in global_labels])
        global_centers = global_centers[global_order]
        traversal = np.asarray([int(row["lo_to_hi"]) for row in selected])
        traversal_accuracy = max(
            float(np.mean(global_labels == traversal)),
            float(np.mean(global_labels == (1 - traversal))),
        )

        sweep = {}
        hop_models = {}
        for k in range(2, 7):
            labels, centers, inertia = _spherical_kmeans(
                hop_vectors, k, seed=200 + 10 * side_number + k,
            )
            sweep[str(k)] = {
                "silhouette": _silhouette(hop_vectors, labels),
                "sizes": [int(np.sum(labels == cluster)) for cluster in range(k)],
                "inertia": inertia,
            }
            hop_models[k] = (labels, centers)

        # A two-component descriptive summary is used for both sides. It is deliberately
        # called a candidate partition: lower-side k=3 is only 0.025 better in silhouette,
        # and the subsampling stability below reveals whether k=2 is robust.
        hop_labels, hop_centers = hop_models[2]
        hop_order = np.argsort([_angles(center)[1] for center in hop_centers])
        hop_remap = {int(old): new for new, old in enumerate(hop_order)}
        hop_labels = np.asarray([hop_remap[int(label)] for label in hop_labels])
        hop_centers = hop_centers[hop_order]
        stability = _cluster_stability(
            hop_vectors, hop_labels, hop_centers, seed=300 + side_number,
        )
        for row, global_label, hop_label in zip(selected, global_labels, hop_labels):
            row["global_cluster"] = int(global_label)
            row["hop_candidate_cluster"] = int(hop_label)

        side_summary = {
            "n_crossovers": len(selected),
            "global_apparent_k2": {
                "silhouette": _silhouette(global_vectors, global_labels),
                "sizes": [int(np.sum(global_labels == cluster)) for cluster in range(2)],
                "centers": [
                    {"azimuth_deg": _angles(center)[0], "polar_deg": _angles(center)[1]}
                    for center in global_centers
                ],
                "traversal_direction_explained_fraction": traversal_accuracy,
                "interpretation": "coordinate/traversal polarity, not a conformational state",
            },
            "hop_frame_silhouette_sweep": sweep,
            "hop_candidate_k2": {
                "silhouette": _silhouette(hop_vectors, hop_labels),
                "sizes": [int(np.sum(hop_labels == cluster)) for cluster in range(2)],
                "centers": [
                    {"azimuth_deg": _angles(center)[0], "polar_deg": _angles(center)[1]}
                    for center in hop_centers
                ],
                "stability": stability,
            },
        }
        summary["sides"][side] = side_summary
        per_side[side] = selected

        variables = {
            "source_base": [row["source_base"] for row in selected],
            "destination_base": [row["destination_base"] for row in selected],
            "source_purine_pyrimidine": [row["source_chemistry"] for row in selected],
            "destination_purine_pyrimidine": [
                row["destination_chemistry"] for row in selected
            ],
        }
        strata = [row["structural_stratum"] for row in selected]
        for variable_number, (variable, labels) in enumerate(variables.items()):
            eta2, pvalue = _stratified_permutation_test(
                hop_vectors, labels, strata,
                seed=1000 + 100 * side_number + variable_number,
            )
            result = {
                "side": side, "variable": variable,
                "n_categories": len(set(labels)), "eta_squared": eta2,
                "permutation_p": pvalue, "n_permutations": 20_000,
                "stratification": "lattice_edge × bp_mod21",
                "category_counts": dict(sorted(Counter(labels).items())),
                "primary_test": True,
            }
            primary_tests.append(result)
            association_rows.append(result)

        # Exploratory 16-level dinucleotide test; sparse cells make it less interpretable
        # than the prespecified source/destination effects, so it is not in the FDR family.
        dinucleotide = [row["dinucleotide_3to5"] for row in selected]
        eta2, pvalue = _stratified_permutation_test(
            hop_vectors, dinucleotide, strata, seed=1500 + side_number,
        )
        association_rows.append({
            "side": side, "variable": "source_destination_dinucleotide_exploratory",
            "n_categories": len(set(dinucleotide)), "eta_squared": eta2,
            "permutation_p": pvalue, "n_permutations": 20_000,
            "stratification": "lattice_edge × bp_mod21",
            "category_counts": dict(sorted(Counter(dinucleotide).items())),
            "primary_test": False, "fdr_q": None,
        })

    qvalues = _bh_qvalues([row["permutation_p"] for row in primary_tests])
    for row, qvalue in zip(primary_tests, qvalues):
        row["fdr_q"] = qvalue

    upper = per_side["reciprocal_upper"]
    chemistry_bootstrap = _chemistry_bootstrap(upper, seed=20260825)
    upper_cluster_table = np.zeros((2, 2), dtype=int)
    for row in upper:
        chemistry_index = 0 if row["source_chemistry"] == "purine" else 1
        upper_cluster_table[chemistry_index, row["hop_candidate_cluster"]] += 1
    fisher = fisher_exact(upper_cluster_table)
    summary["upper_source_purine_pyrimidine_effect"] = {
        **chemistry_bootstrap,
        "candidate_cluster_contingency_rows_purine_pyrimidine": upper_cluster_table.tolist(),
        "candidate_cluster_fisher_odds_ratio": float(fisher.statistic),
        "candidate_cluster_fisher_p": float(fisher.pvalue),
        "note": "paired-complement identity is deterministic and is not an independent test",
    }
    summary["association_tests"] = association_rows

    # Write one row per independent crossover with all explanatory variables and labels.
    export_fields = (
        "crossover_id", "site_class", "source_helix", "destination_helix", "bp",
        "lattice_edge", "bp_mod21", "structural_stratum", "lo_to_hi",
        "source_base", "destination_base", "dinucleotide_3to5", "source_paired_base",
        "destination_paired_base", "source_chemistry", "destination_chemistry",
        "global_azimuth_deg", "global_polar_deg", "hop_azimuth_deg", "hop_polar_deg",
        "global_cluster", "hop_candidate_cluster", "resultant_length", "n_stable",
    )
    with (DATA / "24hb_subpopulation_membership.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=export_fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            global_azimuth, global_polar = _angles(row["global_vector"])
            hop_azimuth, hop_polar = _angles(row["hop_vector"])
            writer.writerow({
                **{key: row[key] for key in export_fields if key in row},
                "global_azimuth_deg": global_azimuth, "global_polar_deg": global_polar,
                "hop_azimuth_deg": hop_azimuth, "hop_polar_deg": hop_polar,
            })
    association_fields = (
        "side", "variable", "n_categories", "eta_squared", "permutation_p", "fdr_q",
        "n_permutations", "stratification", "primary_test", "category_counts",
    )
    with (DATA / "24hb_sequence_association_tests.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=association_fields, lineterminator="\n")
        writer.writeheader()
        for row in association_rows:
            writer.writerow({**row, "category_counts": json.dumps(row["category_counts"])})
    (DATA / "24hb_subpopulation_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary, rows, association_rows


def plot(summary: dict, rows: list[dict], association_rows: list[dict]) -> None:
    import matplotlib.pyplot as plt

    PLOTS.mkdir(parents=True, exist_ok=True)
    cluster_colors = ("#2563eb", "#f97316")
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.2), sharex=True, sharey=True,
                             constrained_layout=True)
    for column, side in enumerate(SIDES):
        selected = [row for row in rows if row["site_class"] == side]
        title_side = "Lower-bp" if side.endswith("lower") else "Higher-bp"
        for row_number, (frame, label_key) in enumerate((
            ("global", "global_cluster"), ("hop", "hop_candidate_cluster")
        )):
            ax = axes[row_number, column]
            for cluster in (0, 1):
                group = [row for row in selected if row[label_key] == cluster]
                vectors = np.asarray([row[f"{frame}_vector"] for row in group])
                angles = np.asarray([_angles(vector) for vector in vectors])
                ax.scatter(angles[:, 0], angles[:, 1], s=17, alpha=0.72,
                           color=cluster_colors[cluster], linewidths=0,
                           label=f"component {cluster + 1} (n={len(group)})")
            if frame == "global":
                detail = summary["sides"][side]["global_apparent_k2"]
                subtitle = (
                    f"fixed-ID frame: silhouette={detail['silhouette']:.2f}; "
                    f"traversal explains {100*detail['traversal_direction_explained_fraction']:.1f}%"
                )
            else:
                detail = summary["sides"][side]["hop_candidate_k2"]
                stability = detail["stability"]
                subtitle = (
                    f"chemical-hop frame: silhouette={detail['silhouette']:.2f}; "
                    f"80% subsample ARI={stability['ari_median']:.2f}"
                )
            ax.set_title(f"{title_side}\n{subtitle}", fontsize=10)
            ax.set_xlim(-180, 180); ax.set_ylim(180, 0)
            ax.set_xticks([-180, -90, 0, 90, 180]); ax.set_yticks([0, 45, 90, 135, 180])
            ax.grid(alpha=0.18, linewidth=0.6)
            ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.supxlabel("slab-face azimuth (deg)")
    fig.supylabel("polar angle from +helix axis (deg)")
    fig.suptitle("24hb_1xT apparent versus intrinsic orientation subpopulations")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOTS / f"24hb_orientation_subpopulations.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)

    test_lookup = {(row["side"], row["variable"]): row for row in association_rows}
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 7.6), sharey=True,
                             constrained_layout=True)
    rng = np.random.default_rng(20260825)
    for row_number, variable_prefix in enumerate(("source", "destination")):
        for column, side in enumerate(SIDES):
            ax = axes[row_number, column]
            selected = [row for row in rows if row["site_class"] == side]
            title_side = "Lower-bp" if side.endswith("lower") else "Higher-bp"
            values = []
            for position, base in enumerate(BASES, start=1):
                group = [row for row in selected if row[f"{variable_prefix}_base"] == base]
                polar = np.asarray([_angles(row["hop_vector"])[1] for row in group])
                values.append(polar)
                jitter = rng.normal(position, 0.055, size=len(polar))
                ax.scatter(jitter, polar, s=12, alpha=0.52, color=COLORS[base], linewidths=0)
            boxes = ax.boxplot(values, positions=range(1, 5), widths=0.48,
                               patch_artist=True, showfliers=False)
            for patch, base in zip(boxes["boxes"], BASES):
                patch.set(facecolor=COLORS[base], alpha=0.18, edgecolor=COLORS[base])
            test = test_lookup[(side, f"{variable_prefix}_base")]
            ax.set_title(
                f"{title_side}: {variable_prefix} flank\n"
                f"R²={test['eta_squared']:.3f}, stratified q={test.get('fdr_q', 1):.3f}",
                fontsize=10,
            )
            ax.set_xticks(range(1, 5), list(BASES))
            ax.set_ylim(180, 0)
            ax.set_yticks([0, 45, 90, 135, 180])
            ax.grid(axis="y", alpha=0.18, linewidth=0.6)
    fig.supxlabel("flanking base identity")
    fig.supylabel("chemical-hop-frame slab polar angle (deg)")
    fig.suptitle("Flanking sequence versus crossover extra-base orientation")
    for suffix in ("png", "pdf"):
        fig.savefig(PLOTS / f"24hb_flank_sequence_association.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)
    print(PLOTS)


def main() -> int:
    summary, rows, tests = analyse()
    plot(summary, rows, tests)
    print(DATA / "24hb_subpopulation_membership.csv")
    print(DATA / "24hb_sequence_association_tests.csv")
    print(DATA / "24hb_subpopulation_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pure analysis of exp46 metric dumps: stable windows, states and consensus."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.occupancy_core import occupancy_clusters  # noqa: E402
from backend.core.extra_base_position_clusters import pooled_position_clusters  # noqa: E402


PANELS = {
    "hop_position": ("t_c1", "bow_sd_c1", "h1_c1", "h2_c1", "h3_c1"),
    "pose_orientation": (
        "pose_t", "pose_bow_sd", "pose_ax", "gly_dot_axis", "gly_dot_bow",
        "gly_dot_chord", "norm_dot_axis", "norm_dot_bow", "norm_dot_chord",
    ),
    "environment": (
        "stack_d", "stack_ang", "partner_min_d", "interhelix", "axis_angle_deg",
        "bow_sd_base",
    ),
}


def valid_sample(sample: dict, paired: float, cfg: dict) -> tuple[bool, list[str]]:
    reasons = []
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
    reasons.extend(name for passed, name in checks if not passed)
    return not reasons, reasons


def stable_windows(mask: list[bool], min_samples: int) -> list[tuple[int, int]]:
    windows, start = [], None
    for i, good in enumerate(mask + [False]):
        if good and start is None:
            start = i
        elif not good and start is not None:
            if i - start >= min_samples:
                windows.append((start, i))
            start = None
    return windows


def robust_features(samples: list[dict], keys: tuple[str, ...]) -> tuple[np.ndarray, list[str]]:
    if not samples:
        return np.empty((0, 0)), []
    present = [k for k in keys if all(np.isfinite(s.get(k, np.nan)) for s in samples)]
    if not present:
        return np.empty((len(samples), 0)), []
    X = np.asarray([[s[k] for k in present] for s in samples], dtype=float)
    med = np.median(X, axis=0)
    scale = 1.4826 * np.median(np.abs(X - med), axis=0)
    scale[scale < 1e-9] = np.std(X[:, scale < 1e-9], axis=0)
    scale[scale < 1e-9] = 1.0
    return (X - med) / scale, present


def adjusted_rand(a: list[int], b: list[int]) -> float | None:
    if len(a) != len(b) or len(a) < 2:
        return None
    a, b = np.asarray(a), np.asarray(b)
    _, ai = np.unique(a, return_inverse=True)
    _, bi = np.unique(b, return_inverse=True)
    tab = np.zeros((ai.max() + 1, bi.max() + 1), dtype=int)
    np.add.at(tab, (ai, bi), 1)
    c2 = lambda x: np.sum(x * (x - 1) // 2)
    nij = float(c2(tab))
    aa, bb = float(c2(tab.sum(axis=1))), float(c2(tab.sum(axis=0)))
    total = len(a) * (len(a) - 1) / 2
    expected = aa * bb / total if total else 0.0
    denom = 0.5 * (aa + bb) - expected
    return 1.0 if denom == 0 and nij == expected else float((nij - expected) / denom)


def labels_from(result: dict, n: int) -> list[int] | None:
    if not result.get("ready"):
        return None
    labels = [-1] * n
    for rank, cluster in enumerate(result.get("clusters", [])):
        for frame in cluster["frames"]:
            labels[frame] = rank
    return labels if all(v >= 0 for v in labels) else None


def samples_for_insert(data: dict, insert: dict) -> list[dict]:
    """Read current dumps and repair the historical exp46 multi-insert key bug.

    Before exp53, exp46 keyed records only by crossover id. For n inserts the shared
    list contains ``k0,k1,...`` for every frame and is repeated on every output insert.
    New dumps have exactly one sample per paired-fraction entry.
    """
    samples = insert["samples"]
    n_frames = len(data["paired_fraction"])
    if len(samples) == n_frames:
        return samples
    siblings = [i for i in data["inserts"] if i["crossover_id"] == insert["crossover_id"]]
    n_insert = len(siblings)
    if n_insert > 1 and len(samples) == n_frames * n_insert:
        return samples[int(insert["k"])::n_insert]
    raise ValueError(
        f"{insert['crossover_id']} k{insert['k']}: {len(samples)} samples for "
        f"{n_frames} frames cannot be reconciled"
    )


def analyse_dump(data: dict, cfg: dict) -> dict:
    paired = data["paired_fraction"]
    results = []
    stable_indices = {}
    for insert in data["inserts"]:
        samples = samples_for_insert(data, insert)
        decisions = [valid_sample(s, paired[i], cfg) for i, s in enumerate(samples)]
        mask = [d[0] for d in decisions]
        windows = stable_windows(mask, int(cfg["min_window_samples"]))
        keep = [i for lo, hi in windows for i in range(lo, hi)]
        stable_indices[(str(insert["crossover_id"]), int(insert["k"]))] = keep
        kept = [samples[i] for i in keep]
        failures = {}
        for _, why in decisions:
            for reason in why:
                failures[reason] = failures.get(reason, 0) + 1
        panels, panel_labels = {}, {}
        for name, keys in PANELS.items():
            X, used = robust_features(kept, keys)
            result = (occupancy_clusters(X) if X.shape[1] and len(X) >= 10 else
                      {"ready": False, "reason": "insufficient stable samples or metrics",
                       "n_frames": len(X)})
            result["metrics"] = used
            panels[name] = result
            panel_labels[name] = labels_from(result, len(kept))
        agreement = {}
        names = list(PANELS)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if panel_labels[a] is not None and panel_labels[b] is not None:
                    agreement[f"{a}__{b}"] = adjusted_rand(panel_labels[a], panel_labels[b])
        results.append({
            "crossover_id": insert["crossover_id"], "insert_k": insert["k"],
            "base": insert["base"], "src": insert["src"], "dst": insert["dst"],
            "n_samples": len(samples), "n_valid": int(sum(mask)),
            "valid_fraction": float(np.mean(mask)) if mask else 0.0,
            "failure_counts": failures,
            "stable_windows": [
                {"sample_start": lo, "sample_stop": hi,
                 "frame_start": data["frames"][lo], "frame_stop": data["frames"][hi - 1],
                 "n_samples": hi - lo} for lo, hi in windows
            ],
            "n_stable_samples": len(keep), "panels": panels,
            "panel_agreement_ari": agreement,
        })
    pooled = pooled_position_clusters(data, stable_indices)
    return {
        "schema": "nadoc.exp53.analysis.v2", "stem": data["stem"],
        "job": data["job"], "dcd": data["dcd"], "stride": data["stride"],
        "n_frames": data["n_frames"], "filters": cfg, "inserts": results,
        "pooled_positions": pooled,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("--config", type=Path, default=Path(__file__).with_name("inventory.json"))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text())
    result = analyse_dump(json.loads(args.dump.read_text()), config["filters"])
    out = args.out or args.dump.with_name(args.dump.stem + "_states.json")
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(out)


if __name__ == "__main__":
    main()

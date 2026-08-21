"""Read-only compact evidence bundle for Help > Extra-Base Metrics Audit."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "nadoc.extra-base-metrics-audit.v2"
RESULTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "experiments/exp53_extra_base_state_refinement/results"
)

CPD_1XT_REFERENCE = {
    "label": "Designed reciprocal-T weld pair",
    "source_part": "2hb_1xT",
    "production_ns": 161.8,
    "n_frames": 1619,
    "d_mid_A": {"mean": 11.39, "sd": 1.38, "min": 7.44, "max": 17.97},
    "eta_deg": {"mean": 31.5, "sd": 95.6, "min": -180.0, "max": 180.0},
    "n_below_8A": 10,
    "n_below_6A": 0,
    "reactive_corner": {"n": 0, "total": 1619, "d_max_A": 4.5, "eta_window_deg": 45.0},
    "provenance": "project_cpd_umbrella_sampling Phase 0; 2hb_1xT unbiased k=0",
}

_CACHE_KEY = None
_CACHE_VALUE = None


def _compact_panel(panel: dict) -> dict:
    compact = {
        key: panel.get(key)
        for key in (
            "ready",
            "reason",
            "verdict",
            "k",
            "silhouette",
            "transitions",
            "pc1_lag1",
            "metrics",
            "confidence",
            "clusters",
        )
        if key in panel
    }
    if "clusters" in compact:
        compact["clusters"] = [
            {
                key: cluster.get(key)
                for key in (
                    "rank",
                    "population",
                    "population_sem",
                    "n_frames",
                    "tau_int",
                    "n_eff",
                    "medoid_index",
                    "rmsd_spread_nm",
                    "visits",
                    "pc_scores",
                    "rmsd_to_top_nm",
                )
                if key in cluster
            }
            for cluster in compact["clusters"]
        ]
    return compact


def _source_name(path: Path) -> tuple[str, str]:
    part, role = path.name.removesuffix("__states.json").split("__", 1)
    return part, role


def _compact_pooled_positions(pooled: dict | None) -> dict | None:
    """Keep only the compact pooled-position contract used by the 3D audit."""
    if not pooled:
        return None
    return {
        key: pooled.get(key)
        for key in (
            "ready",
            "reason",
            "classification",
            "n_unpaired_inserts",
            "max_fit_samples_per_side",
            "sides",
        )
        if key in pooled
    }


def _state_cloud(
    root: Path,
    state_path: Path,
    insert_index: int,
    insert: dict,
    metrics: dict | None = None,
) -> dict | None:
    metrics_path = root / state_path.name.replace("__states.json", "__metrics.json")
    if not metrics_path.exists():
        return None
    if metrics is None:
        metrics = json.loads(metrics_path.read_text())
    raw_insert = metrics.get("inserts", [])[insert_index]
    samples = raw_insert.get("samples", [])
    n_frames = len(metrics.get("paired_fraction", []))
    siblings = [
        i for i in metrics["inserts"] if i["crossover_id"] == raw_insert["crossover_id"]
    ]
    if (
        len(samples) != n_frames
        and len(siblings) > 1
        and len(samples) == n_frames * len(siblings)
    ):
        samples = samples[int(raw_insert["k"]) :: len(siblings)]
    keep = [
        i
        for window in insert.get("stable_windows", [])
        for i in range(window["sample_start"], window["sample_stop"])
    ]
    labels = [-1] * len(keep)
    clusters = insert.get("panels", {}).get("hop_position", {}).get("clusters", [])
    for state, cluster in enumerate(clusters):
        for stable_index in cluster.get("frames", []):
            if stable_index < len(labels):
                labels[stable_index] = state
    if not keep:
        return {"axes": ["t_c1", "bow_sd_c1"], "points": []}
    stride = max(1, len(keep) // 600)
    points = []
    for stable_index in range(0, len(keep), stride):
        sample_index = keep[stable_index]
        if sample_index >= len(samples):
            continue
        sample = samples[sample_index]
        points.append(
            [
                sample.get("t_c1"),
                sample.get("bow_sd_c1"),
                labels[stable_index],
                sample_index,
            ]
        )
    return {"axes": ["t_c1", "bow_sd_c1"], "points": points}


def build_extra_base_metrics_audit(results_dir: Path | None = None) -> dict:
    global _CACHE_KEY, _CACHE_VALUE
    root = results_dir or RESULTS_DIR
    watched = sorted(root.glob("*__states.json")) + sorted(root.glob("*__metrics.json"))
    watched += sorted(root.glob("*__topology.txt"))
    cache_key = (
        str(root),
        tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in watched),
    )
    if cache_key == _CACHE_KEY and _CACHE_VALUE is not None:
        return _CACHE_VALUE
    sources = []
    if root.exists():
        for path in sorted(root.glob("*__states.json")):
            if "__exp46_smoke__" in path.name:
                continue
            raw = json.loads(path.read_text())
            part, role = _source_name(path)
            pooled_positions = _compact_pooled_positions(raw.get("pooled_positions"))
            metrics_path = root / path.name.replace("__states.json", "__metrics.json")
            # One large-bundle dump can contain hundreds of inserts.  Parse its metric
            # file once per source; reparsing it for every state cloud scales as
            # O(inserts * file size) and made the Help audit unusable for 24hb.
            metrics = None
            if pooled_positions is None and metrics_path.exists():
                metrics = json.loads(metrics_path.read_text())
            topology_path = root / path.name.replace("__states.json", "__topology.txt")
            topology_text = topology_path.read_text() if topology_path.exists() else ""
            inserts = []
            # Pooled sources deliberately replace hundreds of per-insert cards.  The
            # source state file retains those analyses as provenance, while the Help
            # payload sends only the two i/i+1 ensembles and their physical medoids.
            raw_inserts = [] if pooled_positions is not None else raw.get("inserts", [])
            for insert_index, insert in enumerate(raw_inserts):
                compact_insert = {
                    key: insert.get(key)
                    for key in (
                        "crossover_id",
                        "insert_k",
                        "base",
                        "src",
                        "dst",
                        "n_samples",
                        "n_valid",
                        "valid_fraction",
                        "failure_counts",
                        "stable_windows",
                        "n_stable_samples",
                        "panel_agreement_ari",
                    )
                } | {
                    "panels": {
                        name: _compact_panel(panel)
                        for name, panel in insert.get("panels", {}).items()
                    }
                }
                compact_insert["state_cloud"] = _state_cloud(
                    root, path, insert_index, insert, metrics
                )
                inserts.append(compact_insert)
            sources.append(
                {
                    "part": part,
                    "role": role,
                    "job": raw.get("job"),
                    "dcd": raw.get("dcd"),
                    "n_frames": raw.get("n_frames"),
                    "stride": raw.get("stride"),
                    "filters": raw.get("filters", {}),
                    "topology_pass": "piercings=0" in topology_text,
                    "inserts": inserts,
                    "pooled_positions": pooled_positions,
                    "cpd_reference": CPD_1XT_REFERENCE if part == "2hb_1xT" else None,
                }
            )
    result = {
        "schema": SCHEMA,
        "results_dir": str(root),
        "ready": bool(sources),
        "sources": sources,
        "excluded_parts": [],
        "metric_panels": {
            "hop_position": "Hop position",
            "pose_orientation": "Pose / orientation",
            "environment": "Environment",
        },
    }
    _CACHE_KEY, _CACHE_VALUE = cache_key, result
    return result

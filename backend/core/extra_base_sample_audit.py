"""On-demand real-frame feeds for Help > Extra-Base Metrics Audit.

The source contract is the JSON emitted by ``xb_observables.py``.  Client input selects
only a registered source id, never an arbitrary path.  Every returned pose is expressed
in the metric dump's canonical helix-pair frame, allowing reciprocal crossover records
from the same sampled frame to share one orbitable view.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from backend.core.extra_base_metrics_audit import RESULTS_DIR
from backend.core.extra_base_position_clusters import (
    canonical_medoid,
    reciprocal_crossover_sides,
)
from backend.core.models import Design

CATALOG_SCHEMA = "nadoc.extra-base-sample-catalog.v1"
SAMPLE_SCHEMA = "nadoc.extra-base-sample-audit.v1"


def _sources(root: Path) -> dict[str, Path]:
    return {
        path.name.removesuffix("__metrics.json"): path
        for path in sorted(root.glob("*__metrics.json"))
        if "__exp46_smoke__" not in path.name
    }


def _source_path(source_id: str, root: Path) -> Path:
    path = _sources(root).get(source_id)
    if path is None:
        raise KeyError(f"unknown extra-base metric source: {source_id}")
    return path


@lru_cache(maxsize=2)
def _load_metrics(path_string: str, size: int, mtime_ns: int) -> dict:
    del size, mtime_ns
    return json.loads(Path(path_string).read_text())


def _metrics(source_id: str, root: Path) -> tuple[Path, dict]:
    path = _source_path(source_id, root)
    stat = path.stat()
    return path, _load_metrics(str(path), stat.st_size, stat.st_mtime_ns)


def _design_and_sides(data: dict) -> tuple[Design | None, dict[str, dict]]:
    design_path = Path(str(data.get("job", ""))) / "design.json"
    if not design_path.is_file():
        return None, {}
    design = Design.model_validate_json(design_path.read_text(encoding="utf-8"))
    return design, reciprocal_crossover_sides(design)


def _samples_for_insert(data: dict, insert: dict) -> list[dict]:
    samples = insert.get("samples", [])
    n_samples = len(data.get("paired_fraction", [])) or len(data.get("frames", []))
    siblings = [
        candidate for candidate in data.get("inserts", [])
        if candidate.get("crossover_id") == insert.get("crossover_id")
    ]
    if n_samples and len(samples) != n_samples and len(siblings) > 1:
        if len(samples) == n_samples * len(siblings):
            samples = samples[int(insert.get("k", 0)) :: len(siblings)]
    return samples


def _suggestions(source_id: str, root: Path, side_map: dict[str, dict]) -> list[dict]:
    state_path = root / f"{source_id}__states.json"
    if not state_path.is_file():
        return []
    state = json.loads(state_path.read_text())
    suggestions = []
    for side in state.get("pooled_positions", {}).get("sides", []):
        for cluster in side.get("clusters", []):
            medoid = cluster.get("medoid", {})
            crossover_id = str(medoid.get("crossover_id", ""))
            if not crossover_id or medoid.get("sample_index") is None:
                continue
            pair = side_map.get(crossover_id, {})
            suggestions.append({
                "label": (
                    f"{side.get('label', side.get('side', 'side'))} · cluster "
                    f"{int(cluster.get('rank', 0)) + 1} medoid"
                ),
                "sample_index": int(medoid["sample_index"]),
                "frame": medoid.get("frame"),
                "crossover_ids": [crossover_id],
                "paired_with": pair.get("paired_with"),
                "population": cluster.get("population"),
            })
    return suggestions


def list_extra_base_sample_sources(results_dir: Path | None = None) -> list[dict]:
    root = results_dir or RESULTS_DIR
    return [
        {"source_id": source_id, "metrics_path": str(path)}
        for source_id, path in _sources(root).items()
    ]


def build_extra_base_sample_catalog(
    source_id: str, results_dir: Path | None = None,
) -> dict:
    root = results_dir or RESULTS_DIR
    path, data = _metrics(source_id, root)
    _design, side_map = _design_and_sides(data)
    records: dict[str, dict] = {}
    for insert in data.get("inserts", []):
        crossover_id = str(insert["crossover_id"])
        row = records.setdefault(crossover_id, {
            "crossover_id": crossover_id,
            "bases": [], "insert_count": 0,
            "src": insert.get("src"), "dst": insert.get("dst"),
            "side": side_map.get(crossover_id, {}).get("side", "unpaired"),
            "paired_with": side_map.get(crossover_id, {}).get("paired_with"),
            "pair_id": side_map.get(crossover_id, {}).get("pair_id"),
            "bp_level": side_map.get(crossover_id, {}).get(
                "bp_level", (insert.get("src") or [None, None])[1]
            ),
        })
        row["bases"].append(insert.get("base"))
        row["insert_count"] += 1
    frames = [int(frame) for frame in data.get("frames", [])]
    if not frames:
        n_samples = len(data.get("paired_fraction", []))
        frames = list(range(n_samples))
    return {
        "schema": CATALOG_SCHEMA,
        "source_id": source_id,
        "metrics_path": str(path),
        "job": data.get("job"),
        "design_path": str(Path(str(data.get("job", ""))) / "design.json"),
        "n_samples": len(frames),
        "frames": frames,
        "stride": data.get("stride"),
        "crossovers": sorted(
            records.values(), key=lambda row: (
                str(row["src"][0]) if row.get("src") else "",
                int(row.get("bp_level") or 0), row["crossover_id"],
            )
        ),
        "suggestions": _suggestions(source_id, root, side_map),
        "coordinate_frame": ["interhelix", "helix_axis", "out_of_plane"],
        "coordinate_note": (
            "Every selected observation is shown in its crossover's canonical helix-pair "
            "frame. Reciprocal partners share that frame; unrelated crossovers receive "
            "separate viewer cards."
        ),
    }


def _resolve_sample_index(
    frames: list[int], sample_index: int | None, frame: int | None,
) -> tuple[int, int]:
    if not frames:
        raise ValueError("metric source has no sampled frames")
    if frame is not None:
        index = int(np.argmin(np.abs(np.asarray(frames, dtype=int) - int(frame))))
        return index, frames[index]
    index = 0 if sample_index is None else int(sample_index)
    if index < 0 or index >= len(frames):
        raise ValueError(f"sample_index {index} outside 0..{len(frames) - 1}")
    return index, frames[index]


def build_extra_base_sample_audit(
    source_id: str,
    crossover_ids: list[str],
    *,
    sample_index: int | None = None,
    frame: int | None = None,
    include_reciprocal_partners: bool = True,
    results_dir: Path | None = None,
) -> dict:
    root = results_dir or RESULTS_DIR
    _path, data = _metrics(source_id, root)
    _design, side_map = _design_and_sides(data)
    frames = [int(value) for value in data.get("frames", [])]
    if not frames:
        frames = list(range(len(data.get("paired_fraction", []))))
    resolved_index, resolved_frame = _resolve_sample_index(frames, sample_index, frame)

    available = {str(insert["crossover_id"]) for insert in data.get("inserts", [])}
    requested = {str(value) for value in crossover_ids}
    missing = sorted(requested - available)
    if missing:
        raise KeyError(f"crossovers not present in source: {', '.join(missing)}")
    selected = set(requested)
    if include_reciprocal_partners:
        selected.update(
            side_map[crossover_id]["paired_with"]
            for crossover_id in list(selected)
            if crossover_id in side_map
        )

    records = []
    for insert in data.get("inserts", []):
        crossover_id = str(insert["crossover_id"])
        if crossover_id not in selected:
            continue
        samples = _samples_for_insert(data, insert)
        if resolved_index >= len(samples):
            continue
        sample = samples[resolved_index]
        side_info = side_map.get(crossover_id, {
            "side": "unpaired",
            "pair_id": crossover_id,
            "paired_with": None,
            "bp_level": int((insert.get("src") or [None, 0])[1]),
            "helix_pair": sorted((str(insert["src"][0]), str(insert["dst"][0]))),
        })
        record = canonical_medoid(
            sample, insert, side_info,
            sample_index=resolved_index, frame=resolved_frame,
        )
        record.update({
            "pair_id": side_info.get("pair_id", crossover_id),
            "paired_with": side_info.get("paired_with"),
            "requested": crossover_id in requested,
            "quality": {
                "global_paired_fraction": (
                    data.get("paired_fraction", [None] * len(frames))[resolved_index]
                    if resolved_index < len(data.get("paired_fraction", [])) else None
                ),
                "pose_rmsd_A": sample.get("pose_rmsd"),
                "source_pair_distance_A": sample.get("bp_src"),
                "destination_pair_distance_A": sample.get("bp_dst"),
                "source_bond_A": sample.get("bond_src"),
                "destination_bond_A": sample.get("bond_dst"),
            },
        })
        records.append(record)

    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(str(record["pair_id"]), []).append(record)
    groups = []
    for group_id, group_records in grouped.items():
        group_records.sort(key=lambda row: (
            {"i": 0, "i+1": 1}.get(row["side"], 2), row["crossover_id"], row["insert_k"]
        ))
        normals = [
            np.asarray(record["base_orientation"], dtype=float)[:, 2]
            for record in group_records if record.get("base_orientation") is not None
        ]
        separation = None
        if len(normals) == 2:
            separation = float(np.degrees(np.arccos(np.clip(
                np.dot(normals[0], normals[1]), -1.0, 1.0,
            ))))
        groups.append({
            "group_id": group_id,
            "reciprocal_pair": len({row["side"] for row in group_records} & {"i", "i+1"}) == 2,
            "directed_normal_separation_deg": separation,
            "records": group_records,
        })
    groups.sort(key=lambda group: group["group_id"])
    return {
        "schema": SAMPLE_SCHEMA,
        "source_id": source_id,
        "sample_index": resolved_index,
        "frame": resolved_frame,
        "requested_crossover_ids": sorted(requested),
        "resolved_crossover_ids": sorted(selected),
        "include_reciprocal_partners": include_reciprocal_partners,
        "coordinate_frame": ["interhelix", "helix_axis", "out_of_plane"],
        "groups": groups,
    }

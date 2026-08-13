#!/usr/bin/env python3
"""Audit mrDNA seed frames and rendered crossover phase for one job."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.design_geometry import _geometry_for_helices
from backend.core.models import Design
from backend.core.mrdna_bridge import (
    _MRDNA_REVERSE_PAIR_FRAME,
    _build_nt_arrays,
)


def _keyed(rows) -> dict[tuple, np.ndarray]:
    return {
        (
            row["helix_id"], row["bp_index"],
            getattr(row["direction"], "value", row["direction"]),
            int(row.get("copy", 0)),
        ): np.asarray(row["backbone_position"], dtype=float)
        for row in rows
    }


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(np.clip(
        float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))), -1.0, 1.0
    )))


def _frame_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    relative = a.T @ b
    return math.degrees(math.acos(np.clip(
        0.5 * (float(np.trace(relative)) - 1.0), -1.0, 1.0
    )))


def _summary(values: list[float]) -> dict:
    array = np.asarray(values, dtype=float)
    return {
        "min": float(array.min()) if len(array) else None,
        "median": float(np.median(array)) if len(array) else None,
        "p95": float(np.percentile(array, 95)) if len(array) else None,
        "max": float(array.max()) if len(array) else None,
    }


def _crossover_geometry(design: Design, positions: dict) -> dict:
    angles: list[float] = []
    lengths: list[float] = []
    missing = 0
    for crossover in design.crossovers:
        a, b = crossover.half_a, crossover.half_b
        da, db = a.strand.value, b.strand.value
        keys = (
            (a.helix_id, a.index, da, 0),
            (b.helix_id, b.index, db, 0),
            (a.helix_id, a.index, "REVERSE" if da == "FORWARD" else "FORWARD", 0),
            (b.helix_id, b.index, "REVERSE" if db == "FORWARD" else "FORWARD", 0),
        )
        if any(key not in positions for key in keys):
            missing += 1
            continue
        pa, pb, ma, mb = (positions[key] for key in keys)
        ca, cb = 0.5 * (pa + ma), 0.5 * (pb + mb)
        angles.extend((_angle_deg(pa - ca, pb - pa), _angle_deg(pb - cb, pa - pb)))
        lengths.append(float(np.linalg.norm(pb - pa)))
    return {
        "n_endpoint_angles": len(angles),
        "missing_crossovers": missing,
        "outward_endpoints_gt_90_deg": sum(value > 90.0 for value in angles),
        "facing_angle_deg": _summary(angles),
        "bond_length_nm": _summary(lengths),
    }


def audit(job_dir: Path) -> dict:
    design = Design.model_validate_json((job_dir / "design.json").read_text())
    display = json.loads((job_dir / "display.json").read_text())["positions"]
    _r, pairs, _stack, _three, orientations, *_rest = _build_nt_arrays(
        design, return_nt_key=True, return_identity=True
    )
    frame_errors = [
        _frame_angle_deg(
            orientations[i],
            orientations[int(mate)] @ _MRDNA_REVERSE_PAIR_FRAME,
        )
        for i, mate in enumerate(pairs)
        if int(mate) > i
    ]
    native = _keyed(_geometry_for_helices(design, None, junction_balance=False))
    return {
        "job_dir": str(job_dir),
        "n_base_pairs": len(frame_errors),
        "mrdna_reader_pair_frame_error_deg": _summary(frame_errors),
        "native_crossovers": _crossover_geometry(design, native),
        "rendered_crossovers": _crossover_geometry(design, _keyed(display)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", help="mrDNA job id or job directory")
    parser.add_argument("--workspace", default="workspace")
    args = parser.parse_args()
    candidate = Path(args.job)
    job_dir = candidate if candidate.is_dir() else Path(args.workspace) / "mrdna_jobs" / args.job
    print(json.dumps(audit(job_dir), indent=2))


if __name__ == "__main__":
    main()

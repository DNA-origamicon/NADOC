#!/usr/bin/env python3
"""Audit rendered mrDNA duplex slab centers against their paired backbones."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.mrdna_manifest import MrdnaNucleotideManifest


def _unit(value):
    vector = np.asarray(value, dtype=float)
    return vector / np.linalg.norm(vector)


def _slab_center(bead, base, mate_base, tangent, normal):
    """Python equivalent of frontend pairedSlabCenter for measurement."""
    center = np.asarray(base, dtype=float).copy()
    tangent = _unit(tangent)
    normal = _unit(normal)
    center += tangent * 0.5 * (
        np.dot(mate_base, tangent) - np.dot(center, tangent)
    )
    outward = np.asarray(bead, dtype=float) - center
    outward -= tangent * np.dot(outward, tangent)
    distance = float(np.linalg.norm(outward))
    if distance > 1e-9:
        outward /= distance
        in_plane = _unit(normal - tangent * np.dot(normal, tangent))
        tangential = _unit(np.cross(tangent, in_plane))
        support = abs(np.dot(outward, tangential)) * 0.15
        support += abs(np.dot(outward, in_plane)) * 0.35
        center += outward * max(0.0, distance - support + 0.03)
    return center


def audit(job_dir: Path) -> dict:
    manifest = MrdnaNucleotideManifest.load_required(job_dir)
    positions = json.loads((job_dir / "display.json").read_text())["positions"]
    by_identity = {position["identity"]: position for position in positions}
    centers = {}
    outward = []
    missing_base_positions = []
    for record in manifest.records:
        identity = record.identity.key()
        if record.pair is None or identity not in by_identity or record.pair not in by_identity:
            continue
        position = by_identity[identity]
        mate = by_identity[record.pair]
        if "base_position" not in position or "base_position" not in mate:
            missing_base_positions.append(identity)
            continue
        bead = np.asarray(position["backbone_position"], dtype=float)
        mate_bead = np.asarray(mate["backbone_position"], dtype=float)
        center = _slab_center(
            bead,
            position["base_position"],
            mate["base_position"],
            [position["tx"], position["ty"], position["tz"]],
            [position["nx"], position["ny"], position["nz"]],
        )
        centers[identity] = center
        facing = float(np.dot(_unit(center - bead), _unit(mate_bead - bead)))
        if facing <= 0.0:
            outward.append({"identity": identity, "facing_dot": facing})

    face_gaps = []
    seen = set()
    for record in manifest.records:
        identity = record.identity.key()
        if record.pair is None or identity not in centers or record.pair not in centers:
            continue
        token = tuple(sorted((identity, record.pair)))
        if token in seen:
            continue
        seen.add(token)
        position = by_identity[identity]
        mate = by_identity[record.pair]
        direction = _unit(
            np.asarray(mate["backbone_position"]) - position["backbone_position"]
        )
        own_face = centers[identity] + 0.35 * _unit(
            [position["nx"], position["ny"], position["nz"]]
        )
        mate_face = centers[record.pair] + 0.35 * _unit(
            [mate["nx"], mate["ny"], mate["nz"]]
        )
        face_gaps.append(float(np.dot(mate_face - own_face, direction)))

    return {
        "job_dir": str(job_dir),
        "n_duplex_slabs": len(centers),
        "n_pairs": len(face_gaps),
        "missing_base_positions": len(missing_base_positions),
        "outward_slab_centers": len(outward),
        "outward_examples": outward[:10],
        "face_gap_nm": {
            "min": min(face_gaps, default=None),
            "median": float(np.median(face_gaps)) if face_gaps else None,
            "max": max(face_gaps, default=None),
        },
        "passed": not missing_base_positions and not outward,
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

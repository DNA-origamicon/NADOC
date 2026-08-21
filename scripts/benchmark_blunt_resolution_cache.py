#!/usr/bin/env python3
"""Paired production-path benchmark for blunt connector geometry caching."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.core.deformation as deformation
from backend.core.assembly_connectors import (
    _build_world_connector_frames,
    _local_frame_for_label,
)
from backend.core.models import (
    ConnectionType,
    Design,
    Helix,
    InterfacePoint,
    PartInstance,
    PartSourceInline,
    Vec3,
)


def summarize(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "n": len(values),
        "medianMs": statistics.median(ordered),
        "p95Ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "minMs": ordered[0],
        "maxMs": ordered[-1],
        "meanMs": statistics.mean(ordered),
    }


def fixture(helix_count: int = 12) -> tuple[Design, PartInstance, set[str]]:
    helices = []
    labels: set[str] = set()
    points = []
    for index in range(helix_count):
        helix_id = f"h{index}"
        helices.append(
            Helix(
                id=helix_id,
                axis_start={"x": index * 3.0, "y": index % 3, "z": 0.0},
                axis_end={"x": index * 3.0, "y": index % 3, "z": 27.2},
                length_bp=80,
                bp_start=0,
            )
        )
        for bp_spec in ("start", "end", "bp20", "bp60"):
            label = f"blunt:{helix_id}:{bp_spec}"
            labels.add(label)
            points.append(
                InterfacePoint(
                    label=label,
                    position=Vec3(x=-99.0, y=-99.0, z=-99.0),
                    normal=Vec3(x=0.0, y=0.0, z=1.0),
                    connection_type=ConnectionType.BLUNT_END,
                )
            )
    design = Design(helices=helices)
    instance = PartInstance(
        source=PartSourceInline(design=design), interface_points=points
    )
    return design, instance, labels


def legacy_build(design: Design, instance: PartInstance, labels: set[str]) -> dict:
    """Production builder before #50: each label gets a fresh resolution cache."""
    interface_by_label = {point.label: point for point in instance.interface_points}
    transform = instance.transform.to_array()
    frames = {}
    for label in labels:
        local = _local_frame_for_label(
            instance, label, design, interface_by_label.get(label)
        )
        if local is not None:
            frames[(instance.id, label)] = transform @ local
    return frames


def current_build(design: Design, instance: PartInstance, labels: set[str]) -> dict:
    frames, _cache = _build_world_connector_frames(
        {instance.id: instance}, {instance.id: labels}, lambda _instance: design
    )
    return frames


def frame_fingerprint(frames: dict) -> str:
    digest = hashlib.sha256()
    for key in sorted(frames):
        digest.update(repr(key).encode())
        digest.update(np.asarray(frames[key], dtype="<f8").tobytes())
    return digest.hexdigest()


def assert_equivalent(before: dict, after: dict) -> None:
    assert before.keys() == after.keys()
    for key in before:
        np.testing.assert_allclose(before[key], after[key], rtol=0.0, atol=1e-12)


def solver_counts(fn, design, instance, labels) -> dict[str, int]:
    counts = {"deformedHelixAxes": 0, "deformedNucleotidePositions": 0}
    real_axes = deformation.deformed_helix_axes
    real_positions = deformation.deformed_nucleotide_positions

    def counted_axes(*args, **kwargs):
        counts["deformedHelixAxes"] += 1
        return real_axes(*args, **kwargs)

    def counted_positions(*args, **kwargs):
        counts["deformedNucleotidePositions"] += 1
        return real_positions(*args, **kwargs)

    deformation.deformed_helix_axes = counted_axes
    deformation.deformed_nucleotide_positions = counted_positions
    try:
        fn(design, instance, labels)
    finally:
        deformation.deformed_helix_axes = real_axes
        deformation.deformed_nucleotide_positions = real_positions
    return counts


def timed(fn, design, instance, labels, runs: int) -> dict:
    fn(design, instance, labels)
    elapsed = []
    fingerprints = []
    for _ in range(runs):
        started = time.perf_counter()
        frames = fn(design, instance, labels)
        elapsed.append((time.perf_counter() - started) * 1000.0)
        fingerprints.append(frame_fingerprint(frames))
    assert len(set(fingerprints)) == 1
    return {"summary": summarize(elapsed), "frameFingerprint": fingerprints[0]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    design, instance, labels = fixture()

    before_frames = legacy_build(design, instance, labels)
    after_frames = current_build(design, instance, labels)
    assert_equivalent(before_frames, after_frames)
    before_hash = frame_fingerprint(before_frames)
    after_hash = frame_fingerprint(after_frames)
    assert before_hash == after_hash

    report = {
        "fixture": {
            "helices": len(design.helices),
            "connectorLabels": len(labels),
            "endpointLabels": sum(
                label.endswith((":start", ":end")) for label in labels
            ),
            "interiorBpLabels": sum(":bp" in label for label in labels),
        },
        "audit": {
            "actualProductionCurrentPath": "_build_world_connector_frames",
            "realDeformationGeometry": True,
            "coldIncludesResolutionCacheConstruction": True,
            "identicalFrameKeys": len(before_frames),
            "identicalFrameFingerprint": before_hash,
            "maxAbsoluteFrameDelta": max(
                float(np.max(np.abs(before_frames[key] - after_frames[key])))
                for key in before_frames
            ),
            "solverCalls": {
                "before": solver_counts(legacy_build, design, instance, labels),
                "after": solver_counts(current_build, design, instance, labels),
            },
        },
        "before": timed(legacy_build, design, instance, labels, args.runs),
        "after": timed(current_build, design, instance, labels, args.runs),
    }
    rendered = json.dumps(report, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()

"""Reproducible synthetic benchmark for interactive assembly FK propagation."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.assembly_fk import _move_instance_with_fk_delta
from backend.core.assembly_connectors import _enforce_connector_coincidence
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    Design,
    Mat4x4,
    PartInstance,
    PartSourceInline,
)


def _instance(index: int) -> PartInstance:
    transform = np.eye(4)
    transform[0, 3] = index * 0.1
    return PartInstance(
        id=f"i{index}",
        source=PartSourceInline(design=Design()),
        transform=Mat4x4.from_array(transform),
        base_transform=Mat4x4.from_array(transform),
    )


def _assembly(count: int, rigid_every: int, topology: str) -> Assembly:
    instances = [_instance(i) for i in range(count)]
    joints = [
        AssemblyJoint(
            id=f"j{i}",
            joint_type="rigid" if rigid_every and i % rigid_every == 0 else "revolute",
            instance_a_id="i0" if topology == "star" else f"i{i}",
            instance_b_id=f"i{i + 1}",
            axis_origin=[float(i), 0.0, 0.0],
            axis_direction=[0.0, 0.0, 1.0],
        )
        for i in range(count - 1)
    ]
    return Assembly(instances=instances, joints=joints)


def _summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "n": len(samples),
        "medianMs": statistics.median(samples),
        "p95Ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "minMs": ordered[0],
        "maxMs": ordered[-1],
        "meanMs": statistics.mean(samples),
    }


def run(count: int, repeats: int, rigid_every: int, topology: str) -> dict:
    delta = np.eye(4)
    delta[:3, 3] = [1.0, 2.0, 3.0]
    samples = []
    checksum = 0.0
    for _ in range(repeats + 1):
        assembly = _assembly(count, rigid_every, topology)
        started = time.perf_counter()
        moved = _move_instance_with_fk_delta(assembly, "i0", delta, set())
        elapsed = (time.perf_counter() - started) * 1_000
        assert moved
        if rigid_every in (0, 1):
            assert np.allclose(assembly.instances[-1].transform.to_array()[:3, 3], [1 + (count - 1) * 0.1, 2, 3])
        checksum += float(assembly.instances[-1].transform.to_array()[0, 3])
        samples.append(elapsed)
    samples = samples[1:]  # warm-up
    return {"raw": samples, "summary": _summary(samples), "checksum": checksum}


def run_connector_postpass(count: int, repeats: int, topology: str) -> dict:
    samples = []
    checksum = 0
    for _ in range(repeats + 1):
        assembly = _assembly(count, 0, topology)
        started = time.perf_counter()
        _enforce_connector_coincidence(
            assembly, {instance.id for instance in assembly.instances}
        )
        samples.append((time.perf_counter() - started) * 1_000)
        checksum += len(assembly.joints)
    return {"raw": samples[1:], "summary": _summary(samples[1:]), "checksum": checksum}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1500)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--rigid-every", type=int, default=4)
    parser.add_argument("--topology", choices=("chain", "star"), default="chain")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "environment": {"python": platform.python_version()},
        "fixture": {"instances": args.count, "joints": args.count - 1,
                    "rigidEvery": args.rigid_every, "topology": args.topology},
        "fkMove": run(args.count, args.repeats, args.rigid_every, args.topology),
        "connectorPostpass": run_connector_postpass(args.count, args.repeats, args.topology),
    }
    rendered = json.dumps(report, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()

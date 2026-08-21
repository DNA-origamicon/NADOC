"""Paired benchmark for sharing FK adjacency through connector snap postpasses."""

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

from backend.core.assembly_connectors import (  # noqa: E402
    _enforce_connector_coincidence,
    _get_connector_world,
)
from backend.core.assembly_fk import (  # noqa: E402
    _build_inst_by_id,
    _fk_expand_rigid_group,
    _fk_propagate,
)
from backend.core.models import (  # noqa: E402
    AssemblyJoint,
    ConnectionType,
    Design,
    InterfacePoint,
    Mat4x4,
    PartInstance,
    PartSourceInline,
    Vec3,
)


class _Assembly:
    def __init__(self, instances, joints):
        self.instances = instances
        self.joints = joints


def _translation(x: float) -> Mat4x4:
    matrix = np.eye(4)
    matrix[0, 3] = x
    return Mat4x4.from_array(matrix)


def _instance(instance_id: str, label: str, x: float) -> PartInstance:
    return PartInstance(
        id=instance_id,
        source=PartSourceInline(design=Design()),
        transform=_translation(x),
        base_transform=_translation(x),
        interface_points=[InterfacePoint(
            label=label,
            position=Vec3(x=0.0, y=0.0, z=0.0),
            normal=Vec3(x=0.0, y=0.0, z=1.0),
            connection_type=ConnectionType.BLUNT_END,
        )],
    )


def _fixture(pairs: int) -> tuple[_Assembly, set[str]]:
    instances = []
    joints = []
    visited = set()
    for index in range(pairs):
        parent = _instance(f"p{index}", "A", 0.0)
        child = _instance(f"c{index}", "B", float(index + 1))
        instances.extend((parent, child))
        visited.add(child.id)
        joints.append(AssemblyJoint(
            id=f"j{index}", joint_type="rigid",
            instance_a_id=parent.id, connector_a_label="A",
            instance_b_id=child.id, connector_b_label="B",
        ))
    return _Assembly(instances, joints), visited


def _legacy_enforce(assembly, visited: set[str]) -> None:
    """Previous postpass: child index shared, FK adjacency rebuilt per helper/snap."""
    inst_by_id = _build_inst_by_id(assembly)
    joints_by_child: dict[str, list] = {}
    for joint in assembly.joints:
        if (joint.instance_b_id and joint.joint_type in ("rigid", "revolute") and
                joint.connector_a_label and joint.connector_b_label):
            joints_by_child.setdefault(joint.instance_b_id, []).append(joint)
    for child_id in list(visited):
        for joint in joints_by_child.get(child_id, ()):
            if joint.instance_a_id in visited or not joint.instance_a_id:
                continue
            child = inst_by_id.get(child_id)
            parent = inst_by_id.get(joint.instance_a_id)
            if not child or not parent:
                continue
            child_pos = _get_connector_world(child, joint.connector_b_label)
            parent_pos = _get_connector_world(parent, joint.connector_a_label)
            if child_pos is None or parent_pos is None:
                continue
            snap = parent_pos - child_pos
            if np.linalg.norm(snap) < 1e-6:
                continue
            delta = np.eye(4)
            delta[:3, 3] = snap
            child.transform = Mat4x4.from_array(delta @ child.transform.to_array())
            child.base_transform = Mat4x4.from_array(delta @ child.base_transform.to_array())
            joint.axis_origin = parent_pos.tolist()
            snap_visited = {child_id}
            _fk_expand_rigid_group(
                assembly, child_id, delta, snap_visited, [], inst_by_id
            )
            _fk_propagate(assembly, {child_id}, delta, snap_visited, inst_by_id)


def _checksum(assembly) -> int:
    return int(round(sum(instance.transform.to_array()[0, 3] for instance in assembly.instances)))


def _summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "n": len(samples), "medianMs": statistics.median(samples),
        "p95Ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "minMs": ordered[0], "maxMs": ordered[-1], "meanMs": statistics.mean(samples),
    }


def _measure(pairs: int, repeats: int, fn) -> dict:
    samples = []
    checksums = []
    for _ in range(repeats + 1):
        assembly, visited = _fixture(pairs)
        started = time.perf_counter()
        fn(assembly, visited)
        samples.append((time.perf_counter() - started) * 1_000)
        checksums.append(_checksum(assembly))
    return {"raw": samples[1:], "summary": _summary(samples[1:]), "checksum": checksums[-1]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=500)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    before = _measure(args.pairs, args.repeats, _legacy_enforce)
    after = _measure(args.pairs, args.repeats, _enforce_connector_coincidence)
    if before["checksum"] != after["checksum"]:
        raise RuntimeError(f"checksum mismatch: {before['checksum']} != {after['checksum']}")
    report = {
        "environment": {"python": platform.python_version(), "repeats": args.repeats},
        "fixture": {"independentMates": args.pairs, "instances": args.pairs * 2,
                    "joints": args.pairs},
        "sharedFkAdjacency": {"before": before, "after": after},
    }
    rendered = json.dumps(report, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()

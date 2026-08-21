"""Paired benchmark for assembly interface-point label resolution (batch four)."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.models import ConnectionType, InterfacePoint, Vec3


def _fixture(count: int) -> list[InterfacePoint]:
    return [
        InterfacePoint(
            label=f"connector-{index}",
            position=Vec3(x=float(index), y=float(index % 17), z=0.0),
            normal=Vec3(x=0.0, y=0.0, z=1.0),
            connection_type=ConnectionType.BLUNT_END,
        )
        for index in range(count)
    ]


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


def _measure(repeats: int, fn) -> dict:
    fn()
    samples = []
    checksum = 0
    for _ in range(repeats):
        started = time.perf_counter()
        checksum ^= fn()
        samples.append((time.perf_counter() - started) * 1_000)
    return {"raw": samples, "summary": _summary(samples), "checksum": checksum}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", type=int, default=2_000)
    parser.add_argument("--queries", type=int, default=1_000)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    points = _fixture(args.points)
    labels = [
        f"connector-{(index * 7919) % args.points}" for index in range(args.queries)
    ]
    by_label = {point.label: point for point in points}

    def legacy() -> int:
        checksum = 0
        for label in labels:
            point = next(
                (candidate for candidate in points if candidate.label == label), None
            )
            checksum += int(point.position.x) if point else -1
        return checksum

    def indexed() -> int:
        checksum = 0
        for label in labels:
            point = by_label.get(label)
            checksum += int(point.position.x) if point else -1
        return checksum

    before = _measure(args.repeats, legacy)
    after = _measure(args.repeats, indexed)
    if before["checksum"] != after["checksum"]:
        raise RuntimeError(
            f"checksum mismatch: {before['checksum']} != {after['checksum']}"
        )
    report = {
        "environment": {"python": platform.python_version(), "repeats": args.repeats},
        "fixture": {"interfacePoints": args.points, "queries": args.queries},
        "interfacePointLabelIndex": {"before": before, "after": after},
    }
    rendered = json.dumps(report, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()

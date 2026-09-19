"""Paired A/B correctness and latency gate for feature reconstruction.

Run: uv run python -m scripts.benchmark_feature_evaluation --output /tmp/feature-ab.json
Optional --design path.nadoc adds real history cursors. Never writes a design or
calls mutating endpoints. Timing excludes fixture construction and comparisons.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import platform
import statistics
import time
from unittest.mock import patch

from backend.api.crud import _seek_feature_log
from backend.api.state import encode_design_snapshot
from backend.core.design_diff import encode_child_diff
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    ClusterOpLogEntry, ClusterRigidTransform, Design, MinorMutationLogEntry,
    RoutingClusterLogEntry,
)
from scripts import feature_evaluation_reference as reference_evaluator


def scenarios():
    yield "empty", Design(), -1, None
    for count in (1, 4, 1000):
        d = make_bundle_design([(0, 0), (0, 1)], length_bp=84)
        ct = ClusterRigidTransform(id="bench-cluster", helix_ids=[d.helices[0].id])
        log = [ClusterOpLogEntry(cluster_id=ct.id, translation=[float(i), 0, 0],
                                 rotation=[0, 0, 0, 1], pivot=[0, 0, 0])
               for i in range(count)]
        d = d.copy_with(cluster_transforms=[ct], feature_log=log)
        yield f"poses-{count}", d, -1, None
        if count == 1000:
            yield "poses-1000-mid", d, 450, None
    for count in (1, 4, 100):
        anchor = make_bundle_design([(r, c) for r in range(8) for c in range(8)], length_bp=84)
        current = anchor
        children = []
        for i in range(count):
            # Absolute recorded POST objects, like repeated recolors or resizes.
            strand = current.strands[0].model_copy(update={"color": f"#{i + 1:06x}"})
            post = current.copy_with(strands=[strand, *current.strands[1:]])
            a, r, m, size = encode_child_diff(current, post)
            children.append(MinorMutationLogEntry(op_subtype="strands-color-bulk", label="color",
                diff_added_b64=a, diff_removed_b64=r, diff_modified_b64=m, diff_size_bytes=size))
            current = post
        pre, _ = encode_design_snapshot(anchor)
        post, _ = encode_design_snapshot(current)
        cluster = RoutingClusterLogEntry(children=children, pre_state_gz_b64=pre,
                                        post_state_gz_b64=post)
        d = current.copy_with(feature_log=[cluster])
        yield f"patches-{count}", d, 0, count - 1
        yield f"snapshot-{count}", d, -1, None


def compare(name, design, position, sub_position, repeats=21, iterations=30):
    original = design.model_dump()
    reference = reference_evaluator._seek_feature_log(design, position, sub_position)
    candidate = _seek_feature_log(design, position, sub_position, optimized=True)
    assert candidate.model_dump() == reference.model_dump(), f"State mismatch: {name}"
    assert design.model_dump() == original, f"Input mutation: {name}"
    return measure_pair(name, lambda mode: _seek_feature_log(
        design, position, sub_position, optimized=True,
    ) if mode else reference_evaluator._seek_feature_log(design, position, sub_position), repeats, iterations)


def measure_pair(name, run, repeats, iterations):
    samples = {False: [], True: []}
    # Warm both paths, then alternate order to reduce clock/load/cache bias.
    for mode in (False, True):
        run(mode)
    for repeat in range(repeats):
        for mode in ((False, True) if repeat % 2 == 0 else (True, False)):
            gc.collect()
            gc.disable()
            try:
                start = time.perf_counter_ns()
                for _ in range(iterations):
                    run(mode)
                samples[mode].append((time.perf_counter_ns() - start) / iterations / 1e6)
            finally:
                gc.enable()
    a, b = statistics.median(samples[False]), statistics.median(samples[True])
    # A bounded noise allowance, not a promise of zero wall-clock variation.
    regression = b > a * 1.05 and b - a > 0.05
    return {"case": name, "baseline_ms": a, "optimized_ms": b,
            "ratio": b / a, "regression": regression, "equivalent": True,
            "baseline_p95_ms": sorted(samples[False])[int(0.95 * (repeats - 1))],
            "optimized_p95_ms": sorted(samples[True])[int(0.95 * (repeats - 1))],
            "baseline_samples_ms": samples[False], "optimized_samples_ms": samples[True]}


def geometry_comparisons(repeats, iterations, renderers=("compact",)):
    from backend.api import routes_feature_log as routes

    d = make_bundle_design([(0, 0), (0, 1)], length_bp=21)
    d = d.copy_with(
        cluster_transforms=[ClusterRigidTransform(id="A", helix_ids=[d.helices[0].id])],
        feature_log=[ClusterOpLogEntry(cluster_id="A", translation=[float(i), 0, 0],
                     rotation=[0, 0, 0, 1], pivot=[0, 0, 0]) for i in range(4)],
    )
    original = d.model_dump()
    previous_mode = os.environ.get("NADOC_FEATURE_EVALUATION")
    try:
        with patch.object(routes.design_state, "get_or_404", return_value=d):
            for renderer in renderers:
                method = {"compact": "geometry_batch", "atomistic": "atomistic_batch", "surface": "surface_batch"}[renderer]
                for suffix, positions in (("one", [-1]), ("frames", [0, 1, 2, 3]),
                                          ("end-aliases", [0, 3, -1, 99])):
                    name = f"{renderer}-{suffix}"
                    body = (routes.SurfaceBatchBody(positions=positions, grid_spacing=0.6, smooth=1)
                            if renderer == "surface" else routes.GeometryBatchBody(positions=positions))

                    def run(mode):
                        os.environ["NADOC_FEATURE_EVALUATION"] = "optimized" if mode else "baseline"
                        return getattr(routes if mode else reference_evaluator, method)(body)

                    assert run(False) == run(True), f"Geometry mismatch: {name}"
                    yield measure_pair(name, run, repeats, iterations)
    finally:
        if previous_mode is None:
            os.environ.pop("NADOC_FEATURE_EVALUATION", None)
        else:
            os.environ["NADOC_FEATURE_EVALUATION"] = previous_mode
    assert d.model_dump() == original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--design", type=Path, action="append", default=[])
    parser.add_argument("--repeats", type=int, default=21)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--renderers", nargs="+", choices=["compact", "atomistic", "surface"], default=["compact"])
    parser.add_argument("--only-renderers", action="store_true", help="Skip seek cases for a renderer-only A/B run")
    args = parser.parse_args()
    cases = [] if args.only_renderers else list(scenarios())
    for path in args.design:
        design = Design.from_json(path.read_text())
        for position in sorted({-2, -1, len(design.feature_log) // 2}):
            cases.append((f"{path.name}:{position}", design, position, None))
        for i, entry in enumerate(design.feature_log):
            if entry.feature_type == "routing-cluster" and entry.children and not entry.evicted:
                cases.append((f"{path.name}:{i}:mid", design, i, len(entry.children) // 2))
    rows = []

    def report_row(row):
        rows.append(row)
        print(f"{row['case']}: {row['baseline_ms']:.3f} → {row['optimized_ms']:.3f} ms "
              f"({row['ratio']:.3f}×){' REGRESSION' if row['regression'] else ''}", flush=True)

    for case in cases:
        row = compare(*case, repeats=args.repeats, iterations=args.iterations)
        report_row(row)
    for row in geometry_comparisons(args.repeats, args.iterations, args.renderers):
        report_row(row)
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "gate": "Fail when median increases by both >5% and >0.05 ms",
              "timing": "Warmed alternating A/B batches; cyclic GC disabled only during timing; p95 across batch means",
              "repeats": args.repeats, "iterations": args.iterations, "results": rows}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    raise SystemExit(1 if any(row["regression"] for row in rows) else 0)


if __name__ == "__main__":
    main()

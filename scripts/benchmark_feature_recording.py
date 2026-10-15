"""Paired in-memory recording benchmark against state.py at a Git revision.

Run with `just validate-safe uv run python -m scripts.benchmark_feature_recording`.
Writes only a compact JSON report to stdout; never opens or saves user designs.
The baseline executes the two original recording functions with unchanged state
services, so this isolates recording orchestration rather than geometry kernels.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import gc
import json
import statistics
import subprocess
import time
import tracemalloc

from backend.api import state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.core.lattice import make_bundle_design
from backend.core.models import SnapshotLogEntry


def baseline_functions(ref):
    source = subprocess.check_output(["git", "show", f"{ref}:backend/api/state.py"], text=True)
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
             and n.name in {"mutate_with_feature_log", "mutate_with_minor_log"}]
    if len(nodes) != 2:
        raise ValueError("Baseline must contain both recording functions")
    namespace = dict(vars(state))
    namespace["_dt"] = datetime
    # Old source references this compatibility hook; it has been a no-op since
    # canonical payload retention shipped, before this recording refactor.
    namespace["_evict_oldest_payloads_if_over_budget"] = lambda design: None
    from backend.core.models import RoutingClusterLogEntry
    namespace["RoutingClusterLogEntry"] = RoutingClusterLogEntry
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "baseline_recording", "exec"), namespace)
    return namespace


def canonical(design):
    value = design.model_dump(mode="json")
    for entry in value["feature_log"]:
        entry.pop("id", None)
        entry.pop("timestamp", None)
        for child in entry.get("children", []):
            child.pop("id", None)
            child.pop("timestamp", None)
    return value


def run(fn, template, *, disable_gc=False):
    state.load_design(template.model_copy(deep=True))
    before_revision = state.revision()
    was_enabled = gc.isenabled()
    if disable_gc:
        gc.disable()
    try:
        start = time.perf_counter()
        result, _, _ = fn("nick", "Recording benchmark", {},
                           lambda d: setattr(d.metadata, "name", "Recorded"))
        elapsed = (time.perf_counter() - start) * 1000
    finally:
        if disable_gc and was_enabled:
            gc.enable()
    assert state.revision() == before_revision + 1
    assert state.undo_depth() == 1 and state.redo_depth() == 0
    return elapsed, result


def percentile95(values):
    return sorted(values)[min(len(values) - 1, int(len(values) * .95))]


def allocation_peak(fn, template):
    """Python allocation peak including fixture copy; native allocations excluded."""
    tracemalloc.start()
    try:
        run(fn, template)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="dfa63eeb")
    parser.add_argument("--repeats", type=int, default=31)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--include-gc", action="store_true")
    args = parser.parse_args()
    if args.repeats < 5:
        parser.error("At least five paired repeats are required")
    if args.iterations < 1:
        parser.error("At least one iteration is required")
    ref = subprocess.check_output(["git", "rev-parse", args.baseline_ref], text=True).strip()
    baseline = baseline_functions(ref)
    token = set_current_doc("feature-recording-offline-benchmark")
    cases = []
    try:
        for helices, history in [(1, 0), (24, 0), (24, 100)]:
            template = make_bundle_design([(r, 0) for r in range(helices)], length_bp=84)
            body, size = state.encode_design_snapshot(template)
            template.feature_log = [SnapshotLogEntry(
                op_kind="nick", label="Historical recovery state", params={},
                design_snapshot_gz_b64=body, snapshot_size_bytes=size,
                post_state_gz_b64=body, post_state_size_bytes=size,
            ) for _ in range(history)]
            for name in ("mutate_with_feature_log", "mutate_with_minor_log"):
                old, new = baseline[name], getattr(state, name)
                _, left = run(old, template)
                _, right = run(new, template)
                assert canonical(left) == canonical(right), (name, helices, history)
                samples = {"baseline": [], "candidate": []}
                for i in range(args.repeats):
                    order = [("baseline", old), ("candidate", new)]
                    if i % 2:
                        order.reverse()
                    for label, fn in order:
                        batch = [run(fn, template, disable_gc=not args.include_gc)[0]
                                 for _ in range(args.iterations)]
                        samples[label].append(statistics.mean(batch))
                medians = {k: statistics.median(v) for k, v in samples.items()}
                p95 = {k: percentile95(v) for k, v in samples.items()}
                # Existing feature microbenchmark gate; report, never hide noise.
                regression = (medians["candidate"] > medians["baseline"] * 1.05
                              and medians["candidate"] - medians["baseline"] > .05)
                peaks = {"baseline": allocation_peak(old, template),
                         "candidate": allocation_peak(new, template)}
                cases.append({"operation": name, "helices": helices, "history": history,
                              "median_ms": medians, "p95_ms": p95,
                              "python_peak_bytes_including_fixture_copy": peaks,
                              "regression": regression, "samples_ms": samples})
    finally:
        state.close_session()
        reset_current_doc(token)
    print(json.dumps({"baseline_revision": ref, "repeats": args.repeats,
                      "iterations": args.iterations, "gc_in_timed_region": args.include_gc,
                      "scope": "recording orchestration; in-memory, warm, no rendering or HTTP",
                      "cases": cases}, indent=2))
    return int(any(c["regression"] for c in cases))


if __name__ == "__main__":
    raise SystemExit(main())

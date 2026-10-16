#!/usr/bin/env python3
"""Paired extraction diagnostic; six in-memory sources, no proof or workers.

The historical function shares current imported dependencies, not a historical
binary. Natural GC, the monotonic clock and ordinary capture limits stay intact.
"""

import argparse
import gc
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import subprocess
from time import perf_counter
from types import ModuleType

from backend.api.part_recovery_budget import RecoveryBudget
from backend.core import part_capture_inputs as current
from scripts.benchmark_np_application import prefix
from scripts.benchmark_part_inputs import source
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms


REFERENCE = "5783b656"
SOURCE_PATH = "backend/core/part_capture_inputs.py"
ARGS = dict(max_nodes=30_000, max_bytes=2_000_000, seconds=.025,
            preserve_entry_types=False, copy_inputs=True, retain_owned=False)
TRIGGER = {"relative_median_regression": .05, "absolute_median_regression_ms": .05}


def old_module():
    root = Path(__file__).resolve().parents[1]
    raw = subprocess.run(["git", "show", f"{REFERENCE}:{SOURCE_PATH}"], cwd=root,
                         check=True, capture_output=True).stdout
    module = ModuleType("_capture_reference_5783b656")
    exec(compile(raw, f"git:{REFERENCE}:{SOURCE_PATH}", "exec"), module.__dict__)
    if module.monotonic is not current.monotonic:
        raise RuntimeError("Capture arms do not share the same monotonic clock")
    return module, {"reference": REFERENCE, "reference_source_sha256": hashlib.sha256(raw).hexdigest(),
        "current_source_sha256": hashlib.sha256(Path(current.__file__).read_bytes()).hexdigest(),
        "current_graph_sha256": hashlib.sha256((root / "backend/core/part_capture_graph.py").read_bytes()).hexdigest()}


def stats(values):
    ordered = sorted(values)
    return {"count": len(values), "median_ms": median(values) if values else None,
        "p95_ms": ordered[math.ceil(len(ordered) * .95) - 1] if ordered else None,
        "max_ms": ordered[-1] if ordered else None}


def measure(module, design, probe):
    result, status, error = None, "ok", None
    started = perf_counter()
    try:
        result = module.visit_inputs(design, **ARGS)
    except module.CaptureLimit as failure:
        status, error = "capture_limit", str(failure)
    except Exception as failure:
        status, error = "error", f"{type(failure).__name__}: {failure}"
    ended = perf_counter()
    events = probe.intervals(started, ended)
    return result, [status, (ended - started) * 1000, overlap_ms(events, started, ended),
                    sorted({event["generation"] for event in events}), error]


def summarize(case):
    paired = [pair for pair in case["pairs"] if all(sample[0] == "ok" for sample in pair)]
    case["matched_success_pairs"] = len(paired)
    case["all_sample_timings"] = {mode: stats([p[i][1] for p in case["pairs"]])
        for i, mode in enumerate(("old", "current"))}
    case["capture_refusals"] = {mode: sum(p[i][0] == "capture_limit" for p in case["pairs"])
        for i, mode in enumerate(("old", "current"))}
    case["unmatched_admission_pairs"] = [i for i, p in enumerate(case["pairs"])
        if (p[0][0] == "ok") != (p[1][0] == "ok")]
    old, new = ([p[i][1] for p in paired] for i in (0, 1))
    case["matched_timings"] = {"old": stats(old), "current": stats(new),
        "paired_current_minus_old": stats([b - a for a, b in zip(old, new)])}
    difference = median(new) - median(old) if paired else None
    relative = difference / median(old) if paired and median(old) else None
    case["median_difference_ms"], case["median_relative_regression"] = difference, relative
    case["review_trigger"] = (difference > TRIGGER["absolute_median_regression_ms"]
        and relative > TRIGGER["relative_median_regression"]) if relative is not None else None


def run_case(case, factory, old, repeats, probe, phase):
    expected = None
    try:
        phase[0] = f"{case['case']}:fixture"
        design = factory()
        original = design.model_dump()
        case["source_counts"] = {"rows": len(design.feature_log), "helices": len(design.helices),
            "strands": len(design.strands), "protein_assets": len(design.protein_assets)}
        for iteration in range(repeats):
            outputs, pair, source_matches = {}, [None, None], []
            for index in ((0, 1) if iteration % 2 == 0 else (1, 0)):
                phase[0] = f"{case['case']}:{iteration}:{('old', 'current')[index]}"
                outputs[index], pair[index] = measure((old, current)[index], design, probe)
                phase[0] = f"{case['case']}:outside_timing_source_check"
                source_matches.append(design.model_dump() == original)
                case["source_immutability_checks"] += 1
            case["pairs"].append(pair)
            phase[0] = f"{case['case']}:outside_timing_checks"
            if not all(source_matches):
                raise AssertionError("Capture changed its source model")
            for index, value in outputs.items():
                if pair[index][0] == "error":
                    raise RuntimeError(pair[index][4])
                if value is not None:
                    # Proof headers intentionally use projected history models;
                    # compare their values without expected serializer warnings.
                    snapshot = value.model_dump(warnings=False)
                    if expected is None:
                        expected = snapshot
                    elif snapshot != expected:
                        raise AssertionError("Captured model_dump differs between arms or repetitions")
                    case["output_parity_checks"] += 1
            del outputs, pair, value
        case["completed"] = True
    except Exception as failure:
        case["failure"] = f"{type(failure).__name__}: {failure}"
    finally:
        summarize(case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=31)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 1000:
        parser.error("repeats must be between 1 and 1000")
    report = {"scope": "Shared capture extraction diagnostic; no public latency qualification",
        "capture_args": ARGS, "repeats": args.repeats, "review_trigger_policy": TRIGGER,
        "pair_columns": ["old", "current"],
        "sample_columns": ["status", "elapsed_ms", "gc_overlap_ms", "gc_generations", "error"],
        "notes": ["Both functions use current imported dependencies and the same real monotonic clock.",
            "Pair order alternates; all refusals retained without retry, limit increase or GC policy changes.",
            "Parity/source checks and fixture construction are outside capture timing.",
            "Trigger compares matched-success arm medians; refusals/unmatched pairs remain separate evidence.",
            "GC overlap is correlation, never subtracted from latency. No peak-memory qualification."],
        "cases": [], "completed": False, "failure": None, "latency_qualified": False}
    phase, callbacks = ["setup"], tuple(gc.callbacks)
    probe = RuntimeProbe(phase=lambda: phase[0], max_events=4096)
    try:
        old, report["sources"] = old_module()
        factories = [(f"protein-{count}", lambda count=count: source(count)) for count in (32, 128)]
        factories += [(f"np-{background}-{handles}",
            lambda background=background, handles=handles: prefix(handles, background, RecoveryBudget()))
            for background in ("six-cell", "36-cell-42bp") for handles in (1, 16)]
        with probe:
            for name, factory in factories:
                case = {"case": name, "pairs": [], "completed": False, "failure": None,
                        "source_immutability_checks": 0, "output_parity_checks": 0}
                report["cases"].append(case)
                run_case(case, factory, old, args.repeats, probe, phase)
        report["completed"] = True
    except Exception as failure:
        report["failure"] = f"{type(failure).__name__}: {failure}"
    finally:
        report["cleanup_verified"] = tuple(gc.callbacks) == callbacks
        report["diagnostics"] = {"event_limit": probe.max_events, "gc_events": len(probe.events),
                                 "dropped_gc_events": probe.dropped_events}
        report["correctness_verified"] = (report["completed"] and report["cleanup_verified"]
            and all(c["completed"] and c["matched_success_pairs"] > 0 for c in report["cases"]))
        report["review_required"] = any(c.get("review_trigger") is True for c in report["cases"])
        report["exit_status_basis"] = "Correctness/cleanup; refusals and review triggers require separate review"
        print(json.dumps(report, indent=2, allow_nan=False))
    return int(not report["correctness_verified"])


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Benchmark the exact backend work used by the oxDNA full-trajectory viewer."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api import routes_oxdna
from backend.core.oxdna_health import composite_trajectory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id", help="oxDNA job id under workspace/oxdna_jobs")
    parser.add_argument("--scope", choices=("job", "lineage"), default="job")
    parser.add_argument("--json-estimate", action="store_true")
    args = parser.parse_args()

    job = routes_oxdna._load_job(args.job_id)
    design, stages, ref = routes_oxdna._composite_inputs(job, args.scope)
    started = time.perf_counter()
    phase_completed: dict[str, float] = {}

    def phase(name: str, done: int, total: int) -> None:
        if done == total:
            phase_completed[name] = time.perf_counter() - started

    result = composite_trajectory(
        design,
        stages,
        ref,
        0 if args.scope == "job" else routes_oxdna._SPARSE_FRAME_CAP,
        None,
        True,
        routes_oxdna._capture_bead_count(job),
        routes_oxdna._capture_strand_length(job),
        phase,
        True,
    )
    frames = result["frames"]
    report = {
        "job_id": args.job_id,
        "scope": args.scope,
        "frames": result["n_frames"],
        "n_nucleotides": result["n_nucleotides"],
        "elapsed_s": round(time.perf_counter() - started, 3),
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "binary_bytes": frames.nbytes,
        "phase_completed_s": {k: round(v, 3) for k, v in phase_completed.items()},
    }
    if args.json_estimate and len(frames):
        sample = len(json.dumps(frames[0].tolist(), separators=(",", ":")).encode())
        report["estimated_json_bytes"] = sample * len(frames)
        report["json_to_binary_ratio"] = round(
            report["estimated_json_bytes"] / frames.nbytes, 2
        )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

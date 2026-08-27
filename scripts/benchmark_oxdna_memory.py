#!/usr/bin/env python3
"""Compare upstream and adaptive-memory oxDNA builds on one CUDA input."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


_PATTERNS = {
    "allocated_cuda_mb": re.compile(r"Allocated CUDA memory: ([0-9.]+) MBs"),
    "initial_capacity": re.compile(r"CUDA max_neigh: (\d+)"),
    "observed_max_neighbors": re.compile(
        r"CUDA adaptive neighbour telemetry: (\d+) observed max"
    ),
    "grown_capacity": re.compile(
        r"CUDA adaptive neighbour list grew to (\d+) entries"
    ),
    "edge_capacity_mb": re.compile(
        r"CUDA adaptive edge list: .*?([0-9.]+) MBs"
    ),
    "runtime_s": re.compile(r"Total Running Time: ([0-9.]+) s"),
    "ms_per_step": re.compile(r"per step: ([0-9.]+) ms"),
}


def parse_oxdna_log(text: str) -> dict[str, float | int | None]:
    result: dict[str, float | int | None] = {}
    integer_fields = {
        "initial_capacity",
        "observed_max_neighbors",
        "grown_capacity",
    }
    for name, pattern in _PATTERNS.items():
        matches = pattern.findall(text)
        result[name] = None
        if matches:
            value = matches[-1]
            result[name] = int(value) if name in integer_fields else float(value)
    return result


def run_case(binary: Path, input_path: Path, *, steps: int, adaptive: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="nadoc-oxdna-memory-") as tmp:
        out = Path(tmp)
        command = [
            str(binary),
            str(input_path),
            "seed=424242",
            f"steps={steps}",
            f"print_conf_interval={steps}",
            f"print_energy_every={steps}",
            f"trajectory_file={out / 'trajectory.dat'}",
            f"energy_file={out / 'energy.dat'}",
            f"lastconf_file={out / 'last_conf.dat'}",
        ]
        if adaptive:
            command.extend(
                [
                    "adaptive_neighbor_list=true",
                    "adaptive_neighbor_initial_capacity=64",
                ]
            )
        proc = subprocess.run(
            command,
            cwd=out,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        result = parse_oxdna_log(proc.stdout)
        result.update(returncode=proc.returncode, command=command)
        if proc.returncode:
            result["log_tail"] = proc.stdout[-4000:]
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--upstream-bin", type=Path, required=True)
    parser.add_argument("--adaptive-bin", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=10_000)
    args = parser.parse_args()

    upstream = run_case(args.upstream_bin, args.input.resolve(), steps=args.steps, adaptive=False)
    adaptive = run_case(args.adaptive_bin, args.input.resolve(), steps=args.steps, adaptive=True)
    report = {"upstream": upstream, "adaptive": adaptive}
    before = upstream["allocated_cuda_mb"]
    after = adaptive["allocated_cuda_mb"]
    if isinstance(before, float) and isinstance(after, float) and after > 0:
        report["allocated_memory_reduction_x"] = before / after
    before_ms = upstream["ms_per_step"]
    after_ms = adaptive["ms_per_step"]
    if isinstance(before_ms, float) and isinstance(after_ms, float) and before_ms > 0:
        report["runtime_ratio"] = after_ms / before_ms
    print(json.dumps(report, indent=2))
    return 0 if upstream["returncode"] == adaptive["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

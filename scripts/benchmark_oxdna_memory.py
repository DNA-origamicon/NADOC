#!/usr/bin/env python3
"""Compare upstream and adaptive-memory oxDNA builds on one CUDA input."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
import time
from pathlib import Path


_PATTERNS = {
    "allocated_cuda_mb": re.compile(r"Allocated CUDA memory: ([0-9.]+) MBs"),
    "cell_storage_mb": re.compile(r"CUDA Cells mem: ([0-9.]+) MBs"),
    "initial_capacity": re.compile(r"CUDA max_neigh: (\d+)"),
    "observed_max_neighbors": re.compile(
        r"CUDA adaptive neighbour telemetry: (\d+) observed max"
    ),
    "grown_capacity": re.compile(
        r"CUDA adaptive neighbour list grew to (\d+) entries"
    ),
    "grown_neighbor_mb": re.compile(
        r"CUDA adaptive neighbour list grew to .*?\(([0-9.]+) MBs\)"
    ),
    "edge_capacity_mb": re.compile(
        r"CUDA adaptive edge list: .*?([0-9.]+) MBs"
    ),
    "runtime_s": re.compile(r"Total Running Time: ([0-9.]+) s"),
    "ms_per_step": re.compile(r"per step: ([0-9.]+) ms"),
}

_OBSERVABLES_PATTERN = re.compile(r"\*\*\*> Observables\s+([0-9.]+)")


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
    observables = _OBSERVABLES_PATTERN.findall(text)
    if observables:
        result["observables_s"] = float(observables[-1])
    return result


def _query_device_used_mb() -> int | None:
    try:
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return int(query.stdout.splitlines()[0].strip())
    except (FileNotFoundError, IndexError, ValueError):
        return None


def tile_oxdna_system(
    topology: Path, configuration: Path, copies: int, destination: Path
) -> tuple[Path, Path]:
    """Create non-overlapping translated copies for capacity benchmarking."""
    if copies < 1:
        raise ValueError("copies must be at least 1")
    destination.mkdir(parents=True, exist_ok=True)
    top_lines = topology.read_text(encoding="utf-8").splitlines()
    n_particles, n_strands = (int(value) for value in top_lines[0].split()[:2])
    tiled_top = [f"{n_particles * copies} {n_strands * copies}"]
    particles = top_lines[1:]
    for copy_index in range(copies):
        particle_offset = copy_index * n_particles
        strand_offset = copy_index * n_strands
        for line in particles:
            fields = line.split()
            fields[0] = str(int(fields[0]) + strand_offset)
            for neighbor_index in (2, 3):
                value = int(fields[neighbor_index])
                if value >= 0:
                    fields[neighbor_index] = str(value + particle_offset)
            tiled_top.append(" ".join(fields))

    conf_lines = configuration.read_text(encoding="utf-8").splitlines()
    particle_lines = conf_lines[3:]
    xy = [[float(value) for value in line.split()[:2]] for line in particle_lines]
    span = max(max(row[i] for row in xy) - min(row[i] for row in xy) for i in (0, 1))
    spacing = span + 10.0
    side = math.ceil(math.sqrt(copies))
    box = [float(value) for value in conf_lines[1].split("=", 1)[1].split()]
    box[0] = max(box[0], side * spacing + 20.0)
    box[1] = max(box[1], side * spacing + 20.0)
    cubic_side = max(box)
    box = [cubic_side, cubic_side, cubic_side]
    tiled_conf = ["t = 0", "b = " + " ".join(str(value) for value in box), "E = 0 0 0"]
    for copy_index in range(copies):
        row, col = divmod(copy_index, side)
        dx = (col - (side - 1) / 2) * spacing
        dy = (row - (side - 1) / 2) * spacing
        for line in particle_lines:
            fields = line.split()
            fields[0] = str(float(fields[0]) + dx)
            fields[1] = str(float(fields[1]) + dy)
            tiled_conf.append(" ".join(fields))

    top_out = destination / "tiled.top"
    conf_out = destination / "tiled.dat"
    top_out.write_text("\n".join(tiled_top) + "\n", encoding="utf-8")
    conf_out.write_text("\n".join(tiled_conf) + "\n", encoding="utf-8")
    return top_out, conf_out


def run_case(
    binary: Path,
    input_path: Path,
    *,
    steps: int,
    adaptive: bool,
    copies: int = 1,
    discard_output: bool = False,
    suppress_periodic_output: bool = False,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="nadoc-oxdna-memory-") as tmp:
        out = Path(tmp)
        trajectory = Path("/dev/null") if discard_output else out / "trajectory.dat"
        energy = Path("/dev/null") if discard_output else out / "energy.dat"
        last_conf = Path("/dev/null") if discard_output else out / "last_conf.dat"
        output_interval = steps + 1 if suppress_periodic_output else steps
        command = [
            str(binary),
            str(input_path),
            "seed=424242",
            f"steps={steps}",
            f"print_conf_interval={output_interval}",
            f"print_energy_every={output_interval}",
            f"trajectory_file={trajectory}",
            f"energy_file={energy}",
            f"lastconf_file={last_conf}",
        ]
        if copies > 1:
            settings = {}
            for raw_line in input_path.read_text(encoding="utf-8").splitlines():
                if "=" in raw_line:
                    key, value = raw_line.split("=", 1)
                    settings[key.strip()] = value.strip()
            topology, configuration = tile_oxdna_system(
                Path(settings["topology"]), Path(settings["conf_file"]), copies, out
            )
            command.extend([f"topology={topology}", f"conf_file={configuration}"])
        if adaptive:
            command.extend(
                [
                    "adaptive_neighbor_list=true",
                    "adaptive_neighbor_initial_capacity=64",
                    "adaptive_compact_cells=true",
                ]
            )
        baseline_device_vram_mb = _query_device_used_mb()
        proc = subprocess.Popen(
            command,
            cwd=out,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        peak_process_vram_mb: int | None = None
        peak_device_vram_mb = baseline_device_vram_mb
        while proc.poll() is None:
            device_used = _query_device_used_mb()
            if device_used is not None:
                peak_device_vram_mb = max(peak_device_vram_mb or 0, device_used)
            try:
                query = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-compute-apps=pid,used_memory",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                for line in query.stdout.splitlines():
                    fields = [field.strip() for field in line.split(",")]
                    if len(fields) == 2 and fields[0] == str(proc.pid):
                        used = int(fields[1])
                        peak_process_vram_mb = max(peak_process_vram_mb or 0, used)
            except (FileNotFoundError, ValueError):
                pass
            time.sleep(0.05)
        stdout, _ = proc.communicate()
        result = parse_oxdna_log(stdout)
        runtime_s = result.get("runtime_s")
        observables_s = result.get("observables_s")
        if (
            isinstance(runtime_s, float)
            and isinstance(observables_s, float)
            and steps > 0
        ):
            result["non_observable_runtime_s"] = max(
                0.0, runtime_s - observables_s
            )
            result["non_observable_ms_per_step"] = (
                1000.0 * result["non_observable_runtime_s"] / steps
            )
        result.update(
            returncode=proc.returncode,
            command=command,
            peak_process_vram_mb=peak_process_vram_mb,
            baseline_device_vram_mb=baseline_device_vram_mb,
            peak_device_vram_mb=peak_device_vram_mb,
            peak_device_delta_mb=(
                peak_device_vram_mb - baseline_device_vram_mb
                if peak_device_vram_mb is not None
                and baseline_device_vram_mb is not None
                else None
            ),
        )
        if proc.returncode:
            result["log_tail"] = stdout[-4000:]
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--upstream-bin", type=Path, required=True)
    parser.add_argument("--adaptive-bin", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=10_000)
    parser.add_argument("--copies", type=int, default=1)
    parser.add_argument("--adaptive-only", action="store_true")
    parser.add_argument("--discard-output", action="store_true")
    args = parser.parse_args()

    upstream = None
    if not args.adaptive_only:
        upstream = run_case(
            args.upstream_bin,
            args.input.resolve(),
            steps=args.steps,
            adaptive=False,
            copies=args.copies,
            discard_output=args.discard_output,
        )
    adaptive = run_case(
        args.adaptive_bin,
        args.input.resolve(),
        steps=args.steps,
        adaptive=True,
        copies=args.copies,
        discard_output=args.discard_output,
    )
    report = {"upstream": upstream, "adaptive": adaptive}
    before = upstream["allocated_cuda_mb"] if upstream is not None else None
    after = adaptive["allocated_cuda_mb"]
    if isinstance(before, float) and isinstance(after, float) and after > 0:
        report["allocated_memory_reduction_x"] = before / after
    before_ms = upstream["ms_per_step"] if upstream is not None else None
    after_ms = adaptive["ms_per_step"]
    if isinstance(before_ms, float) and isinstance(after_ms, float) and before_ms > 0:
        report["runtime_ratio"] = after_ms / before_ms
    print(json.dumps(report, indent=2))
    upstream_ok = upstream is None or upstream["returncode"] == 0
    return 0 if upstream_ok and adaptive["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

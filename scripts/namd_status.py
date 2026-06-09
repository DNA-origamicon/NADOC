#!/usr/bin/env python3
"""Report quick progress for currently running NAMD jobs.

The script discovers live ``namd2``/``namd3`` processes from ``/proc``, infers
their working directory and configuration file, then parses nearby NAMD logs and
restart files for a concise status update.

Usage:
    python scripts/namd_status.py
    python scripts/namd_status.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


BENCH_RE = re.compile(
    r"Benchmark time:\s+\d+\s+CPUs\s+([0-9.eE+-]+)\s+s/step\s+([0-9.eE+-]+)\s+days/ns"
)
ENERGY_RE = re.compile(r"^ENERGY:\s+(.*)$")
ETITLE_RE = re.compile(r"^ETITLE:\s+(.*)$")
FATAL_RE = re.compile(r"\b(FATAL ERROR|CUDA error|Segmentation fault|aborted|ERROR:)\b", re.I)


@dataclass
class NamdRunStatus:
    pid: int
    command: list[str]
    cwd: str | None
    config: str | None
    log: str | None
    output_name: str | None
    restart_xsc: str | None
    elapsed_wall: str | None = None
    cpu_percent: float | None = None
    mem_percent: float | None = None
    affinity: str | None = None
    current_step: int | None = None
    start_step: int | None = None
    target_step: int | None = None
    run_steps: int | None = None
    timestep_fs: float | None = None
    progress_percent: float | None = None
    ns_done: float | None = None
    ns_remaining: float | None = None
    recent_ns_per_day: float | None = None
    recent_s_per_step: float | None = None
    eta_hours: float | None = None
    last_energy_step: int | None = None
    temp_k: float | None = None
    tempavg_k: float | None = None
    pressure_bar: float | None = None
    volume_a3: float | None = None
    last_error: str | None = None
    warnings: list[str] = field(default_factory=list)


def read_cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [p.decode(errors="replace") for p in raw.split(b"\0") if p]


def proc_cwd(pid: int) -> Path | None:
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd"))
    except OSError:
        return None


def is_namd_cmd(cmd: list[str]) -> bool:
    if not cmd:
        return False
    exe = Path(cmd[0]).name.lower()
    return exe in {"namd2", "namd3"} or exe.startswith("namd")


def discover_namd_pids() -> list[int]:
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if is_namd_cmd(read_cmdline(pid)):
            pids.append(pid)
    return sorted(pids)


def format_elapsed(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def read_stat_times(pid: int) -> tuple[float | None, float | None, float | None, str | None]:
    """Return cpu%, mem%, elapsed wall string, processor if available."""
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "pcpu=,pmem=,etimes=,psr="],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        parts = out.split()
        if len(parts) >= 4:
            return float(parts[0]), float(parts[1]), float(parts[2]), parts[3]
    except Exception:
        return None, None, None, None
    return None, None, None, None


def read_affinity(pid: int) -> str | None:
    """Summarize per-thread CPU affinity masks.

    Charm++ pins worker threads individually, so the process leader often shows
    only CPU 0. A per-task summary is much more useful for NAMD.
    """
    masks: dict[str, int] = {}
    try:
        task_dir = Path(f"/proc/{pid}/task")
        for task in task_dir.iterdir():
            status = task / "status"
            for line in status.read_text(errors="replace").splitlines():
                if line.startswith("Cpus_allowed_list:"):
                    mask = line.split(":", 1)[1].strip()
                    masks[mask] = masks.get(mask, 0) + 1
                    break
    except OSError:
        return None
    if not masks:
        return None
    if len(masks) == 1:
        return next(iter(masks))
    single_cpus = sorted(int(mask) for mask, count in masks.items() if count == 1 and mask.isdigit())
    parts: list[str] = []
    if single_cpus:
        ranges: list[str] = []
        start = prev = single_cpus[0]
        for cpu in single_cpus[1:]:
            if cpu == prev + 1:
                prev = cpu
                continue
            ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = cpu
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        parts.append(f"{','.join(ranges)} ({len(single_cpus)} pinned threads)")
    for mask, count in sorted(masks.items()):
        if count == 1 and mask.isdigit():
            continue
        parts.append(f"{mask}x{count}")
    return ", ".join(parts)


def infer_config(cmd: list[str], cwd: Path | None) -> Path | None:
    for arg in reversed(cmd[1:]):
        if arg.endswith((".namd", ".conf")):
            p = Path(arg)
            return p if p.is_absolute() else ((cwd or Path.cwd()) / p)
    return None


def parse_simple_config(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    data: dict[str, str] = {}
    try:
        for raw in path.read_text(errors="replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].lower()
                if key in {
                    "outputname",
                    "run",
                    "minimize",
                    "timestep",
                    "firsttimestep",
                    "extendedsystem",
                    "bincoordinates",
                    "binvelocities",
                    "dcdfile",
                    "xstfile",
                }:
                    data[key] = parts[1]
    except OSError:
        return data
    return data


def tail_text(path: Path, max_bytes: int = 4_000_000) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            return fh.read().decode(errors="replace")
    except OSError:
        return ""


def head_text(path: Path, max_bytes: int = 500_000) -> str:
    try:
        with path.open("rb") as fh:
            return fh.read(max_bytes).decode(errors="replace")
    except OSError:
        return ""


def find_log(cwd: Path | None, config: Path | None) -> Path | None:
    if not cwd:
        return None
    candidates: list[Path] = []
    if config:
        candidates.extend(
            [
                cwd / f"{config.stem}.log",
                cwd / "output" / f"{config.stem}.log",
                config.with_suffix(".log"),
            ]
        )
    candidates.extend(sorted(cwd.glob("*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True))
    candidates.extend(
        sorted((cwd / "output").glob("*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        if (cwd / "output").is_dir()
        else []
    )
    seen: set[Path] = set()
    config_name = config.name if config else None
    for path in candidates:
        if path in seen or not path.exists() or not path.is_file():
            continue
        seen.add(path)
        if not config_name:
            return path
        text = tail_text(path, 300_000)
        if f"Configuration file is {config_name}" in text or path.name == f"{config.stem}.log":
            return path
    return None


def parse_log(path: Path | None) -> dict[str, object]:
    result: dict[str, object] = {
        "benchmark_ns_day": [],
        "benchmark_s_step": [],
        "last_energy": None,
        "first_energy_step": None,
        "last_error": None,
    }
    if not path or not path.exists():
        return result
    head = head_text(path)
    tail = tail_text(path)
    text = head if head == tail else head + "\n" + tail
    cols: dict[str, int] = {}
    first_energy_step: int | None = None
    last_energy: dict[str, float] | None = None
    for line in text.splitlines():
        m = ETITLE_RE.match(line)
        if m:
            fields = m.group(1).split()
            cols = {name: i for i, name in enumerate(fields)}
            continue
        m = ENERGY_RE.match(line)
        if m:
            vals = m.group(1).split()
            try:
                nums = [float(v) for v in vals]
            except ValueError:
                continue
            if nums:
                step = int(nums[0])
                if first_energy_step is None:
                    first_energy_step = step
                last_energy = {"TS": step}
                for name, idx in cols.items():
                    if idx < len(nums):
                        last_energy[name] = nums[idx]
            continue
        m = BENCH_RE.search(line)
        if m:
            try:
                s_step = float(m.group(1))
                days_ns = float(m.group(2))
                if days_ns > 0:
                    result["benchmark_ns_day"].append(1.0 / days_ns)  # type: ignore[index]
                    result["benchmark_s_step"].append(s_step)  # type: ignore[index]
            except ValueError:
                pass
        if FATAL_RE.search(line):
            result["last_error"] = line.strip()
    result["first_energy_step"] = first_energy_step
    result["last_energy"] = last_energy
    return result


def read_restart_step(path: Path | None) -> int | None:
    if not path or not path.exists():
        return None
    try:
        for line in reversed(path.read_text(errors="replace").splitlines()):
            if line.strip() and not line.startswith("#"):
                return int(float(line.split()[0]))
    except (OSError, ValueError, IndexError):
        return None
    return None


def resolve_restart_xsc(cwd: Path | None, config_data: dict[str, str]) -> Path | None:
    if not cwd:
        return None
    output = config_data.get("outputname")
    if output:
        candidate = cwd / f"{output}.restart.xsc"
        if candidate.exists():
            return candidate
    ext = config_data.get("extendedsystem")
    if ext:
        candidate = cwd / ext
        if candidate.exists():
            return candidate
    if output:
        return cwd / f"{output}.restart.xsc"
    return None


def mean_recent(values: list[float], n: int = 12) -> float | None:
    vals = values[-n:]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_status(pid: int) -> NamdRunStatus:
    cmd = read_cmdline(pid)
    cwd = proc_cwd(pid)
    config = infer_config(cmd, cwd)
    config_data = parse_simple_config(config)
    log = find_log(cwd, config)
    log_data = parse_log(log)
    restart_xsc = resolve_restart_xsc(cwd, config_data)
    restart_step = read_restart_step(restart_xsc)

    cpu, mem, elapsed_s, _psr = read_stat_times(pid)
    run_steps = int(float(config_data["run"])) if config_data.get("run") else None
    if not run_steps and config_data.get("minimize"):
        run_steps = int(float(config_data["minimize"]))
    timestep_fs = float(config_data["timestep"]) if config_data.get("timestep") else None

    last_energy = log_data["last_energy"] if isinstance(log_data.get("last_energy"), dict) else None
    last_energy_step = int(last_energy["TS"]) if last_energy and "TS" in last_energy else None
    current_step = restart_step or last_energy_step

    start_step: int | None = None
    first_energy_step = log_data.get("first_energy_step")
    if isinstance(first_energy_step, int):
        start_step = first_energy_step
    elif config_data.get("firsttimestep"):
        start_step = int(float(config_data["firsttimestep"]))

    target_step = start_step + run_steps if start_step is not None and run_steps is not None else None
    progress_percent = None
    ns_done = None
    ns_remaining = None
    eta_hours = None
    recent_ns_day = mean_recent(log_data["benchmark_ns_day"])  # type: ignore[arg-type]
    recent_s_step = mean_recent(log_data["benchmark_s_step"])  # type: ignore[arg-type]

    if current_step is not None and start_step is not None and run_steps:
        completed = max(0, min(run_steps, current_step - start_step))
        progress_percent = 100.0 * completed / run_steps
        if timestep_fs:
            ns_done = completed * timestep_fs / 1_000_000.0
            ns_remaining = max(0, (run_steps - completed) * timestep_fs / 1_000_000.0)
            if recent_ns_day and recent_ns_day > 0:
                eta_hours = ns_remaining / recent_ns_day * 24.0

    status = NamdRunStatus(
        pid=pid,
        command=cmd,
        cwd=str(cwd) if cwd else None,
        config=str(config) if config else None,
        log=str(log) if log else None,
        output_name=config_data.get("outputname"),
        restart_xsc=str(restart_xsc) if restart_xsc else None,
        elapsed_wall=format_elapsed(elapsed_s),
        cpu_percent=cpu,
        mem_percent=mem,
        affinity=read_affinity(pid),
        current_step=current_step,
        start_step=start_step,
        target_step=target_step,
        run_steps=run_steps,
        timestep_fs=timestep_fs,
        progress_percent=progress_percent,
        ns_done=ns_done,
        ns_remaining=ns_remaining,
        recent_ns_per_day=recent_ns_day,
        recent_s_per_step=recent_s_step,
        eta_hours=eta_hours,
        last_energy_step=last_energy_step,
        temp_k=last_energy.get("TEMP") if last_energy else None,
        tempavg_k=last_energy.get("TEMPAVG") if last_energy else None,
        pressure_bar=last_energy.get("PRESSURE") if last_energy else None,
        volume_a3=last_energy.get("VOLUME") if last_energy else None,
        last_error=log_data.get("last_error") if isinstance(log_data.get("last_error"), str) else None,
    )

    if not config:
        status.warnings.append("Could not infer .namd/.conf config from command line.")
    if not log:
        status.warnings.append("Could not infer matching log file.")
    if current_step is None:
        status.warnings.append("Could not infer current step from restart or ENERGY lines.")
    return status


def maybe_gpu_status() -> str | None:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except Exception:
        return None
    if not out:
        return None
    first = out.splitlines()[0].split(",")
    if len(first) >= 4:
        return f"GPU {first[0].strip()}%, mem {first[1].strip()} MiB, {first[2].strip()} W, {first[3].strip()} C"
    return out


def fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "?"
    return f"{value:.{digits}f}{suffix}"


def print_human(statuses: list[NamdRunStatus], include_gpu: bool) -> None:
    if not statuses:
        print("No live NAMD processes found.")
        return
    gpu = maybe_gpu_status() if include_gpu else None
    if gpu:
        print(gpu)
        print()
    for i, s in enumerate(statuses, 1):
        name = Path(s.config).name if s.config else "unknown config"
        print(f"[{i}] PID {s.pid}  {name}")
        print(f"    cwd: {s.cwd or '?'}")
        if s.log:
            print(f"    log: {s.log}")
        print(
            "    process: "
            f"elapsed {s.elapsed_wall or '?'}, CPU {fmt(s.cpu_percent, 0, '%')}, "
            f"mem {fmt(s.mem_percent, 1, '%')}, affinity {s.affinity or '?'}"
        )
        if s.current_step is not None:
            target = f" / {s.target_step}" if s.target_step is not None else ""
            print(f"    step: {s.current_step}{target}  progress {fmt(s.progress_percent, 1, '%')}")
        print(
            "    speed: "
            f"{fmt(s.recent_ns_per_day, 3)} ns/day"
            f"  ({fmt(s.recent_s_per_step, 4)} s/step)"
        )
        if s.ns_done is not None or s.ns_remaining is not None:
            print(
                "    simulated: "
                f"{fmt(s.ns_done, 3)} ns done, {fmt(s.ns_remaining, 3)} ns remaining, "
                f"ETA {fmt(s.eta_hours, 1)} h"
            )
        if s.temp_k is not None or s.pressure_bar is not None:
            print(
                "    health: "
                f"T {fmt(s.temp_k, 1)} K"
                f"  Tavg {fmt(s.tempavg_k, 1)} K"
                f"  P {fmt(s.pressure_bar, 2)} bar"
                f"  V {fmt(s.volume_a3, 0)} A^3"
            )
        if s.last_error:
            print(f"    last error: {s.last_error}")
        for warning in s.warnings:
            print(f"    warning: {warning}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--no-gpu", action="store_true", help="Skip nvidia-smi summary.")
    args = parser.parse_args()

    statuses = [build_status(pid) for pid in discover_namd_pids()]
    if args.json:
        print(json.dumps([asdict(s) for s in statuses], indent=2))
    else:
        print_human(statuses, include_gpu=not args.no_gpu)


if __name__ == "__main__":
    main()

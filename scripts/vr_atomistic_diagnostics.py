#!/usr/bin/env python3
"""Probe, publish, and validate full-origami MD data for native VR.

This tool is intentionally independent of the browser's current design.  It uses
the same read-only ``/ws/md-run`` protocol as Display MD, records bounded JSONL
process/progress/resource telemetry, and writes the atom-owner visualization feed
that the native viewer consumes.

Example (the current 24hb_2xT Alpine fixture)::

    uv run python scripts/vr_atomistic_diagnostics.py capture-md \
      --job-id fc12195d0636 \
      --config /media/jojo/Archive/NADOC_archive/fc12195d0636/package/\
24hb_2xT_namd_solvated/nadoc_md_run.json \
      --visualization /tmp/24hb_2xT-latest.visualization.txt \
      --metrics /tmp/24hb_2xT-vr-diagnostics.jsonl

The visualization file is mode 0600 because it contains local simulation data.
Production-trajectory commands add bounded DCD I/O probes, sequenced playback,
ScryWrite representation automation, and strict SteamVR evidence assessment.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import platform
import random
import shlex
import shutil
import statistics
import struct
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import quote

# Direct script execution places ``scripts/`` rather than the repository root on
# sys.path. Keep the diagnostic runnable exactly as documented without installation.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


DEFAULT_JOB_ID = "fc12195d0636"
DEFAULT_CONFIG = Path(
    "/media/jojo/Archive/NADOC_archive/fc12195d0636/package/"
    "24hb_2xT_namd_solvated/nadoc_md_run.json"
)

DEFAULT_TRAJECTORY_CONFIG = Path(
    "/media/jojo/Archive/NADOC_archive/6950d3b79138/package/"
    "24hb_1xT_namd_solvated/nadoc_md_run.json"
)


def _now() -> float:
    return time.time()


def _read_kib(path: Path, key: str) -> int | None:
    try:
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def _process_rss_mib(pid: int | None) -> float | None:
    if not pid:
        return None
    value = _read_kib(Path(f"/proc/{pid}/status"), "VmRSS")
    return None if value is None else round(value / 1024.0, 3)


def _find_backend_pid() -> int | None:
    candidates: list[tuple[int, int]] = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except (OSError, UnicodeDecodeError):
            continue
        is_uvicorn = "backend.api.main:app" in cmdline
        is_spawn_worker = "multiprocessing.spawn" in cmdline
        if (not is_uvicorn and not is_spawn_worker) or "resource_tracker" in cmdline:
            continue
        pid = int(entry.name)
        rss = _read_kib(entry / "status", "VmRSS") or 0
        candidates.append((rss, pid))
    return max(candidates, default=(0, 0))[1] or None


def _memory_sample() -> dict[str, float | None]:
    fields = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, raw = line.split(":", 1)
            fields[name] = int(raw.split()[0]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return {
        "memory_available_mib": round(fields.get("MemAvailable", 0.0), 3),
        "swap_free_mib": round(fields.get("SwapFree", 0.0), 3),
    }


def _gpu_sample() -> dict[str, float | int | str | None]:
    if not shutil.which("nvidia-smi"):
        return {}
    query = (
        "name,memory.total,memory.used,utilization.gpu,temperature.gpu,"
        "power.draw"
    )
    try:
        completed = subprocess.run(
            [
                "nvidia-smi", f"--query-gpu={query}",
                "--format=csv,noheader,nounits", "--id=0",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        name, total, used, utilization, temperature, power = [
            part.strip() for part in completed.stdout.splitlines()[0].split(",")
        ]
        return {
            "gpu_name": name,
            "gpu_memory_total_mib": int(total),
            "gpu_memory_used_mib": int(used),
            "gpu_utilization_pct": int(utilization),
            "gpu_temperature_c": int(temperature),
            "gpu_power_w": float(power),
        }
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return {"gpu_sample_error": True}


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _system_check(metrics: "JsonlMetrics") -> dict[str, Any]:
    metrics.emit("process_start", phase="system_check")
    memory = _memory_sample()
    gpu = _gpu_sample()
    disk = shutil.disk_usage(Path.cwd().anchor or "/")
    facts: dict[str, Any] = {
        "cpu_model": _cpu_model(),
        "logical_cpus": os.cpu_count(),
        **memory,
        **gpu,
        "root_free_gib": round(disk.free / (1024 ** 3), 3),
    }
    checks = {
        # The measured exact 24hb workflow peaked at ~2.9 GiB native + ~1.6 GiB
        # backend.  Six available GiB leaves room for SteamVR and the browser.
        "memory_headroom": (memory.get("memory_available_mib") or 0) >= 6144,
        "disk_headroom": facts["root_free_gib"] >= 2,
        "gpu_vram_capacity": (gpu.get("gpu_memory_total_mib") or 0) >= 8192,
        "gpu_vram_headroom": (
            (gpu.get("gpu_memory_total_mib") or 0)
            - (gpu.get("gpu_memory_used_mib") or 0)
        ) >= 4096,
    }
    warnings = []
    if (memory.get("swap_free_mib") == 0):
        warnings.append("swap is full; close unrelated memory-heavy applications")
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        **facts,
        "checks": checks,
        "warnings": warnings,
        "status": "capable" if not failed else "insufficient_headroom",
        "failed_checks": failed,
    }
    metrics.emit("process_progress", phase="system_capacity", **result)
    metrics.emit("process_end", phase="system_check", **result)
    return result


def _find_vrcmd(explicit: Path | None) -> Path:
    candidates = [
        explicit,
        Path.home() / ".local/share/Steam/steamapps/common/SteamVR/bin/linux64/vrcmd",
        Path.home() / ".steam/root/steamapps/common/SteamVR/bin/linux64/vrcmd",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("SteamVR vrcmd was not found; install/start SteamVR")


def _read_steamvr_stats(
    command: Path, environment: dict[str, str], timeout: float,
) -> dict[str, Any]:
    completed = subprocess.run(
        [str(command), "--stats"], capture_output=True, text=True,
        timeout=timeout, env=environment, check=False,
    )
    raw = completed.stdout.strip()
    if completed.returncode != 0:
        raise RuntimeError(
            f"vrcmd --stats exited {completed.returncode}: "
            f"{completed.stderr.strip() or raw}"
        )
    try:
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"vrcmd returned no JSON statistics: {raw[:500]}") from exc
    rows = payload if isinstance(payload, list) else [payload]
    stats = next(
        (row for row in rows if isinstance(row, dict)
         and row.get("operation") == "compositor_stats"),
        None,
    )
    if stats is None:
        raise RuntimeError(f"vrcmd returned no compositor_stats record: {raw[:500]}")
    return stats


STEAMVR_INTERVAL_COUNTERS = (
    "frame_presents", "frame_submits", "dropped_frames",
    "dropped_frames_loading", "dropped_frames_on_startup",
    "dropped_frames_timed_out", "reprojected_frames",
    "reprojected_frames_loading", "reprojected_frames_on_startup",
    "reprojected_frames_timed_out", "timed_out",
)


def _steamvr_counter_deltas(
    before: dict[str, Any], after: dict[str, Any],
) -> dict[str, int]:
    """Return reset-safe compositor counter changes for the measured interval."""
    return {
        name: max(0, int(after.get(name, 0)) - int(before.get(name, 0)))
        for name in STEAMVR_INTERVAL_COUNTERS
    }


def _steamvr_stats(args: argparse.Namespace, metrics: "JsonlMetrics") -> dict[str, Any]:
    command = _find_vrcmd(args.vrcmd)
    metrics.emit(
        "process_start", phase="steamvr_stats", command=str(command),
        sample_seconds=args.sample_seconds,
    )
    environment = os.environ.copy()
    # SteamVR ships libopenvr_api beside vrcmd.  Preserve any caller path after it.
    environment["LD_LIBRARY_PATH"] = str(command.parent) + (
        ":" + environment["LD_LIBRARY_PATH"]
        if environment.get("LD_LIBRARY_PATH") else ""
    )
    before = _read_steamvr_stats(command, environment, args.timeout)
    if args.sample_seconds > 0:
        time.sleep(args.sample_seconds)
    stats = _read_steamvr_stats(command, environment, args.timeout)
    interval = _steamvr_counter_deltas(before, stats)
    same_application = before.get("key") == stats.get("key")
    cpu_ms = stats.get("average_application_cpu_time_ms")
    gpu_ms = stats.get("average_application_gpu_time_ms")
    active_sample = (
        same_application
        and isinstance(stats.get("key"), str)
        and interval["frame_presents"] > 0
        and interval["timed_out"] == 0
        and interval["dropped_frames_timed_out"] == 0
    )
    assessment = {
        "same_application_interval": same_application,
        "active_headset_sample": active_sample,
        "app_cpu_within_90hz": isinstance(cpu_ms, (int, float)) and cpu_ms < 11.111,
        "app_gpu_within_90hz": isinstance(gpu_ms, (int, float)) and gpu_ms < 11.111,
        "no_interval_reprojection": interval["reprojected_frames"] == 0,
        "no_interval_drops": interval["dropped_frames"] == 0,
    }
    result = {
        "stats": stats,
        "interval": interval,
        "sample_seconds": args.sample_seconds,
        "assessment": assessment,
    }
    metrics.emit("process_progress", phase="steamvr_compositor", **result)
    metrics.emit(
        "process_end", phase="steamvr_stats",
        status="ok" if all(assessment.values()) else "performance_warning", **result,
    )
    return result


def _percentile(values: list[float], fraction: float) -> float:
    """Linear percentile without requiring numpy in unit tests."""
    if not values:
        raise ValueError("cannot calculate a percentile of no values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _resolve_production_dcd(config: Path, explicit: Path | None) -> tuple[Path, dict]:
    manifest = json.loads(config.read_text())
    if explicit is not None:
        return explicit.resolve(), manifest
    package = Path(manifest.get("package_dir") or config.parent)
    output = package / str((manifest.get("files") or {}).get("output_dir", "output"))
    stages = manifest.get("segments") or []
    production = [
        output / f"{stage['name']}.dcd"
        for stage in stages
        if isinstance(stage, dict) and stage.get("name") and "production" in stage["name"]
    ]
    existing = [path for path in production if path.is_file()]
    if not existing:
        existing = sorted(output.glob("*production*.dcd"))
    if not existing:
        raise FileNotFoundError(f"no production DCD found under {output}")
    return max(existing, key=lambda path: path.stat().st_size).resolve(), manifest


def _dna_prefix_atoms(manifest: dict) -> int:
    """Input-PDB DNA atoms (useful provenance, not the hydrogenated PSF prefix)."""
    topology = (
        (manifest.get("charge_audit") or {}).get("topology_metadata") or {}
    )
    segments = topology.get("segments") or []
    counts = [
        int(row.get("n_atoms_input", 0))
        for row in segments
        if isinstance(row, dict) and str(row.get("segid", "")).startswith("D")
    ]
    total = sum(counts)
    if total <= 0:
        raise ValueError("manifest has no DNA-prefix atom count")
    return total


def _dna_segment_ids(manifest: dict) -> set[str]:
    topology = (
        (manifest.get("charge_audit") or {}).get("topology_metadata") or {}
    )
    segments = topology.get("segments") or []
    result = {
        str(row["segid"])
        for row in segments
        if isinstance(row, dict) and str(row.get("segid", "")).startswith("D")
    }
    if not result:
        raise ValueError("manifest has no DNA topology segments")
    return result


def _topology_path(config: Path, manifest: dict) -> Path:
    package = Path(manifest.get("package_dir") or config.parent)
    name = (manifest.get("files") or {}).get("topology")
    if not name:
        raise ValueError("manifest has no topology path")
    return (package / str(name)).resolve()


def _psf_dna_prefix_indices(
    path: Path, dna_segments: set[str],
) -> tuple[int, list[int]]:
    """Return hydrogenated DNA-prefix size and its non-hydrogen DCD indices."""
    declared = 0
    in_atoms = False
    last_dna_serial = 0
    indices: list[int] = []
    with path.open("r", errors="replace") as handle:
        for line in handle:
            if not in_atoms:
                if "!NATOM" not in line:
                    continue
                declared = int(line.split()[0])
                in_atoms = True
                continue
            fields = line.split()
            if len(fields) < 8:
                raise ValueError(f"invalid PSF atom row {len(indices) + 1}")
            if fields[1] not in dna_segments:
                break
            row = int(fields[0]) - 1
            last_dna_serial = row + 1
            try:
                mass = float(fields[7])
            except ValueError as exc:
                raise ValueError(f"invalid PSF mass at atom row {row + 1}") from exc
            if mass >= 2.0:
                indices.append(row)
    prefix_atoms = last_dna_serial
    if prefix_atoms > declared:
        raise ValueError("PSF DNA prefix exceeds declared atom count")
    if not indices:
        raise ValueError("PSF DNA prefix contains no heavy atoms")
    return prefix_atoms, indices


def _benchmark_frame_indices(n_frames: int, samples: int) -> list[int]:
    if n_frames <= 0:
        raise ValueError("trajectory has no complete frames")
    count = max(1, min(samples, n_frames))
    if count == 1:
        return [n_frames - 1]
    # Distributed deterministic seeks exercise the archive drive honestly without
    # requiring privileged cache eviction or reading the entire trajectory.
    indices = {round(index * (n_frames - 1) / (count - 1)) for index in range(count)}
    ordered = list(indices)
    random.Random(2401).shuffle(ordered)
    return ordered


def _read_dcd_prefix_frame(
    fd: int, layout: Any, frame_idx: int, prefix_atoms: int, heavy_indices: Any,
) -> Any:
    import numpy as np

    cell_bytes = 56 if layout.has_cell else 0
    axis_record_bytes = 8 + 4 * layout.n_atoms
    base = layout.header_bytes + frame_idx * layout.frame_bytes + cell_bytes
    xyz = np.empty((len(heavy_indices), 3), dtype=np.float32)
    for axis in range(3):
        raw = os.pread(fd, 4 * prefix_atoms, base + axis * axis_record_bytes + 4)
        if len(raw) != 4 * prefix_atoms:
            raise OSError(f"short DCD read at frame {frame_idx}, axis {axis}")
        source = np.frombuffer(raw, dtype=np.dtype(layout.endian + "f4"))
        xyz[:, axis] = source[heavy_indices]
    if not np.isfinite(xyz).all():
        raise ValueError(f"non-finite coordinate in frame {frame_idx}")
    return xyz


def _trajectory_feasibility(
    args: argparse.Namespace, metrics: "JsonlMetrics",
) -> dict[str, Any]:
    import numpy as np

    from backend.core.dcd_fast import read_layout

    config = args.config.resolve()
    if not config.is_file():
        raise FileNotFoundError(config)
    dcd, manifest = _resolve_production_dcd(config, args.dcd)
    if not dcd.is_file():
        raise FileNotFoundError(dcd)
    metrics.emit(
        "process_start", phase="trajectory_feasibility", config=str(config),
        trajectory=str(dcd), samples=args.samples, target_hmd_hz=args.target_hmd_hz,
        target_trajectory_fps=args.target_trajectory_fps,
    )
    metrics.start_sampler(args.sample_interval)

    layout_started = time.monotonic()
    layout = read_layout(dcd)
    topology = _topology_path(config, manifest)
    topology_started = time.monotonic()
    input_dna_atoms = _dna_prefix_atoms(manifest)
    prefix_atoms, heavy_rows = _psf_dna_prefix_indices(
        topology, _dna_segment_ids(manifest)
    )
    heavy_indices = np.asarray(heavy_rows, dtype=np.int64)
    if prefix_atoms > layout.n_atoms:
        raise ValueError("DNA prefix exceeds DCD atom count")
    topology_ms = (time.monotonic() - topology_started) * 1000.0
    frame_indices = _benchmark_frame_indices(layout.n_frames, args.samples)
    metrics.emit(
        "process_progress", phase="trajectory_inventory",
        layout=asdict(layout), trajectory_bytes=dcd.stat().st_size,
        trajectory_gib=round(dcd.stat().st_size / 1024**3, 3),
        layout_ms=round((time.monotonic() - layout_started) * 1000.0, 3),
        topology=str(topology), topology_ms=round(topology_ms, 3),
        dna_input_atoms=input_dna_atoms, dna_prefix_atoms=prefix_atoms,
        dna_heavy_atoms=len(heavy_indices),
        sampled_frames=frame_indices,
    )

    timings: list[float] = []
    frame_bytes = int(len(heavy_indices) * 3 * 4)
    fd = os.open(dcd, os.O_RDONLY)
    try:
        for sample_number, frame_idx in enumerate(frame_indices, start=1):
            if args.cache_mode == "cold" and hasattr(os, "posix_fadvise"):
                os.posix_fadvise(
                    fd, layout.header_bytes + frame_idx * layout.frame_bytes,
                    layout.frame_bytes, os.POSIX_FADV_DONTNEED,
                )
            started = time.monotonic()
            xyz = _read_dcd_prefix_frame(
                fd, layout, frame_idx, prefix_atoms, heavy_indices
            )
            elapsed_ms = (time.monotonic() - started) * 1000.0
            timings.append(elapsed_ms)
            metrics.emit(
                "process_progress", phase="trajectory_frame_probe",
                sample=sample_number, samples=len(frame_indices), frame_idx=frame_idx,
                read_extract_ms=round(elapsed_ms, 3), output_bytes=xyz.nbytes,
                self_rss_mib=_process_rss_mib(os.getpid()),
            )
    finally:
        os.close(fd)

    p50_ms = _percentile(timings, 0.50)
    p95_ms = _percentile(timings, 0.95)
    worst_ms = max(timings)
    direct_limit_fps = 1000.0 / p95_ms
    compact_bytes = frame_bytes * layout.n_frames
    full_duration_ps = layout.first_ps + max(0, layout.n_frames - 1) * layout.delta_ps
    source_free_bytes = shutil.disk_usage(dcd.parent).free
    cache_dir = args.cache_dir.resolve() if args.cache_dir else dcd.parent
    if not cache_dir.exists():
        raise FileNotFoundError(cache_dir)
    cache_free_bytes = shutil.disk_usage(cache_dir).free
    production_steps = max(
        [int(row.get("steps", 0)) for row in (manifest.get("segments") or [])
         if isinstance(row, dict) and "production" in str(row.get("name", ""))]
        or [0]
    )
    timestep_fs = float(manifest.get("production_timestep_fs") or 0.0)
    expected_frames = (
        math.ceil(production_steps * timestep_fs / (layout.delta_ps * 1000.0))
        if production_steps > 0 and timestep_fs > 0 and layout.delta_ps > 0 else 0
    )
    expected_compact_bytes = frame_bytes * expected_frames
    targets = {}
    for fps in (5, 10, 15, 30, 60):
        required_ms = 1000.0 / fps
        targets[str(fps)] = {
            "direct_random_p95_meets_cadence": p95_ms <= required_ms,
            "direct_random_headroom_20pct": p95_ms <= required_ms * 0.8,
            "compact_stream_mib_s": round(frame_bytes * fps / 1024**2, 3),
        }

    target_budget_ms = 1000.0 / args.target_trajectory_fps
    direct_ok = p95_ms <= target_budget_ms * 0.8
    compact_disk_ok = compact_bytes <= cache_free_bytes * 0.8
    expected_compact_disk_ok = expected_frames > 0 and expected_compact_bytes <= cache_free_bytes * 0.8
    # Coordinate delivery must never consume the OpenXR render budget. It runs on
    # a producer thread and publishes the newest complete frame to a bounded queue.
    status = "feasible_with_compact_streaming" if compact_disk_ok else "feasible_with_live_streaming_only"
    result = {
        "status": status,
        "conclusion": (
            "Do not load the trajectory into RAM or decode it on the OpenXR thread. "
            "Render at headset cadence from a two-frame buffer; deliver DNA-heavy "
            "keyframes asynchronously and interpolate by predicted display time."
        ),
        "trajectory": str(dcd),
        "trajectory_bytes": dcd.stat().st_size,
        "trajectory_gib": round(dcd.stat().st_size / 1024**3, 3),
        "layout": asdict(layout),
        "observed_duration_ns": round(full_duration_ps / 1000.0, 6),
        "dna_input_atoms": input_dna_atoms,
        "dna_prefix_atoms": prefix_atoms,
        "dna_heavy_atoms": len(heavy_indices),
        "compact_frame_bytes": frame_bytes,
        "compact_trajectory_bytes": compact_bytes,
        "compact_trajectory_gib": round(compact_bytes / 1024**3, 3),
        "expected_production_frames": expected_frames,
        "expected_compact_trajectory_bytes": expected_compact_bytes,
        "expected_compact_trajectory_gib": round(expected_compact_bytes / 1024**3, 3),
        "source_storage_free_gib": round(source_free_bytes / 1024**3, 3),
        "cache_target": str(cache_dir),
        "cache_target_free_gib": round(cache_free_bytes / 1024**3, 3),
        "benchmark": {
            "method": "distributed os.pread of the DNA prefix plus heavy-atom gather",
            "cache_mode": args.cache_mode,
            "samples": len(timings),
            "sampled_frames": frame_indices,
            "read_extract_ms": [round(value, 3) for value in timings],
            "p50_ms": round(p50_ms, 3),
            "p95_ms": round(p95_ms, 3),
            "worst_ms": round(worst_ms, 3),
            "direct_random_limit_fps_p95": round(direct_limit_fps, 3),
        },
        "targets": targets,
        "assessment": {
            "target_hmd_hz": args.target_hmd_hz,
            "hmd_frame_budget_ms": round(1000.0 / args.target_hmd_hz, 6),
            "target_trajectory_fps": args.target_trajectory_fps,
            "trajectory_update_budget_ms": round(target_budget_ms, 6),
            "direct_random_has_20pct_headroom": direct_ok,
            "compact_cache_has_disk_headroom": compact_disk_ok,
            "expected_production_cache_has_disk_headroom": expected_compact_disk_ok,
            "trajectory_and_hmd_cadence_decoupled": True,
            "live_headset_compositor_validation_required": True,
        },
        "required_validation": [
            "run the producer off the OpenXR/render thread with a queue bounded to two frames",
            "measure visualization parse, publish, upload, and sequence gaps",
            "run steamvr-stats during real-headset playback and require zero interval drops/reprojection",
            "exercise Full, Ball + Stick, and Stick while playback remains active",
        ],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report.with_name(args.report.name + ".next")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, args.report)
        result["report"] = str(args.report.resolve())
    metrics.emit("process_end", phase="trajectory_feasibility", **result)
    return result


def _metric_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _viewer_metric_rows(path: Path) -> tuple[list[dict[str, str]], str]:
    content = path.read_text(errors="replace")
    rows: list[dict[str, str]] = []
    for line in content.splitlines():
        marker = "VR_METRIC "
        if marker not in line:
            continue
        fields: dict[str, str] = {}
        for token in shlex.split(line.split(marker, 1)[1]):
            if "=" in token:
                key, value = token.split("=", 1)
                fields[key] = value
        rows.append(fields)
    return rows, content


def _capture_evidence(path: Path) -> dict[str, Any]:
    """Reject uniform/black actor-eye captures while tolerating sparse atom scenes."""
    from PIL import Image, ImageStat

    expected = (
        "trajectory_ballstick_unobstructed.png",
        "trajectory_stick_unobstructed.png",
        "trajectory_full_unobstructed.png",
        "trajectory_ballstick_return_unobstructed.png",
    )
    images: dict[str, dict[str, Any]] = {}
    for name in expected:
        capture = path / name
        if not capture.is_file():
            images[name] = {"visible": False, "reason": "missing"}
            continue
        with Image.open(capture) as source:
            rgb = source.convert("RGB")
            luminance = rgb.convert("L")
            histogram = luminance.histogram()
            pixels = max(1, sum(histogram))
            bright_fraction = sum(histogram[8:]) / pixels
            deviation = max(ImageStat.Stat(rgb).stddev)
            visible = deviation >= 1.0 and bright_fraction >= 0.001
            images[name] = {
                "visible": visible,
                "width": rgb.width,
                "height": rgb.height,
                "bright_fraction": round(bright_fraction, 6),
                "max_channel_stddev": round(deviation, 3),
            }
    return {"passed": all(row["visible"] for row in images.values()), "images": images}


def _assess_playback(args: argparse.Namespace, metrics: "JsonlMetrics") -> dict[str, Any]:
    metrics.emit(
        "process_start", phase="playback_assessment", viewer_log=str(args.viewer_log),
        producer_metrics=str(args.producer_metrics),
        steamvr_metrics=str(args.steamvr_metrics),
    )
    viewer, viewer_text = _viewer_metric_rows(args.viewer_log)
    coordinate_updates = [
        row for row in viewer
        if row.get("phase") == "coordinate_update" and row.get("status") == "applied"
    ]
    visualization_updates = [
        row for row in viewer if row.get("phase") == "visualization_update"
    ]
    updates = coordinate_updates or visualization_updates
    frames = [row for row in viewer if row.get("phase") == "frame_timing"]
    producer_rows = _metric_rows(args.producer_metrics)
    steamvr_rows = _metric_rows(args.steamvr_metrics)
    producer_end = next(
        (row for row in reversed(producer_rows) if row.get("phase") == "md_playback"
         and row.get("event") == "process_end"), None,
    )
    steamvr_end = next(
        (row for row in reversed(steamvr_rows) if row.get("phase") == "steamvr_stats"
         and row.get("event") == "process_end"), None,
    )

    def numbers(rows: list[dict[str, str]], key: str) -> list[float]:
        result = []
        for row in rows:
            try:
                result.append(float(row[key]))
            except (KeyError, TypeError, ValueError):
                continue
        return result

    total_ms = numbers(updates, "total_ms")
    parse_ms = numbers(updates, "parse_ms")
    apply_ms = numbers(updates, "apply_upload_ms")
    if coordinate_updates:
        cpu_ms = numbers(updates, "cpu_update_ms")
        upload_ms = numbers(updates, "upload_ms")
        apply_ms = [cpu + upload for cpu, upload in zip(cpu_ms, upload_ms)]
    periods = numbers(frames, "runtime_period_ms")
    scene_p95 = numbers(frames, "scene_p95_ms")
    budget_ms = statistics.median(periods) if periods else 1000.0 / args.target_hmd_hz
    sequence_gaps = sum(int(float(row.get("sequence_gap", "0"))) for row in updates)
    compositor = (steamvr_end or {}).get("assessment") or {}
    captures_path = getattr(args, "captures", None)
    capture_evidence = _capture_evidence(captures_path) if captures_path else None
    checks = {
        "scrywrite_passed": "ScryWrite Witness PASSED" in viewer_text,
        "minimum_visualization_updates": len(updates) >= args.min_updates,
        "no_visualization_sequence_gaps": sequence_gaps == 0,
        "visualization_updates_within_hmd_budget": bool(total_ms)
        and max(total_ms) <= budget_ms,
        "scene_p95_within_hmd_budget": bool(scene_p95)
        and max(scene_p95) <= budget_ms,
        "producer_finished_without_deadline_miss": producer_end is not None
        and producer_end.get("status") == "ok"
        and int(producer_end.get("deadline_misses", 1)) == 0,
        "active_headset_sample": bool(compositor.get("active_headset_sample")),
        "no_compositor_drops": bool(compositor.get("no_interval_drops")),
        "no_compositor_reprojection": bool(compositor.get("no_interval_reprojection")),
        "app_cpu_within_budget": bool(compositor.get("app_cpu_within_90hz")),
        "app_gpu_within_budget": bool(compositor.get("app_gpu_within_90hz")),
    }
    if capture_evidence is not None:
        checks["unobstructed_captures_visible"] = capture_evidence["passed"]
    failures = [name for name, passed in checks.items() if not passed]
    result = {
        "status": "pass" if not failures else "fail",
        "checks": checks,
        "failures": failures,
        "hmd_budget_ms": round(budget_ms, 6),
        "visualization": {
            "transport": "binary_coordinates" if coordinate_updates else "text_snapshot",
            "updates": len(updates), "sequence_gaps": sequence_gaps,
            "parse_p50_ms": round(_percentile(parse_ms, 0.50), 3) if parse_ms else None,
            "parse_p95_ms": round(_percentile(parse_ms, 0.95), 3) if parse_ms else None,
            "apply_p50_ms": round(_percentile(apply_ms, 0.50), 3) if apply_ms else None,
            "apply_p95_ms": round(_percentile(apply_ms, 0.95), 3) if apply_ms else None,
            "total_p95_ms": round(_percentile(total_ms, 0.95), 3) if total_ms else None,
            "total_max_ms": round(max(total_ms), 3) if total_ms else None,
        },
        "scene_p95_max_ms": round(max(scene_p95), 3) if scene_p95 else None,
        "producer": producer_end,
        "steamvr": steamvr_end,
        "captures": capture_evidence,
    }
    metrics.emit("process_end", phase="playback_assessment", **result)
    return result


def _terminate_owned(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _openxr_environment() -> dict[str, str]:
    """Match the native bridge's sanitized SteamVR/OpenXR launch environment."""
    env = dict(os.environ)
    for key in (
        "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "CPATH",
        "CPLUS_INCLUDE_PATH", "CMAKE_PREFIX_PATH", "LIBRARY_PATH",
        "LD_LIBRARY_PATH", "CONDA_PREFIX",
    ):
        env.pop(key, None)
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    runtime = (
        Path.home() / ".local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json"
    )
    if runtime.is_file():
        env["XR_RUNTIME_JSON"] = str(runtime)
    return env


def _validate_playback(args: argparse.Namespace, metrics: "JsonlMetrics") -> dict[str, Any]:
    """Run producer + ScryWrite viewer + compositor sample, then assess evidence."""
    scene = args.scene.resolve()
    viewer = args.viewer.resolve()
    if not scene.is_file():
        raise FileNotFoundError(scene)
    if not viewer.is_file():
        raise FileNotFoundError(viewer)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    paths = {
        "visualization": output / "trajectory.visualization.txt",
        "coordinate": output / "trajectory.coordinates.bin",
        "trajectory_state": output / "trajectory.state.txt",
        "producer_metrics": output / "producer.jsonl",
        "producer_log": output / "producer.log",
        "viewer_log": output / "viewer.log",
        "steamvr_metrics": output / "steamvr.jsonl",
        "steamvr_log": output / "steamvr.log",
        "captures": output / "captures",
        "mirror": output / "mirror.jsonl",
    }
    paths["captures"].mkdir(exist_ok=True)
    metrics.emit(
        "process_start", phase="automated_playback_validation", scene=str(scene),
        viewer=str(viewer), output_dir=str(output),
    )
    producer: subprocess.Popen[Any] | None = None
    viewer_process: subprocess.Popen[Any] | None = None
    steamvr: subprocess.Popen[Any] | None = None
    handles = []
    try:
        initial_publication = (
            (paths["visualization"].stat().st_mtime_ns,
             paths["visualization"].stat().st_size)
            if paths["visualization"].is_file() else None
        )
        producer_handle = paths["producer_log"].open("w")
        handles.append(producer_handle)
        producer = subprocess.Popen(
            [
                sys.executable, str(Path(__file__).resolve()), "playback-md",
                "--job-id", args.job_id, "--config", str(args.config.resolve()),
                "--ws-url", args.ws_url, "--visualization", str(paths["visualization"]),
                "--coordinate", str(paths["coordinate"]),
                "--trajectory-state", str(paths["trajectory_state"]),
                "--metrics", str(paths["producer_metrics"]),
                "--start-frame", str(args.start_frame),
                "--frame-count", str(args.frame_count), "--stride", str(args.stride),
                "--fps", str(args.fps), "--timeout", str(args.timeout),
            ],
            stdout=producer_handle, stderr=subprocess.STDOUT,
        )
        metrics.emit("process_progress", phase="producer_started", pid=producer.pid)
        wait_started = time.monotonic()
        while True:
            current_publication = (
                (paths["visualization"].stat().st_mtime_ns,
                 paths["visualization"].stat().st_size)
                if paths["visualization"].is_file() else None
            )
            if (
                current_publication is not None
                and current_publication != initial_publication
                and paths["coordinate"].is_file()
                and paths["trajectory_state"].is_file()
            ):
                break
            if producer.poll() is not None:
                raise RuntimeError(
                    f"trajectory producer exited {producer.returncode}; see {paths['producer_log']}"
                )
            if time.monotonic() - wait_started > args.timeout:
                raise TimeoutError("timed out waiting for first trajectory frame")
            time.sleep(0.1)
        metrics.emit(
            "process_progress", phase="first_publication_ready",
            wait_ms=round((time.monotonic() - wait_started) * 1000.0, 3),
            bytes=paths["visualization"].stat().st_size,
            coordinate_bytes=paths["coordinate"].stat().st_size,
        )

        viewer_handle = paths["viewer_log"].open("w")
        handles.append(viewer_handle)
        viewer_process = subprocess.Popen(
            [
                str(viewer), str(scene), "--visualization", str(paths["visualization"]),
                "--coordinates", str(paths["coordinate"]),
                "--trajectory", str(paths["trajectory_state"]),
                "--scrywrite-witness", str(args.witness.resolve()),
                "--witness-captures", str(paths["captures"]),
                "--witness-exit", "on", "--mirror-eye", "right",
                "--mirror-diagnostics", str(paths["mirror"]),
            ],
            stdout=viewer_handle, stderr=subprocess.STDOUT,
            env=_openxr_environment(),
        )
        metrics.emit("process_progress", phase="viewer_started", pid=viewer_process.pid)
        time.sleep(1.0)
        if viewer_process.poll() is not None:
            raise RuntimeError(
                f"VR viewer exited {viewer_process.returncode}; see {paths['viewer_log']}"
            )

        steamvr_handle = paths["steamvr_log"].open("w")
        handles.append(steamvr_handle)
        steamvr = subprocess.Popen(
            [
                sys.executable, str(Path(__file__).resolve()), "steamvr-stats",
                "--sample-seconds", str(args.steamvr_seconds),
                "--metrics", str(paths["steamvr_metrics"]),
            ],
            stdout=steamvr_handle, stderr=subprocess.STDOUT,
        )
        metrics.emit("process_progress", phase="steamvr_sample_started", pid=steamvr.pid)
        viewer_return = viewer_process.wait(timeout=args.timeout)
        producer_return = producer.wait(timeout=max(30.0, args.timeout / 4.0))
        steamvr_return = steamvr.wait(timeout=max(30.0, args.steamvr_seconds + 20.0))
        metrics.emit(
            "process_progress", phase="child_processes_finished",
            viewer_returncode=viewer_return, producer_returncode=producer_return,
            steamvr_returncode=steamvr_return,
        )
    finally:
        _terminate_owned(steamvr)
        _terminate_owned(viewer_process)
        _terminate_owned(producer)
        for handle in handles:
            handle.close()

    assessment_args = argparse.Namespace(
        viewer_log=paths["viewer_log"],
        producer_metrics=paths["producer_metrics"],
        steamvr_metrics=paths["steamvr_metrics"],
        target_hmd_hz=args.target_hmd_hz,
        min_updates=args.min_updates,
        captures=paths["captures"],
    )
    result = _assess_playback(assessment_args, metrics)
    result["artifacts"] = {name: str(path) for name, path in paths.items()}
    metrics.emit(
        "process_end", phase="automated_playback_validation",
        status=result["status"], artifacts=result["artifacts"],
    )
    return result


class JsonlMetrics:
    def __init__(self, path: Path, backend_pid: int | None) -> None:
        self.path = path
        self.backend_pid = backend_pid
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")
        os.chmod(self.path, 0o600)

    def emit(self, event: str, **detail: Any) -> None:
        record = {
            "schema": "nadoc-vr-atomistic-diagnostic-v1",
            "event": event,
            "at_unix_s": _now(),
            "elapsed_s": round(time.monotonic() - self.started, 6),
            **detail,
        }
        with self._lock:
            self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._file.flush()
        print("VR_DIAGNOSTIC " + json.dumps(record, separators=(",", ":")), flush=True)

    def start_sampler(self, interval_s: float) -> None:
        def sample() -> None:
            while not self._stop.wait(interval_s):
                self.emit(
                    "process_progress",
                    phase="resource_sample",
                    self_rss_mib=_process_rss_mib(os.getpid()),
                    backend_pid=self.backend_pid,
                    backend_rss_mib=_process_rss_mib(self.backend_pid),
                    **_memory_sample(),
                    **_gpu_sample(),
                )

        self._thread = threading.Thread(target=sample, name="vr-metric-sampler", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            self._file.close()


def _encode_atom_owner(base_key: str, name: str) -> str:
    normalized = {"O1P": "OP1", "O2P": "OP2", "C5M": "C7"}.get(name, name)
    payload = json.dumps(
        ["atom", base_key, normalized], ensure_ascii=False, separators=(",", ":")
    )
    return quote(payload, safe="-_.!~*'()")


def _identity_value(identity: dict[str, Any], key: str, index: int) -> Any:
    values = identity.get(key)
    if not isinstance(values, list) or index >= len(values):
        raise ValueError(f"atom_ident.{key} is missing row {index}")
    return values[index]


_MD_ATOM_SOURCE_HEADER = struct.Struct("<8sIIIIId")


def _decode_md_atom_source_frame(raw: bytes):
    """Decode the browser's negotiated NADOCMDA SoA frame into an XYZ view."""
    import numpy as np

    if len(raw) < _MD_ATOM_SOURCE_HEADER.size:
        raise ValueError("truncated binary MD atom frame")
    magic, version, header_bytes, frame_idx, n_frames, n_atoms, time_ps = (
        _MD_ATOM_SOURCE_HEADER.unpack_from(raw)
    )
    if magic != b"NADOCMDA" or version != 1 or header_bytes != 36:
        raise ValueError("unsupported binary MD atom frame")
    expected = header_bytes + n_atoms * 3 * 4
    if n_frames <= 0 or frame_idx >= n_frames or n_atoms <= 0 or len(raw) != expected:
        raise ValueError("invalid binary MD atom frame dimensions")
    columns = np.frombuffer(raw, dtype="<f4", count=n_atoms * 3, offset=header_bytes)
    coordinates = columns.reshape(3, n_atoms).T
    if not np.isfinite(coordinates).all():
        raise ValueError("binary MD atom frame contains non-finite coordinates")
    return {
        "type": "frame",
        "frame_idx": int(frame_idx),
        "n_frames": int(n_frames),
        "time_ps": float(time_ps),
    }, coordinates


def _atom_coordinate_array(atoms):
    """Normalize legacy JSON rows or a binary-frame ndarray to float32 XYZ."""
    import numpy as np

    if isinstance(atoms, np.ndarray):
        coordinates = np.asarray(atoms, dtype="<f4")
        if coordinates.ndim != 2 or coordinates.shape[1:] != (3,):
            raise ValueError("atom coordinates must have shape (N, 3)")
    else:
        coordinates = np.empty((len(atoms), 3), dtype="<f4")
        for index, atom in enumerate(atoms):
            try:
                coordinates[index] = (atom["x"], atom["y"], atom["z"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid atom coordinates at row {index}") from exc
    if not np.isfinite(coordinates).all():
        raise ValueError("atom frame contains non-finite coordinates")
    return coordinates


def _write_visualization(
    output: Path,
    atoms,
    identity: dict[str, Any],
    metrics: JsonlMetrics,
    *,
    sequence: int = 1,
) -> int:
    coordinates = _atom_coordinate_array(atoms)
    names = identity.get("names")
    base_keys = identity.get("base_keys")
    if not isinstance(names, list) or not isinstance(base_keys, list):
        raise ValueError("ready message does not contain atom names/base keys")
    if len(coordinates) != len(names) or len(coordinates) != len(base_keys):
        raise ValueError(
            f"atom/frame identity mismatch: atoms={len(coordinates)}, names={len(names)}, "
            f"base_keys={len(base_keys)}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".next")
    seen: set[str] = set()
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(
            f"NADOCVR_VISUALIZATION 3 {sequence} namd_display "
            f"ballstick cpk {len(coordinates)}\n"
        )
        for index, (x, y, z) in enumerate(coordinates):
            owner = _encode_atom_owner(str(base_keys[index]), str(names[index]))
            if owner in seen:
                raise ValueError(f"duplicate normalized atom owner at row {index}: {owner}")
            seen.add(owner)
            handle.write(f"V {owner} {x:.7g} {y:.7g} {z:.7g} -\n")
            if (index + 1) % 100_000 == 0:
                metrics.emit(
                    "process_progress",
                    phase="visualization_write",
                    completed=index + 1,
                    total=len(coordinates),
                )
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    return len(coordinates)


def _write_coordinate_frame(
    output: Path, atoms, *, sequence: int,
    frame_idx: int, n_frames: int,
) -> int:
    """Atomically publish stable-order little-endian float32 XYZ coordinates."""
    coordinates = _atom_coordinate_array(atoms)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".next")
    with temporary.open("wb") as handle:
        handle.write(struct.pack(
            "<8sIIQIII", b"NVRCOORD", 1, 36, sequence,
            frame_idx, n_frames, len(coordinates),
        ))
        handle.write(coordinates.tobytes(order="C"))
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    return len(coordinates)


def _write_trajectory_state(
    output: Path, *, sequence: int, frame_idx: int, n_frames: int,
    playing: bool, fps: float, stride: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".next")
    speed = max(0.1, min(8.0, fps / 10.0))
    temporary.write_text(
        f"NADOCVR_TRAJECTORY 1 {sequence} 1 {frame_idx} {n_frames} "
        f"{int(playing)} 0 0 {speed:.7g} {stride}\n"
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)


async def _capture_md(args: argparse.Namespace, metrics: JsonlMetrics) -> dict[str, Any]:
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - operator environment error
        raise RuntimeError("websockets is required; run this through `uv run python`") from exc

    config = args.config.resolve()
    if not config.is_file():
        raise FileNotFoundError(config)
    uri = args.ws_url
    metrics.emit(
        "process_start",
        phase="md_capture",
        uri=uri,
        job_id=args.job_id,
        config=str(config),
        backend_pid=metrics.backend_pid,
        system=platform.platform(),
        python=sys.version.split()[0],
    )
    metrics.start_sampler(args.sample_interval)

    identity: dict[str, Any] | None = None
    load_sent_at = time.monotonic()
    ready_at: float | None = None
    async with websockets.connect(
        uri,
        max_size=None,
        open_timeout=args.timeout,
        ping_timeout=None,
    ) as socket:
        await socket.send(json.dumps({
            "action": "load",
            "config_path": str(config),
            "mode": "ballstick",
            "job_id": args.job_id,
            "binary_atom_frames": True,
        }))
        metrics.emit("process_progress", phase="load_sent")
        while True:
            raw = await asyncio.wait_for(socket.recv(), timeout=args.timeout)
            if not isinstance(raw, str):
                if identity is None or ready_at is None:
                    raise ValueError("binary atom frame arrived before ready identity")
                message, atoms = _decode_md_atom_source_frame(raw)
                parse_ms = 0.0
                kind = "frame"
            else:
                parse_started = time.monotonic()
                message = json.loads(raw)
                parse_ms = (time.monotonic() - parse_started) * 1000.0
                kind = message.get("type", "unknown")
            if kind == "loading":
                metrics.emit(
                    "process_progress", phase="backend_loading",
                    message=message.get("message"), chars=len(raw), parse_ms=round(parse_ms, 3),
                )
            elif kind == "log":
                metrics.emit(
                    "process_progress", phase="backend_log",
                    message=message.get("message"),
                )
            elif kind == "ready":
                identity = message.get("atom_ident")
                if not isinstance(identity, dict):
                    raise ValueError("ballstick load returned no atom_ident")
                ready_at = time.monotonic()
                metrics.emit(
                    "process_progress",
                    phase="topology_ready",
                    load_ms=round((ready_at - load_sent_at) * 1000.0, 3),
                    chars=len(raw),
                    parse_ms=round(parse_ms, 3),
                    frames=message.get("n_frames"),
                    p_atoms=message.get("n_p_atoms"),
                    dna_heavy_atoms=len(identity.get("names") or []),
                    bonds=len(message.get("atom_bonds") or []) // 2,
                )
                await socket.send(json.dumps({"action": "get_latest"}))
                metrics.emit("process_progress", phase="latest_requested")
            elif kind == "frame":
                if identity is None or ready_at is None:
                    raise ValueError("frame arrived before ready identity")
                if isinstance(raw, str):
                    atoms = message.get("atoms")
                    if not isinstance(atoms, list):
                        raise ValueError("ballstick frame contains no atoms")
                metrics.emit(
                    "process_progress",
                    phase="frame_received",
                    frame_idx=message.get("frame_idx"),
                    frames=message.get("n_frames"),
                    atoms=len(atoms),
                    payload_bytes=len(raw),
                    source_transport=("binary" if not isinstance(raw, str) else "json"),
                    parse_ms=round(parse_ms, 3),
                    request_ms=round((time.monotonic() - ready_at) * 1000.0, 3),
                )
                write_started = time.monotonic()
                points = _write_visualization(args.visualization, atoms, identity, metrics)
                result = {
                    "frame_idx": message.get("frame_idx"),
                    "n_frames": message.get("n_frames"),
                    "points": points,
                    "visualization": str(args.visualization.resolve()),
                    "visualization_bytes": args.visualization.stat().st_size,
                    "load_ms": round((ready_at - load_sent_at) * 1000.0, 3),
                    "frame_request_ms": round((write_started - ready_at) * 1000.0, 3),
                    "visualization_write_ms": round(
                        (time.monotonic() - write_started) * 1000.0, 3
                    ),
                }
                metrics.emit("process_end", phase="md_capture", status="ok", **result)
                return result
            elif kind == "error":
                raise RuntimeError(str(message.get("message") or "MD stream error"))
            else:
                metrics.emit("process_progress", phase="message", message_type=kind)


async def _playback_md(args: argparse.Namespace, metrics: JsonlMetrics) -> dict[str, Any]:
    """Publish a bounded real-trajectory sequence for native VR/ScryWrite tests."""
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - operator environment error
        raise RuntimeError("websockets is required; run this through `uv run python`") from exc

    config = args.config.resolve()
    if not config.is_file():
        raise FileNotFoundError(config)
    if args.frame_count <= 0 or args.stride <= 0 or args.fps <= 0:
        raise ValueError("frame count, stride, and fps must be positive")
    if args.warmup_frames < 0:
        raise ValueError("warm-up frame count must be non-negative")
    if args.deadline_tolerance_ms < 0:
        raise ValueError("deadline tolerance must be non-negative")
    metrics.emit(
        "process_start", phase="md_playback", uri=args.ws_url,
        job_id=args.job_id, config=str(config), fps=args.fps,
        start_frame=args.start_frame, frame_count=args.frame_count,
        stride=args.stride, visualization=str(args.visualization),
    )
    metrics.start_sampler(args.sample_interval)
    request_timings: list[float] = []
    write_timings: list[float] = []
    deadline_misses = 0
    bootstrap_request_ms = None
    bootstrap_write_ms = None
    sequence = args.sequence_start or int(time.time() * 1000.0)
    load_started = time.monotonic()
    async with websockets.connect(
        args.ws_url, max_size=None, open_timeout=args.timeout, ping_timeout=None,
    ) as socket:
        await socket.send(json.dumps({
            "action": "load", "config_path": str(config), "mode": "ballstick",
            "job_id": args.job_id, "binary_atom_frames": True,
        }))
        identity: dict[str, Any] | None = None
        n_frames = 0
        while identity is None:
            raw = await asyncio.wait_for(socket.recv(), timeout=args.timeout)
            if not isinstance(raw, str):
                continue
            message = json.loads(raw)
            kind = message.get("type")
            if kind == "ready":
                identity = message.get("atom_ident")
                if not isinstance(identity, dict):
                    raise ValueError("ballstick load returned no atom_ident")
                n_frames = int(message.get("n_frames") or 0)
                metrics.emit(
                    "process_progress", phase="playback_topology_ready",
                    load_ms=round((time.monotonic() - load_started) * 1000.0, 3),
                    frames=n_frames, dna_heavy_atoms=len(identity.get("names") or []),
                    binary_atom_frames=bool(message.get("binary_atom_frames")),
                    dcd_prefix_atoms=message.get("binary_atom_prefix_atoms"),
                    source_atom_count=message.get("source_atom_count"),
                )
            elif kind == "loading":
                metrics.emit(
                    "process_progress", phase="backend_loading",
                    message=message.get("message"),
                )
            elif kind == "error":
                raise RuntimeError(str(message.get("message") or "MD stream error"))
        if n_frames <= 0:
            raise ValueError("backend reported no trajectory frames")

        frame_indices = [
            min(n_frames - 1, args.start_frame + index * args.stride)
            for index in range(args.frame_count)
        ]
        frame_indices = list(dict.fromkeys(frame_indices))
        # Prime a bounded sequential window before starting the visible cadence.
        # Cold archive storage can make the first 2–3 prefix reads exceed 100 ms
        # even though steady-state delivery is ~60 ms. The OpenXR loop is already
        # independent; this warm-up prevents that storage spin-up from appearing
        # as an animation hitch or a false steady-state cadence failure.
        warmup_count = min(args.warmup_frames, len(frame_indices))
        for warmup_ordinal, frame_idx in enumerate(
            frame_indices[:warmup_count], start=1
        ):
            warmup_started = time.monotonic()
            await socket.send(json.dumps({"action": "seek", "frame_idx": frame_idx}))
            while True:
                raw = await asyncio.wait_for(socket.recv(), timeout=args.timeout)
                if not isinstance(raw, str):
                    warmup_message, _ = _decode_md_atom_source_frame(raw)
                    if warmup_message["frame_idx"] == frame_idx:
                        break
                    continue
                warmup_message = json.loads(raw)
                if warmup_message.get("type") == "error":
                    raise RuntimeError(
                        str(warmup_message.get("message") or "MD warm-up seek error")
                    )
                if warmup_message.get("type") == "frame":
                    break
            metrics.emit(
                "process_progress",
                phase="playback_source_warmup",
                ordinal=warmup_ordinal,
                total=warmup_count,
                frame_idx=frame_idx,
                request_ms=round((time.monotonic() - warmup_started) * 1000.0, 3),
                source_transport=("binary" if not isinstance(raw, str) else "json"),
            )
        next_deadline: float | None = None
        for ordinal, frame_idx in enumerate(frame_indices, start=1):
            requested_at = time.monotonic()
            await socket.send(json.dumps({"action": "seek", "frame_idx": frame_idx}))
            while True:
                raw = await asyncio.wait_for(socket.recv(), timeout=args.timeout)
                if not isinstance(raw, str):
                    message, atoms = _decode_md_atom_source_frame(raw)
                    source_transport = "binary"
                    break
                message = json.loads(raw)
                if message.get("type") == "error":
                    raise RuntimeError(str(message.get("message") or "MD seek error"))
                if message.get("type") == "frame":
                    atoms = message.get("atoms")
                    if not isinstance(atoms, list):
                        raise ValueError("ballstick frame contains no atoms")
                    source_transport = "json"
                    break
            received_at = time.monotonic()
            sequence += 1
            # Topology/identity is published once. Every subsequent frame uses the
            # coordinate-only binary channel exercised by the browser bridge.
            if ordinal == 1 or args.coordinate is None:
                _write_visualization(
                    args.visualization, atoms, identity, metrics, sequence=sequence
                )
            if args.coordinate is not None:
                _write_coordinate_frame(
                    args.coordinate, atoms, sequence=sequence,
                    frame_idx=frame_idx, n_frames=n_frames,
                )
                if args.trajectory_state is None:
                    raise ValueError("--trajectory-state is required with --coordinate")
                _write_trajectory_state(
                    args.trajectory_state, sequence=sequence, frame_idx=frame_idx,
                    n_frames=n_frames, playing=ordinal < len(frame_indices),
                    fps=args.fps, stride=args.stride,
                )
            published_at = time.monotonic()
            request_ms = (received_at - requested_at) * 1000.0
            write_ms = (published_at - received_at) * 1000.0
            if next_deadline is None:
                # The first revision includes the one-time 13 MB topology/identity
                # snapshot. Cadence starts after that bootstrap publication.
                next_deadline = published_at
                lateness_ms = 0.0
                bootstrap_request_ms = request_ms
                bootstrap_write_ms = write_ms
            else:
                request_timings.append(request_ms)
                write_timings.append(write_ms)
                next_deadline += 1.0 / args.fps
                lateness_ms = max(0.0, (published_at - next_deadline) * 1000.0)
            if lateness_ms > args.deadline_tolerance_ms:
                deadline_misses += 1
            metrics.emit(
                "process_progress", phase="playback_frame_published",
                ordinal=ordinal, total=len(frame_indices), frame_idx=frame_idx,
                sequence=sequence, atoms=len(atoms), request_ms=round(request_ms, 3),
                write_ms=round(write_ms, 3), lateness_ms=round(lateness_ms, 3),
                deadline_tolerance_ms=args.deadline_tolerance_ms,
                deadline_misses=deadline_misses,
                transport="binary" if args.coordinate is not None else "text",
                source_transport=source_transport,
                payload_bytes=(args.coordinate.stat().st_size
                               if args.coordinate is not None else
                               args.visualization.stat().st_size),
            )
            remaining = next_deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)

    result = {
        "status": "ok" if deadline_misses == 0 else "cadence_warning",
        "frames_published": len(frame_indices),
        "first_frame": frame_indices[0],
        "last_frame": frame_indices[-1],
        "fps": args.fps,
        "deadline_misses": deadline_misses,
        "deadline_tolerance_ms": args.deadline_tolerance_ms,
        "bootstrap_request_ms": round(bootstrap_request_ms or 0.0, 3),
        "bootstrap_write_ms": round(bootstrap_write_ms or 0.0, 3),
        "request_p50_ms": round(_percentile(request_timings, 0.50), 3),
        "request_p95_ms": round(_percentile(request_timings, 0.95), 3),
        "write_p50_ms": round(_percentile(write_timings, 0.50), 3),
        "write_p95_ms": round(_percentile(write_timings, 0.95), 3),
        "visualization": str(args.visualization.resolve()),
        "coordinate": str(args.coordinate.resolve()) if args.coordinate else None,
        "trajectory_state": (
            str(args.trajectory_state.resolve()) if args.trajectory_state else None
        ),
        "final_sequence": sequence,
        "source_transport": source_transport,
        "warmup_frames": warmup_count,
    }
    metrics.emit("process_end", phase="md_playback", **result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture-md", help="capture latest all-atom MD frame")
    capture.add_argument("--job-id", default=DEFAULT_JOB_ID)
    capture.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    capture.add_argument("--ws-url", default="ws://127.0.0.1:8000/ws/md-run")
    capture.add_argument(
        "--visualization", type=Path,
        default=Path("/tmp/24hb_2xT-latest.visualization.txt"),
    )
    capture.add_argument(
        "--metrics", type=Path,
        default=Path("/tmp/24hb_2xT-vr-diagnostics.jsonl"),
    )
    capture.add_argument("--timeout", type=float, default=600.0)
    capture.add_argument("--sample-interval", type=float, default=2.0)
    capture.add_argument("--backend-pid", type=int)
    playback = commands.add_parser(
        "playback-md",
        help="publish bounded real MD frames for native VR/ScryWrite validation",
    )
    playback.add_argument("--job-id", default="6950d3b79138")
    playback.add_argument("--config", type=Path, default=DEFAULT_TRAJECTORY_CONFIG)
    playback.add_argument("--ws-url", default="ws://127.0.0.1:8000/ws/md-run")
    playback.add_argument(
        "--visualization", type=Path,
        default=Path("/tmp/24hb_1xT-trajectory.visualization.txt"),
    )
    playback.add_argument(
        "--coordinate", type=Path,
        help="publish coordinate-only binary revisions after the first topology frame",
    )
    playback.add_argument(
        "--trajectory-state", type=Path,
        help="small synchronized playback-state feed (required with --coordinate)",
    )
    playback.add_argument(
        "--metrics", type=Path,
        default=Path("/tmp/24hb_1xT-vr-playback.jsonl"),
    )
    playback.add_argument("--start-frame", type=int, default=0)
    playback.add_argument("--frame-count", type=int, default=30)
    playback.add_argument("--stride", type=int, default=1)
    playback.add_argument("--fps", type=float, default=10.0)
    playback.add_argument("--sequence-start", type=int)
    playback.add_argument("--timeout", type=float, default=600.0)
    playback.add_argument("--sample-interval", type=float, default=2.0)
    playback.add_argument(
        "--warmup-frames", type=int, default=3,
        help="prime this many source frames before measuring visible playback cadence",
    )
    playback.add_argument(
        "--deadline-tolerance-ms", type=float, default=5.0,
        help="late-keyframe tolerance; the independent HMD loop never waits on it",
    )
    playback.add_argument("--backend-pid", type=int)
    system = commands.add_parser("system", help="check full-origami hardware headroom")
    system.add_argument(
        "--metrics", type=Path,
        default=Path("/tmp/24hb_2xT-vr-system.jsonl"),
    )
    steamvr = commands.add_parser(
        "steamvr-stats", help="capture authoritative SteamVR compositor timing"
    )
    steamvr.add_argument("--vrcmd", type=Path)
    steamvr.add_argument("--timeout", type=float, default=15.0)
    steamvr.add_argument(
        "--sample-seconds", type=float, default=3.0,
        help="measure dropped/reprojected counter deltas over this active interval",
    )
    steamvr.add_argument(
        "--metrics", type=Path,
        default=Path("/tmp/24hb_2xT-steamvr-stats.jsonl"),
    )
    trajectory = commands.add_parser(
        "trajectory-feasibility",
        help="probe a production DCD and model bounded VR trajectory streaming",
    )
    trajectory.add_argument("--config", type=Path, default=DEFAULT_TRAJECTORY_CONFIG)
    trajectory.add_argument(
        "--dcd", type=Path,
        help="production DCD (otherwise discovered from the run manifest)",
    )
    trajectory.add_argument("--samples", type=int, default=33)
    trajectory.add_argument(
        "--cache-mode", choices=("cold", "system"), default="cold",
        help="cold advises the kernel to discard each sampled frame before reading",
    )
    trajectory.add_argument("--sample-interval", type=float, default=2.0)
    trajectory.add_argument("--target-hmd-hz", type=float, default=90.0)
    trajectory.add_argument("--target-trajectory-fps", type=float, default=10.0)
    trajectory.add_argument(
        "--cache-dir", type=Path,
        help="candidate compact-cache filesystem (defaults to the DCD filesystem)",
    )
    trajectory.add_argument(
        "--metrics", type=Path,
        default=Path("/tmp/24hb_1xT-vr-trajectory-feasibility.jsonl"),
    )
    trajectory.add_argument(
        "--report", type=Path,
        default=Path("/tmp/24hb_1xT-vr-trajectory-feasibility.json"),
    )
    assess = commands.add_parser(
        "assess-playback",
        help="combine producer, native viewer, ScryWrite, and SteamVR evidence",
    )
    assess.add_argument("--viewer-log", type=Path, required=True)
    assess.add_argument("--producer-metrics", type=Path, required=True)
    assess.add_argument("--steamvr-metrics", type=Path, required=True)
    assess.add_argument(
        "--captures", type=Path,
        help="optional ScryWrite capture directory; rejects missing/uniform HMD-eye images",
    )
    assess.add_argument("--target-hmd-hz", type=float, default=90.0)
    assess.add_argument("--min-updates", type=int, default=10)
    assess.add_argument(
        "--metrics", type=Path,
        default=Path("/tmp/24hb_1xT-vr-playback-assessment.jsonl"),
    )
    validate = commands.add_parser(
        "validate-playback",
        help="one-command real-headset producer/ScryWrite/compositor validation",
    )
    validate.add_argument("scene", type=Path)
    validate.add_argument(
        "--viewer", type=Path,
        default=REPOSITORY_ROOT / "native/vr_viewer/build/nadoc-vr-viewer",
    )
    validate.add_argument("--job-id", default="6950d3b79138")
    validate.add_argument("--config", type=Path, default=DEFAULT_TRAJECTORY_CONFIG)
    validate.add_argument("--ws-url", default="ws://127.0.0.1:8000/ws/md-run")
    validate.add_argument(
        "--witness", type=Path,
        default=REPOSITORY_ROOT / "native/vr_viewer/examples/"
        "scrywrite_witness_trajectory_24hb.scry",
    )
    validate.add_argument("--output-dir", type=Path, default=Path("/tmp/24hb_1xT-vr-validation"))
    validate.add_argument("--start-frame", type=int, default=0)
    validate.add_argument("--frame-count", type=int, default=24)
    validate.add_argument("--stride", type=int, default=1)
    validate.add_argument("--fps", type=float, default=1.0)
    validate.add_argument("--steamvr-seconds", type=float, default=8.0)
    validate.add_argument("--target-hmd-hz", type=float, default=90.0)
    validate.add_argument("--min-updates", type=int, default=10)
    validate.add_argument("--timeout", type=float, default=600.0)
    validate.add_argument(
        "--metrics", type=Path,
        default=Path("/tmp/24hb_1xT-vr-validation.jsonl"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    backend_pid = getattr(args, "backend_pid", None) or (
        _find_backend_pid() if args.command in ("capture-md", "playback-md") else None
    )
    metrics = JsonlMetrics(args.metrics.resolve(), backend_pid)
    try:
        if args.command == "capture-md":
            result = asyncio.run(_capture_md(args, metrics))
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "playback-md":
            result = asyncio.run(_playback_md(args, metrics))
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "ok" else 1
        if args.command == "system":
            result = _system_check(metrics)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "capable" else 1
        if args.command == "steamvr-stats":
            result = _steamvr_stats(args, metrics)
            print(json.dumps(result, indent=2))
            return 0 if all(result["assessment"].values()) else 1
        if args.command == "trajectory-feasibility":
            if args.samples <= 0:
                raise ValueError("--samples must be positive")
            if args.target_hmd_hz <= 0 or args.target_trajectory_fps <= 0:
                raise ValueError("target rates must be positive")
            result = _trajectory_feasibility(args, metrics)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "assess-playback":
            result = _assess_playback(args, metrics)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "pass" else 1
        if args.command == "validate-playback":
            result = _validate_playback(args, metrics)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "pass" else 1
        raise AssertionError(args.command)
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary records all failures
        metrics.emit(
            "process_end",
            phase=getattr(args, "command", "unknown"),
            status="error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        print(f"VR diagnostic failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        metrics.close()


if __name__ == "__main__":
    raise SystemExit(main())

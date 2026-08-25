#!/usr/bin/env python3
"""Measure and capture a full-origami MD frame for native VR.

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
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import quote


DEFAULT_JOB_ID = "fc12195d0636"
DEFAULT_CONFIG = Path(
    "/media/jojo/Archive/NADOC_archive/fc12195d0636/package/"
    "24hb_2xT_namd_solvated/nadoc_md_run.json"
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


def _write_visualization(
    output: Path,
    atoms: list[dict[str, Any]],
    identity: dict[str, Any],
    metrics: JsonlMetrics,
) -> int:
    names = identity.get("names")
    base_keys = identity.get("base_keys")
    if not isinstance(names, list) or not isinstance(base_keys, list):
        raise ValueError("ready message does not contain atom names/base keys")
    if len(atoms) != len(names) or len(atoms) != len(base_keys):
        raise ValueError(
            f"atom/frame identity mismatch: atoms={len(atoms)}, names={len(names)}, "
            f"base_keys={len(base_keys)}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".next")
    seen: set[str] = set()
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(
            f"NADOCVR_VISUALIZATION 3 1 namd_display ballstick cpk {len(atoms)}\n"
        )
        for index, atom in enumerate(atoms):
            owner = _encode_atom_owner(str(base_keys[index]), str(names[index]))
            if owner in seen:
                raise ValueError(f"duplicate normalized atom owner at row {index}: {owner}")
            seen.add(owner)
            try:
                x, y, z = float(atom["x"]), float(atom["y"]), float(atom["z"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid atom coordinates at row {index}") from exc
            handle.write(f"V {owner} {x:.7g} {y:.7g} {z:.7g} -\n")
            if (index + 1) % 100_000 == 0:
                metrics.emit(
                    "process_progress",
                    phase="visualization_write",
                    completed=index + 1,
                    total=len(atoms),
                )
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    return len(atoms)


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
        }))
        metrics.emit("process_progress", phase="load_sent")
        while True:
            raw = await asyncio.wait_for(socket.recv(), timeout=args.timeout)
            if not isinstance(raw, str):
                metrics.emit("process_progress", phase="unexpected_binary", bytes=len(raw))
                continue
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
                atoms = message.get("atoms")
                if not isinstance(atoms, list):
                    raise ValueError("ballstick frame contains no atoms")
                metrics.emit(
                    "process_progress",
                    phase="frame_received",
                    frame_idx=message.get("frame_idx"),
                    frames=message.get("n_frames"),
                    atoms=len(atoms),
                    chars=len(raw),
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
    return parser


def main() -> int:
    args = _parser().parse_args()
    backend_pid = getattr(args, "backend_pid", None) or (
        _find_backend_pid() if args.command == "capture-md" else None
    )
    metrics = JsonlMetrics(args.metrics.resolve(), backend_pid)
    try:
        if args.command == "capture-md":
            result = asyncio.run(_capture_md(args, metrics))
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "system":
            result = _system_check(metrics)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "capable" else 1
        if args.command == "steamvr-stats":
            result = _steamvr_stats(args, metrics)
            print(json.dumps(result, indent=2))
            return 0 if all(result["assessment"].values()) else 1
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

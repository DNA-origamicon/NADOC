"""Whole-machine resource snapshot — CPU %, host RAM, GPU utilisation + VRAM — for
the live "System monitor" sparklines in each simulation engine's Graphs-and-Metrics
card.

Live-only and local: the frontend polls :func:`sample_system_resources` a few times a
second while the monitor is open and buffers the samples client-side into a rolling
sparkline.  Nothing is persisted (no per-job timeseries).  This is a *display-only*
readout of the host machine and never touches the topology (Three-Layer Law).

GPU fields are ``None`` when there is no NVIDIA GPU / ``nvidia-smi`` (e.g. a CPU-only
box running a CanDo FEM solve), so the card can render the CPU/RAM lines and mark GPU
"n/a" without erroring.

The shaping is split into a pure core (:func:`build_resource_sample`, no I/O — unit
tested) and a thin gatherer (:func:`sample_system_resources`) that reads psutil +
``nvidia-smi`` and hands the raw numbers to the core.
"""
from __future__ import annotations

from typing import Optional

import psutil

from .md_vram import detect_gpu_activity

_MB = 1024 * 1024

# Prime psutil's per-process CPU% baseline at import.  ``cpu_percent(interval=None)``
# reports utilisation *since the previous call*; without this warm-up the first real
# sample the frontend sees would be a meaningless 0.0.
try:  # best-effort — never let a probe failure break import
    psutil.cpu_percent(interval=None)
except Exception:  # pragma: no cover - platform quirk
    pass


def build_resource_sample(
    cpu_pct: Optional[float],
    ram_total_bytes: Optional[int],
    ram_available_bytes: Optional[int],
    gpu_activity: Optional[dict],
) -> dict:
    """Shape raw host readings into the sparkline sample the card consumes (pure).

    ``cpu_pct`` is whole-machine CPU utilisation (0–100).  ``ram_*_bytes`` come from
    :func:`psutil.virtual_memory`.  ``gpu_activity`` is the dict from
    :func:`backend.core.md_vram.detect_gpu_activity` (``{used_mb, total_mb, util_pct,
    …}``) or ``None`` when no GPU is present.

    Percentages are clamped to 0–100 and rounded to one decimal; MB values are ints.
    Any field that cannot be computed is ``None`` (the card renders "n/a").
    """
    ram_used_mb = ram_total_mb = ram_pct = None
    if ram_total_bytes:
        ram_total_mb = round(ram_total_bytes / _MB)
        used = ram_total_bytes - (ram_available_bytes or 0)
        ram_used_mb = round(used / _MB)
        ram_pct = _clamp_pct(100.0 * used / ram_total_bytes)

    gpu_present = bool(gpu_activity) and bool(gpu_activity.get("total_mb"))
    gpu_pct = vram_used_mb = vram_total_mb = vram_pct = None
    if gpu_present:
        vram_used_mb = gpu_activity.get("used_mb")
        vram_total_mb = gpu_activity.get("total_mb")
        gpu_pct = _clamp_pct(gpu_activity.get("util_pct"))
        if vram_used_mb is not None and vram_total_mb:
            vram_pct = _clamp_pct(100.0 * vram_used_mb / vram_total_mb)

    return {
        "cpu_pct": _clamp_pct(cpu_pct),
        "ram_pct": ram_pct,
        "ram_used_mb": ram_used_mb,
        "ram_total_mb": ram_total_mb,
        "gpu_present": gpu_present,
        "gpu_pct": gpu_pct,
        "vram_pct": vram_pct,
        "vram_used_mb": vram_used_mb,
        "vram_total_mb": vram_total_mb,
    }


def _clamp_pct(v) -> Optional[float]:
    """Round to 0.1 and clamp to [0, 100]; pass ``None`` through."""
    if v is None:
        return None
    try:
        return round(max(0.0, min(100.0, float(v))), 1)
    except (TypeError, ValueError):
        return None


def sample_system_resources(*, devices: str = "0") -> dict:
    """One whole-machine sample for the live monitor.  Reads psutil (CPU + host RAM)
    and ``nvidia-smi`` (GPU util + VRAM, via :func:`detect_gpu_activity`), then shapes
    them with :func:`build_resource_sample`.  Best-effort: a failed probe degrades that
    field to ``None`` rather than raising, so the endpoint always returns a sample."""
    try:
        cpu_pct = psutil.cpu_percent(interval=None)
    except Exception:
        cpu_pct = None
    try:
        vm = psutil.virtual_memory()
        ram_total, ram_avail = vm.total, vm.available
    except Exception:
        ram_total = ram_avail = None
    try:
        gpu_activity = detect_gpu_activity(devices=devices)
    except Exception:
        gpu_activity = None
    return build_resource_sample(cpu_pct, ram_total, ram_avail, gpu_activity)

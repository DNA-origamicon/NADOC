"""System resources — REST surface for the live "System monitor" sparklines.

A single snapshot endpoint the simulation cards poll a few times a second while their
monitor is open; the frontend buffers the samples into rolling CPU / GPU / RAM
sparklines (live-only, no persistence).  Whole-machine, local host.  Read-only /
display-only — never touches any design (Three-Layer Law).  Registered in
``backend/api/main.py``.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.system_resources import sample_system_resources

router = APIRouter(tags=["system"])


@router.get("/system/resources")
def system_resources(devices: str = "0") -> dict:
    """Current whole-machine utilisation: ``{cpu_pct, ram_pct, ram_used_mb,
    ram_total_mb, gpu_present, gpu_pct, vram_pct, vram_used_mb, vram_total_mb}``.

    Percentages are 0–100 (or ``None`` if unavailable).  ``gpu_present`` is False on a
    box with no NVIDIA GPU / ``nvidia-smi``, with every GPU/VRAM field then ``None``.
    ``devices`` selects which GPU to report (first id used)."""
    return sample_system_resources(devices=devices)

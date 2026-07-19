"""Whole-machine resource snapshot for the live System-monitor sparklines.

Pins the pure shaper (:func:`build_resource_sample`) — GPU present / absent, %
clamping, MB conversion, missing fields — and the ``GET /system/resources`` route
(with the sampler stubbed so the test never shells ``nvidia-smi`` or reads real load).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import backend.api.routes_system as routes_system
from backend.api.main import app
from backend.core.system_resources import build_resource_sample

_GB = 1024 ** 3
_MB = 1024 ** 2


def test_build_sample_with_gpu():
    s = build_resource_sample(
        42.7, 32 * _GB, 10 * _GB,
        {"used_mb": 3100, "total_mb": 8192, "util_pct": 88},
    )
    assert s["cpu_pct"] == 42.7
    assert s["gpu_present"] is True
    assert s["gpu_pct"] == 88.0
    assert s["vram_used_mb"] == 3100 and s["vram_total_mb"] == 8192
    assert s["vram_pct"] == 37.8                       # 3100/8192
    assert s["ram_total_mb"] == 32 * 1024              # bytes → MB
    assert s["ram_used_mb"] == 22 * 1024               # total - available
    assert s["ram_pct"] == round(100 * 22 / 32, 1)


def test_build_sample_no_gpu_and_clamps():
    s = build_resource_sample(150.0, 8 * _GB, 8 * _GB, None)  # cpu over 100, GPU absent
    assert s["cpu_pct"] == 100.0                        # clamped to [0,100]
    assert s["gpu_present"] is False
    assert s["gpu_pct"] is None and s["vram_pct"] is None
    assert s["ram_used_mb"] == 0                        # available == total
    assert s["ram_pct"] == 0.0


def test_build_sample_none_and_zero_total_are_safe():
    s = build_resource_sample(None, None, None, {"used_mb": 0, "total_mb": 0, "util_pct": 0})
    assert s["cpu_pct"] is None
    assert s["ram_total_mb"] is None and s["ram_pct"] is None
    assert s["gpu_present"] is False                    # total_mb == 0 → treated as no GPU


def test_route_returns_sampled_shape(monkeypatch):
    fake = {
        "cpu_pct": 12.5, "ram_pct": 40.0, "ram_used_mb": 4096, "ram_total_mb": 16384,
        "gpu_present": True, "gpu_pct": 55.0, "vram_pct": 30.0,
        "vram_used_mb": 2400, "vram_total_mb": 8000,
    }
    seen = {}

    def _fake_sample(*, devices="0"):
        seen["devices"] = devices
        return fake

    monkeypatch.setattr(routes_system, "sample_system_resources", _fake_sample)
    with TestClient(app) as client:
        r = client.get("/api/system/resources?devices=1")
    assert r.status_code == 200
    assert r.json() == fake
    assert seen["devices"] == "1"                       # query param threaded through

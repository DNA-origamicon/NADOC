"""HTTP tests for GET /simulate/recommendation (backend/api/routes_simulate).

The route plumbs live GPU/CPU sensors into the pure engine_policy; here we
monkeypatch the sensors to deterministic values and assert the branch behaviour.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


def _patch(monkeypatch, *, activity, contention, active_jobs=(), free=16, ox_pids=None):
    import backend.core.md_vram as md_vram
    import backend.core.namd_runner as namd_runner
    import backend.core.oxdna_runner as oxdna_runner
    import backend.api.routes_jobs as routes_jobs

    monkeypatch.setattr(md_vram, "detect_gpu_activity", lambda devices="0": activity)
    monkeypatch.setattr(
        md_vram, "gpu_contention_summary", lambda act, own_pids=(): contention
    )
    monkeypatch.setattr(routes_jobs, "_collect_active", lambda: list(active_jobs))
    monkeypatch.setattr(namd_runner, "active_namd_pids", lambda: set())
    monkeypatch.setattr(oxdna_runner, "_ACTIVE_PIDS", ox_pids or {})
    from backend.core import lammps_runner

    monkeypatch.setattr(lammps_runner, "free_cpu_cores", lambda: free)


def test_recommendation_shape_and_free_gpu(monkeypatch):
    _patch(
        monkeypatch,
        activity={"free_mb": 12000, "total_mb": 12000, "util_pct": 3, "processes": []},
        contention={
            "available": True,
            "busy": False,
            "processes": [],
            "free_mb": 12000,
            "total_mb": 12000,
            "util_pct": 3,
        },
    )
    r = client.get("/api/simulate/recommendation")
    assert r.status_code == 200
    b = r.json()
    for k in ("recommendation", "gpu", "free_cores", "has_proteins", "n_nucleotides"):
        assert k in b
    assert b["gpu"]["busy"] is False
    assert b["recommendation"]["engine"] == "oxdna"  # GPU free → oxDNA


def test_recommendation_external_busy_gpu_picks_lammps(monkeypatch):
    _patch(
        monkeypatch,
        activity={
            "free_mb": 2000,
            "total_mb": 12000,
            "util_pct": 95,
            "processes": [{"pid": 999, "name": "namd3", "mem_mb": 8000}],
        },
        contention={
            "available": True,
            "busy": True,
            "processes": [{"pid": 999, "name": "namd3", "mem_mb": 8000}],
            "free_mb": 2000,
            "total_mb": 12000,
            "util_pct": 95,
        },
    )
    b = client.get("/api/simulate/recommendation").json()
    assert b["gpu"]["busy"] is True
    assert b["gpu"]["holder_kind"] == "external"
    rec = b["recommendation"]
    assert rec["engine"] == "lammps" and rec["backend"] == "CPU"
    assert rec["needs_dialog"] is True


def test_recommendation_own_gpu_job_is_busy_with_eta(monkeypatch):
    """A running NADOC GPU job counts as busy (a new run would contend) and its ETA shows."""
    _patch(
        monkeypatch,
        activity={"free_mb": 6000, "total_mb": 12000, "util_pct": 60, "processes": []},
        contention={
            "available": True,
            "busy": False,
            "processes": [],
            "free_mb": 6000,
            "total_mb": 12000,
            "util_pct": 60,
        },
        active_jobs=[
            {
                "engine": "md",
                "resource_class": "gpu",
                "status": "running",
                "eta_seconds": 425.0,
            }
        ],
    )
    b = client.get("/api/simulate/recommendation").json()
    assert b["gpu"]["busy"] is True and b["gpu"]["holder_kind"] == "nadoc"
    assert b["gpu_eta_seconds"] == 425.0
    assert b["recommendation"]["engine"] == "lammps"  # our NAMD job holds GPU → CPU

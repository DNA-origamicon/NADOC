"""Live-job end-to-end check: Display-MD works + is ready in time for 3x6x200.

ENVIRONMENT-DEPENDENT integration test.  Registered *slow* (skipped by
``just test-fast``) and SKIPS unless the real 3x6x200_test NAMD job is present, and
under xdist (``just test`` uses ``-n auto`` — 16 workers + the live sim saturate the
CPU and inflate the wall-clock budgets into false failures).  Run it directly:

    python -m pytest tests/test_md_display_ready_live.py

It drives ``/ws/md-run`` against the actual job (143 MB PSF, live DCD) mapped onto
the design the job was built from, and checks BOTH things that were broken/slow:

  * CORRECTNESS — the segid-based p_order maps every trajectory DNA P atom, and the
    streamed frame Kabsch-aligns to the design at a physically sane RMSD (a scrambled
    mapping — the psfgen chainID-collision bug this replaced — lands at >50 Å).
  * READINESS   — one-time ``load`` → ``ready`` (what the prewarm hides) and the warm
    ``get_latest`` frame (what a prewarmed toggle pays) stay within budget.  The
    ``_try_unwrap`` make-whole skip keeps the load off its former multi-minute path.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import Design


_REPO = Path(__file__).resolve().parents[1]
_JOBS = _REPO / "workspace" / "md_jobs"

_LOAD_BUDGET_S = 30.0        # cold model build + PSF parse ≈ ~9 s (regression ceiling)
_WARM_FRAME_BUDGET_S = 2.0   # warm get_latest = O(1) dcd read + PBC/Kabsch (~tens of ms)
_RMSD_SANE_A = 20.0          # correct mapping ≈ 7 Å; a scrambled one is >50 Å


def _find_job():
    if not _JOBS.exists():
        return None
    for psf in sorted(_JOBS.glob("*/package/*/*_hmr.psf")):
        if "3x6x200" not in psf.name:
            continue
        run_dir = psf.parent
        job_root = run_dir.parents[1]
        design_json = job_root / "design.json"
        dcds = sorted(run_dir.glob("output/*.dcd"), key=lambda p: p.stat().st_mtime)
        pdb = run_dir / "3x6x200_test.pdb"
        if design_json.exists() and pdb.exists() and dcds:
            return {"design": design_json, "psf": psf, "pdb": pdb, "dcd": dcds[-1]}
    return None


_JOB = _find_job()

pytestmark = [
    pytest.mark.skipif(_JOB is None, reason="3x6x200_test live NAMD job not present"),
    pytest.mark.skipif(
        bool(os.environ.get("PYTEST_XDIST_WORKER")),
        reason="timing test — run serially, not under xdist parallelism",
    ),
]


def _design_p_reference(design):
    """{(helix_id, bp_index, direction): (x,y,z) nm} for the design's rigid P atoms."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import md_pkey

    model = build_atomistic_model(design)
    ref = {}
    for a in model.atoms:
        if a.name == "P":
            ref[tuple(md_pkey(a))] = (a.x, a.y, a.z)
    return ref


def test_display_md_end_to_end_correct_and_ready(capsys):
    from fastapi.testclient import TestClient

    design = Design.model_validate(json.loads(_JOB["design"].read_text()))
    design_state.set_design(design)
    p_ref = _design_p_reference(design)

    client = TestClient(app)
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json({
            "action": "load",
            "topology_path": str(_JOB["psf"]),
            "xtc_path": str(_JOB["dcd"]),
            "coordinate_path": str(_JOB["pdb"]),
            "mode": "nadoc",
        })
        t0 = time.perf_counter()
        ready = None
        for _ in range(400):
            m = ws.receive_json()
            if m["type"] == "ready":
                ready = m
                break
            if m["type"] == "error":
                pytest.fail(f"load errored (mapping regressed?): {m['message']}")
            assert m["type"] == "log", m
        t_load = time.perf_counter() - t0
        assert ready is not None and ready["n_frames"] > 0

        t1 = time.perf_counter()
        ws.send_json({"action": "get_latest"})
        frame = ws.receive_json()
        t_frame = time.perf_counter() - t1
        assert frame["type"] == "frame", frame

    positions = frame["positions"]
    # Every trajectory DNA P atom mapped to a design key (no drop) — the whole point
    # of the segid map vs the old colliding reference-PDB path.
    assert len(positions) > 6000, f"only {len(positions)} P atoms mapped"

    # Correctness: rigid (bp>=0) streamed positions Kabsch-align to the design.
    got, des = [], []
    for p in positions:
        key = (p["helix_id"], p["bp_index"], p["direction"])
        if isinstance(p["bp_index"], int) and p["bp_index"] >= 0 and key in p_ref:
            got.append([p["x"], p["y"], p["z"]])
            des.append(p_ref[key])
    got = np.asarray(got)
    des = np.asarray(des)
    assert len(got) > 5000, f"only {len(got)} rigid P atoms matched the design"
    A = des - des.mean(0)
    B = got - got.mean(0)
    H = A.T @ B
    U, _, Vt = np.linalg.svd(H)
    D = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, D]) @ U.T
    rmsd_A = float(np.sqrt(((B - A @ R.T) ** 2).sum(1).mean()) * 10.0)  # nm→Å

    with capsys.disabled():
        print(
            f"\n[md-e2e] {_JOB['dcd'].name}: mapped {len(positions)} P "
            f"({len(got)} rigid) · RMSD-to-design {rmsd_A:.1f} Å · "
            f"load {t_load:.2f}s · warm frame {t_frame * 1000:.0f} ms · "
            f"{ready['n_frames']} frames"
        )

    assert rmsd_A < _RMSD_SANE_A, (
        f"rigid RMSD to design {rmsd_A:.1f} Å exceeds {_RMSD_SANE_A} Å "
        "— the p_order mapping is likely scrambled"
    )
    assert t_load < _LOAD_BUDGET_S, f"load {t_load:.1f}s exceeds {_LOAD_BUDGET_S}s ceiling"
    assert t_frame < _WARM_FRAME_BUDGET_S, f"warm frame {t_frame:.2f}s exceeds budget"

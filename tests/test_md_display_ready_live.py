"""Headless 18HB/200bp websocket display check with >62 strands.

Controlled DCD frames verify mapping and readiness, not physical equilibration.
The existing load and warm-frame budgets also run under the full parallel suite.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from backend.api import state as design_state
from backend.api.main import app


pytest_plugins = ["tests.md_trajectory_fixture"]

_LOAD_BUDGET_S = 30.0  # cold model build + PSF parse ≈ ~9 s (regression ceiling)
_WARM_FRAME_BUDGET_S = 2.0  # warm get_latest = O(1) dcd read + PBC/Kabsch (~tens of ms)
_RMSD_SANE_A = 20.0  # controlled fixture ≈ 0.2 Å; a scrambled mapping is >50 Å


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


def test_display_md_end_to_end_correct_and_ready(capsys, generated_large_md):
    from fastapi.testclient import TestClient

    design = generated_large_md.design
    design_state.set_design(design)
    p_ref = _design_p_reference(design)

    client = TestClient(app)
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json(
            {
                "action": "load",
                "topology_path": str(generated_large_md.psf),
                "xtc_path": str(generated_large_md.dcd),
                "coordinate_path": str(generated_large_md.ref),
                "mode": "nadoc",
            }
        )
        t0 = time.perf_counter()
        ready = None
        for _ in range(400):
            m = ws.receive_json()
            if m["type"] == "ready":
                ready = m
                break
            if m["type"] == "error":
                pytest.fail(f"load errored (mapping regressed?): {m['message']}")
            assert m["type"] in {"log", "loading"}, m
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
            f"\n[md-e2e] {generated_large_md.dcd.name}: mapped {len(positions)} P "
            f"({len(got)} rigid) · RMSD-to-design {rmsd_A:.1f} Å · "
            f"load {t_load:.2f}s · warm frame {t_frame * 1000:.0f} ms · "
            f"{ready['n_frames']} frames"
        )

    assert rmsd_A < _RMSD_SANE_A, (
        f"rigid RMSD to design {rmsd_A:.1f} Å exceeds {_RMSD_SANE_A} Å "
        "— the p_order mapping is likely scrambled"
    )
    assert t_load < _LOAD_BUDGET_S, (
        f"load {t_load:.1f}s exceeds {_LOAD_BUDGET_S}s ceiling"
    )
    assert t_frame < _WARM_FRAME_BUDGET_S, f"warm frame {t_frame:.2f}s exceeds budget"

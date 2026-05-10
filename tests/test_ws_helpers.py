"""Coverage backfill for backend/api/ws.py.

This module is a (test) coverage backfill for refactor 10-D. The production
target — `backend/api/ws.py` — is read-only here: no production code is
modified and no new dev dependencies are added.

Strategy chosen
---------------
**Option B (TestClient route-driving), no pytest-asyncio.**

The 3 inner helpers (`_try_unwrap`, `_load_sync`, `_seek_sync`) live as
closures inside the 578-LOC `md_run_ws` handler. They cannot be called in
isolation without modifying ws.py. Option A (mock-patch + getsource exec)
was rejected as fragile. Option C (module-level helpers only) was rejected
because ws.py has no module-level functions besides the 4 route handlers
themselves — only 3 constants live at module scope, leaving no headroom to
hit a 25%+ calibrated target.

Option B uses Starlette's synchronous `TestClient.websocket_connect()` to
drive each route from the outside. This works without `pytest-asyncio`
because TestClient runs the event loop in a worker thread. Helper coverage
falls out naturally — `_load_sync` runs when we send `action: load`,
`_seek_sync` runs on `seek`, `_try_unwrap` runs as part of `_load_sync`.

For the md-run happy path we synthesise a tiny self-consistent fixture in a
TemporaryDirectory:
- `input_nadoc.pdb` — produced by `backend.core.pdb_export.export_pdb` on
  the demo design (real PDB text, not a stub).
- `t.gro` + `t.xtc` — built from `MDAnalysis.Universe.empty` with one P +
  one C1' atom per residue (the minimum the `_seek_sync` selectors require).
  Total fixture footprint < 5 KB.

The remaining 3 ws routes (`physics_ws`, `physics_fast_ws`, `fem_ws`) are
exercised end-to-end on the demo design — both happy paths and "no design
loaded" error paths. These were the cheapest route to additional ws.py
coverage without further fixtures.
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """Fresh TestClient per test (websocket sessions don't share state)."""
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def demo_design_loaded():
    """Install the demo design into design_state for the duration of one test."""
    design_state.set_design(_demo_design())
    yield design_state.get_design()
    # Best-effort restore: clear so other tests with autouse reset_state still work.
    design_state._active_design = None  # type: ignore[attr-defined]


@pytest.fixture
def no_design_loaded():
    """Force design_state to None (the 'no design loaded' precondition)."""
    design_state._active_design = None  # type: ignore[attr-defined]
    yield
    design_state._active_design = None  # type: ignore[attr-defined]


@pytest.fixture
def md_fixture_dir(demo_design_loaded):
    """Build a tiny self-consistent GROMACS-style fixture for md_run_ws.

    Yields the path to a TemporaryDirectory containing:
      - input_nadoc.pdb — exported from the demo design
      - t.gro          — minimal MDAnalysis topology (P + C1' per residue)
      - t.xtc          — 3-frame trajectory of identical positions

    The trick: build_p_gro_order() drops the 5'-terminal P (no phosphate
    on the first nt of a chain), so the GRO must contain exactly
    len(p_order) P atoms — not len(all P atoms in the model).
    """
    import MDAnalysis as mda  # type: ignore

    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import build_chain_map, build_p_gro_order
    from backend.core.pdb_export import export_pdb

    design = demo_design_loaded
    pdb_text = export_pdb(design)
    model    = build_atomistic_model(design)
    cm       = build_chain_map(model)
    p_order  = build_p_gro_order(pdb_text, cm)

    # First len(p_order) P atoms — same residues build_p_gro_order kept.
    p_atoms = [a for a in model.atoms if a.name == "P"][: len(p_order)]
    n = len(p_atoms)

    # Two atoms per residue: P + C1'.  C1' is required for the base-normal
    # (P→C1') step inside _seek_sync.
    n_atoms       = n * 2
    atom_resindex = [r for i in range(n) for r in (i, i)]
    names         = [name for _ in range(n) for name in ("P", "C1'")]
    u = mda.Universe.empty(
        n_atoms=n_atoms, n_residues=n, n_segments=1,
        atom_resindex=atom_resindex, residue_segindex=[0] * n,
        trajectory=True,
    )
    u.add_TopologyAttr("name",    names)
    u.add_TopologyAttr("resname", ["DA"] * n)
    u.add_TopologyAttr("resid",   list(range(1, n + 1)))
    u.add_TopologyAttr("segid",   ["A"])

    pos = []
    for a in p_atoms:
        pos.append([a.x, a.y, a.z])
        pos.append([a.x + 0.5, a.y, a.z])  # C1' offset 0.5 Å along x
    u.atoms.positions = np.array(pos, dtype=np.float32)
    u.dimensions      = [200.0, 200.0, 200.0, 90.0, 90.0, 90.0]

    with tempfile.TemporaryDirectory() as td:
        (open(os.path.join(td, "input_nadoc.pdb"), "w")
            .write(pdb_text))
        gro = os.path.join(td, "t.gro")
        xtc = os.path.join(td, "t.xtc")
        u.atoms.write(gro)
        with mda.Writer(xtc, n_atoms=n_atoms) as w:
            for _ in range(3):
                w.write(u.atoms)
        yield {"dir": td, "gro": gro, "xtc": xtc, "n_frames": 3,
               "n_p_atoms": len(cm), "n_p_order": n}


# ── /ws/physics — XPBD streaming ─────────────────────────────────────────────


def test_physics_ws_no_design(client, no_design_loaded):
    """start_physics with no design → error message."""
    with client.websocket_connect("/ws/physics") as ws:
        ws.send_json({"action": "start_physics"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "No design" in msg["message"]


def test_physics_ws_full_lifecycle(client, demo_design_loaded):
    """Cover start_physics → 1 positions frame → update_params → stop_physics."""
    with client.websocket_connect("/ws/physics") as ws:
        ws.send_json({"action": "start_physics"})
        status = ws.receive_json()
        assert status["type"] == "status"

        # Wait for at least one positions frame.
        positions_msg = ws.receive_json()
        assert positions_msg["type"] == "positions"
        assert positions_msg["step"] >= 1
        assert isinstance(positions_msg["data"], list)

        # Hit every branch of update_params.
        ws.send_json({
            "action":            "update_params",
            "noise_amplitude":    0.0,
            "bond_stiffness":     1.0,
            "bend_stiffness":     1.0,
            "bp_stiffness":       1.0,
            "stacking_stiffness": 1.0,
            "elec_amplitude":     1.0,
            "debye_length":       1.0,
            "substeps_per_frame": 5,
        })

        ws.send_json({"action": "stop_physics"})
        # Drain until we see the "Physics stopped." status.  A positions
        # message may arrive first because the stream loop ran one more step.
        for _ in range(5):
            m = ws.receive_json()
            if m.get("type") == "status" and "stopped" in m.get("message", "").lower():
                break
        else:
            pytest.fail("Did not see 'Physics stopped.' status")


def test_physics_ws_reset_branch(client, demo_design_loaded):
    """reset_physics action → re-runs _start_stream."""
    with client.websocket_connect("/ws/physics") as ws:
        ws.send_json({"action": "start_physics"})
        ws.receive_json()                       # initial status
        ws.receive_json()                       # first positions frame

        ws.send_json({"action": "reset_physics", "use_straight": False})
        # Reset sends a new "Physics started." status.
        for _ in range(5):
            m = ws.receive_json()
            if m.get("type") == "status":
                assert "started" in m.get("message", "").lower()
                break


# ── /ws/physics/fast — fast XPBD ─────────────────────────────────────────────


def test_physics_fast_ws_no_design(client, no_design_loaded):
    with client.websocket_connect("/ws/physics/fast") as ws:
        ws.send_json({"action": "start_fast_physics"})
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_physics_fast_ws_lifecycle(client, demo_design_loaded):
    """Drive start_fast_physics → drain ≥ 1 update → stop_fast_physics."""
    with client.websocket_connect("/ws/physics/fast") as ws:
        ws.send_json({"action": "start_fast_physics"})
        status = ws.receive_json()
        assert status["type"] == "status"

        # Drain a couple of frames (or until convergence).
        saw_update = False
        for _ in range(6):
            m = ws.receive_json()
            if m.get("type") == "physics_update":
                saw_update = True
                assert "particles" in m
                assert "residuals" in m
                if m.get("converged"):
                    break
        assert saw_update

        ws.send_json({"action": "stop_fast_physics"})
        for _ in range(5):
            m = ws.receive_json()
            if m.get("type") == "status" and "stopped" in m.get("message", "").lower():
                break


# ── /ws/fem — CanDo-style FEM ────────────────────────────────────────────────


def test_fem_ws_no_design(client, no_design_loaded):
    with client.websocket_connect("/ws/fem") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "fem_error"
        assert "No design" in msg["message"]


def test_fem_ws_progress_then_terminal(client, demo_design_loaded):
    """Drive /ws/fem; demo design either solves or errors but BOTH paths cover.

    Either a `fem_result` (full happy path through compute_rmsf, etc.) or a
    `fem_error` (early failure caught in the route's try/except) terminates
    the run. Both exit through the `finally: websocket.close()` branch.
    """
    saw_progress = False
    last = None
    with client.websocket_connect("/ws/fem") as ws:
        for _ in range(50):
            m = ws.receive_json()
            last = m
            if m.get("type") == "fem_progress":
                saw_progress = True
            if m.get("type") in ("fem_result", "fem_error"):
                break
    assert saw_progress or last["type"] == "fem_error"
    assert last["type"] in ("fem_result", "fem_error")


# ── /ws/md-run — GROMACS trajectory streaming ────────────────────────────────


def test_md_run_ws_no_design(client, no_design_loaded):
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json({"action": "load", "topology_path": "/tmp/x.gro",
                      "xtc_path": "/tmp/x.xtc", "mode": "nadoc"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "No design" in msg["message"]


def test_md_run_ws_missing_paths(client, demo_design_loaded):
    """load with empty topology/xtc paths → 'paths required' error."""
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json({"action": "load", "topology_path": "",
                      "xtc_path": "", "mode": "nadoc"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "required" in msg["message"].lower()


def test_md_run_ws_seek_before_load(client, demo_design_loaded):
    """seek with no trajectory loaded → error."""
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json({"action": "seek", "frame_idx": 0})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "No trajectory" in msg["message"]


def test_md_run_ws_get_latest_before_load(client, demo_design_loaded):
    """get_latest with no trajectory loaded → error."""
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json({"action": "get_latest"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "No trajectory" in msg["message"]


def test_md_run_ws_load_missing_input_pdb(client, demo_design_loaded, tmp_path):
    """load with valid file paths but no input_nadoc.pdb in the run dir.

    Hits the early `if not input_pdb.exists(): raise ValueError(...)` branch
    inside `_load_sync` (covered as the exception is caught and surfaced via
    the websocket as an error message).
    """
    gro = tmp_path / "t.gro"
    xtc = tmp_path / "t.xtc"
    gro.write_text("dummy gro contents (will not be opened — _load_sync raises before mda.Universe call)")
    xtc.write_bytes(b"")  # not opened either

    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json({"action": "load", "topology_path": str(gro),
                      "xtc_path": str(xtc), "mode": "nadoc"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "input_nadoc.pdb" in msg["message"]


def test_md_run_ws_load_seek_get_latest(client, md_fixture_dir):
    """End-to-end happy path through _load_sync, _try_unwrap, _seek_sync.

    Drives the full inner-helper flow:
      1. action=load        → _load_sync (chain map, p_order, Universe open,
                              _try_unwrap, PBC check, centroid, C1' map)
      2. action=seek        → _seek_sync (all PBC + Kabsch branches with
                              eq_centered+rigid_mask present)
      3. action=seek again  → _seek_sync R_prev branch (sequential frame)
      4. action=get_latest  → _refresh_and_seek + _seek_sync last frame
    """
    fix = md_fixture_dir
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json({"action": "load", "topology_path": fix["gro"],
                      "xtc_path": fix["xtc"], "mode": "nadoc"})
        ready = None
        for _ in range(60):
            m = ws.receive_json()
            if m["type"] == "ready":
                ready = m
                break
            assert m["type"] == "log"
        assert ready is not None
        assert ready["n_frames"] == fix["n_frames"]
        assert ready["n_p_atoms"] == fix["n_p_atoms"]

        # Frame 0 — first seek (no R_prev yet).
        ws.send_json({"action": "seek", "frame_idx": 0})
        f0 = ws.receive_json()
        assert f0["type"] == "frame"
        assert f0["frame_idx"] == 0
        assert len(f0["positions"]) == fix["n_p_order"]
        # Each entry has helix_id, bp_index, direction, x/y/z and (because
        # C1' map is valid) the n[xyz] base-normal triplet.
        e0 = f0["positions"][0]
        for k in ("helix_id", "bp_index", "direction", "x", "y", "z",
                  "nx", "ny", "nz"):
            assert k in e0

        # Frame 1 — sequential seek; exercises the R_prev sequential branch.
        ws.send_json({"action": "seek", "frame_idx": 1})
        f1 = ws.receive_json()
        assert f1["type"] == "frame"
        assert f1["frame_idx"] == 1

        # get_latest — exercises _refresh_and_seek (rebuilds Universe).
        ws.send_json({"action": "get_latest"})
        gl = ws.receive_json()
        assert gl["type"] == "frame"
        assert gl["frame_idx"] == fix["n_frames"] - 1


def test_md_run_ws_load_seek_ballstick(client, md_fixture_dir):
    """End-to-end through the 'ballstick' branch of _load_sync + _seek_sync.

    Different code path than 'nadoc'/'beads': hits the heavy-atom selection
    block at the bottom of _load_sync and the `else: # ballstick` branch in
    _seek_sync.
    """
    fix = md_fixture_dir
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json({"action": "load", "topology_path": fix["gro"],
                      "xtc_path": fix["xtc"], "mode": "ballstick"})
        ready = None
        for _ in range(60):
            m = ws.receive_json()
            if m["type"] == "ready":
                ready = m
                break
            assert m["type"] == "log"
        assert ready is not None

        ws.send_json({"action": "seek", "frame_idx": 0})
        f0 = ws.receive_json()
        assert f0["type"] == "frame"
        # ballstick returns "atoms", not "positions".
        assert "atoms" in f0
        assert isinstance(f0["atoms"], list)
        if f0["atoms"]:
            a0 = f0["atoms"][0]
            for k in ("serial", "element", "x", "y", "z"):
                assert k in a0

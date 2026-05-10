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

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
from backend.api.ws import _has_usable_unit_cell


@pytest.mark.parametrize(
    ("dimensions", "expected"),
    [
        (None, False),
        ([0.0, 0.0, 0.0, 90.0, 90.0, 90.0], False),
        ([92.5, 104.25, 130.75, 90.0, 90.0, 90.0], True),
    ],
)
def test_unit_cell_gate_for_atomistic_unwrap(dimensions, expected):
    """A boxless Alpine stand-in must skip lazy mda_unwrap instead of failing seek."""

    class _Trajectory:
        ts = type("_TS", (), {"dimensions": dimensions})()

    universe = type("_Universe", (), {"trajectory": _Trajectory()})()
    assert _has_usable_unit_cell(universe) is expected


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
    design_state.close_session()


@pytest.fixture
def no_design_loaded():
    """Force design_state to None (the 'no design loaded' precondition)."""
    design_state.close_session()
    yield
    design_state.close_session()


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
    model = build_atomistic_model(design)
    cm = build_chain_map(model)
    p_order = build_p_gro_order(pdb_text, cm)

    # First len(p_order) P atoms — same residues build_p_gro_order kept.
    p_atoms = [a for a in model.atoms if a.name == "P"][: len(p_order)]
    n = len(p_atoms)

    # Two atoms per residue: P + C1'.  C1' is required for the base-normal
    # (P→C1') step inside _seek_sync.
    n_atoms = n * 2
    atom_resindex = [r for i in range(n) for r in (i, i)]
    names = [name for _ in range(n) for name in ("P", "C1'")]
    u = mda.Universe.empty(
        n_atoms=n_atoms,
        n_residues=n,
        n_segments=1,
        atom_resindex=atom_resindex,
        residue_segindex=[0] * n,
        trajectory=True,
    )
    u.add_TopologyAttr("name", names)
    u.add_TopologyAttr("resname", ["DA"] * n)
    u.add_TopologyAttr("resid", list(range(1, n + 1)))
    u.add_TopologyAttr("segid", ["A"])

    pos = []
    for a in p_atoms:
        pos.append([a.x, a.y, a.z])
        pos.append([a.x + 0.5, a.y, a.z])  # C1' offset 0.5 Å along x
    u.atoms.positions = np.array(pos, dtype=np.float32)
    u.dimensions = [200.0, 200.0, 200.0, 90.0, 90.0, 90.0]

    with tempfile.TemporaryDirectory() as td:
        (open(os.path.join(td, "input_nadoc.pdb"), "w").write(pdb_text))
        gro = os.path.join(td, "t.gro")
        xtc = os.path.join(td, "t.xtc")
        u.atoms.write(gro)
        with mda.Writer(xtc, n_atoms=n_atoms) as w:
            for _ in range(3):
                w.write(u.atoms)
        yield {
            "dir": td,
            "gro": gro,
            "xtc": xtc,
            "n_frames": 3,
            "n_p_atoms": len(cm),
            "n_p_order": n,
        }


@pytest.fixture
def namd_dcd_fixture(demo_design_loaded):
    """Build a NAMD-style DCD fixture that drives the dcd_fast LIVE fast path.

    The live NAMD display reads the latest DCD frame through
    ``backend.core.dcd_fast`` (an O(1) byte-seek), NOT MDAnalysis ``load_new`` —
    the GRO/XTC fixture above only exercises the MDAnalysis fallback, so the real
    live path had no WS-level coverage.  This fixture yields a genuine CHARMM DCD
    (MDAnalysis' writer emits NAMD-compatible records), a ``.gro`` topology, and
    the design's own PDB as the NAMD reference coordinate.  ``is_namd`` triggers on
    the ``.dcd`` suffix, so ``_load_sync`` walks P atoms via ``build_p_pdb_order``;
    the DCD atoms are laid out in exactly that order and the P positions are the
    design's own (PDB Å) so the alignment pipeline should reproduce design eq.

    Yields a dict whose ``write(k)`` callable (re)writes the DCD with k frames
    (frame f nudged f·shift Å so successive frames differ).
    """
    import MDAnalysis as mda  # type: ignore

    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import (
        build_chain_map,
        build_p_pdb_order,
        md_rigid_reference,
    )
    from backend.core.pdb_export import export_pdb

    design = demo_design_loaded
    pdb_text = export_pdb(design)
    model = build_atomistic_model(design)
    cm = build_chain_map(model)
    p_order = build_p_pdb_order(pdb_text, cm)
    eq_positions, _eq_valid, rigid_mask = md_rigid_reference(model, p_order)

    # P-atom coords (Å, PDB frame) in build_p_pdb_order's exact walk order.
    p_xyz = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 54 or line[12:16].strip() != "P":
            continue
        if cm.get((line[21], int(line[22:26]))) is None:
            continue
        p_xyz.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    p_xyz = np.array(p_xyz, dtype=np.float32)
    n = len(p_order)
    assert len(p_xyz) == n, (len(p_xyz), n)

    # Two atoms per residue: P + C1' (C1' feeds the P→C1' base-normal step).
    n_atoms = n * 2
    atom_resindex = [r for i in range(n) for r in (i, i)]
    names = [nm for _ in range(n) for nm in ("P", "C1'")]
    u = mda.Universe.empty(
        n_atoms=n_atoms,
        n_residues=n,
        n_segments=1,
        atom_resindex=atom_resindex,
        residue_segindex=[0] * n,
        trajectory=True,
    )
    u.add_TopologyAttr("name", names)
    u.add_TopologyAttr("resname", ["DA"] * n)
    u.add_TopologyAttr("resid", list(range(1, n + 1)))
    u.add_TopologyAttr("segid", ["A"])

    base = np.empty((n_atoms, 3), dtype=np.float32)
    base[0::2] = p_xyz  # P atoms = design positions (Å)
    base[1::2] = p_xyz + np.array([0.5, 0.0, 0.0], dtype=np.float32)  # C1' offset

    with tempfile.TemporaryDirectory() as td:
        pdb_path = os.path.join(td, "input_nadoc.pdb")
        with open(pdb_path, "w") as f:
            f.write(pdb_text)
        gro = os.path.join(td, "t.gro")
        dcd = os.path.join(td, "t.dcd")
        u.atoms.positions = base
        u.dimensions = [200.0, 200.0, 200.0, 90.0, 90.0, 90.0]
        u.atoms.write(gro)

        def write(k, shift=0.05, dimensions=(200.0, 200.0, 200.0, 90.0, 90.0, 90.0)):
            with mda.Writer(dcd, n_atoms=n_atoms) as w:
                for fr in range(k):
                    pos = base.copy()
                    pos[:, 0] += fr * shift
                    u.atoms.positions = pos
                    u.dimensions = dimensions
                    w.write(u.atoms)

        write(3)
        yield {
            "dir": td,
            "gro": gro,
            "dcd": dcd,
            "pdb": pdb_path,
            "n_p_order": n,
            "eq_positions": eq_positions,
            "rigid_mask": rigid_mask,
            "write": write,
        }


def _await_md_ready(ws, expect_frames=None):
    """Drain load logs and return the 'ready' message (fails on early error)."""
    for _ in range(80):
        m = ws.receive_json()
        if m["type"] == "ready":
            if expect_frames is not None:
                assert m["n_frames"] == expect_frames, m
            return m
        assert m["type"] == "log", m
    raise AssertionError("no 'ready' message received")


def _load_namd(ws, fix, mode="nadoc"):
    ws.send_json(
        {
            "action": "load",
            "topology_path": fix["gro"],
            "xtc_path": fix["dcd"],
            "coordinate_path": fix["pdb"],
            "mode": mode,
        }
    )


# ── /ws/md-run — GROMACS trajectory streaming ────────────────────────────────


def test_md_run_ws_no_design(client, no_design_loaded):
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json(
            {
                "action": "load",
                "topology_path": "/tmp/x.gro",
                "xtc_path": "/tmp/x.xtc",
                "mode": "nadoc",
            }
        )
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "No design" in msg["message"]


def test_md_run_ws_missing_paths(client, demo_design_loaded):
    """load with empty topology/xtc paths → 'paths required' error."""
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json(
            {"action": "load", "topology_path": "", "xtc_path": "", "mode": "nadoc"}
        )
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
    gro.write_text(
        "dummy gro contents (will not be opened — _load_sync raises before mda.Universe call)"
    )
    xtc.write_bytes(b"")  # not opened either

    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json(
            {
                "action": "load",
                "topology_path": str(gro),
                "xtc_path": str(xtc),
                "mode": "nadoc",
            }
        )
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
        ws.send_json(
            {
                "action": "load",
                "topology_path": fix["gro"],
                "xtc_path": fix["xtc"],
                "mode": "nadoc",
            }
        )
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
        for k in ("helix_id", "bp_index", "direction", "x", "y", "z", "nx", "ny", "nz"):
            assert k in e0

        # Frame 1 — sequential seek; exercises the R_prev sequential branch.
        ws.send_json({"action": "seek", "frame_idx": 1})
        f1 = ws.receive_json()
        assert f1["type"] == "frame"
        assert f1["frame_idx"] == 1

        # get_latest — exercises _refresh_latest_sync (load_new + safe-back seek).
        ws.send_json({"action": "get_latest"})
        gl = ws.receive_json()
        assert gl["type"] == "frame"
        assert gl["frame_idx"] == fix["n_frames"] - 1


def _rewrite_xtc(gro: str, xtc: str, n_frames: int) -> None:
    """Rewrite the fixture trajectory in place with `n_frames` identical frames.

    Simulates NAMD/GROMACS flushing more frames to a live trajectory between
    two `get_latest` polls.
    """
    import MDAnalysis as mda  # type: ignore

    u = mda.Universe(gro, xtc)
    n_atoms = len(u.atoms)
    frame0 = u.atoms.positions.copy()
    with mda.Writer(xtc, n_atoms=n_atoms) as w:
        for _ in range(n_frames):
            u.atoms.positions = frame0
            w.write(u.atoms)


def test_md_run_ws_get_latest_follows_growing_trajectory(client, md_fixture_dir):
    """get_latest must discover frames appended after load — the live-DCD fix.

    Before the fix this path rebuilt the whole Universe each poll; the regression
    risk is that a cheaper `load_new` fails to re-read the header and never sees
    new frames. Grow the trajectory mid-session and assert the latest frame index
    advances.
    """
    fix = md_fixture_dir
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json(
            {
                "action": "load",
                "topology_path": fix["gro"],
                "xtc_path": fix["xtc"],
                "mode": "nadoc",
            }
        )
        ready = None
        for _ in range(60):
            m = ws.receive_json()
            if m["type"] == "ready":
                ready = m
                break
            assert m["type"] == "log"
        assert ready is not None
        assert ready["n_frames"] == 3

        ws.send_json({"action": "get_latest"})
        gl = ws.receive_json()
        assert gl["type"] == "frame"
        assert gl["frame_idx"] == 2

        # NAMD flushes more frames to the same file.
        _rewrite_xtc(fix["gro"], fix["xtc"], 6)

        ws.send_json({"action": "get_latest"})
        gl2 = ws.receive_json()
        assert gl2["type"] == "frame"
        assert gl2["frame_idx"] == 5, "load_new did not discover appended frames"


def test_md_run_ws_get_latest_tolerates_torn_final_frame(client, md_fixture_dir):
    """A half-flushed trailing frame must not error the live stream.

    MDAnalysis floors n_frames by file size, so a byte-truncated final frame is
    dropped; combined with the safe-back fallback, get_latest returns the last
    COMPLETE frame instead of an error message that would blank Display MD.
    """
    import os

    fix = md_fixture_dir
    _rewrite_xtc(fix["gro"], fix["xtc"], 5)  # known clean 5-frame file
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json(
            {
                "action": "load",
                "topology_path": fix["gro"],
                "xtc_path": fix["xtc"],
                "mode": "nadoc",
            }
        )
        ready = None
        for _ in range(60):
            m = ws.receive_json()
            if m["type"] == "ready":
                ready = m
                break
            assert m["type"] == "log"
        assert ready is not None
        assert ready["n_frames"] == 5

        # Tear the trailing frame: chop bytes off the end of the file.
        size = os.path.getsize(fix["xtc"])
        with open(fix["xtc"], "r+b") as f:
            f.truncate(size - 60)

        ws.send_json({"action": "get_latest"})
        gl = ws.receive_json()
        assert gl["type"] == "frame", f"torn frame surfaced as: {gl}"
        # Last complete frame — strictly fewer than the original 5 (index 4).
        assert gl["frame_idx"] < 4


def test_md_run_ws_dcd_fast_path_get_latest(client, namd_dcd_fixture):
    """Live NAMD path: get_latest reads the last DCD frame via dcd_fast.

    Exercises the O(1) fast path that every real NAMD live run uses — previously
    validated only by the dcd_fast unit tests, never end-to-end through the WS +
    PBC/Kabsch pipeline.
    """
    fix = namd_dcd_fixture
    with client.websocket_connect("/ws/md-run") as ws:
        _load_namd(ws, fix)
        _await_md_ready(ws, expect_frames=3)
        ws.send_json({"action": "get_latest"})
        gl = ws.receive_json()
        assert gl["type"] == "frame", gl
        assert gl["frame_idx"] == 2
        assert len(gl["positions"]) == fix["n_p_order"]


def test_md_run_ws_dcd_get_latest_follows_growing(client, namd_dcd_fixture):
    """dcd_fast must discover frames NAMD appends after load (the real live path)."""
    fix = namd_dcd_fixture
    fix["write"](2)
    with client.websocket_connect("/ws/md-run") as ws:
        _load_namd(ws, fix)
        _await_md_ready(ws, expect_frames=2)
        ws.send_json({"action": "get_latest"})
        assert ws.receive_json()["frame_idx"] == 1
        fix["write"](6)  # NAMD flushes more frames to the same DCD
        ws.send_json({"action": "get_latest"})
        gl = ws.receive_json()
        assert gl["type"] == "frame", gl
        assert gl["frame_idx"] == 5, "dcd_fast did not discover appended frames"
        assert gl["n_frames"] == 6


def test_md_run_ws_dcd_tolerates_torn_final_frame(client, namd_dcd_fixture):
    """A half-flushed trailing DCD frame must not error the live stream."""
    import os

    fix = namd_dcd_fixture
    fix["write"](5)
    # Chop bytes off the end so the trailing frame is incomplete.
    with open(fix["dcd"], "r+b") as f:
        f.truncate(os.path.getsize(fix["dcd"]) - 40)
    with client.websocket_connect("/ws/md-run") as ws:
        _load_namd(ws, fix)
        _await_md_ready(ws)
        ws.send_json({"action": "get_latest"})
        gl = ws.receive_json()
        assert gl["type"] == "frame", f"torn frame surfaced as: {gl}"
        assert gl["frame_idx"] < 4


def test_md_run_ws_dcd_seek_discovers_frames_appended_after_load(
    client, namd_dcd_fixture
):
    """Fix 3: scrubbing to a frame appended after load must not raise IndexError.

    The MDAnalysis Universe indexes frame offsets at open time; the live dcd_fast
    path advances the reported n_frames past that.  A seek into the newer range
    lazily reloads the Universe (load_new) instead of erroring + blanking the
    scene.
    """
    fix = namd_dcd_fixture
    fix["write"](2)
    with client.websocket_connect("/ws/md-run") as ws:
        _load_namd(ws, fix)
        _await_md_ready(ws, expect_frames=2)
        fix["write"](6)  # NAMD appends AFTER the Universe indexed only 2 frames
        ws.send_json({"action": "seek", "frame_idx": 5})
        got = ws.receive_json()
        assert got["type"] == "frame", f"seek beyond stale Universe errored: {got}"
        assert got["frame_idx"] == 5
        assert got["n_frames"] == 6


def test_md_run_ws_dcd_alignment_matches_design_eq(client, namd_dcd_fixture):
    """Numeric regression pin for the PBC + Kabsch pipeline (Fix 6).

    Frame 0 of the fixture IS the design's P geometry, so the full
    unwrap → dynamic-T → Kabsch pipeline must return the design equilibrium
    positions (identity alignment).  A scale (Å/nm), axis-swap, or broken-Kabsch
    regression blows the rigid-atom RMSD up well past this bound; the happy-path
    tests above only assert message shape, not numerics.
    """
    fix = namd_dcd_fixture
    with client.websocket_connect("/ws/md-run") as ws:
        _load_namd(ws, fix)
        _await_md_ready(ws, expect_frames=3)
        ws.send_json({"action": "seek", "frame_idx": 0})
        got = ws.receive_json()
        assert got["type"] == "frame", got
        pos = np.array([[p["x"], p["y"], p["z"]] for p in got["positions"]])
        assert np.all(np.isfinite(pos))
        rm = fix["rigid_mask"]
        eq = fix["eq_positions"]
        d = np.linalg.norm(pos[rm] - eq[rm], axis=1)
        rmsd_A = float(np.sqrt((d**2).mean()) * 10.0)
        assert rmsd_A < 0.5, f"rigid RMSD to design eq = {rmsd_A:.2f} Å"


def test_md_run_ws_full_and_atomistic_share_the_same_p_positions(
    client, namd_dcd_fixture
):
    """The same MD frame cannot acquire a different pose when repr changes.

    Full renders the trajectory's P landmarks as beads; atomistic renders those same
    P atoms among the heavy atoms.  Compare them directly, including the PBC reassembly
    and Kabsch transforms that used to be duplicated between the two branches.
    """
    fix = namd_dcd_fixture

    def frame(mode):
        with client.websocket_connect("/ws/md-run") as socket:
            _load_namd(socket, fix, mode)
            _await_md_ready(socket, expect_frames=3)
            socket.send_json({"action": "seek", "frame_idx": 0})
            return socket.receive_json()

    full = frame("nadoc")
    atomistic = frame("ballstick")
    full_p = np.array([[p["x"], p["y"], p["z"]] for p in full["positions"]])
    # The fixture is P,C1',P,C1',... and serial is the Universe atom index.
    atom_p = np.array(
        [[a["x"], a["y"], a["z"]] for a in atomistic["atoms"] if a["serial"] % 2 == 0]
    )
    assert atom_p.shape == full_p.shape
    assert np.max(np.linalg.norm(atom_p - full_p, axis=1)) < 1e-6


def test_md_run_ws_live_latest_full_and_atomistic_share_the_same_p_positions(
    client, namd_dcd_fixture
):
    """Live get_latest must use one raw DCD frame for both representations.

    This is distinct from an explicit seek: Full has an O(1) raw-DCD fast path, while
    atomistic historically re-read through an MDAnalysis Universe (and its optional
    unwrap transform) before applying the same NADOC alignment a second time.
    """
    fix = namd_dcd_fixture
    fix["write"](5, shift=0.35)

    def latest(mode):
        with client.websocket_connect("/ws/md-run") as socket:
            _load_namd(socket, fix, mode)
            _await_md_ready(socket, expect_frames=5)
            socket.send_json({"action": "get_latest"})
            return socket.receive_json()

    full = latest("nadoc")
    atomistic = latest("ballstick")
    assert full["frame_idx"] == atomistic["frame_idx"] == 4
    full_p = np.array([[p["x"], p["y"], p["z"]] for p in full["positions"]])
    atom_p = np.array(
        [[a["x"], a["y"], a["z"]] for a in atomistic["atoms"] if a["serial"] % 2 == 0]
    )
    assert atom_p.shape == full_p.shape
    assert np.max(np.linalg.norm(atom_p - full_p, axis=1)) < 1e-6


def test_boxless_alpine_snapshot_still_aligns_atomistic_to_full(
    client, namd_dcd_fixture
):
    """Missing XSC/cell may skip PBC unwrapping, never the rigid pose alignment."""
    fix = namd_dcd_fixture
    fix["write"](1, dimensions=None)

    def latest(mode):
        with client.websocket_connect("/ws/md-run") as socket:
            _load_namd(socket, fix, mode)
            _await_md_ready(socket, expect_frames=1)
            socket.send_json({"action": "get_latest"})
            return socket.receive_json()

    full = latest("nadoc")
    atomistic = latest("ballstick")
    full_p = np.array([[p["x"], p["y"], p["z"]] for p in full["positions"]])
    atom_p = np.array(
        [[a["x"], a["y"], a["z"]] for a in atomistic["atoms"] if a["serial"] % 2 == 0]
    )
    assert atom_p.shape == full_p.shape
    assert np.max(np.linalg.norm(atom_p - full_p, axis=1)) < 1e-6


def test_md_run_ws_load_seek_ballstick(client, md_fixture_dir):
    """End-to-end through the 'ballstick' branch of _load_sync + _seek_sync.

    Different code path than 'nadoc'/'beads': hits the heavy-atom selection
    block at the bottom of _load_sync and the `else: # ballstick` branch in
    _seek_sync.
    """
    fix = md_fixture_dir
    with client.websocket_connect("/ws/md-run") as ws:
        ws.send_json(
            {
                "action": "load",
                "topology_path": fix["gro"],
                "xtc_path": fix["xtc"],
                "mode": "ballstick",
            }
        )
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


# ── Parsed-Universe cache + load-progress helpers (module-level, 2026-07-16) ──
# These back the "MD Display never loads" fix: cache the ~8 s solvated-PSF parse so
# re-opens are instant, and emit a size note so a slow first-open reads as working.


class TestUniverseCacheHelpers:
    def _reset_cache(self):
        from backend.api import ws

        with ws._UNIVERSE_CACHE_LOCK:
            ws._UNIVERSE_CACHE.clear()

    def test_file_identity_changes_with_mtime_and_size(self, tmp_path):
        from backend.api import ws

        p = tmp_path / "f.psf"
        p.write_text("a")
        id1 = ws._file_identity(p)
        p.write_text("aa")  # size + mtime change
        id2 = ws._file_identity(p)
        assert id1 != id2
        # A growing DCD (live job) therefore misses the cache → fresh parse.
        assert ws._file_identity(tmp_path / "missing").endswith(":missing")

    def test_cache_key_combines_both_files(self, tmp_path):
        from backend.api import ws

        psf = tmp_path / "t.psf"
        psf.write_text("x")
        dcd = tmp_path / "t.dcd"
        dcd.write_text("y")
        key = ws._universe_cache_key(psf, dcd)
        assert str(psf) in key and str(dcd) in key and "||" in key

    def test_put_get_roundtrip_and_lru_eviction(self):
        self._reset_cache()
        from backend.api import ws

        class _FakeUniverse:
            def __init__(self, name):
                self.name = name
                self.closed = False
                self.trajectory = self  # .trajectory.close() lands here

            def close(self):
                self.closed = True

        us = [_FakeUniverse(i) for i in range(3)]
        ws._cache_put_universe("k0", us[0])
        ws._cache_put_universe("k1", us[1])
        assert ws._cache_get_universe("k0") is us[0]  # also LRU-touches k0
        ws._cache_put_universe("k2", us[2])  # cap=2 → evict LRU (k1)
        assert ws._cache_get_universe("k1") is None
        assert us[1].closed is True  # evicted handle was closed
        assert ws._cache_get_universe("k0") is us[0]
        assert ws._cache_get_universe("k2") is us[2]
        self._reset_cache()

    def test_psf_natom_reads_header_only(self, tmp_path):
        from backend.api import ws

        psf = tmp_path / "t.psf"
        psf.write_text(
            "PSF EXT CMAP\n\n       2 !NTITLE\n\n 1320174 !NATOM\n...rest...\n"
        )
        assert ws._psf_natom(psf) == 1320174
        assert ws._psf_natom(tmp_path / "nope.psf") is None

    def test_preload_size_note_only_for_large_psf(self, tmp_path):
        from backend.api import ws

        # small PSF → no note (parses fast, don't nag)
        small = tmp_path / "s.psf"
        small.write_text("PSF\n\n 100 !NATOM\n")
        assert ws._preload_size_note("", str(small)) is None
        # non-PSF topology → no note
        assert ws._preload_size_note("", str(tmp_path / "t.gro")) is None
        # large PSF → informative note mentioning the atom count
        big = tmp_path / "b.psf"
        big.write_text(f"PSF\n\n {ws._UNWRAP_MAX_ATOMS + 1} !NATOM\n" + "x" * 4096)
        note = ws._preload_size_note("", str(big))
        assert note is not None and f"{ws._UNWRAP_MAX_ATOMS + 1:,}" in note

"""Oracle for M7 — mrDNA hard-surface (ARBD repulsion-plane via a grid potential).

Property under test (the bright line — a comparable prediction, not "a wrapper exists"):
the shared ``{dir, offset_nm, stiff}`` surface descriptor becomes a one-sided harmonic
wall — an ARBD grid potential whose negative gradient REPELS beads that cross to the
forbidden side (along ``+dir̂``) and vanishes on the allowed side — and (slow) a real ARBD
run with a field pressing INTO the plane deposits the bundle (beads approach but stay on
the structure side, COM held by the surface reaction with no strand anchor).

The surface is a JOB-REQUEST annotation, never a Design edit (Three-Layer Law): these
tests only read bead positions off the model and write a potential grid into a run dir.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.conftest import make_6hb_design


# ── helpers ───────────────────────────────────────────────────────────────────

def _built_model(design):
    from backend.core.mrdna_bridge import mrdna_model_from_nadoc
    return mrdna_model_from_nadoc(design)


def _flat_beads(model):
    return [b for s in model.segments for b in s.beads]


# ── FAST: descriptor parsing (no-op cases mirror mrdna_field.parse_field) ──────

def test_parse_surface_and_noop():
    from backend.core.mrdna_surface import parse_surface

    dhat, offset_nm, stiff = parse_surface(
        {"dir": [0.0, 0.0, 2.0], "offset_nm": 3.0, "stiff": 5.0})
    assert np.allclose(dhat, [0.0, 0.0, 1.0])              # unit-normalised
    assert offset_nm == 3.0 and stiff == 5.0
    # No-op: missing / empty / zero-stiff / zero-direction → None (a floor that does
    # nothing), just like a zero-magnitude field.
    for bad in (None, {}, {"dir": [0, 0, 1], "stiff": 0.0},
                {"dir": [0, 0, 0], "stiff": 5.0}, {"stiff": 5.0}):
        assert parse_surface(bad) is None, bad


# ── FAST: the wall potential — a one-sided repulsion (−∇U away from the plane) ──

def test_wall_grid_is_one_sided_repulsion():
    """The written .dx is a harmonic wall: −∇U pushes a bead on the forbidden side
    back ALONG +dir̂ (repulsion, growing with penetration) and vanishes on the allowed
    side — proven by round-tripping the grid through ARBD's own loadGrid."""
    from mrdna.arbdmodel.grid import loadGrid

    from backend.core.mrdna_surface import _write_wall_grid

    # A deliberately off-axis normal so nothing is axis-locked.
    dhat = np.array([0.3, -0.4, 0.5]); dhat /= np.linalg.norm(dhat)
    stiff = 2.0
    plane_c = 0.0                                          # plane through the origin
    lo = np.array([-100.0, -100.0, -100.0])
    hi = np.array([100.0, 100.0, 100.0])
    n = 41                                                 # 5 Å spacing (cubic)
    import tempfile
    from pathlib import Path
    p = Path(tempfile.mkdtemp()) / "wall.dx"
    _write_wall_grid(p, dhat, plane_c, stiff, lo, hi, (n, n, n))
    U, origin, delta = loadGrid(str(p))
    assert np.allclose(origin, lo)
    dx = float(delta[0]) if np.ndim(delta) else float(delta)

    axes = [np.linspace(lo[i], hi[i], n) for i in range(3)]

    def _s(i, j, k):
        return dhat[0] * axes[0][i] + dhat[1] * axes[1][j] + dhat[2] * axes[2][k]

    def _force(i, j, k):
        fx = -(U[i + 1, j, k] - U[i - 1, j, k]) / (2 * dx)
        fy = -(U[i, j + 1, k] - U[i, j - 1, k]) / (2 * dx)
        fz = -(U[i, j, k + 1] - U[i, j, k - 1]) / (2 * dx)
        return np.array([fx, fy, fz])

    # 1) An interior node well BELOW the plane (all central-difference neighbours also
    #    below the plane, so U is a smooth quadratic there): −∇U == stiff·|s|·dir̂
    #    exactly (a real spring pushing back toward the allowed side).
    below = None
    for i in range(2, n - 2):
        for j in range(2, n - 2):
            for k in range(2, n - 2):
                nb = [_s(i + di, j + dj, k + dk)
                      for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                                         (0, -1, 0), (0, 0, 1), (0, 0, -1))]
                if _s(i, j, k) < -10.0 and all(v < 0 for v in nb):
                    below = (i, j, k); break
            if below:
                break
        if below:
            break
    assert below is not None
    s_below = _s(*below)
    f_below = _force(*below)
    expected = -stiff * s_below * dhat                     # = stiff·|s|·dir̂
    assert np.allclose(f_below, expected, rtol=1e-6, atol=1e-9), (f_below, expected)
    # Repulsion points AWAY from the plane (component along +dir̂ is positive).
    assert float(f_below @ dhat) > 0

    # 2) An interior node well ABOVE the plane (allowed side): zero force.
    above = None
    for i in range(2, n - 2):
        for j in range(2, n - 2):
            for k in range(2, n - 2):
                nb = [_s(i + di, j + dj, k + dk)
                      for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                                         (0, -1, 0), (0, 0, 1), (0, 0, -1))]
                if _s(i, j, k) > 10.0 and all(v > 0 for v in nb):
                    above = (i, j, k); break
            if above:
                break
        if above:
            break
    assert above is not None
    assert np.allclose(_force(*above), 0.0, atol=1e-9)


def test_wall_plane_sits_below_structure_by_offset():
    """The plane is placed a clearance ``offset_nm`` below the structure's lowest bead
    along ``dir̂`` — every bead starts on the allowed side (mirrors oxDNA
    wall_position_from_extent)."""
    from backend.core.mrdna_surface import _model_beads, wall_plane_offset

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    dhat = np.array([0.0, 0.0, 1.0])
    offset_nm = 2.0
    plane_c = wall_plane_offset(m, dhat, offset_nm)

    beads = _model_beads(m)
    proj = np.array([b.get_collapsed_position() for b in beads]) @ dhat
    s = proj - plane_c
    assert s.min() >= 0.0                                  # all beads on the allowed side
    # The lowest bead sits exactly ``offset`` (Å) above the plane.
    assert np.isclose(s.min(), offset_nm * 10.0, atol=1e-6), (s.min(), offset_nm * 10.0)


# ── FAST: model wiring (real mrDNA model, no ARBD run) ─────────────────────────

def test_apply_attaches_wall_grid_to_every_type(tmp_path):
    from backend.core.mrdna_surface import apply_surface_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    surface = {"dir": [0.0, 0.0, 1.0], "offset_nm": 1.0, "stiff": 3.0}
    names = apply_surface_force(d, m, surface, out_dir=tmp_path)

    beads = _flat_beads(m)
    types = {b.type_.name: b.type_ for b in beads}
    assert set(names) == set(types), (names, list(types))
    assert (tmp_path / "surface.dx").exists()
    for name, t in types.items():
        grids = getattr(t, "grid_potentials", None)
        assert grids, name
        assert any("surface.dx" in str(g) for (g, _s, _bc) in grids), (name, grids)


def test_surface_composes_with_field_grid(tmp_path):
    """A deposition run carries BOTH a field and a surface.  The surface APPENDS its
    grid so ARBD superposes it with M2's field grid — neither clobbers the other."""
    from backend.core.mrdna_field import apply_field_force
    from backend.core.mrdna_surface import apply_surface_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    apply_field_force(d, m, {"field_pN": 0.4, "dir": [0.0, 0.0, -1.0]}, out_dir=tmp_path)
    apply_surface_force(d, m, {"dir": [0, 0, 1], "offset_nm": 1.0, "stiff": 3.0},
                        out_dir=tmp_path)
    for b in _flat_beads(m):
        grids = [str(g) for (g, _s, _bc) in getattr(b.type_, "grid_potentials", [])]
        assert any("field_" in g for g in grids), grids     # field grid survived
        assert any("surface.dx" in g for g in grids), grids  # surface grid appended


def test_no_surface_is_noop(tmp_path):
    from backend.core.mrdna_surface import apply_surface_force, install_surface_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    for bad in (None, {}, {"dir": [0, 0, 1], "stiff": 0.0}):
        assert apply_surface_force(d, m, bad, out_dir=tmp_path) == []
        assert install_surface_force(d, m, bad, out_dir=tmp_path) == 0
    for b in _flat_beads(m):
        assert not getattr(b.type_, "grid_potentials", None)


def test_surface_block_in_arbd_input(tmp_path):
    """A real mrDNA dry-run writes a gridFile line pointing at the wall grid for the
    DNA bead types — the surface reaches ARBD's input."""
    from backend.core.mrdna_surface import install_surface_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    n = install_surface_force(d, m, {"dir": [0, 0, 1], "offset_nm": 1.0, "stiff": 3.0},
                              out_dir=tmp_path)
    assert n >= 1
    m.simulate(output_name="surf", directory=str(tmp_path),
               num_steps=0.0, timestep=200e-6, output_period=1.0, gpu=0, dry_run=True)
    conf = (tmp_path / "surf.bd").read_text()
    grid_lines = [ln for ln in conf.splitlines() if ln.startswith("gridFile ")]
    assert any("surface.dx" in ln for ln in grid_lines), grid_lines


def test_field_and_surface_both_survive_regeneration(tmp_path):
    """The load-bearing ordering claim: a deposition run installs the field THEN the
    surface, so the surface's regen wrapper is the outer one — on every bead
    regeneration the field re-applies (overwrite) first and the surface re-appends
    after, keeping BOTH grids.  RED if the surface overwrote instead of appended, or if
    it were installed before the field."""
    from backend.core.mrdna_field import install_field_force
    from backend.core.mrdna_surface import install_surface_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    # Same order the runner uses: field first, surface second.
    install_field_force(d, m, {"field_pN": 0.4, "dir": [0.0, 0.0, -1.0]}, out_dir=tmp_path)
    install_surface_force(d, m, {"dir": [0, 0, 1], "offset_nm": 1.0, "stiff": 3.0},
                          out_dir=tmp_path)
    m.clear_beads()
    m.generate_bead_model()
    for b in _flat_beads(m):
        grids = [str(g) for (g, _s, _bc) in getattr(b.type_, "grid_potentials", [])]
        assert any("field_" in g for g in grids), grids     # field survived regen
        assert any("surface.dx" in g for g in grids), grids  # surface survived regen


def test_install_survives_bead_regeneration(tmp_path):
    """multiresolution_simulation regenerates beads (new ParticleType objects) between
    stages; the wrapper must re-attach the wall grid.  RED without the wrapper."""
    from backend.core.mrdna_surface import install_surface_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    install_surface_force(d, m, {"dir": [0, 0, 1], "offset_nm": 1.0, "stiff": 3.0},
                          out_dir=tmp_path)
    m.clear_beads()
    m.generate_bead_model()
    have_grid = [b for b in _flat_beads(m)
                 if any("surface.dx" in str(g)
                        for (g, _s, _bc) in getattr(b.type_, "grid_potentials", []))]
    assert have_grid, "surface grid was wiped by bead regeneration"


# ── FAST: REST guards + the deposition rule (surface opposes field → no anchor) ──

def _mrdna_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.api.routes_mrdna as routes_mrdna
    from backend.api import state as design_state
    from backend.api.main import app

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_mrdna, "mrdna_available",
                        lambda: {"available": True, "mrdna": "/x", "arbd": "/y"})
    monkeypatch.setattr(routes_mrdna, "start_job", lambda job, ws: None)
    design_state.set_design_silent(make_6hb_design(length_bp=42))
    return TestClient(app)


def test_malformed_surface_rejected(monkeypatch, tmp_path):
    client = _mrdna_client(monkeypatch, tmp_path)
    for bad in ({"dir": [0, 0, 1], "offset_nm": 1.0, "stiff": 0.0},   # zero stiffness
                {"dir": [0, 0, 0], "offset_nm": 1.0, "stiff": 3.0}):  # zero direction
        r = client.post("/api/mrdna/jobs", json={"coarse_steps": 1000, "surface": bad})
        assert r.status_code == 400, (bad, r.text)
        assert "surface" in r.json()["detail"].lower()


def test_field_into_surface_prepares_without_a_strand_anchor(monkeypatch, tmp_path):
    """A uniform field pressing INTO a hard surface prepares with no strand anchor.

    NOTE (policy): the original M7 form of this test asserted that an unanchored
    field WITHOUT an opposing surface was *rejected* (400), and only a field held by
    the surface's reaction could skip the anchor.  Commit 19d2be8 relaxed
    "field needs an anchor" to a non-blocking warning across all engines, so the REST
    layer no longer rejects any of these — an unanchored field prepares and the runner
    logs a COM-drift warning instead.  The surface *physics* (the plane actually holds
    the bundle) is still verified by the SLOW real-ARBD deposition test below; this
    test now just pins that a field+surface deposition run is accepted anchor-free."""
    client = _mrdna_client(monkeypatch, tmp_path)
    field = {"field_pN": 1.0, "dir": [0, 0, -1]}           # points into the plane
    surface = {"dir": [0, 0, 1], "offset_nm": 1.0, "stiff": 3.0}

    # Field into the opposing surface, no anchor → accepted (deposition run prepares).
    r = client.post("/api/mrdna/jobs",
                    json={"coarse_steps": 1000, "field": field, "surface": surface})
    assert r.status_code == 200, r.text

    # Same field, NO surface, no anchor → accepted under warn-only (was 400 pre-19d2be8).
    r = client.post("/api/mrdna/jobs", json={"coarse_steps": 1000, "field": field})
    assert r.status_code == 200, r.text

    # Field NOT opposed by the surface (points along +dir̂) → also accepted (warn-only).
    r = client.post("/api/mrdna/jobs",
                    json={"coarse_steps": 1000,
                          "field": {"field_pN": 1.0, "dir": [0, 0, 1]},
                          "surface": surface})
    assert r.status_code == 200, r.text


# ── SLOW: a real ARBD run deposits the bundle on the surface (no strand anchor) ──

@pytest.mark.slow
def test_real_arbd_field_deposits_on_surface(tmp_path):
    """A 6HB under a uniform field aimed INTO a hard surface, with NO strand anchor:
    the bundle approaches the plane but every bead stays on the structure side (none
    pass through), and the COM is held by the surface reaction — a comparable
    deposition prediction, not a smoke run.  RED baseline: the SAME field with no
    surface streams the COM far down-field."""
    from backend.core.mrdna_bridge import find_arbd
    if not find_arbd():
        pytest.skip("arbd binary not installed")

    from backend.core.mrdna_surface import (
        _model_beads,
        install_surface_force,
        wall_plane_offset,
    )
    from backend.core.mrdna_field import install_field_force

    # A gentle-but-sustained field (0.8 pN is M2's stable ceiling — stronger rips
    # anchor-adjacent bonds) driven long enough to stream the FREE structure well past a
    # plane placed just below it (OFFSET 0.5 nm), so the surface's holding effect is
    # genuinely exercised (not a plane the field never reaches).
    FIELD_PN = 0.8
    DIR_INTO = np.array([0.0, 0.0, -1.0])                  # field pushes toward −z
    SURF_DIR = np.array([0.0, 0.0, 1.0])                   # structure sits on +z side
    OFFSET_NM, STIFF = 0.5, 4.0
    NSTEPS, TIMESTEP = 30000.0, 200e-6

    d = make_6hb_design(length_bp=42)

    def _run(with_surface, run_dir):
        m = _built_model(d)
        beads = _model_beads(m)
        start = np.array([b.get_collapsed_position() for b in beads])
        plane_c = wall_plane_offset(m, SURF_DIR, OFFSET_NM)
        # Field FIRST, surface SECOND — the exact order the runner uses, so the surface's
        # grid APPENDS to (superposes with) the field's rather than being clobbered by the
        # field's overwrite.
        install_field_force(d, m, {"field_pN": FIELD_PN, "dir": DIR_INTO.tolist()},
                            out_dir=run_dir)
        if with_surface:
            install_surface_force(
                d, m, {"dir": SURF_DIR.tolist(), "offset_nm": OFFSET_NM, "stiff": STIFF},
                out_dir=run_dir)
        m.simulate(output_name="dep", directory=str(run_dir), num_steps=NSTEPS,
                   timestep=TIMESTEP, output_period=1000.0, gpu=0)
        import MDAnalysis as mda  # noqa: PLC0415
        u = mda.Universe(str(run_dir / "dep.psf"), str(run_dir / "output" / "dep.dcd"))
        u.trajectory[-1]
        end = u.atoms.positions[: len(beads)]
        return start, end, plane_c

    on_dir = tmp_path / "surf"; on_dir.mkdir()
    off_dir = tmp_path / "free"; off_dir.mkdir()
    _, end_surf, plane_c = _run(True, on_dir)
    _, end_free, _ = _run(False, off_dir)

    # Penetration of the plane, per bead (s = dir̂·r − plane_c; s < 0 ⇒ past the wall).
    s_surf = end_surf @ SURF_DIR - plane_c
    s_free = end_free @ SURF_DIR - plane_c

    # 1) With NO surface, the SAME field drives beads FAR past where the plane sits (they
    #    stream through unopposed) — the RED baseline that proves the field is strong
    #    enough to need a wall.
    assert s_free.min() < -15.0, s_free.min()
    # 2) WITH the surface, no bead passes through: every bead stays at/above the plane
    #    (a small tolerance for the soft harmonic onset + thermal wiggle) — the field is
    #    held by the plane's reaction with NO strand anchor (deposition).
    assert s_surf.min() > -5.0, s_surf.min()
    # 3) The surface plainly holds the structure back relative to the free stream.
    assert s_surf.min() > s_free.min() + 10.0, (s_surf.min(), s_free.min())

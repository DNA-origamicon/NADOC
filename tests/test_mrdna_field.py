"""Oracle for M2 — mrDNA uniform E-field via ARBD grid-potential forces.

Property under test (the bright line — a comparable prediction, not "a wrapper exists"):
the shared ``{field_pN, dir}`` descriptor becomes a constant per-bead force scaled by the
bead's nucleotide content, and (slow) a real ARBD run holds the anchored region while the
free bulk DEFLECTS ALONG the field by the amount overdamped Brownian dynamics predicts
from the engine's OWN bead mobility.

The field is a JOB-REQUEST annotation, never a Design edit (Three-Layer Law): these tests
only read positions/masses off the design + model and write force grids into a run dir.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.conftest import make_6hb_design


# ── First-principles pN → kcal/mol/Å (independent of the code's constant) ──────────
_KCAL_J = 4184.0
_AVOGADRO = 6.02214076e23
#: 1 kcal·mol⁻¹·Å⁻¹ expressed in newtons, then 1 pN in kcal·mol⁻¹·Å⁻¹.
_KCAL_MOL_A_IN_N = _KCAL_J / _AVOGADRO / 1e-10
_PN_IN_KCAL_MOL_A = 1e-12 / _KCAL_MOL_A_IN_N  # ≈ 0.0143933


# ── helpers ───────────────────────────────────────────────────────────────────


def _built_model(design):
    from backend.core.mrdna_bridge import mrdna_model_from_nadoc

    return mrdna_model_from_nadoc(design)


def _flat_beads(model):
    return [b for s in model.segments for b in s.beads]


# ── FAST: the per-bead force scaling (first-principles, not the code's constant) ──


def test_field_force_vector_matches_first_principles():
    from backend.core.mrdna_field import field_force_vector

    field = {"field_pN": 3.0, "dir": [0.0, 0.0, 1.0]}
    dpn = 140.0
    mass = 1380.0
    f = field_force_vector(field, mass, dpn)
    # Force per bead = field_pN (per nt) × nt-in-bead × (pN → kcal/mol/Å).
    n_nt = mass / dpn
    expected_mag = 3.0 * n_nt * _PN_IN_KCAL_MOL_A
    assert np.allclose(f, [0.0, 0.0, expected_mag], rtol=1e-4), (f, expected_mag)
    # Direction is +dir̂ (a phosphate-charged strand pushed ALONG the requested field).
    assert f[2] > 0


def test_field_force_vector_linear_and_noop():
    from backend.core.mrdna_field import field_force_vector

    d = {"dir": [1.0, 0.0, 0.0]}
    f1 = field_force_vector({**d, "field_pN": 1.0}, 690.0, 140.0)
    f2 = field_force_vector({**d, "field_pN": 2.0}, 690.0, 140.0)
    assert np.allclose(f2, 2.0 * f1)  # linear in field magnitude
    # Heavier (more-nucleotide) bead feels proportionally more force.
    fh = field_force_vector({**d, "field_pN": 1.0}, 1380.0, 140.0)
    assert np.allclose(fh, 2.0 * f1)  # 2× mass ⇒ 2× force
    # No-op cases → zero force.
    for bad in (
        None,
        {},
        {"field_pN": 0.0, "dir": [1, 0, 0]},
        {"field_pN": 5.0, "dir": [0, 0, 0]},
    ):
        assert np.allclose(field_force_vector(bad, 690.0, 140.0), 0.0)


def test_ramp_grid_encodes_constant_force():
    """The written .dx is a ramp whose negative gradient is the requested force."""
    from mrdna.arbdmodel.grid import loadGrid

    from backend.core.mrdna_field import _write_ramp_grid

    fvec = np.array([0.7, -0.3, 0.1])
    lo = np.array([-100.0, -100.0, -100.0])
    hi = np.array([100.0, 100.0, 100.0])  # cubic ⇒ one delta for all axes
    import tempfile
    from pathlib import Path

    p = Path(tempfile.mkdtemp()) / "ramp.dx"
    _write_ramp_grid(p, fvec, lo, hi)
    U, origin, delta = loadGrid(str(p))
    # -∇U recovered by finite difference along each axis == fvec.
    fx = -(U[1, 0, 0] - U[0, 0, 0]) / delta
    fy = -(U[0, 1, 0] - U[0, 0, 0]) / delta
    fz = -(U[0, 0, 1] - U[0, 0, 0]) / delta
    assert np.allclose([fx, fy, fz], fvec, atol=1e-6), ([fx, fy, fz], fvec)
    assert np.allclose(origin, lo)


# ── FAST: the model wiring (real mrDNA model, no ARBD run) ─────────────────────


def test_apply_sets_per_type_force_grid(tmp_path):
    from backend.core.mrdna_field import (
        apply_field_force,
        dalton_per_nucleotide,
        field_force_vector,
    )

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    field = {"field_pN": 0.5, "dir": [1.0, 0.0, 0.0]}
    names = apply_field_force(d, m, field, out_dir=tmp_path)

    beads = _flat_beads(m)
    types = {b.type_.name: b.type_ for b in beads}
    assert set(names) == set(types), (names, list(types))
    dpn = dalton_per_nucleotide(d, m)
    for name, t in types.items():
        assert getattr(t, "grid_potentials", None), name
        gpath, scale, bc = t.grid_potentials[0]
        assert (tmp_path / f"field_{name}.dx").exists()
        assert scale == 1 and bc == "dirichlet"
    # Per-type force scales with the type's nucleotide content (mass): the full-bead
    # type (D001, ~10 nt) feels exactly 2× the half-bead type (D000, ~5 nt).
    f_full = field_force_vector(field, 1380.0, dpn)
    f_half = field_force_vector(field, 690.0, dpn)
    assert np.allclose(f_full, 2.0 * f_half)


def test_no_field_is_noop(tmp_path):
    from backend.core.mrdna_field import apply_field_force, install_field_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    for bad in (None, {}, {"field_pN": 0.0, "dir": [1, 0, 0]}):
        assert apply_field_force(d, m, bad, out_dir=tmp_path) == []
        assert install_field_force(d, m, bad, out_dir=tmp_path) == 0
    # No grid potential was attached to any bead type.
    for b in _flat_beads(m):
        assert not getattr(b.type_, "grid_potentials", None)


def test_field_block_in_arbd_input(tmp_path):
    """A real mrDNA dry-run writes gridFile lines pointing at the field ramp (not
    null.dx) for the DNA bead types — the force block reaches ARBD's input."""
    from backend.core.mrdna_field import install_field_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    n = install_field_force(
        d, m, {"field_pN": 0.4, "dir": [1.0, 0.0, 0.0]}, out_dir=tmp_path
    )
    assert n >= 1
    m.simulate(
        output_name="field",
        directory=str(tmp_path),
        num_steps=0.0,
        timestep=200e-6,
        output_period=1.0,
        gpu=0,
        dry_run=True,
    )
    conf = (tmp_path / "field.bd").read_text()
    grid_lines = [ln for ln in conf.splitlines() if ln.startswith("gridFile ")]
    assert any("field_" in ln and ".dx" in ln for ln in grid_lines), grid_lines


def test_install_survives_bead_regeneration(tmp_path):
    """multiresolution_simulation regenerates beads (new ParticleType objects) between
    stages; the wrapper must re-attach the grids.  RED without the wrapper."""
    from backend.core.mrdna_field import install_field_force

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    install_field_force(
        d, m, {"field_pN": 0.4, "dir": [1.0, 0.0, 0.0]}, out_dir=tmp_path
    )
    # Simulate a resolution-stage regeneration: fresh bead cloud + fresh types.
    m.clear_beads()
    m.generate_bead_model()
    have_grid = [b for b in _flat_beads(m) if getattr(b.type_, "grid_potentials", None)]
    assert have_grid, "field grids were wiped by bead regeneration"


# ── FAST: REST guards (a field needs an anchor; malformed field → 400) ─────────


def _mrdna_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.api.routes_mrdna as routes_mrdna
    from backend.api import state as design_state
    from backend.api.main import app

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(
        routes_mrdna,
        "mrdna_available",
        lambda: {"available": True, "mrdna": "/x", "arbd": "/y"},
    )
    monkeypatch.setattr(routes_mrdna, "start_job", lambda job, ws: None)
    design_state.set_design_silent(make_6hb_design(length_bp=42))
    return TestClient(app)


def test_field_without_anchor_allowed(monkeypatch, tmp_path):
    """An unanchored uniform field just streams the structure down-field (COM drift)
    — the UI warns, but the job is no longer rejected."""
    client = _mrdna_client(monkeypatch, tmp_path)
    r = client.post(
        "/api/mrdna/jobs",
        json={"coarse_steps": 1000, "field": {"field_pN": 1.0, "dir": [1, 0, 0]}},
    )
    assert r.status_code == 200, r.text


def test_malformed_field_rejected(monkeypatch, tmp_path):
    client = _mrdna_client(monkeypatch, tmp_path)
    for bad in (
        {"field_pN": 0.0, "dir": [1, 0, 0]},  # zero magnitude
        {"field_pN": 1.0, "dir": [0, 0, 0]},  # zero direction
        {"field_pN": "abc", "dir": [1, 0, 0]},
    ):  # non-numeric → 400 not 500
        r = client.post("/api/mrdna/jobs", json={"coarse_steps": 1000, "field": bad})
        assert r.status_code == 400, (bad, r.text)
        assert "field" in r.json()["detail"].lower()


# ── SLOW: real ARBD anchored field run deflects the free bulk along the field ──


@pytest.mark.slow
def test_real_arbd_field_deflects_along_field(tmp_path):
    """Anchored 6HB under a uniform field: the anchored region holds, the free bulk
    drifts ALONG the field, and the drift magnitude matches the overdamped Brownian
    prediction from the engine's OWN diffusivity/mass — a comparable field-deflection
    prediction, not a smoke run.  RED baseline: field-off shows no directional drift."""
    from backend.core.mrdna_bridge import find_arbd

    if not find_arbd():
        pytest.skip("arbd binary not installed")

    from backend.core.mrdna_anchors import (
        install_anchor_restraints,
        resolve_anchor_beads,
    )
    from backend.core.mrdna_field import (
        dalton_per_nucleotide,
        install_field_force,
    )

    # Chosen so the field drift (~8 Å) dominates the anchored bulk's stochastic
    # relaxation wander (~±2 Å) while the anchor-adjacent bonds stay intact (a much
    # stronger field rips them → ARBD instability).
    FIELD_PN, DIRECTION = 0.8, np.array([1.0, 0.0, 0.0])
    NSTEPS, TIMESTEP = 6000.0, 200e-6  # ns
    d = make_6hb_design(length_bp=42)
    anchor = [{"kind": "strand", "id": d.strands[0].id}]

    def _run(with_field, run_dir):
        m = _built_model(d)
        beads = _flat_beads(m)
        idx_of = {id(b): i for i, b in enumerate(beads)}
        held = resolve_anchor_beads(d, m, anchor)
        held_idx = {idx_of[id(b)] for b in held}
        free_idx = [i for i in range(len(beads)) if i not in held_idx]
        assert held and free_idx
        start = np.array([b.get_collapsed_position() for b in beads])
        install_anchor_restraints(d, m, anchor)
        if with_field:
            install_field_force(
                d, m, {"field_pN": FIELD_PN, "dir": DIRECTION.tolist()}, out_dir=run_dir
            )
        m.simulate(
            output_name="f",
            directory=str(run_dir),
            num_steps=NSTEPS,
            timestep=TIMESTEP,
            output_period=1000.0,
            gpu=0,
        )
        import MDAnalysis as mda  # noqa: PLC0415

        u = mda.Universe(str(run_dir / "f.psf"), str(run_dir / "output" / "f.dcd"))
        u.trajectory[-1]
        disp = u.atoms.positions[: len(beads)] - start
        return disp, held_idx, free_idx, beads

    on_dir = tmp_path / "on"
    on_dir.mkdir()
    off_dir = tmp_path / "off"
    off_dir.mkdir()
    disp_on, held_idx, free_idx, beads = _run(True, on_dir)
    disp_off, _, _, _ = _run(False, off_dir)

    dhat = DIRECTION / np.linalg.norm(DIRECTION)
    held_move = float(np.median(np.linalg.norm(disp_on[list(held_idx)], axis=1)))
    free_move = float(np.median(np.linalg.norm(disp_on[free_idx], axis=1)))
    proj_on = float(disp_on[free_idx].mean(axis=0) @ dhat)
    proj_off = float(disp_off[free_idx].mean(axis=0) @ dhat)

    # 1) The anchored region holds while the free bulk moves.
    assert held_move < free_move, (held_move, free_move)
    # 2) The field induces a clear net drift ALONG +field.  Field-off the anchored bulk
    #    only wanders a couple Å with no strong lab-direction bias (RED baseline); the
    #    field drift is several times larger.
    assert abs(proj_off) < 4.0, proj_off
    assert proj_on > 4.0, proj_on
    differential = proj_on - proj_off

    # 3) The drift magnitude matches overdamped Brownian dynamics from the engine's OWN
    #    per-type diffusivity + mass (v = D·F/kT ⇒ Δx = D·F·T/(k_B·T_kelvin)).  The
    #    predicted force is built from field_pN via the FIRST-PRINCIPLES pN→kcal/mol/Å
    #    factor (_PN_IN_KCAL_MOL_A), NOT via the code's field_force_vector — so the code's
    #    emission constant (PN_TO_KCAL_MOL_A) does NOT appear on the prediction side.  A
    #    corrupted emission constant scales the REAL ARBD drift but not `pred`, pushing the
    #    ratio out of the band (the exact constant is pinned deterministically by the fast
    #    oracle; this is the physical independence check).  The band is deliberately loose:
    #    a free-drift model vs a tethered structure, sampled on ONE stochastic 6000-step
    #    realization whose ±2 Å relaxation wander is comparable to the drift signal itself.
    #    That noise floor sits BELOW a 2× force error's signature (~0.5·pred), so a single
    #    realization cannot both absorb the stochastic tail AND flag a 2× error — the lower
    #    bound is set to survive the wander (catches only gross ≳5× magnitude/sign errors on
    #    the constant).  Fine direction + substantial-drift are guarded independently and
    #    robustly by the proj_on > 4 Å / |proj_off| < 4 Å / held < free assertions above;
    #    restoring fine ≥2× sensitivity here would require averaging over seeded replicas.
    KB = 831447.2  # k_B in amu·Å²·ns⁻²·K⁻¹
    KCAL_TO_INTERNAL = (
        _KCAL_MOL_A_IN_N * 6.02214076e26 * 1e10 * 1e-18
    )  # kcal/mol/Å→amu·Å/ns²
    T_KELVIN = 295.0
    sim_ns = NSTEPS * TIMESTEP
    dpn = dalton_per_nucleotide(d, _built_model(d))
    preds = []
    for i in free_idx:
        t = beads[i].type_
        n_nt_bead = float(t.mass) / dpn
        f_int = FIELD_PN * n_nt_bead * _PN_IN_KCAL_MOL_A * KCAL_TO_INTERNAL  # amu·Å/ns²
        preds.append(float(t.diffusivity) * f_int * sim_ns / (KB * T_KELVIN))
    pred = float(np.mean(preds))
    assert 0.2 * pred < differential < 2.0 * pred, (differential, pred)

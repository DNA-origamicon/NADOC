"""Composite NAMD trajectory for animation trajectory keyframes (Phase 2).

These exercise the real DCD→NADOC bead extraction, so they need MDAnalysis AND a
real NAMD job on disk (a stopped/failed run with ≥1 written DCD is fine). Guarded
with skipif so they no-op in environments without the fixture.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("MDAnalysis")

from backend.core.models import Design  # noqa: E402

_WS = Path(__file__).resolve().parent.parent / "workspace"
_JOB = _WS / "md_jobs" / "5c6a87247a60" / "package" / "2hb_namd_solvated"
_PSF = _JOB / "2hb.psf"
_REF = _JOB / "2hb.pdb"
_DESIGN = _WS / "2hb.nadoc"

_HAVE_FIXTURE = _PSF.exists() and _REF.exists() and _DESIGN.exists() and any(
    (_JOB / "output").glob("*.dcd")
) if _JOB.exists() else False

skip_no_fixture = pytest.mark.skipif(
    not _HAVE_FIXTURE, reason="real 2hb NAMD job fixture not present"
)


def _load_2hb() -> Design:
    raw = _DESIGN.read_text()
    try:
        return Design.model_validate_json(raw)
    except Exception:
        obj = json.loads(raw)
        return Design.model_validate(obj.get("design", obj))


@skip_no_fixture
def test_md_composite_trajectory_shape_and_alignment():
    """Composite NAMD trajectory matches the oxDNA payload shape (6 floats/nuc) and
    frame 0 sits ON the design geometry (rigid RMSD < 1 nm → alignment correct)."""
    from backend.core.md_trajectory import (
        md_composite_trajectory, _build_md_nadoc_ctx, _extract_md_nadoc_frame,
    )
    design = _load_2hb()
    dcds = sorted((_JOB / "output").glob("*.dcd"))
    segments = [(d.stem, "md", d) for d in dcds]

    r = md_composite_trajectory(_PSF, segments, _REF, design, max_frames=20)
    assert r["n_frames"] > 0
    M = r["n_nucleotides"]
    assert M > 0 and len(r["keys"]) == M
    assert all(len(f) == 6 * M for f in r["frames"])    # backbone xyz + a1 per nuc

    ctx = _build_md_nadoc_ctx(_PSF, [d for _, _, d in segments], _REF, design)
    p0, normals = _extract_md_nadoc_frame(ctx, 0)
    assert normals is not None                          # NAMD has C1' → real normals
    rm = ctx["rigid_mask"]
    eq = ctx["eq_positions"]
    rmsd = float(np.sqrt(((p0[rm] - eq[rm]) ** 2).sum(axis=1).mean()))
    assert rmsd < 1.0, f"frame-0 rigid RMSD to design eq too large: {rmsd:.3f} nm"


@skip_no_fixture
def test_md_composite_meta_matches_full():
    """The lightweight NAMD meta (DCD frame count only) reports the SAME n_frames +
    markers as the full composite, so the trajectory slider sizes itself instantly."""
    from backend.core.md_trajectory import md_composite_trajectory, md_composite_meta
    design = _load_2hb()
    dcds = sorted((_JOB / "output").glob("*.dcd"))
    segments = [(d.stem, "md", d) for d in dcds]
    full = md_composite_trajectory(_PSF, segments, _REF, design)
    meta = md_composite_meta(segments)
    assert meta["n_frames"] == full["n_frames"]
    assert [m["frame"] for m in meta["markers"]] == [m["frame"] for m in full["markers"]]


@skip_no_fixture
def test_md_frames_atomistic_and_surface():
    """Phase 2b: per-frame NAMD heavy atoms + surface for trajectory frame indices,
    in the same wire shapes the player's atomistic/surface paths consume."""
    from backend.core.md_trajectory import md_frames_atomistic, md_frames_surface
    design = _load_2hb()
    dcds = sorted((_JOB / "output").glob("*.dcd"))
    segments = [(d.stem, "md", d) for d in dcds]

    atom = md_frames_atomistic(_PSF, segments, _REF, design, [0, 5, 999, -1])
    assert sorted(atom.keys()) == ["0", "5"]            # out-of-range dropped
    frame = atom["0"]
    assert frame["bonds"] == []
    assert len(frame["atoms"]) > 0
    a0 = frame["atoms"][0]
    assert set(a0) >= {"serial", "element", "x", "y", "z"}
    # One P per nucleotide → P count is a sane structural check.
    n_p = sum(1 for a in frame["atoms"] if a["element"] == "P")
    assert n_p > 0

    surf = md_frames_surface(_PSF, segments, _REF, design, [0], smooth=3)
    assert list(surf.keys()) == ["0"]
    v = surf["0"]
    assert len(v["vertices"]) > 0 and len(v["vertices"]) % 3 == 0
    assert len(v["faces"]) > 0 and len(v["faces"]) % 3 == 0


@skip_no_fixture
def test_md_rmsf_shape_and_values():
    """Per-nucleotide flexibility map (RMSF) over the NAMD run mirrors the oxDNA
    /rmsf payload shape, with finite non-negative fluctuations and unit base normals."""
    from backend.core.md_trajectory import md_rmsf
    design = _load_2hb()
    dcds = sorted((_JOB / "output").glob("*.dcd"))
    segments = [(d.stem, "md", d) for d in dcds]

    r = md_rmsf(_PSF, segments, _REF, design, max_frames=40)
    assert r["ready"] is True and r["n_frames"] > 0
    pos = r["positions"]
    assert len(pos) > 0
    p0 = pos[0]
    assert set(p0) >= {"helix_id", "bp_index", "direction",
                       "backbone_position", "nx", "ny", "nz", "rmsf"}
    rms = np.array([p["rmsf"] for p in pos])
    assert np.all(np.isfinite(rms)) and np.all(rms >= 0.0)
    assert r["min_rmsf"] <= r["mean_rmsf"] <= r["max_rmsf"]
    # Base normals are unit length (within tolerance).
    nmag = np.linalg.norm([[p["nx"], p["ny"], p["nz"]] for p in pos], axis=1)
    assert np.allclose(nmag, 1.0, atol=1e-3)


@skip_no_fixture
def test_md_trajectory_route_uses_active_design():
    """GET /md/jobs/{id}/trajectory returns the composite for the active design."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state as design_state

    design_state.set_design(_load_2hb())
    client = TestClient(app)
    r = client.get("/api/md/jobs/5c6a87247a60/trajectory")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ready"] is True and j["n_frames"] > 0
    assert len(j["frames"][0]) == j["n_nucleotides"] * 6


@skip_no_fixture
def test_md_rmsf_route_uses_active_design():
    """GET /md/jobs/{id}/rmsf returns the flexibility map for the active design,
    with a confidence block."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state as design_state

    design_state.set_design(_load_2hb())
    client = TestClient(app)
    r = client.get("/api/md/jobs/5c6a87247a60/rmsf")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ready"] is True and len(j["positions"]) > 0
    assert "confidence" in j and "n_frames" in j["confidence"]

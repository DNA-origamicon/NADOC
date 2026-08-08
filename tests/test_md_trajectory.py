"""Composite NAMD trajectory for animation trajectory keyframes (Phase 2).

These exercise the real DCD→NADOC bead extraction, so they need MDAnalysis AND a
real NAMD job on disk (a stopped/failed run with ≥1 written DCD is fine). Guarded
with skipif so they no-op in environments without the fixture.
"""

from __future__ import annotations

import json
import os
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

_HAVE_FIXTURE = (
    _PSF.exists()
    and _REF.exists()
    and _DESIGN.exists()
    and any((_JOB / "output").glob("*.dcd"))
    if _JOB.exists()
    else False
)

skip_no_fixture = pytest.mark.skipif(
    not _HAVE_FIXTURE, reason="real 2hb NAMD job fixture not present"
)

# Many-strand fixture that reproduces the psfgen chainID-collapse collision (77 strands
# → multi-char chain ids).  Local-only (multi-GB package); skipped where absent.
_JOB_3X6 = _WS / "md_jobs" / "c89a67841933" / "package" / "3x6x200_test_namd_solvated"
_PSF_3X6 = _JOB_3X6 / "3x6x200_test.psf"
_REF_3X6 = _JOB_3X6 / "3x6x200_test.pdb"
_DESIGN_3X6 = _WS / "md_jobs" / "c89a67841933" / "design.json"

_HAVE_3X6 = (
    _PSF_3X6.exists()
    and _REF_3X6.exists()
    and _DESIGN_3X6.exists()
    and any(_JOB_3X6.glob("output/*.dcd"))
    if _JOB_3X6.exists()
    else False
)

# The always-on collision regression lives in test_md_p_order_mapping.py; these real
# tests need the multi-GB package, so they're fixture-gated (skipped where absent).
skip_no_3x6 = pytest.mark.skipif(
    not _HAVE_3X6, reason="real 3x6x200 many-strand NAMD job fixture not present"
)

# The equivalence proof re-adds the whole-system mda_unwrap to a REFERENCE universe
# (~180 s/frame by design), so it stays opt-in even where the fixture exists.
skip_no_3x6_heavy = pytest.mark.skipif(
    not (_HAVE_3X6 and os.environ.get("NADOC_RUN_HEAVY_MD_FIXTURE")),
    reason="slow unwrap-reference equivalence — set NADOC_RUN_HEAVY_MD_FIXTURE=1 to run",
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
        md_composite_trajectory,
        _build_md_nadoc_ctx,
        _extract_md_nadoc_frame,
    )

    design = _load_2hb()
    dcds = sorted((_JOB / "output").glob("*.dcd"))
    segments = [(d.stem, "md", d) for d in dcds]

    r = md_composite_trajectory(_PSF, segments, _REF, design, max_frames=20)
    assert r["n_frames"] > 0
    M = r["n_nucleotides"]
    assert M > 0 and len(r["keys"]) == M
    assert all(len(f) == 6 * M for f in r["frames"])  # backbone xyz + a1 per nuc

    ctx = _build_md_nadoc_ctx(_PSF, [d for _, _, d in segments], _REF, design)
    p0, normals = _extract_md_nadoc_frame(ctx, 0)
    assert normals is not None  # NAMD has C1' → real normals
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
    assert [m["frame"] for m in meta["markers"]] == [
        m["frame"] for m in full["markers"]
    ]
    # …and for a user-set frame interval, which is what the panel's readout promises.
    full7 = md_composite_trajectory(_PSF, segments, _REF, design, stride=7)
    meta7 = md_composite_meta(segments, stride=7)
    assert meta7["n_frames"] == full7["n_frames"]
    assert [m["frame"] for m in meta7["markers"]] == [
        m["frame"] for m in full7["markers"]
    ]
    # Raw counts are what the panel prices other intervals against — they must describe
    # what is ON DISK, not what this response downsampled to.
    assert meta7["total_raw"] == sum(s["n_raw"] for s in meta7["stages"])
    assert meta7["total_raw"] >= meta7["n_frames"]


@skip_no_fixture
def test_md_frames_atomistic_and_surface():
    """Phase 2b: per-frame NAMD heavy atoms + surface for trajectory frame indices,
    in the same wire shapes the player's atomistic/surface paths consume."""
    from backend.core.md_trajectory import md_frames_atomistic, md_frames_surface

    design = _load_2hb()
    dcds = sorted((_JOB / "output").glob("*.dcd"))
    segments = [(d.stem, "md", d) for d in dcds]

    atom = md_frames_atomistic(_PSF, segments, _REF, design, [0, 5, 999, -1])
    assert sorted(atom.keys()) == ["0", "5"]  # out-of-range dropped
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
    assert set(p0) >= {
        "helix_id",
        "bp_index",
        "direction",
        "backbone_position",
        "nx",
        "ny",
        "nz",
        "rmsf",
    }
    rms = np.array([p["rmsf"] for p in pos])
    assert np.all(np.isfinite(rms)) and np.all(rms >= 0.0)
    assert r["min_rmsf"] <= r["mean_rmsf"] <= r["max_rmsf"]
    # Base normals are unit length (within tolerance).
    nmag = np.linalg.norm([[p["nx"], p["ny"], p["nz"]] for p in pos], axis=1)
    assert np.allclose(nmag, 1.0, atol=1e-3)


@skip_no_3x6
def test_md_rmsf_many_strand_uses_segid_order():
    """Regression for the 3x6x200 flexibility map "not ready".  A many-strand design's
    multi-char chain ids collapse in the reference PDB's single-char chainID field, so
    the PDB-key P-order path drops atoms and md_rmsf's strict length guard voids every
    frame.  The segid-map path must recover the full P-atom order so the map builds."""
    from backend.core.md_trajectory import _build_md_nadoc_ctx, md_rmsf

    raw = _DESIGN_3X6.read_text()
    try:
        design = Design.model_validate_json(raw)
    except Exception:
        obj = json.loads(raw)
        design = Design.model_validate(obj.get("design", obj))

    # One small (p10) DCD keeps the Kabsch/model cost bounded for the test.
    dcds = sorted(_JOB_3X6.glob("output/*p10.dcd")) or sorted(
        _JOB_3X6.glob("output/*.dcd")
    )
    seg = dcds[:1]
    segments = [(seg[0].stem, "md", seg[0])]

    ctx = _build_md_nadoc_ctx(_PSF_3X6, [d for _, _, d in segments], _REF_3X6, design)
    # The fix: segid-mapped order covers EVERY simulated DNA-P atom (no collision drop).
    assert ctx["p_order_source"] == "segid"
    assert len(ctx["p_order"]) == ctx["n_dna_p"]

    r = md_rmsf(_PSF_3X6, segments, _REF_3X6, design, max_frames=2)
    assert r["ready"] is True, r.get("reason")
    assert len(r["positions"]) == ctx["n_dna_p"]


def _load_3x6_design():
    raw = _DESIGN_3X6.read_text()
    try:
        return Design.model_validate_json(raw)
    except Exception:
        return Design.model_validate(json.loads(raw))


@skip_no_3x6_heavy
def test_md_extraction_matches_unwrap_reference():
    """Perf regression: per-frame extraction drops the whole-system ``mda_unwrap``
    (~180 s/frame over ~1 M solvated atoms) and reconstructs DNA from RAW coords via
    the vectorised min-image path instead.  Assert the fast output is numerically
    IDENTICAL (to float32 rounding, ~1e-8 nm) to a reference universe that still
    applies the unwrap — proving the speedup changes nothing about the geometry."""
    import MDAnalysis as mda  # type: ignore
    from MDAnalysis.transformations import unwrap as mda_unwrap  # type: ignore
    from backend.core.md_trajectory import _build_md_nadoc_ctx, _extract_md_nadoc_frame

    design = _load_3x6_design()
    dcd = (
        sorted(_JOB_3X6.glob("output/*p10.dcd"))
        or sorted(_JOB_3X6.glob("output/*.dcd"))
    )[0]

    # Fast ctx: no unwrap transformation (production path).
    ctx_fast = _build_md_nadoc_ctx(_PSF_3X6, [dcd], _REF_3X6, design)
    # Reference universe WITH the whole-system unwrap, reusing the same design arrays.
    u_ref = mda.Universe(str(_PSF_3X6), str(dcd))
    u_ref.trajectory.add_transformations(mda_unwrap(u_ref.atoms))
    ctx_ref = dict(ctx_fast)
    ctx_ref["universe"] = u_ref

    n = ctx_fast["n_frames"]
    for f in {0, min(5, n - 1), n - 1}:
        for c in (ctx_fast, ctx_ref):
            c["R_prev"] = None
            c["prev_frame_idx"] = -999
        p_fast, n_fast = _extract_md_nadoc_frame(ctx_fast, f)
        p_ref, n_ref = _extract_md_nadoc_frame(ctx_ref, f)
        assert np.allclose(p_fast, p_ref, atol=1e-6), f"frame {f}: positions diverge"
        assert np.allclose(n_fast, n_ref, atol=1e-6), f"frame {f}: normals diverge"


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

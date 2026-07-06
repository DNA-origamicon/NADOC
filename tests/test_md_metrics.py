"""MD "Graphs and Metrics" — twist/curvature/base-pairing over a NAMD run.

The heavy PSF/DCD reconstruction (``_build_md_nadoc_ctx`` / ``_extract_md_nadoc_frame``)
is faked so these stay fast + always-on: the point is the metric ASSEMBLY (single pass,
all three metrics, both domains, C1'…C1' pairing) and the route/chain glue, not the
MDAnalysis reader (covered by the env-gated heavy fixtures in test_md_trajectory.py).
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest


def _paired_bundle(n_helix=4, n_axial=12, radius=1.2, rise=0.34):
    """Straight bundle with BOTH strands at every (helix, bp) → designed base pairs.
    Returns (p_order, analytic_reference) sharing (helix, bp, direction) keys."""
    order: list[tuple] = []
    analytic: list[dict] = []
    for h in range(n_helix):
        ang = 2 * math.pi * h / n_helix
        x, y = radius * math.cos(ang), radius * math.sin(ang)
        for i in range(n_axial):
            for d, dx in (("FORWARD", 0.0), ("REVERSE", 0.1)):
                pos = [x + dx, y, rise * i]
                order.append((h, i, d))
                analytic.append({"helix_id": h, "bp_index": i, "direction": d,
                                 "backbone_position": pos})
    return order, analytic


def _install_fake_reader(monkeypatch, order, analytic, n_frames, *, c1p_offset=0.0):
    """Patch the DCD reader so md_metric_series walks synthetic frames.

    Each frame's backbone = the analytic positions (twist/curvature diff ≈ 0); each
    nucleotide's C1' = backbone + c1p_offset·ẑ, so FORWARD/REVERSE C1' sit 0.1 nm apart
    (paired) unless c1p_offset pushes them past MD_BP_CUTOFF_NM."""
    import backend.core.md_trajectory as mt

    p_nm = np.array([a["backbone_position"] for a in analytic], dtype=float)
    c1p = p_nm + np.array([0.0, 0.0, c1p_offset])

    monkeypatch.setattr(mt, "_build_md_nadoc_ctx",
                        lambda *a, **k: {"p_order": order, "n_frames": n_frames})

    def _fake_extract(ctx, idx, with_c1p=False):
        if with_c1p:
            return p_nm, None, c1p
        return p_nm, None
    monkeypatch.setattr(mt, "_extract_md_nadoc_frame", _fake_extract)


def test_md_metric_series_one_pass_all_metrics(monkeypatch):
    from backend.core.md_trajectory import md_metric_series
    order, analytic = _paired_bundle(n_axial=12)
    _install_fake_reader(monkeypatch, order, analytic, 4)

    seen: list[int] = []
    out = md_metric_series("psf", [], "ref", object(), analytic,
                           on_frame=lambda: seen.append(1))
    assert out["ready"] is True
    assert out["n_frames"] == 4
    assert len(seen) == 4                                   # progress hook fired per frame
    for key in ("twist", "curvature", "base_pairing"):
        assert len(out[key]["temporal"]["per_frame"]) == 4
        assert out[key]["spatial"]                          # non-empty profile
    # Frames equal the analytic reference → differential twist/curvature ≈ 0.
    assert all(abs(v) < 1e-3 for v in out["twist"]["temporal"]["per_frame"])
    # Every designed pair is within the C1' cutoff → fraction 1.0.
    bp = out["base_pairing"]["temporal"]["per_frame"]
    assert all(v == pytest.approx(1.0) for v in bp)
    assert out["base_pairing"]["temporal"]["n_designed"] == 4 * 12


def test_md_metric_series_pairing_drops_when_c1p_separated(monkeypatch):
    """Push the C1' atoms apart in z so no FORWARD/REVERSE pair is within cutoff → 0."""
    from backend.core.md_trajectory import MD_BP_CUTOFF_NM, md_metric_series
    order, analytic = _paired_bundle(n_axial=12)
    # Same z-offset on every C1' keeps the pair separation... so instead offset would not
    # separate FWD/REV (they share z).  Use a large asymmetric offset via a custom reader.
    import backend.core.md_trajectory as mt
    p_nm = np.array([a["backbone_position"] for a in analytic], dtype=float)
    c1p = p_nm.copy()
    # Shove only REVERSE C1' atoms far in +z so each pair's C1'…C1' >> cutoff.
    for i, (_h, _bp, d) in enumerate(order):
        if d == "REVERSE":
            c1p[i, 2] += MD_BP_CUTOFF_NM * 5
    monkeypatch.setattr(mt, "_build_md_nadoc_ctx",
                        lambda *a, **k: {"p_order": order, "n_frames": 3})
    monkeypatch.setattr(mt, "_extract_md_nadoc_frame",
                        lambda ctx, idx, with_c1p=False:
                        (p_nm, None, c1p) if with_c1p else (p_nm, None))

    out = md_metric_series("psf", [], "ref", object(), analytic)
    assert out["ready"] is True
    assert all(v == pytest.approx(0.0) for v in out["base_pairing"]["temporal"]["per_frame"])


def test_md_metric_series_tolerates_extra_base_inserts(monkeypatch):
    """Regression (MD 'Generate' crash): a design with crossover extra bases interleaves
    ``("__xb__", crossover_id, k)`` keys whose bp_index is a crossover id (a str, not an
    integer column).  Those ssDNA inserts reach the per-frame reference-core filter AND
    the base-pairing spatial profile; both must SKIP them, not ``int()`` them — the bug
    was ``invalid literal for int() with base 10: '<crossover-uuid>'``."""
    import backend.core.md_trajectory as mt
    from backend.core.md_trajectory import md_metric_series
    order, analytic = _paired_bundle(n_axial=12)
    xo_id = "accc07e6-a6df-431d-9090-d24cf77a8ec9"
    # Two inserts threaded in-chain at the junction, keyed like the real extra bases.
    order = order + [("__xb__", xo_id, 0), ("__xb__", xo_id, 1)]
    p_nm = np.array([a["backbone_position"] for a in analytic]
                    + [[0.0, 0.0, 0.5], [0.1, 0.0, 0.6]], dtype=float)
    c1p = p_nm.copy()
    monkeypatch.setattr(mt, "_build_md_nadoc_ctx",
                        lambda *a, **k: {"p_order": order, "n_frames": 3})
    monkeypatch.setattr(mt, "_extract_md_nadoc_frame",
                        lambda ctx, idx, with_c1p=False:
                        (p_nm, None, c1p) if with_c1p else (p_nm, None))
    # analytic reference EXCLUDES __xb__ (core_reference_geometry drops _XB_SENTINEL).
    out = md_metric_series("psf", [], "ref", object(), analytic)   # must NOT raise
    assert out["ready"] is True
    # Inserts are ssDNA, not designed pairs, and every profile still resolves.
    assert out["base_pairing"]["temporal"]["n_designed"] == 4 * 12
    assert out["base_pairing"]["spatial"]
    assert out["twist"]["spatial"] and out["curvature"]["spatial"]


def test_filter_to_reference_core_skips_extra_base_inserts():
    """Unit pin on the crash site itself: the core filter drops non-integer bp_index
    (extra-base inserts) instead of int()-ing a crossover-id string."""
    from backend.core.oxdna_health import _filter_to_reference_core
    reference = [{"helix_id": 0, "bp_index": 3, "direction": "FORWARD",
                  "backbone_position": [0.0, 0.0, 0.0]}]
    positions = reference + [
        {"helix_id": "__xb__", "bp_index": "accc07e6-a6df-431d-9090-d24cf77a8ec9",
         "direction": 0, "backbone_position": [1.0, 0.0, 0.0]}]
    core = _filter_to_reference_core(positions, reference)          # must NOT raise
    assert [p["helix_id"] for p in core] == [0]                     # insert dropped


def test_md_job_chain_resolves_refit_lineage():
    from backend.api.routes_md_metrics import _md_job_chain
    root = SimpleNamespace(job_id="root", parent_job_id=None, created_at=1.0)
    c1 = SimpleNamespace(job_id="c1", parent_job_id="root", created_at=2.0)
    c2 = SimpleNamespace(job_id="c2", parent_job_id="c1", created_at=3.0)
    other = SimpleNamespace(job_id="x", parent_job_id=None, created_at=5.0)
    allj = [c2, other, root, c1]
    assert [j.job_id for j in _md_job_chain("c2", allj)] == ["root", "c1", "c2"]
    assert [j.job_id for j in _md_job_chain("root", allj)] == ["root", "c1", "c2"]
    assert [j.job_id for j in _md_job_chain("x", allj)] == ["x"]
    assert _md_job_chain("missing", allj) == []


def test_md_metrics_route_unknown_job_404():
    from fastapi import HTTPException

    from backend.api.routes_md_metrics import MdMetricsStartRequest, start_md_metrics
    with pytest.raises(HTTPException) as ei:
        start_md_metrics("nope", MdMetricsStartRequest(scope="latest"))
    assert ei.value.status_code == 404


def test_count_md_frames_missing_files_is_zero():
    from backend.core.md_trajectory import count_md_frames
    assert count_md_frames([("s", "md", "/no/such.dcd")]) == 0
    assert count_md_frames([]) == 0

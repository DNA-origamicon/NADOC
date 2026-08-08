"""Oracle for C5 — CanDo FEM as the second live source for the cross-engine comparison
card (S5).

The bright-line pass criterion is a *comparable prediction*, not a run: CanDo's
``predict_shape`` output must turn into the shared ``{engine, descriptors, rmsf,
shape_frame, field}`` bundle ``build_comparison_report`` consumes, so a CanDo column
appears next to the oxDNA one and the report yields the FIRST real oxDNA-vs-CanDo
agreement numbers (shape RMSD + RMSF Pearson/Spearman with CanDo as the RMSF reference).

Fast property tests pin the pure assembler ``build_cando_shape_source``:

  * descriptors are the SAME estimator (``compute_shape_descriptors``) on the core-filtered
    frame — self-consistent, so the card shows CanDo's own ABSOLUTE twist/bend;
  * the core mask (``core_reference_geometry``) drops the ragged ssDNA ends;
  * CanDo's direction-less per-bp NMA RMSF (``{helix_id, bp_index, rmsf_nm}``) maps to the
    card's RMSF-profile shape with ``direction=None`` (``_rmsf_per_bp`` collapses over
    direction, so it still pairs with oxDNA's per-strand ensemble RMSF — the S3 lesson);
  * an empty core mask yields ``None`` descriptors/frame (RED guard);
  * the bundle drops into ``build_comparison_report`` as a ready ``cando`` source and, with
    an oxDNA partner, produces the cross-engine agreement rows.

One SLOW test runs the real in-process FEM solve on a 6HB fixture and assembles the bundle
end-to-end (registered slow in conftest — a full ``predict_shape`` with NMA RMSF).
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.cando_shape_source import _rmsf_profile, build_cando_shape_source
from backend.core.models import LatticeType
from backend.core.shape_compare import build_comparison_report
from backend.core.shape_metrics import compute_shape_descriptors, reference_for


# ── synthetic frames ────────────────────────────────────────────────────────


def _straight_core(
    n_helix: int = 2, n_bp: int = 12, spacing: float = 2.5, rise: float = 0.34
):
    """A straight synthetic dsDNA core: ``n_helix`` parallel helices, ``n_bp`` columns,
    both strands per column.  Returns ``(frame, reference)`` sharing identical keys — the
    reference doubles as the core MASK (so ``_filter_to_reference_core`` keeps everything).
    """
    frame, reference = [], []
    for h in range(n_helix):
        for bp in range(n_bp):
            for d in ("forward", "reverse"):
                rec = {
                    "helix_id": f"h{h}",
                    "bp_index": bp,
                    "direction": d,
                    "backbone_position": [h * spacing, 0.0, bp * rise],
                }
                frame.append(dict(rec))
                reference.append({**rec, "copy": 0})
    return frame, reference


def _nma_rmsf(n_helix: int = 2, n_bp: int = 12, base: float = 0.9):
    """CanDo ``predict_shape``-shaped per-bp NMA RMSF: one direction-less entry per
    duplex-core node (``{helix_id, bp_index, rmsf_nm}``)."""
    return [
        {"helix_id": f"h{h}", "bp_index": bp, "rmsf_nm": base + 0.01 * bp}
        for h in range(n_helix)
        for bp in range(n_bp)
    ]


# ── build_cando_shape_source: pure property tests (fast) ─────────────────────


def test_engine_tag_and_descriptors_self_consistent():
    frame, reference = _straight_core()
    src = build_cando_shape_source(frame, reference)
    assert src["engine"] == "cando"
    # descriptors are the SAME estimator on the core-filtered frame (no ss ends here → the
    # whole frame) — the card shows CanDo's own absolute shape descriptors.
    expected = compute_shape_descriptors(src["shape_frame"])
    assert src["descriptors"] == expected
    # a 2-helix straight bundle has computable twist/Rg (not the degenerate single-helix case)
    assert src["descriptors"]["radius_of_gyration_nm"] is not None


def test_core_mask_drops_ssdna_ends():
    frame, reference = _straight_core(n_helix=2, n_bp=8)
    # append ssDNA-end columns present in the FRAME but absent from the core reference
    frame += [
        {
            "helix_id": "h0",
            "bp_index": 99,
            "direction": "forward",
            "backbone_position": [0.0, 0.0, 40.0],
        },
        {
            "helix_id": "h1",
            "bp_index": 99,
            "direction": "reverse",
            "backbone_position": [2.5, 0.0, 40.0],
        },
    ]
    src = build_cando_shape_source(frame, reference)
    keys = {(p["helix_id"], p["bp_index"]) for p in src["shape_frame"]}
    assert (99,) not in {(bp,) for _, bp in keys}  # bp 99 dropped
    assert all(p["bp_index"] != 99 for p in src["shape_frame"])
    # descriptors match the estimator run on the masked (core-only) frame
    assert src["descriptors"] == compute_shape_descriptors(src["shape_frame"])


def test_rmsf_remap_is_directionless_and_drops_none():
    rmsf = [
        {"helix_id": "h0", "bp_index": 0, "rmsf_nm": 0.9},
        {"helix_id": "h0", "bp_index": 1, "rmsf_nm": None},  # no sample → dropped
        {"helix_id": "h1", "bp_index": 2, "rmsf_nm": 1.1},
    ]
    out = _rmsf_profile(rmsf)
    assert len(out) == 2  # the None entry dropped
    for e in out:
        assert e["direction"] is None  # CanDo NMA RMSF is direction-less
        assert e["copy"] == 0
        assert isinstance(e["rmsf_nm"], float)
    assert {(e["helix_id"], e["bp_index"]) for e in out} == {("h0", 0), ("h1", 2)}


def test_field_passthrough_and_none_default():
    frame, reference = _straight_core()
    sentinel = {
        "anchored_max_drift_nm": 0.0,
        "free_proj_along_field_nm": 3.0,
        "passed": True,
        "per_nt": [],
    }
    assert build_cando_shape_source(frame, reference)["field"] is None
    assert (
        build_cando_shape_source(frame, reference, field=sentinel)["field"] is sentinel
    )


def test_empty_core_mask_yields_none_descriptors():
    frame, _ = _straight_core()
    # a reference with no shared keys → empty core → no comparable frame (RED guard)
    src = build_cando_shape_source(frame, core_reference=[])
    assert src["descriptors"] is None
    assert src["shape_frame"] is None
    assert src["rmsf"] is None  # no rmsf supplied here


# ── integration: the first oxDNA-vs-CanDo agreement numbers ──────────────────


def test_cando_bundle_yields_cross_engine_agreement():
    frame, reference = _straight_core()
    cando = build_cando_shape_source(frame, reference, rmsf=_nma_rmsf())
    # a synthetic oxDNA partner on the SAME core (rigid-shifted a hair) + per-strand RMSF
    ox_frame = [
        {
            **p,
            "backbone_position": [
                p["backbone_position"][0] + 0.2,
                *p["backbone_position"][1:],
            ],
        }
        for p in frame
    ]
    ox_rmsf = [
        {
            "helix_id": f"h{h}",
            "bp_index": bp,
            "direction": d,
            "rmsf_nm": 0.9 + 0.01 * bp,
        }
        for h in range(2)
        for bp in range(12)
        for d in ("forward", "reverse")
    ]
    oxdna = {
        "engine": "oxdna",
        "descriptors": compute_shape_descriptors(ox_frame),
        "rmsf": ox_rmsf,
        "shape_frame": ox_frame,
        "field": None,
    }

    report = build_comparison_report([oxdna, cando])
    assert report["ready"]
    assert set(report["engines"]) == {"oxdna", "cando"}
    # per-observable references: oxDNA is the SHAPE reference, CanDo the RMSF reference
    assert report["references"]["shape"] == "oxdna"
    assert report["references"]["rmsf"] == "cando"
    assert reference_for(report["engines"], "rmsf") == "cando"

    # the FIRST real cross-engine numbers: CanDo scored against oxDNA (shape) + oxDNA scored
    # against CanDo (RMSF, since CanDo is the RMSF reference)
    by_eng = {a["engine"]: a for a in report["agreement"]}
    assert (
        by_eng["cando"]["shape_rmsd_nm"] is not None
    )  # rigid 0.2nm shift → finite RMSD
    assert by_eng["cando"]["shape_rmsd_nm"] == pytest.approx(
        0.0, abs=1e-6
    )  # rigid → Kabsch ~0
    ox_rmsf_ag = by_eng["oxdna"]["rmsf"]
    assert ox_rmsf_ag is not None
    assert ox_rmsf_ag["pearson"] == pytest.approx(
        1.0, abs=1e-9
    )  # identical rmsf ramp → r=1
    assert ox_rmsf_ag["n"] == 24  # 2 helices × 12 bp shared

    # CanDo appears as a selectable engine with its own RMSF overlay profile
    cando_prof = [p for p in report["rmsf_profiles"] if p["engine"] == "cando"]
    assert cando_prof and cando_prof[0]["is_reference"] is True
    assert len(cando_prof[0]["points"]) == 24


# ── SLOW: real in-process FEM solve → assembled bundle ───────────────────────


def _routed_6hb():
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def test_real_predict_shape_assembles_and_compares():
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.physics.fem_solver import predict_shape

    design = _routed_6hb()
    result = predict_shape(design, nonlinear=False, with_rmsf=True)
    reference = core_reference_geometry(design)

    src = build_cando_shape_source(result["positions"], reference, rmsf=result["rmsf"])
    assert src["engine"] == "cando"
    # a real 6HB duplex core → computable absolute shape descriptors (not degenerate)
    assert src["descriptors"]["radius_of_gyration_nm"] is not None
    assert src["descriptors"]["end_to_end_nm"] is not None
    assert src["descriptors"]["twist_per_turn_deg"] is not None
    # the free-free NMA RMSF profile carries through
    assert src["rmsf"] and all(np.isfinite(e["rmsf_nm"]) for e in src["rmsf"])

    # it drops into the comparison report as a lone ready CanDo source (RMSF reference)
    report = build_comparison_report([src])
    assert report["ready"] and report["engines"] == ["cando"]
    assert report["references"]["rmsf"] == "cando"
    assert any(p["engine"] == "cando" for p in report["rmsf_profiles"])

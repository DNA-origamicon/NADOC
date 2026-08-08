"""Oracle for S5 — build_comparison_report (shape_compare.py).

The pass criterion is a *comparable prediction, made viewable/exportable*: given a set of
per-engine source bundles (the same substrate S1–S4 produce), the assembled report must

  * pick the per-observable reference per the S3 policy (oxDNA=shape/field, CanDo=RMSF,
    NAMD overrides once present),
  * carry each engine's scalar value and its signed %-delta vs the SHAPE reference (0 for
    the reference itself; recovered exactly for a known perturbation),
  * score cross-engine agreement (RMSF Pearson/Spearman, aligned-shape RMSD, field cosine),
  * degrade gracefully — one engine → raw values, no deltas; missing observable → no rows
    for it — never crash.

This is the data layer behind the comparison card; the card's pure render/CSV helpers are
pinned separately in the vitest suite.
"""

import math

import pytest

from backend.core.shape_compare import build_comparison_report


def _pos(hid, bp, direction, xyz, **extra):
    d = {
        "helix_id": hid,
        "bp_index": bp,
        "direction": direction,
        "backbone_position": list(xyz),
    }
    d.update(extra)
    return d


def _grid_frame(n_helix=3, n_axial=20, radius=1.2, rise=0.34, shift=(0.0, 0.0, 0.0)):
    out = []
    for h in range(n_helix):
        ang = 2 * math.pi * h / n_helix
        x, y = radius * math.cos(ang), radius * math.sin(ang)
        for i in range(n_axial):
            out.append(
                _pos(h, i, "forward", (x + shift[0], y + shift[1], rise * i + shift[2]))
            )
    return out


def _descriptors(**over):
    base = {
        "twist_total_deg": 100.0,
        "twist_per_turn_deg": 34.0,
        "bend_angle_deg": 12.0,
        "bend_radius_nm": 40.0,
        "radius_of_gyration_nm": 5.0,
        "end_to_end_nm": 6.5,
        "axial_span_nm": 6.8,
        "n_nucleotides": 60,
    }
    base.update(over)
    return base


def _rmsf_profile(values, hid=0):
    return [
        {"helix_id": hid, "bp_index": i, "direction": "forward", "rmsf_nm": float(v)}
        for i, v in enumerate(values)
    ]


def _field_profile(disp_by_key, field_dir=(1.0, 0.0, 0.0), anchor_keys=()):
    """A minimal field_response_profile-shaped result built directly from a per-nt
    displacement map so the comparison-agreement math can be checked without a solver."""
    from backend.core.shape_metrics import field_response_profile

    ref = []
    fld = []
    for (h, bp, d), disp in disp_by_key.items():
        ref.append(_pos(h, bp, d, (0.0, 0.0, 0.0)))
        fld.append(_pos(h, bp, d, disp))
    return field_response_profile(
        fld, ref, field_dir, anchor_keys, anchor_tol_nm=1.0, min_free_proj_nm=0.1
    )


def _src(engine, **kw):
    return {
        "engine": engine,
        "descriptors": kw.get("descriptors"),
        "rmsf": kw.get("rmsf"),
        "shape_frame": kw.get("shape_frame"),
        "field": kw.get("field"),
    }


# ── reference selection follows the S3 per-observable policy ────────────────────────


def test_reference_selection_per_observable():
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors()),
            _src("cando", descriptors=_descriptors()),
        ]
    )
    assert rep["ready"] is True
    assert rep["references"] == {"shape": "oxdna", "rmsf": "cando", "field": "oxdna"}


def test_namd_overrides_every_reference_when_present():
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors()),
            _src("cando", descriptors=_descriptors()),
            _src("namd", descriptors=_descriptors()),
        ]
    )
    assert rep["references"]["shape"] == "namd"
    assert rep["references"]["rmsf"] == "namd"
    assert rep["references"]["field"] == "namd"


# ── scalar table: reference has zero delta, candidate recovers a known % ────────────


def test_scalar_table_values_and_deltas():
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(twist_total_deg=100.0)),
            _src("cando", descriptors=_descriptors(twist_total_deg=110.0)),
        ]
    )
    row = next(r for r in rep["scalars"] if r["name"] == "twist_total_deg")
    assert row["reference"] == "oxdna"
    # oxDNA is the reference -> no delta against itself.
    assert row["cells"]["oxdna"]["value"] == 100.0
    assert row["cells"]["oxdna"]["signed_pct_delta"] is None
    # cando is +10% relative to oxDNA.
    assert row["cells"]["cando"]["value"] == 110.0
    assert abs(row["cells"]["cando"]["signed_pct_delta"] - 10.0) < 1e-9


def test_scalar_delta_sign_is_negative_below_reference():
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(bend_angle_deg=20.0)),
            _src("cando", descriptors=_descriptors(bend_angle_deg=15.0)),
        ]
    )
    row = next(r for r in rep["scalars"] if r["name"] == "bend_angle_deg")
    assert row["cells"]["cando"]["signed_pct_delta"] < 0
    assert abs(row["cells"]["cando"]["signed_pct_delta"] - (-25.0)) < 1e-9


def test_zero_reference_scalar_yields_none_delta_no_div0():
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(twist_total_deg=0.0)),
            _src("cando", descriptors=_descriptors(twist_total_deg=5.0)),
        ]
    )
    row = next(r for r in rep["scalars"] if r["name"] == "twist_total_deg")
    assert row["cells"]["cando"]["signed_pct_delta"] is None


# ── RMSF: perfect agreement for identical profiles; overlay points present ──────────


def test_rmsf_agreement_and_profiles():
    rmsf = _rmsf_profile([1.0, 2.0, 3.0, 4.0, 5.0])
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(), rmsf=list(rmsf)),
            _src("cando", descriptors=_descriptors(), rmsf=list(rmsf)),
        ]
    )
    # cando is the RMSF reference -> oxDNA is the candidate scored against it.
    ox = next(a for a in rep["agreement"] if a["engine"] == "oxdna")
    assert ox["rmsf"]["pearson"] == 1.0
    assert ox["rmsf"]["n"] == 5
    # both engines contribute an overlay profile; cando flagged as the reference.
    engs = {p["engine"]: p for p in rep["rmsf_profiles"]}
    assert set(engs) == {"oxdna", "cando"}
    assert engs["cando"]["is_reference"] is True
    assert engs["oxdna"]["points"] == [
        [0.0, 1.0],
        [1.0, 2.0],
        [2.0, 3.0],
        [3.0, 4.0],
        [4.0, 5.0],
    ]


def _twisted_frame(n_helix=3, n_axial=30, radius=1.2, rise=0.34, deg_per_bp=6.0):
    """A bundle whose cross-section rotates by ``deg_per_bp`` per axial step → a known,
    monotone cumulative twist along the axis (so the profile is non-trivial + signed)."""
    out = []
    for i in range(n_axial):
        phi = math.radians(deg_per_bp * i)
        for h in range(n_helix):
            ang = 2 * math.pi * h / n_helix + phi
            out.append(
                _pos(
                    h,
                    i,
                    "forward",
                    (radius * math.cos(ang), radius * math.sin(ang), rise * i),
                )
            )
    return out


def test_twist_profiles_per_engine_endpoint_matches_scalar():
    from backend.core.shape_metrics import compute_shape_descriptors

    frame = _twisted_frame()
    scalar = compute_shape_descriptors(frame)["twist_total_deg"]
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(), shape_frame=frame),
            _src("cando", descriptors=_descriptors(), shape_frame=list(frame)),
        ]
    )
    engs = {p["engine"]: p for p in rep["twist_profiles"]}
    assert set(engs) == {"oxdna", "cando"}
    assert engs["oxdna"]["is_reference"] is True  # oxDNA is the SHAPE reference
    assert engs["cando"]["is_reference"] is False
    prof = engs["oxdna"]["points"]
    assert len(prof) >= 3
    assert prof[0][0] == 0.0  # x-axis normalised to start at 0 nm
    assert prof[-1][1] == pytest.approx(scalar)  # last y == the scalar twist_total_deg
    assert abs(scalar) > 20.0  # non-trivial (can-go-red on a flat frame)


def test_twist_profile_absent_without_a_shape_frame():
    # An engine that supplied only descriptors (no frame) contributes no twist curve.
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors()),
            _src("cando", descriptors=_descriptors()),
        ]
    )
    assert rep["twist_profiles"] == []


def test_shape_rmsd_zero_for_identical_frames_survives_rigid_shift():
    frame = _grid_frame()
    shifted = _grid_frame(shift=(10.0, -5.0, 3.0))  # pure rigid translation
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(), shape_frame=frame),
            _src("cando", descriptors=_descriptors(), shape_frame=shifted),
        ]
    )
    cando = next(a for a in rep["agreement"] if a["engine"] == "cando")
    # Kabsch strips the rigid pose -> intrinsic shape identical -> ~0 RMSD.
    assert cando["shape_rmsd_nm"] < 1e-6


# ── field panel: verdict per engine + cross-engine deflection agreement ─────────────


def test_field_panel_cosine_and_verdict():
    # oxDNA (reference) deflects free nts +x by 2 nm; cando deflects the same way but
    # 3x as far (more compliant) -> cosine +1, magnitude ratio 3.
    keys = [(0, i, "forward") for i in range(4)]
    ox_disp = {k: (2.0, 0.0, 0.0) for k in keys}
    cando_disp = {k: (6.0, 0.0, 0.0) for k in keys}
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(), field=_field_profile(ox_disp)),
            _src("cando", descriptors=_descriptors(), field=_field_profile(cando_disp)),
        ]
    )
    assert rep["field"]["reference"] == "oxdna"
    rows = {r["engine"]: r for r in rep["field"]["rows"]}
    assert rows["oxdna"]["is_reference"] is True
    assert rows["oxdna"]["passed"] is True
    assert abs(rows["cando"]["cosine_vs_ref"] - 1.0) < 1e-9
    assert abs(rows["cando"]["magnitude_ratio"] - 3.0) < 1e-9


def test_opposite_field_deflection_gives_negative_cosine():
    keys = [(0, i, "forward") for i in range(4)]
    ox_disp = {k: (2.0, 0.0, 0.0) for k in keys}
    cando_disp = {k: (-2.0, 0.0, 0.0) for k in keys}  # opposite direction
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(), field=_field_profile(ox_disp)),
            _src(
                "cando",
                descriptors=_descriptors(),
                field=_field_profile(cando_disp, field_dir=(1.0, 0.0, 0.0)),
            ),
        ]
    )
    cando = next(r for r in rep["field"]["rows"] if r["engine"] == "cando")
    assert cando["cosine_vs_ref"] < -0.999999


def test_field_reference_resolves_among_field_carrying_engines_only():
    # oxDNA is the field POLICY reference but carries no field data here; cando + mrdna do.
    # The panel must not mislabel oxDNA as the reference — with no policy-valid field carrier
    # present (policy=oxDNA), the field reference is None and cosines are honestly None.
    keys = [(0, i, "forward") for i in range(4)]
    disp = {k: (2.0, 0.0, 0.0) for k in keys}
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors()),  # no field
            _src("cando", descriptors=_descriptors(), field=_field_profile(disp)),
            _src("mrdna", descriptors=_descriptors(), field=_field_profile(disp)),
        ]
    )
    # references dict still reports the POLICY reference (data-agnostic, like shape/rmsf).
    assert rep["references"]["field"] == "oxdna"
    # the panel only lists field-carrying engines, and none is mislabelled the reference.
    engs = {r["engine"] for r in rep["field"]["rows"]}
    assert engs == {"cando", "mrdna"}
    assert rep["field"]["reference"] is None
    assert all(r["is_reference"] is False for r in rep["field"]["rows"])
    assert all(r["cosine_vs_ref"] is None for r in rep["field"]["rows"])


# ── graceful degradation ────────────────────────────────────────────────────────────


def test_single_engine_reports_raw_values_no_agreement():
    rep = build_comparison_report([_src("oxdna", descriptors=_descriptors())])
    assert rep["ready"] is True
    assert rep["engines"] == ["oxdna"]
    row = next(r for r in rep["scalars"] if r["name"] == "twist_total_deg")
    assert row["cells"]["oxdna"]["value"] == 100.0
    assert row["cells"]["oxdna"]["signed_pct_delta"] is None
    assert rep["agreement"] == []  # nothing to compare against
    assert rep["field"] is None


def test_empty_sources_not_ready():
    rep = build_comparison_report([])
    assert rep["ready"] is False
    assert rep["engines"] == []


# ── REST registry: start → poll → result, and 404 ─────────────────────────────────


def _run_compare(sources):
    import time

    from backend.api.routes_shape_metrics import (
        CompareStartRequest,
        get_compare,
        start_compare,
    )

    rid = start_compare(CompareStartRequest(sources=sources))["metrics_id"]
    for _ in range(200):
        st = get_compare(rid)
        if st["state"] != "running":
            return st
        time.sleep(0.02)
    raise AssertionError("comparison run did not finish")


def test_compare_route_start_poll_result():
    st = _run_compare(
        [
            _src("oxdna", descriptors=_descriptors(twist_total_deg=100.0)),
            _src("cando", descriptors=_descriptors(twist_total_deg=110.0)),
        ]
    )
    assert st["state"] == "done"
    assert st["progress"] == 1.0
    res = st["result"]
    assert res["ready"] is True
    row = next(r for r in res["scalars"] if r["name"] == "twist_total_deg")
    assert abs(row["cells"]["cando"]["signed_pct_delta"] - 10.0) < 1e-9


def test_compare_route_unknown_run_404():
    from fastapi import HTTPException

    from backend.api.routes_shape_metrics import get_compare

    with pytest.raises(HTTPException) as ei:
        get_compare("nope")
    assert ei.value.status_code == 404


def test_missing_observable_omits_its_rows_but_keeps_scalars():
    # cando carries only descriptors (no rmsf/frame/field) -> scalar row present, but no
    # rmsf profile / field panel; agreement still has the shape-rmsd None-safe path.
    rep = build_comparison_report(
        [
            _src("oxdna", descriptors=_descriptors(twist_total_deg=100.0)),
            _src("cando", descriptors=_descriptors(twist_total_deg=120.0)),
        ]
    )
    assert rep["rmsf_profiles"] == []
    assert rep["field"] is None
    row = next(r for r in rep["scalars"] if r["name"] == "twist_total_deg")
    assert abs(row["cells"]["cando"]["signed_pct_delta"] - 20.0) < 1e-9

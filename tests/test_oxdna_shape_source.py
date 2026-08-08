"""Oracle for O1 — the oxDNA source bundle for the cross-engine comparison card.

The pass criterion is a *comparable prediction*, not "the endpoint answered": the bundle
``build_oxdna_shape_source`` emits must (a) carry shape descriptors that MATCH the locked
``oxdna_health`` estimator on the core-filtered frame (so oxDNA's numbers are the same
numbers the metrics card already reports — not a second, divergent estimate), (b) drop the
ragged ssDNA ends via the same core mask the metrics use, (c) map the production RMSF map
into the card's ``rmsf_nm`` profile shape, and (d) drop into ``build_comparison_report`` as
a live oxDNA column that becomes the SHAPE reference.  The assertions GO RED when the core
reference is empty (no comparable frame) — the descriptor discriminates, it isn't a
constant.

Pure Physical-layer assembly (Three-Layer Law): synthetic display frames only, no oxDNA
run.  Frame fixtures mirror ``tests/test_shape_metrics.py`` (a display map is a list of
``{helix_id, bp_index, direction, backbone_position}`` dicts).
"""

import math

import pytest

from backend.core.oxdna_health import _filter_to_reference_core, measure_bundle_twist
from backend.core.oxdna_shape_source import build_oxdna_shape_source
from backend.core.shape_compare import build_comparison_report


def _pos(hid, bp, direction, xyz):
    return {
        "helix_id": hid,
        "bp_index": bp,
        "direction": direction,
        "backbone_position": list(xyz),
    }


def _twist_bundle(total_deg, n_helix=4, n_axial=24, radius=1.2, rise=0.34):
    """Bundle whose cross-section rotates ``total_deg`` (right-handed about +z) evenly
    from the first axial level to the last — a known global twist (mirrors
    ``tests/test_shape_metrics.py``)."""
    out = []
    zmax = rise * (n_axial - 1)
    for h in range(n_helix):
        ang0 = 2 * math.pi * h / n_helix
        for i in range(n_axial):
            z = rise * i
            phi = math.radians(total_deg) * (z / zmax if zmax else 0.0)
            a = ang0 + phi
            out.append(
                _pos(h, i, "forward", (radius * math.cos(a), radius * math.sin(a), z))
            )
    return out


def _core_reference(frame):
    """A core mask (list of dicts carrying (helix_id, bp_index, direction)) covering
    every column of ``frame`` — stands in for ``core_reference_geometry(design)``."""
    return [
        {
            "helix_id": p["helix_id"],
            "bp_index": p["bp_index"],
            "direction": p["direction"],
        }
        for p in frame
    ]


# ── descriptors match the locked oxdna_health estimator on the core frame ─────────


def test_descriptors_match_oxdna_health_on_core_frame():
    frame = _twist_bundle(60.0)
    ref = _core_reference(frame)
    src = build_oxdna_shape_source(frame, ref)
    assert src["engine"] == "oxdna"
    assert src["shape_frame"] is not None
    # The bundle's twist IS oxdna_health's twist on the exact core-filtered frame —
    # not a second, divergent estimate.
    core = _filter_to_reference_core(frame, ref)
    assert src["descriptors"]["twist_total_deg"] == pytest.approx(
        measure_bundle_twist(core)
    )
    assert src["descriptors"]["twist_total_deg"] == pytest.approx(60.0, abs=10.0)


# ── the core mask drops ssDNA ends absent from the reference ──────────────────────


def test_core_mask_drops_ssdna_ends():
    frame = _twist_bundle(60.0, n_axial=24)
    ref = _core_reference(frame)
    # Append two floppy ssDNA-end nucleotides on a NEW column absent from the reference.
    frame = frame + [
        _pos(0, 999, "forward", (5.0, 5.0, 5.0)),
        _pos(1, 999, "forward", (5.0, 5.0, 6.0)),
    ]
    src = build_oxdna_shape_source(frame, ref)
    # The two end bases are excluded from the emitted frame + descriptor count.
    assert src["descriptors"]["n_nucleotides"] == 4 * 24
    keys = {(p["helix_id"], p["bp_index"]) for p in src["shape_frame"]}
    assert (0, 999) not in keys and (1, 999) not in keys


# ── production RMSF map → the card's rmsf_nm profile shape ────────────────────────


def test_rmsf_positions_mapped_to_profile():
    frame = _twist_bundle(0.0, n_axial=6)
    ref = _core_reference(frame)
    rmsf_positions = [
        {"helix_id": 0, "bp_index": 0, "direction": "forward", "copy": 0, "rmsf": 0.15},
        {"helix_id": 0, "bp_index": 1, "direction": "reverse", "copy": 0, "rmsf": 0.42},
        {"helix_id": 1, "bp_index": 0, "direction": "forward", "copy": 0, "rmsf": None},
    ]
    src = build_oxdna_shape_source(frame, ref, rmsf_positions=rmsf_positions)
    prof = src["rmsf"]
    assert prof is not None
    # None-rmsf entries are dropped; the rest carry rmsf_nm.
    assert len(prof) == 2
    by_key = {
        (e["helix_id"], e["bp_index"], e["direction"]): e["rmsf_nm"] for e in prof
    }
    assert by_key[(0, 0, "forward")] == pytest.approx(0.15)
    assert by_key[(0, 1, "reverse")] == pytest.approx(0.42)
    assert all("rmsf_nm" in e for e in prof)


def test_no_rmsf_positions_yields_none():
    frame = _twist_bundle(0.0, n_axial=6)
    ref = _core_reference(frame)
    src = build_oxdna_shape_source(frame, ref)
    assert src["rmsf"] is None


def test_rmsf_profile_drops_extra_base_inserts_without_crashing():
    # production_rmsf DOES emit crossover extra-base inserts (helix_id "__xb__", a STRING
    # bp_index = crossover id). Before the guard, int(bp_index) raised → 500 on ANY design
    # with a linker/extra base. They are flexible ssDNA with no dsDNA-core RMSF counterpart,
    # so they are dropped; real design nucleotides survive.
    frame = _twist_bundle(0.0, n_axial=6)
    ref = _core_reference(frame)
    rmsf_positions = [
        {"helix_id": 0, "bp_index": 0, "direction": "forward", "copy": 0, "rmsf": 0.15},
        {
            "helix_id": "__xb__",
            "bp_index": "d8565ee9-9f77-48dc-bde6-a4e9fa24e02c",
            "direction": 0,
            "copy": 0,
            "rmsf": 0.42,
        },  # string bp_index → would crash int()
    ]
    src = build_oxdna_shape_source(frame, ref, rmsf_positions=rmsf_positions)
    prof = src["rmsf"]
    assert prof is not None
    assert len(prof) == 1  # the __xb__ insert is dropped
    assert prof[0]["helix_id"] == 0 and prof[0]["bp_index"] == 0


# ── field profile passes through untouched ───────────────────────────────────────


def test_field_profile_passes_through():
    frame = _twist_bundle(0.0, n_axial=6)
    ref = _core_reference(frame)
    field = {
        "passed": True,
        "anchored_max_drift_nm": 0.2,
        "free_proj_along_field_nm": 3.1,
    }
    src = build_oxdna_shape_source(frame, ref, field=field)
    assert src["field"] is field


# ── the bundle becomes a live oxDNA column + the SHAPE reference in the card ──────


def test_source_drops_into_comparison_report_as_shape_reference():
    frame = _twist_bundle(60.0)
    ref = _core_reference(frame)
    src = build_oxdna_shape_source(frame, ref)
    report = build_comparison_report([src])
    assert report["ready"] is True
    assert report["engines"] == ["oxdna"]
    assert report["references"]["shape"] == "oxdna"
    # The scalar table carries oxDNA's real descriptor value (no delta — it's the ref).
    twist_row = next(r for r in report["scalars"] if r["name"] == "twist_total_deg")
    assert twist_row["cells"]["oxdna"]["value"] == pytest.approx(
        src["descriptors"]["twist_total_deg"]
    )
    assert twist_row["cells"]["oxdna"]["signed_pct_delta"] is None


# ── RED: an empty core reference leaves no comparable frame ───────────────────────


def test_empty_core_reference_yields_no_descriptors():
    frame = _twist_bundle(60.0)
    src = build_oxdna_shape_source(frame, [])
    assert src["descriptors"] is None
    assert src["shape_frame"] is None
    # And such a bundle is not a usable shape source in the card.
    report = build_comparison_report([src])
    twist_row = next(r for r in report["scalars"] if r["name"] == "twist_total_deg")
    assert twist_row["cells"]["oxdna"]["value"] is None

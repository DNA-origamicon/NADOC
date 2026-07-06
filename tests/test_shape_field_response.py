"""Oracle for S4 — unified field-response descriptor (shape_metrics.py).

The pass criterion is a *comparable prediction with a property assertion*, not "an
engine ran": given a candidate frame after an E-field stage and the field-off reference
it started from, ``field_response_profile`` must report that the ANCHORED nucleotides
barely moved (held by their traps) while the FREE nucleotides deflected ALONG the field,
monotonically in field magnitude — the same physical verdict ``oxdna_health.
measure_field_response`` asserts, now engine-agnostic and copy-aware, plus a per-nt
deflection map so two engines' deflections can be compared.

``compare_field_response`` scores cross-engine agreement of the two per-nt deflection
maps: cosine similarity of the deflection field (same way? opposite?) and the ratio of
deflection magnitudes (one engine twice as compliant as another?).

A display frame is a list of {helix_id, bp_index, direction, backbone_position} dicts —
the substrate every engine's overlay emits (mirrors the other shape_metrics oracles).
Positions are NOT Kabsch-aligned here: the anchored region IS the common frame, and
aligning would remove the very field-driven motion being measured.
"""
import math

import numpy as np
import pytest

from backend.core.shape_metrics import (
    compare_field_response,
    field_response_profile,
)


def _pos(hid, bp, direction, xyz, **extra):
    d = {"helix_id": hid, "bp_index": bp, "direction": direction,
         "backbone_position": list(xyz)}
    d.update(extra)
    return d


def _bundle(n_helix=3, n_axial=20, radius=1.2, rise=0.34):
    """A small straight bundle — the field-off reference the field frames perturb."""
    out = []
    for h in range(n_helix):
        ang = 2 * math.pi * h / n_helix
        x, y = radius * math.cos(ang), radius * math.sin(ang)
        for i in range(n_axial):
            out.append(_pos(h, i, "forward", (x, y, rise * i)))
    return out


def _anchor_low_z(ref, n_axial=20, band=4):
    """Anchor keys = the low-z end band of the bundle (a tethered base)."""
    return [(p["helix_id"], p["bp_index"], p["direction"])
            for p in ref if p["bp_index"] < band]


def _deflect(ref, field_dir, amount_nm, anchor_keys):
    """Field frame: anchored nts stay put, free nts shift by ``amount_nm`` along field."""
    aset = {(h, bp, d) for (h, bp, d) in anchor_keys}
    fdir = np.asarray(field_dir, float)
    fdir = fdir / np.linalg.norm(fdir)
    out = []
    for p in ref:
        k = (p["helix_id"], p["bp_index"], p["direction"])
        pos = np.asarray(p["backbone_position"], float)
        if k not in aset:
            pos = pos + amount_nm * fdir
        out.append(_pos(p["helix_id"], p["bp_index"], p["direction"], pos))
    return out


# ── field_response_profile ─────────────────────────────────────────────────────────

def test_anchors_held_and_free_deflects_along_field():
    ref = _bundle()
    field_dir = (1.0, 0.0, 0.0)
    anchors = _anchor_low_z(ref)
    fld = _deflect(ref, field_dir, 2.0, anchors)

    r = field_response_profile(fld, ref, field_dir, anchors)
    assert r["passed"] is True
    assert r["anchored_max_drift_nm"] < 1e-6          # traps held exactly
    assert r["free_proj_along_field_nm"] == pytest.approx(2.0, abs=1e-6)
    assert r["free_mean_disp_nm"] == pytest.approx(2.0, abs=1e-6)
    assert r["n_anchored"] == len(anchors)
    assert r["n_free"] == len(ref) - len(anchors)
    # mean free deflection vector points along +x
    v = np.asarray(r["deflection_vec_nm"], float)
    assert v[0] == pytest.approx(2.0, abs=1e-6)
    assert abs(v[1]) < 1e-6 and abs(v[2]) < 1e-6


def test_per_nt_map_covers_shared_and_flags_anchors():
    ref = _bundle()
    field_dir = (1.0, 0.0, 0.0)
    anchors = _anchor_low_z(ref)
    fld = _deflect(ref, field_dir, 1.5, anchors)

    r = field_response_profile(fld, ref, field_dir, anchors)
    per_nt = r["per_nt"]
    assert len(per_nt) == len(ref)                    # every shared nt present
    aset = {(h, bp, d) for (h, bp, d) in anchors}
    for e in per_nt:
        is_anchor = (e["helix_id"], e["bp_index"], e["direction"]) in aset
        assert e["anchored"] is is_anchor
        if is_anchor:
            assert e["disp_nm"] < 1e-6
        else:
            assert e["disp_nm"] == pytest.approx(1.5, abs=1e-6)
            assert e["proj_along_field_nm"] == pytest.approx(1.5, abs=1e-6)


def test_deflection_is_monotone_in_field_magnitude():
    ref = _bundle()
    field_dir = (0.0, 1.0, 0.0)
    anchors = _anchor_low_z(ref)
    small = field_response_profile(_deflect(ref, field_dir, 0.8, anchors), ref, field_dir, anchors)
    large = field_response_profile(_deflect(ref, field_dir, 3.0, anchors), ref, field_dir, anchors)
    assert large["free_proj_along_field_nm"] > small["free_proj_along_field_nm"]
    assert large["free_mean_disp_nm"] > small["free_mean_disp_nm"]


def test_fails_when_anchors_drift():
    ref = _bundle()
    field_dir = (1.0, 0.0, 0.0)
    anchors = _anchor_low_z(ref)
    fld = _deflect(ref, field_dir, 2.0, anchors)
    # yank one anchored nt far off — the trap "failed"
    fld[0]["backbone_position"][0] += 5.0
    r = field_response_profile(fld, ref, field_dir, anchors, anchor_tol_nm=1.0)
    assert r["passed"] is False
    assert "anchor" in r["reason"].lower()
    assert r["anchored_max_drift_nm"] > 1.0


def test_fails_when_free_does_not_deflect():
    ref = _bundle()
    field_dir = (1.0, 0.0, 0.0)
    anchors = _anchor_low_z(ref)
    # free nts barely move -> below min_free_proj
    fld = _deflect(ref, field_dir, 0.1, anchors)
    r = field_response_profile(fld, ref, field_dir, anchors, min_free_proj_nm=0.5)
    assert r["passed"] is False
    assert "field" in r["reason"].lower()


def test_copy_aware_keys_kept_distinct():
    # two inserted copies at the same (helix,bp,dir) must not collapse
    ref = [_pos(0, 5, "forward", (0, 0, 0), copy=0),
           _pos(0, 5, "forward", (0, 0, 0.3), copy=1),
           _pos(1, 5, "forward", (2, 0, 0), copy=0)]
    field_dir = (1.0, 0.0, 0.0)
    anchors = [(1, 5, "forward")]
    fld = [_pos(0, 5, "forward", (1.0, 0, 0), copy=0),
           _pos(0, 5, "forward", (2.0, 0, 0.3), copy=1),
           _pos(1, 5, "forward", (2, 0, 0), copy=0)]
    r = field_response_profile(fld, ref, field_dir, anchors)
    assert r["n_free"] == 2                            # both copies measured
    assert r["n_anchored"] == 1
    keys = {(e["helix_id"], e["bp_index"], e["direction"], e["copy"]) for e in r["per_nt"]}
    assert (0, 5, "forward", 0) in keys and (0, 5, "forward", 1) in keys


def test_zero_field_direction_raises():
    ref = _bundle()
    with pytest.raises(ValueError):
        field_response_profile(ref, ref, (0.0, 0.0, 0.0), [])


def test_no_free_nucleotides_raises():
    ref = _bundle(n_helix=1, n_axial=3)
    all_anchored = [(p["helix_id"], p["bp_index"], p["direction"]) for p in ref]
    with pytest.raises(ValueError):
        field_response_profile(ref, ref, (1, 0, 0), all_anchored)


# ── compare_field_response (cross-engine) ────────────────────────────────────────────

def test_identical_engines_perfect_cosine_unit_ratio():
    ref = _bundle()
    field_dir = (1.0, 0.0, 0.0)
    anchors = _anchor_low_z(ref)
    a = field_response_profile(_deflect(ref, field_dir, 2.0, anchors), ref, field_dir, anchors)
    b = field_response_profile(_deflect(ref, field_dir, 2.0, anchors), ref, field_dir, anchors)
    c = compare_field_response(a, b)
    assert c["cosine_similarity"] == pytest.approx(1.0, abs=1e-6)
    assert c["magnitude_ratio"] == pytest.approx(1.0, abs=1e-6)
    assert c["n_shared_free"] == a["n_free"]


def test_opposite_deflection_anti_correlated():
    ref = _bundle()
    anchors = _anchor_low_z(ref)
    a = field_response_profile(_deflect(ref, (1, 0, 0), 2.0, anchors), ref, (1, 0, 0), anchors)
    b = field_response_profile(_deflect(ref, (-1, 0, 0), 2.0, anchors), ref, (-1, 0, 0), anchors)
    c = compare_field_response(a, b)
    assert c["cosine_similarity"] == pytest.approx(-1.0, abs=1e-6)


def test_orthogonal_deflection_zero_cosine():
    ref = _bundle()
    anchors = _anchor_low_z(ref)
    a = field_response_profile(_deflect(ref, (1, 0, 0), 2.0, anchors), ref, (1, 0, 0), anchors)
    b = field_response_profile(_deflect(ref, (0, 1, 0), 2.0, anchors), ref, (0, 1, 0), anchors)
    c = compare_field_response(a, b)
    assert abs(c["cosine_similarity"]) < 1e-6


def test_magnitude_ratio_scales_with_compliance():
    ref = _bundle()
    field_dir = (1.0, 0.0, 0.0)
    anchors = _anchor_low_z(ref)
    stiff = field_response_profile(_deflect(ref, field_dir, 1.0, anchors), ref, field_dir, anchors)
    soft = field_response_profile(_deflect(ref, field_dir, 3.0, anchors), ref, field_dir, anchors)
    c = compare_field_response(soft, stiff)
    assert c["magnitude_ratio"] == pytest.approx(3.0, abs=1e-6)
    assert c["cosine_similarity"] == pytest.approx(1.0, abs=1e-6)


def test_compare_no_shared_free_is_none():
    ref = _bundle()
    anchors = _anchor_low_z(ref)
    a = field_response_profile(_deflect(ref, (1, 0, 0), 2.0, anchors), ref, (1, 0, 0), anchors)
    # a profile over a disjoint bundle (different helix ids) -> no shared free nts
    ref2 = _bundle(n_helix=3)
    for p in ref2:
        p["helix_id"] += 100
    anch2 = _anchor_low_z(ref2)
    b = field_response_profile(_deflect(ref2, (1, 0, 0), 2.0, anch2), ref2, (1, 0, 0), anch2)
    c = compare_field_response(a, b)
    assert c["cosine_similarity"] is None
    assert c["magnitude_ratio"] is None
    assert c["n_shared_free"] == 0

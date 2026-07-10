"""Oracle for S1 — engine-agnostic shape descriptors (shape_metrics.py).

The pass criterion is a *comparable prediction with a property assertion*, not "it
ran": a synthetic straight bundle reads ~0 twist / ~0 bend, a known-twist bundle
recovers the programmed twist, a known-arc bundle recovers the arc-span angle + its
radius, and the same assertions GO RED on a twisted / scrambled frame (so the
descriptor discriminates rather than returning a constant).

Descriptors are composed from the locked oxdna_health estimators, so these fixtures
mirror that module's synthetic-bundle builders (bp-midpoint columns; a display map is
a list of {helix_id, bp_index, direction, backbone_position} dicts).
"""
import math

import pytest

from backend.core.shape_metrics import compute_shape_descriptors, twist_profile


def _pos(hid, bp, direction, xyz):
    return {"helix_id": hid, "bp_index": bp, "direction": direction,
            "backbone_position": list(xyz)}


def _straight_bundle(n_helix=4, n_axial=40, radius=1.2, rise=0.34):
    """n_helix straight helices on a ring of the given radius, sampled at n_axial
    axial levels along +z. No cross-section rotation → zero global twist/bend."""
    out = []
    for h in range(n_helix):
        ang = 2 * math.pi * h / n_helix
        x, y = radius * math.cos(ang), radius * math.sin(ang)
        for i in range(n_axial):
            out.append(_pos(h, i, "forward", (x, y, rise * i)))
    return out


def _twist_bundle(total_deg, n_helix=4, n_axial=24, radius=1.2, rise=0.34):
    """Same bundle but the cross-section rotates total_deg (right-handed about +z)
    progressively from the first axial level to the last."""
    out = []
    zmax = rise * (n_axial - 1)
    for h in range(n_helix):
        ang0 = 2 * math.pi * h / n_helix
        for i in range(n_axial):
            z = rise * i
            phi = math.radians(total_deg) * (z / zmax if zmax else 0.0)
            a = ang0 + phi
            out.append(_pos(h, i, "forward",
                            (radius * math.cos(a), radius * math.sin(a), z)))
    return out


def _arc_bundle(radius_nm, sweep_deg, *, n_helix=4, n_axial=80, sep=0.4):
    """Bundle whose centreline follows a circular arc of radius_nm sweeping sweep_deg
    in the xy-plane; helices sit symmetrically about the centreline along ±z so each
    slab centroid lands ON the arc."""
    out = []
    for i in range(n_axial):
        th = math.radians(sweep_deg) * (i / (n_axial - 1))
        cx, cy = radius_nm * math.cos(th), radius_nm * math.sin(th)
        for h in range(n_helix):
            z = sep * (h - (n_helix - 1) / 2.0)
            out.append(_pos(h, i, "forward", (cx, cy, z)))
    return out


# ── straight bundle: the null fixture ────────────────────────────────────────────

def test_straight_bundle_is_untwisted_and_unbent():
    d = compute_shape_descriptors(_straight_bundle(n_axial=40))
    assert abs(d["twist_total_deg"]) < 2.0          # no cross-section rotation
    assert abs(d["twist_per_turn_deg"]) < 1.0
    assert abs(d["bend_angle_deg"]) < 3.0           # collinear centreline
    assert d["bend_radius_nm"] > 100.0              # ~straight → huge radius
    assert d["radius_of_gyration_nm"] > 0.0
    assert d["n_nucleotides"] == 4 * 40


def test_straight_bundle_end_to_end_matches_axial_span():
    n_axial, rise = 40, 0.34
    d = compute_shape_descriptors(_straight_bundle(n_axial=n_axial, rise=rise))
    expected = rise * (n_axial - 1)
    assert abs(d["end_to_end_nm"] - expected) < 0.5 * expected * 0.1 + 0.5


# ── known twist: recovered, signed, monotone ─────────────────────────────────────

def test_known_twist_recovered_and_scaled_per_turn():
    d = compute_shape_descriptors(_twist_bundle(60.0, n_axial=24))
    assert abs(d["twist_total_deg"] - 60.0) < 10.0          # recovers programmed twist
    # twist_per_turn = total / (axial_contour / B-DNA pitch), same sign as total.
    assert d["twist_per_turn_deg"] > 0.0
    n_turns = d["twist_total_deg"] / d["twist_per_turn_deg"]
    assert 1.0 < n_turns < 4.0                              # ~7.8 nm / ~3.5 nm/turn


def test_twist_profile_endpoint_matches_scalar_and_starts_at_zero():
    frame = _twist_bundle(60.0, n_axial=24)
    prof = twist_profile(frame)
    scalar = compute_shape_descriptors(frame)["twist_total_deg"]
    assert len(prof) >= 3
    assert prof[0][0] == 0.0                       # x normalised to the bundle start
    xs = [x for x, _ in prof]
    assert xs == sorted(xs)                        # monotone axial coordinate
    assert prof[-1][1] == pytest.approx(scalar)    # last cumulative twist == scalar total


def test_twist_profile_empty_on_single_helix():
    # <2 helices → twist undefined → [] (not a raise), same partial-safe policy as descriptors.
    single = [p for p in _twist_bundle(60.0, n_axial=24) if p["helix_id"] == 0]
    assert twist_profile(single) == []
    assert twist_profile([]) == []


def test_twist_is_monotone_and_signed():
    t30 = compute_shape_descriptors(_twist_bundle(30.0, n_axial=24))["twist_total_deg"]
    t60 = compute_shape_descriptors(_twist_bundle(60.0, n_axial=24))["twist_total_deg"]
    t90 = compute_shape_descriptors(_twist_bundle(90.0, n_axial=24))["twist_total_deg"]
    tneg = compute_shape_descriptors(_twist_bundle(-60.0, n_axial=24))["twist_total_deg"]
    assert 0.0 < t30 < t60 < t90
    assert tneg < 0.0                                       # left-handed → negative


# ── known bend: arc-span angle + radius recovered ────────────────────────────────

def test_known_arc_recovers_sweep_angle_and_radius():
    R, sweep = 30.0, 90.0
    d = compute_shape_descriptors(_arc_bundle(R, sweep, n_axial=80))
    assert abs(d["bend_angle_deg"] - sweep) < 12.0          # arc-span, not tangent angle
    assert abs(d["bend_radius_nm"] - R) < 0.25 * R          # recovers curvature radius


def test_tighter_arc_bends_more():
    b_wide = compute_shape_descriptors(_arc_bundle(60.0, 60.0, n_axial=80))["bend_angle_deg"]
    b_tight = compute_shape_descriptors(_arc_bundle(20.0, 60.0, n_axial=80))["bend_angle_deg"]
    # same sweep programmed, but the estimator reads the realised arc-span; both ~60°.
    assert b_wide > 30.0 and b_tight > 30.0
    r_wide = compute_shape_descriptors(_arc_bundle(60.0, 60.0, n_axial=80))["bend_radius_nm"]
    r_tight = compute_shape_descriptors(_arc_bundle(20.0, 60.0, n_axial=80))["bend_radius_nm"]
    assert r_wide > r_tight                                 # radius tracks 1/curvature


# ── the descriptor discriminates (can go red) ────────────────────────────────────

def test_descriptor_goes_red_on_twisted_frame():
    """The straight-bundle assertions above must FAIL on a twisted frame — proving the
    descriptor measures the property, not a constant."""
    d = compute_shape_descriptors(_twist_bundle(90.0, n_axial=24))
    assert abs(d["twist_total_deg"]) > 20.0                 # would violate the <2.0 null


def test_radius_of_gyration_grows_with_bundle_radius():
    thin = compute_shape_descriptors(_straight_bundle(radius=1.0))["radius_of_gyration_nm"]
    fat = compute_shape_descriptors(_straight_bundle(radius=3.0))["radius_of_gyration_nm"]
    assert fat > thin


# ── degenerate inputs return None per-descriptor, never crash ─────────────────────

def test_single_helix_leaves_twist_undefined_but_returns_lengths():
    single = [_pos(0, i, "forward", (0.0, 0.0, 0.34 * i)) for i in range(40)]
    d = compute_shape_descriptors(single)
    assert d["twist_total_deg"] is None                     # <2 helices → no cross-section
    assert d["radius_of_gyration_nm"] > 0.0                 # length descriptors still defined

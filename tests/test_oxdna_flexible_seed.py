"""oxDNA seed placement of marked-flexible ssDNA runs.

A flexible (unpaired) scaffold run is otherwise seeded as a rigid B-DNA half-helix
jutting out of whichever cluster owns its helix; here we pin that the oxDNA
configuration writer re-seats it onto a contour-length arc between the two posed
rigid anchors (near-relaxed ssDNA, FENE-safe bonds) — matching the on-screen arc.

Physical-layer only: never mutates Design topology.
"""
from __future__ import annotations

import numpy as np

import backend.physics.oxdna_interface as ox
from backend.core.constants import OXDNA_LENGTH_UNIT, SSDNA_RISE_PER_BASE_NM
from backend.core.design_geometry import _geometry_for_design
from backend.core.flexible_display import flexible_segment_atomistic_frame_overrides
from backend.core.flexible_segments import apply_marks
from tests.test_flexible_segments import _hinge_design, _mark_run


# ── arc solver (port of flexible_arcs.js _arcPoints) ────────────────────────────

def test_arc_points_taut_is_straight_lerp():
    a, b = np.array([0.0, 0.0, 0.0]), np.array([3.0, 0.0, 0.0])
    bow = np.array([0.0, 1.0, 0.0])
    # chord (3) >= contour (2) → taut → evenly-spaced points ON the chord.
    pts = ox._flexible_arc_points(a, b, contour_nm=2.0, n=3, bow=bow)
    assert len(pts) == 3
    for i, p in enumerate(pts, start=1):
        assert p[1] == 0.0 and p[2] == 0.0            # no bow
        assert abs(p[0] - 3.0 * i / 4) < 1e-9         # even lerp along the chord


def test_arc_points_slack_bows_and_conserves_contour():
    a, b = np.array([0.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])
    bow = np.array([0.0, 1.0, 0.0])
    n, contour = 5, 6.0                               # chord 2 << contour 6 → bowed
    pts = ox._flexible_arc_points(a, b, contour_nm=contour, n=n, bow=bow)
    assert len(pts) == n
    # Bulges off the chord in the bow plane (sign is irrelevant for a seed).
    assert max(abs(p[1]) for p in pts) > 0.3
    assert all(abs(p[2]) < 1e-9 for p in pts)         # stays in the chord-bow plane
    # Backbone bonds (straight anchor→bead→…→anchor) are EVEN and each a chord of an
    # equal arc-step contour/(n+1) — so ≤ that step (a chord underruns its arc), and
    # close to it (the ssDNA rise).  This is what keeps the seed FENE-safe.
    chain = [a, *pts, b]
    segs = [float(np.linalg.norm(chain[i + 1] - chain[i])) for i in range(len(chain) - 1)]
    step = contour / (n + 1)
    assert max(segs) - min(segs) < 1e-6                # evenly spaced
    for s in segs:
        assert 0.5 * step < s <= step + 1e-6


# ── integration through the config resolver ─────────────────────────────────────

def _flex_design():
    return apply_marks(_mark_run(_hinge_design()))


def test_geo_keys_resolve_for_the_hinge_run():
    d = _flex_design()
    specs = ox.flexible_segment_geo_keys(d)
    assert len(specs) == 1
    ka, kb, beads, contour = specs[0]
    assert len(beads) == 6
    assert contour == 6 * SSDNA_RISE_PER_BASE_NM
    # anchors are rigid beads on the two arms, not part of the run
    assert ka not in beads and kb not in beads


def test_resolved_map_reseats_flexible_run_onto_arc():
    d = _flex_design()
    geom = _geometry_for_design(d)
    raw = {(n["helix_id"], n["bp_index"], n["direction"]):
           np.asarray(n["backbone_position"], float) for n in geom}
    resolved = ox.resolved_nuc_map(d, geom)

    (ka, kb, beads, contour) = ox.flexible_segment_geo_keys(d)[0]
    p_a = np.asarray(resolved[ka]["backbone_position"], float)
    p_b = np.asarray(resolved[kb]["backbone_position"], float)

    # 1) beads MOVED off their raw helix-axis placement.
    moved = [float(np.linalg.norm(np.asarray(resolved[k]["backbone_position"], float) - raw[k]))
             for k in beads]
    assert max(moved) > 0.3, "flexible beads were not re-seated"

    # 2) consecutive backbone bonds (anchor→beads→anchor) are FENE-safe and even.
    chain = [p_a] + [np.asarray(resolved[k]["backbone_position"], float) for k in beads] + [p_b]
    segs = [float(np.linalg.norm(chain[i + 1] - chain[i])) for i in range(len(chain) - 1)]
    for s in segs:
        assert 0.2 < s < 0.75, f"backbone bond {s:.3f} nm outside FENE-safe range"

    # 3) every bead sits within the contour length of BOTH anchors (between them,
    #    not stretched rigidly out of one arm).
    for k in beads:
        p = np.asarray(resolved[k]["backbone_position"], float)
        assert np.linalg.norm(p - p_a) <= contour + 0.05
        assert np.linalg.norm(p - p_b) <= contour + 0.05

    # 4) unit a1/a3 written for each re-seated bead (valid conf line).
    for k in beads:
        line = ox.nuc_conf_line(resolved[k]).split()
        a1 = np.array(line[3:6], float)
        a3 = np.array(line[6:9], float)
        assert abs(np.linalg.norm(a1) - 1.0) < 1e-4
        assert abs(np.linalg.norm(a3) - 1.0) < 1e-4
        assert abs(float(np.dot(a1, a3))) < 1e-4       # a1 ⟂ a3


def test_display_atomistic_overrides_place_flexible_run_on_full_rep_arc():
    d = _flex_design()
    geom = _geometry_for_design(d)
    raw = {(n["helix_id"], n["bp_index"], n["direction"]):
           np.asarray(n["backbone_position"], float) for n in geom}
    (_ka, _kb, beads, _contour) = ox.flexible_segment_geo_keys(d)[0]

    overrides = flexible_segment_atomistic_frame_overrides(d)

    assert set(beads).issubset(overrides.keys())
    moved = [float(np.linalg.norm(overrides[k].position - raw[k])) for k in beads]
    assert max(moved) > 0.3, "display atomistic/surface overrides left the ssDNA rigid"
    for k in beads:
        assert abs(np.linalg.norm(overrides[k].base_normal) - 1.0) < 1e-9
        assert abs(np.linalg.norm(overrides[k].axis_tangent) - 1.0) < 1e-9


def test_atomistic_display_consumes_flexible_full_rep_frames():
    from backend.core.atomistic import build_atomistic_model

    d = _flex_design()
    overrides = flexible_segment_atomistic_frame_overrides(d)
    (_ka, _kb, beads, _contour) = ox.flexible_segment_geo_keys(d)[0]

    model = build_atomistic_model(d, nuc_frame_override=overrides)
    rigid = build_atomistic_model(d)

    for k in beads:
        placed = np.array([
            [a.x, a.y, a.z] for a in model.atoms
            if (a.helix_id, a.bp_index, a.direction) == k
        ])
        rigid_placed = np.array([
            [a.x, a.y, a.z] for a in rigid.atoms
            if (a.helix_id, a.bp_index, a.direction) == k
        ])
        assert np.linalg.norm(placed.mean(axis=0) - rigid_placed.mean(axis=0)) > 0.3


def test_reseat_is_readonly_over_topology():
    d = _flex_design()
    before = d.model_dump_json()
    ox.resolved_nuc_map(d, _geometry_for_design(d))
    assert d.model_dump_json() == before


def test_no_flexible_connections_is_identity():
    d = _hinge_design()            # no marks → no connections
    geom = _geometry_for_design(d)
    resolved = ox.resolved_nuc_map(d, geom)
    # every real bead keeps its raw geometry position (no arc pass fired).
    for n in geom:
        k = (n["helix_id"], n["bp_index"], n["direction"])
        if k in resolved:
            assert np.allclose(resolved[k]["backbone_position"],
                               n["backbone_position"], atol=1e-9)


# guard: OXDNA_LENGTH_UNIT import kept meaningful (conf writer uses NM_TO_OXDNA)
assert OXDNA_LENGTH_UNIT > 0

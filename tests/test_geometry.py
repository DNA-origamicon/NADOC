"""
Tests for backend/core/geometry.py.

All expected values are derived from oxDNA literature and standard B-DNA
crystallographic parameters:
  rise          = 0.334 nm/bp
  twist         = 34.3 deg/bp  →  0.598430… rad/bp
  radius        = 1.0 nm
  minor groove  = 150°  (caDNAno convention; FORWARD and REVERSE are NOT antipodal)

The helix axis runs along +Z in all test cases for clarity.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core.constants import (
    BASE_DISPLACEMENT,
    BDNA_MINOR_GROOVE_ANGLE_DEG,
    BDNA_MINOR_GROOVE_ANGLE_RAD,
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_DEG,
    BDNA_TWIST_PER_BP_RAD,
    HELIX_RADIUS,
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_HELIX_SPACING,
    HONEYCOMB_LATTICE_RADIUS,
    HONEYCOMB_ROW_PITCH,
    SQUARE_HELIX_SPACING,
    SQUARE_TWIST_PER_BP_DEG,
)
from backend.core.geometry import nucleotide_positions, helix_axis_point
from backend.core.models import ClusterRigidTransform, Design, Direction, Helix, Vec3


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_z_helix(length_bp: int, phase_offset: float = 0.0) -> Helix:
    """Simple helix running along +Z from origin."""
    return Helix(
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=phase_offset,
        length_bp=length_bp,
    )


def by_bp_dict(positions):
    """Index positions as {bp_index: {Direction.FORWARD: nuc, Direction.REVERSE: nuc}}."""
    d: dict = {}
    for p in positions:
        d.setdefault(p.bp_index, {})[p.direction] = p
    return d


# ── Count and type tests ───────────────────────────────────────────────────────


def test_nucleotide_count():
    """Each bp produces exactly 2 nucleotides (FORWARD + REVERSE)."""
    length = 21
    helix = make_z_helix(length)
    positions = nucleotide_positions(helix)
    assert len(positions) == 2 * length


def test_nucleotide_types_present():
    """Both FORWARD and REVERSE nucleotides are present at every bp index."""
    helix = make_z_helix(10)
    positions = nucleotide_positions(helix)
    for bp in range(10):
        bp_positions = [p for p in positions if p.bp_index == bp]
        directions = {p.direction for p in bp_positions}
        assert Direction.FORWARD in directions
        assert Direction.REVERSE in directions


# ── Rise tests ─────────────────────────────────────────────────────────────────


def test_rise_per_bp():
    """
    The axial separation between consecutive FORWARD nucleotides must equal
    BDNA_RISE_PER_BP (0.334 nm), measured along the helix axis (+Z).
    """
    helix = make_z_helix(10, phase_offset=0.0)
    positions = nucleotide_positions(helix)
    fwd = sorted([p for p in positions if p.direction == Direction.FORWARD],
                 key=lambda p: p.bp_index)
    for i in range(1, len(fwd)):
        dz = fwd[i].position[2] - fwd[i - 1].position[2]
        assert abs(dz - BDNA_RISE_PER_BP) < 1e-9, (
            f"Rise at bp {i}: {dz:.6f} nm (expected {BDNA_RISE_PER_BP} nm)"
        )


def test_rise_accumulated():
    """Total axial span equals (length_bp - 1) × rise."""
    length = 42
    helix = make_z_helix(length)
    fwd = sorted([p for p in nucleotide_positions(helix) if p.direction == Direction.FORWARD],
                 key=lambda p: p.bp_index)
    total_rise = fwd[-1].position[2] - fwd[0].position[2]
    expected = (length - 1) * BDNA_RISE_PER_BP
    assert abs(total_rise - expected) < 1e-9


# ── Radius tests ───────────────────────────────────────────────────────────────


def test_helix_radius_forward():
    """Every FORWARD backbone bead must be exactly HELIX_RADIUS from the axis."""
    helix = make_z_helix(21)
    for p in nucleotide_positions(helix):
        if p.direction != Direction.FORWARD:
            continue
        r = math.sqrt(p.position[0]**2 + p.position[1]**2)
        assert abs(r - HELIX_RADIUS) < 1e-9, (
            f"bp {p.bp_index} FORWARD radius: {r:.6f} nm (expected {HELIX_RADIUS} nm)"
        )


def test_helix_radius_reverse():
    """
    Every REVERSE backbone bead must also be exactly HELIX_RADIUS from the axis.
    With the major/minor groove geometry, REVERSE sits at 150° from FORWARD,
    but at the same radial distance.
    """
    helix = make_z_helix(21)
    for p in nucleotide_positions(helix):
        if p.direction != Direction.REVERSE:
            continue
        r = math.sqrt(p.position[0]**2 + p.position[1]**2)
        assert abs(r - HELIX_RADIUS) < 1e-9, (
            f"bp {p.bp_index} REVERSE radius: {r:.6f} nm (expected {HELIX_RADIUS} nm)"
        )


# ── Major/minor groove geometry ────────────────────────────────────────────────


def test_minor_groove_angle():
    """
    The angular separation between FORWARD and REVERSE backbone beads at the
    same bp index (measured at the helix axis) must equal
    BDNA_MINOR_GROOVE_ANGLE_DEG (150°).
    """
    helix = make_z_helix(21)
    positions = nucleotide_positions(helix)
    by = by_bp_dict(positions)

    for bp, strands in by.items():
        fwd = strands[Direction.FORWARD]
        rev = strands[Direction.REVERSE]
        axis_pt = np.array([0.0, 0.0, bp * BDNA_RISE_PER_BP])
        fwd_r = fwd.position - axis_pt
        rev_r = rev.position - axis_pt
        cos_a = np.dot(fwd_r, rev_r) / (np.linalg.norm(fwd_r) * np.linalg.norm(rev_r))
        angle_deg = math.degrees(math.acos(np.clip(cos_a, -1.0, 1.0)))
        assert abs(angle_deg - BDNA_MINOR_GROOVE_ANGLE_DEG) < 1e-6, (
            f"bp {bp}: groove angle {angle_deg:.4f}° (expected {BDNA_MINOR_GROOVE_ANGLE_DEG}°)"
        )


def test_forward_reverse_backbone_distance():
    """
    FORWARD–REVERSE backbone distance at each bp must equal
    2 × HELIX_RADIUS × sin(MINOR_GROOVE_ANGLE / 2) ≈ 1.932 nm.
    (They are NOT antipodal — that would be 2.0 nm.)
    """
    expected = 2.0 * HELIX_RADIUS * math.sin(BDNA_MINOR_GROOVE_ANGLE_RAD / 2.0)
    helix = make_z_helix(21)
    by = by_bp_dict(nucleotide_positions(helix))
    for bp, strands in by.items():
        dist = np.linalg.norm(
            strands[Direction.FORWARD].position - strands[Direction.REVERSE].position
        )
        assert abs(dist - expected) < 1e-9, (
            f"bp {bp}: backbone distance {dist:.6f} nm (expected {expected:.6f} nm)"
        )


# ── Twist tests ────────────────────────────────────────────────────────────────


def test_twist_per_bp():
    """
    The angular step between consecutive FORWARD backbone beads must equal
    BDNA_TWIST_PER_BP_DEG (34.3°).
    """
    helix = make_z_helix(21)
    fwd = sorted([p for p in nucleotide_positions(helix) if p.direction == Direction.FORWARD],
                 key=lambda p: p.bp_index)
    for i in range(1, len(fwd)):
        xy0 = fwd[i - 1].position[:2]
        xy1 = fwd[i].position[:2]
        angle0 = math.atan2(xy0[1], xy0[0])
        angle1 = math.atan2(xy1[1], xy1[0])
        delta_deg = (math.degrees(angle1 - angle0) + 180) % 360 - 180
        assert abs(abs(delta_deg) - BDNA_TWIST_PER_BP_DEG) < 1e-6, (
            f"Twist at step {i}: {delta_deg:.4f}° (expected ±{BDNA_TWIST_PER_BP_DEG}°)"
        )


def test_twist_accumulation_matches_formula():
    """
    Angular advance from bp 0 to bp N equals N × BDNA_TWIST_PER_BP_RAD (mod 2π).
    Measured as relative increment so frame construction convention is irrelevant.
    """
    phase = math.pi / 7
    helix = make_z_helix(50, phase_offset=phase)
    fwd = {p.bp_index: p for p in nucleotide_positions(helix) if p.direction == Direction.FORWARD}
    angle_0 = math.atan2(fwd[0].position[1], fwd[0].position[0])
    for bp, p in fwd.items():
        measured = math.atan2(p.position[1], p.position[0]) - angle_0
        expected = bp * BDNA_TWIST_PER_BP_RAD
        delta = (measured - expected + math.pi) % (2 * math.pi) - math.pi
        assert abs(delta) < 1e-9, f"bp {bp}: twist error {math.degrees(delta):.6f}°"


# ── Phase offset test ──────────────────────────────────────────────────────────


def test_phase_offset():
    """phase_offset of π/2 rotates the bp=0 FORWARD nucleotide by 90°."""
    h0   = make_z_helix(5, phase_offset=0.0)
    hpi2 = make_z_helix(5, phase_offset=math.pi / 2)
    fwd0   = next(p for p in nucleotide_positions(h0)   if p.bp_index == 0 and p.direction == Direction.FORWARD)
    fwdpi2 = next(p for p in nucleotide_positions(hpi2) if p.bp_index == 0 and p.direction == Direction.FORWARD)
    a0   = math.atan2(fwd0.position[1],   fwd0.position[0])
    api2 = math.atan2(fwdpi2.position[1], fwdpi2.position[0])
    delta = abs(api2 - a0)
    assert abs(delta - math.pi / 2) < 1e-9, (
        f"Phase offset angular diff: {math.degrees(delta):.4f}° (expected 90°)"
    )


# ── Axis tangent ───────────────────────────────────────────────────────────────


def test_axis_tangent_direction():
    """axis_tangent must be a unit vector along +Z for a Z-axis helix."""
    helix = make_z_helix(10)
    for p in nucleotide_positions(helix):
        norm = np.linalg.norm(p.axis_tangent)
        assert abs(norm - 1.0) < 1e-9
        assert abs(p.axis_tangent[2] - 1.0) < 1e-9, (
            f"axis_tangent not along Z: {p.axis_tangent}"
        )


# ── Base normal — cross-strand direction ───────────────────────────────────────


def test_base_normal_is_unit_vector():
    """base_normal must be a unit vector for all nucleotides."""
    helix = make_z_helix(10)
    for p in nucleotide_positions(helix):
        norm = np.linalg.norm(p.base_normal)
        assert abs(norm - 1.0) < 1e-9, (
            f"base_normal not unit at bp {p.bp_index} {p.direction}: norm={norm:.6f}"
        )


def test_base_normal_cross_strand_direction():
    """
    FORWARD base_normal must point exactly toward the REVERSE backbone bead
    at the same bp index (and vice versa).  This is the cross-strand
    (NOT inward-radial) convention required by the major/minor groove geometry.
    """
    helix = make_z_helix(10)
    by = by_bp_dict(nucleotide_positions(helix))
    for bp, strands in by.items():
        fwd = strands[Direction.FORWARD]
        rev = strands[Direction.REVERSE]
        fwd_to_rev = rev.position - fwd.position
        fwd_to_rev_hat = fwd_to_rev / np.linalg.norm(fwd_to_rev)
        assert np.allclose(fwd.base_normal, fwd_to_rev_hat, atol=1e-9), (
            f"bp {bp}: FORWARD base_normal {fwd.base_normal} ≠ "
            f"cross-strand direction {fwd_to_rev_hat}"
        )
        assert np.allclose(rev.base_normal, -fwd_to_rev_hat, atol=1e-9), (
            f"bp {bp}: REVERSE base_normal {rev.base_normal} ≠ "
            f"cross-strand direction {-fwd_to_rev_hat}"
        )


# ── Non-Z-axis helix ────────────────────────────────────────────────────────────


def test_tilted_helix_radius():
    """A tilted helix still places all backbone beads at HELIX_RADIUS from axis."""
    raw = np.array([1.0, 1.0, 1.0])
    axis_len = np.linalg.norm(raw) * 10 * BDNA_RISE_PER_BP
    ax_hat = raw / np.linalg.norm(raw)
    axis_end_scaled = Vec3(
        x=float(ax_hat[0] * axis_len),
        y=float(ax_hat[1] * axis_len),
        z=float(ax_hat[2] * axis_len),
    )
    helix = Helix(
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=axis_end_scaled,
        phase_offset=0.0,
        length_bp=10,
    )
    for p in nucleotide_positions(helix):
        axis_pt = ax_hat * (p.bp_index * BDNA_RISE_PER_BP)
        r = np.linalg.norm(p.position - axis_pt)
        assert abs(r - HELIX_RADIUS) < 1e-9, (
            f"Tilted helix bp {p.bp_index} {p.direction}: radius {r:.6f} nm"
        )


# ── helix_axis_point helper ─────────────────────────────────────────────────────


def test_helix_axis_point_z():
    """helix_axis_point returns the correct axis position along Z."""
    helix = make_z_helix(10)
    for bp in range(10):
        pt = helix_axis_point(helix, bp)
        assert abs(pt[2] - bp * BDNA_RISE_PER_BP) < 1e-9
        assert abs(pt[0]) < 1e-9
        assert abs(pt[1]) < 1e-9


# ── Base bead (DTP-0a) ─────────────────────────────────────────────────────────


def test_base_position_displacement_from_backbone():
    """base_position must be exactly BASE_DISPLACEMENT from the backbone."""
    helix = make_z_helix(21)
    for p in nucleotide_positions(helix):
        dist = np.linalg.norm(p.base_position - p.position)
        assert abs(dist - BASE_DISPLACEMENT) < 1e-9, (
            f"bp {p.bp_index} {p.direction}: backbone→base {dist:.6f} nm "
            f"(expected {BASE_DISPLACEMENT} nm)"
        )


def test_base_position_closer_to_axis():
    """
    base_position must be closer to the helix axis than the backbone.
    With the cross-strand base_normal, the base moves partly tangentially,
    so its axis distance is no longer exactly (HELIX_RADIUS - BASE_DISPLACEMENT);
    we only assert it is strictly less than HELIX_RADIUS.
    """
    helix = make_z_helix(21)
    for p in nucleotide_positions(helix):
        axis_pt = np.array([0.0, 0.0, p.bp_index * BDNA_RISE_PER_BP])
        backbone_r = np.linalg.norm(p.position - axis_pt)
        base_r     = np.linalg.norm(p.base_position - axis_pt)
        assert base_r < backbone_r, (
            f"bp {p.bp_index} {p.direction}: base ({base_r:.4f} nm) not closer to axis "
            f"than backbone ({backbone_r:.4f} nm)"
        )


def test_base_position_on_base_normal_ray():
    """
    base_position = backbone + BASE_DISPLACEMENT × base_normal,
    regardless of what direction base_normal points.
    """
    helix = make_z_helix(21)
    for p in nucleotide_positions(helix):
        expected = p.position + BASE_DISPLACEMENT * p.base_normal
        delta = np.linalg.norm(p.base_position - expected)
        assert delta < 1e-9, (
            f"bp {p.bp_index} {p.direction}: base_position off base_normal ray "
            f"(delta={delta:.2e} nm)"
        )


def test_base_pair_bead_distance():
    """
    FORWARD–REVERSE base bead distance at each bp =
    backbone_pair_distance − 2 × BASE_DISPLACEMENT.
    With the 150° groove angle: backbone pair distance = 2 × sin(75°) ≈ 1.932 nm.
    """
    backbone_pair_dist = 2.0 * HELIX_RADIUS * math.sin(BDNA_MINOR_GROOVE_ANGLE_RAD / 2.0)
    expected = backbone_pair_dist - 2.0 * BASE_DISPLACEMENT
    helix = make_z_helix(21)
    by = by_bp_dict(nucleotide_positions(helix))
    for bp, strands in by.items():
        dist = np.linalg.norm(
            strands[Direction.FORWARD].base_position - strands[Direction.REVERSE].base_position
        )
        assert abs(dist - expected) < 1e-9, (
            f"bp {bp}: base-pair bead distance {dist:.6f} nm (expected {expected:.6f} nm)"
        )


# ── Zero-length helix guard ─────────────────────────────────────────────────────


def test_zero_length_axis_raises():
    """A helix with axis_start == axis_end must raise ValueError."""
    helix = Helix(
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=0),
        phase_offset=0.0,
        length_bp=5,
    )
    with pytest.raises(ValueError, match="zero-length"):
        nucleotide_positions(helix)


# ── Deformation geometry ───────────────────────────────────────────────────────


def _make_6hb_420():
    from backend.core.lattice import make_bundle_design
    cells = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
    return make_bundle_design(cells, length_bp=420)


def _add_bend(design, plane_a, plane_b, angle_deg=180.0):
    from backend.core.models import BendParams, DeformationOp
    from backend.core.deformation import helices_crossing_planes
    span = max(1, plane_b - plane_a)
    op = DeformationOp(
        type="bend",
        plane_a_bp=plane_a,
        plane_b_bp=plane_b,
        affected_helix_ids=helices_crossing_planes(design, plane_a, plane_b),
        params=BendParams(curvature_deg_per_bp=angle_deg / span, direction_deg=0.0),
    )
    return design.model_copy(update={"deformations": [op]}, deep=True)


def _collect_positions(design):
    from backend.core.deformation import deformed_nucleotide_positions
    return {
        (nuc.helix_id, nuc.bp_index, nuc.direction): nuc.position
        for h in design.helices
        for nuc in deformed_nucleotide_positions(h, design)
    }


def _make_unequal_bundle():
    """Two parallel +Z helices of unequal length, both starting at global bp 0.

    Mimics teeth.nadoc: a long "backbone" helix (bp 0–199) and a short "tooth"
    that ends mid-structure (bp 0–99).
    """
    long_h  = make_z_helix(200).model_copy(update={"id": "h_long"})
    short_h = make_z_helix(100).model_copy(update={
        "id": "h_short",
        "axis_start": Vec3(x=2.5, y=0, z=0),
        "axis_end":   Vec3(x=2.5, y=0, z=100 * BDNA_RISE_PER_BP),
    })
    return Design(helices=[long_h, short_h])


def test_helices_crossing_planes_includes_partially_spanning_helix():
    """A bend window extending past a short helix's end must still include it.

    Regression for teeth.nadoc: the old "covers BOTH planes" test silently dropped
    helices that ended mid-window (teeth, bp 0–209) while the backbone (bp 0–251)
    bent, leaving only the full-length helices deformed.  The overlap test includes
    any helix whose span intersects the window.
    """
    from backend.core.deformation import helices_crossing_planes
    design = _make_unequal_bundle()
    # Window [0, 150]: long covers it fully; short ends at bp 99 — overlaps → included.
    assert set(helices_crossing_planes(design, 0, 150)) == {"h_long", "h_short"}
    # Window [120, 150] lies entirely past the short helix → no overlap → excluded.
    assert set(helices_crossing_planes(design, 120, 150)) == {"h_long"}


def test_short_helix_bends_when_window_extends_past_its_end():
    """End-to-end: a short helix's nucleotides move under a bend whose far plane
    is past the short helix's end (it follows the arc and terminates partway)."""
    from backend.core.models import BendParams, DeformationOp
    from backend.core.deformation import (
        helices_crossing_planes,
        deformed_nucleotide_positions,
    )
    design = _make_unequal_bundle()
    op = DeformationOp(
        type="bend", plane_a_bp=0, plane_b_bp=150,
        affected_helix_ids=helices_crossing_planes(design, 0, 150),
        params=BendParams(curvature_deg_per_bp=90.0 / 150, direction_deg=0.0),
    )
    design = design.model_copy(update={"deformations": [op]}, deep=True)
    short = next(h for h in design.helices if h.id == "h_short")
    straight = {(n.bp_index, n.direction): np.array(n.position)
                for n in nucleotide_positions(short)}
    bent = {(n.bp_index, n.direction): np.array(n.position)
            for n in deformed_nucleotide_positions(short, design)}
    moved = max(float(np.linalg.norm(bent[k] - straight[k])) for k in bent)
    assert moved > 1.0, f"short helix did not bend (max nuc move {moved:.3f} nm)"


def test_overlapping_helix_level_cluster_transforms_compose_for_nucleotides_and_axes():
    """Imported caDNAno designs can have umbrella scaffold clusters plus geometry clusters.

    A first identity cluster must not mask a later moved cluster for the same helix.
    """
    from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_arrays

    helix = make_z_helix(3).model_copy(update={"id": "h1"})
    identity = ClusterRigidTransform(
        name="Scaffold Cluster",
        helix_ids=["h1"],
    )
    moved = ClusterRigidTransform(
        name="Geometry Cluster",
        helix_ids=["h1"],
        translation=[0.0, 0.0, 7.5],
    )
    design = Design(helices=[helix], cluster_transforms=[identity, moved])

    straight = deformed_nucleotide_arrays(helix, Design(helices=[helix]))
    moved_arrs = deformed_nucleotide_arrays(helix, design)
    np.testing.assert_allclose(
        moved_arrs["positions"] - straight["positions"],
        np.tile(np.array([0.0, 0.0, 7.5]), (len(straight["positions"]), 1)),
        atol=1e-9,
    )

    axes = deformed_helix_axes(design)
    assert axes[0]["start"][2] == pytest.approx(7.5)
    assert axes[0]["end"][2] == pytest.approx(helix.axis_end.z + 7.5)


# ── Combined bend + twist (superhelix) ──────────────────────────────────────────
#
# These lock the sub-interval screw integration in deformation.py: single-op
# intervals must reduce to the legacy arc / axial-spin math, OVERLAPPING bend+twist
# must compose into a superhelix (not silently drop one op), and the scalar
# (_frame_at_bp) and vectorised (_precompute_arm_frames) paths must agree.


def _bend_op(plane_a, plane_b, angle_deg, direction_deg=0.0):
    from backend.core.models import BendParams, DeformationOp
    span = max(1, plane_b - plane_a)
    return DeformationOp(
        type="bend", plane_a_bp=plane_a, plane_b_bp=plane_b,
        affected_helix_ids=[],  # empty = all crossing helices
        params=BendParams(curvature_deg_per_bp=angle_deg / span, direction_deg=direction_deg),
    )


def _twist_op(plane_a, plane_b, total_degrees):
    from backend.core.models import DeformationOp, TwistParams
    return DeformationOp(
        type="twist", plane_a_bp=plane_a, plane_b_bp=plane_b,
        affected_helix_ids=[],
        params=TwistParams(total_degrees=total_degrees),
    )


def _frame(design, bp):
    from backend.core.deformation import _frame_at_bp
    return _frame_at_bp(design, bp, list(design.helices))


def test_single_bend_reduces_to_arc_formula():
    """A lone bend op must reproduce the legacy constant-curvature arc exactly."""
    N, angle = 200, 90.0
    design = Design(helices=[make_z_helix(N)],
                    deformations=[_bend_op(0, N, angle, direction_deg=0.0)])
    angle_rad = math.radians(angle)
    radius = N * BDNA_RISE_PER_BP / angle_rad
    world_dir = np.array([1.0, 0.0, 0.0])   # direction_deg=0, R=I at start
    tangent0 = np.array([0.0, 0.0, 1.0])
    for p in (0, 37, 100, N):
        theta = p * angle_rad / N
        expect = radius * (1 - math.cos(theta)) * world_dir + radius * math.sin(theta) * tangent0
        spine, _, _ = _frame(design, p)
        np.testing.assert_allclose(spine, expect, atol=1e-9)


def test_single_twist_is_straight_axial_spin():
    """A lone twist op leaves the spine straight along +Z and rotates R about it."""
    from backend.core.deformation import _rot_around_axis
    N, total = 200, 45.0
    design = Design(helices=[make_z_helix(N)],
                    deformations=[_twist_op(0, N, total)])
    for p in (0, 80, N):
        spine, R, tangent = _frame(design, p)
        np.testing.assert_allclose(spine, [0, 0, p * BDNA_RISE_PER_BP], atol=1e-9)
        np.testing.assert_allclose(tangent, [0, 0, 1], atol=1e-9)
        expect_R = _rot_around_axis(np.array([0.0, 0.0, 1.0]),
                                    math.radians(total) * p / N)
        np.testing.assert_allclose(R, expect_R, atol=1e-9)


def test_overlapping_bend_twist_composes_not_drops():
    """Bend and twist over the SAME bp range compose: the result is neither the
    pure-bend nor the pure-twist frame (the old single-cursor walk dropped one)."""
    N = 200
    bend_only = Design(helices=[make_z_helix(N)],
                       deformations=[_bend_op(0, N, 90.0)])
    twist_only = Design(helices=[make_z_helix(N)],
                        deformations=[_twist_op(0, N, 60.0)])
    combined = Design(helices=[make_z_helix(N)],
                      deformations=[_bend_op(0, N, 90.0), _twist_op(0, N, 60.0)])

    sp_b, R_b, _ = _frame(bend_only, N)
    sp_t, R_t, _ = _frame(twist_only, N)
    sp_c, R_c, _ = _frame(combined, N)

    # Combined is curved (unlike pure twist, which is straight) → twist did not win.
    assert np.linalg.norm(sp_c - sp_t) > 1.0
    # Combined frame carries twist (unlike pure bend) → bend did not win.
    assert np.linalg.norm(R_c - R_b) > 1e-3
    assert np.linalg.norm(R_c - R_t) > 1e-3


def test_combined_order_independent():
    """Adding the bend before the twist or vice-versa yields identical geometry."""
    from backend.core.deformation import deformed_nucleotide_arrays
    N = 200
    h = make_z_helix(N)
    bt = Design(helices=[h], deformations=[_bend_op(0, N, 90.0), _twist_op(0, N, 60.0)])
    tb = Design(helices=[h], deformations=[_twist_op(0, N, 60.0), _bend_op(0, N, 90.0)])
    a = deformed_nucleotide_arrays(h, bt)["positions"]
    b = deformed_nucleotide_arrays(h, tb)["positions"]
    np.testing.assert_allclose(a, b, atol=1e-9)


def test_scalar_and_vectorised_frames_agree_for_overlap():
    """_frame_at_bp (scalar) and _precompute_arm_frames (vectorised) must match for
    a design with overlapping bend+twist."""
    from backend.core.deformation import _precompute_arm_frames
    N = 150
    design = Design(helices=[make_z_helix(N)],
                    deformations=[_bend_op(0, N, 80.0, direction_deg=30.0),
                                  _twist_op(0, N, 55.0)])
    arm = list(design.helices)
    spines, Rs, tans = _precompute_arm_frames(design, arm, 0, N - 1)
    for p in range(0, N, 7):
        spine, R, tangent = _frame(design, p)
        np.testing.assert_allclose(spine, spines[p], atol=1e-9)
        np.testing.assert_allclose(R, Rs[p], atol=1e-9)
        np.testing.assert_allclose(tangent, tans[p], atol=1e-9)


def test_combined_matches_fine_step_integration():
    """The closed-form screw integration matches a fine-step forward integration
    of the same constant world angular velocity (independent numerical reference)."""
    from backend.core.deformation import _rot_around_axis
    N, angle, total = 120, 70.0, 50.0
    design = Design(helices=[make_z_helix(N)],
                    deformations=[_bend_op(0, N, angle, direction_deg=0.0),
                                  _twist_op(0, N, total)])
    # omega (rad/bp): bend about +Y (dir=0 → binormal = ẑ×x̂ = ŷ), twist about +Z.
    kappa = math.radians(angle) / N
    tau = math.radians(total) / N
    omega = np.array([0.0, kappa, 0.0]) + np.array([0.0, 0.0, tau])
    w = np.linalg.norm(omega)
    axis = omega / w
    sub = 200  # sub-steps per bp
    ds = 1.0 / sub
    R = np.eye(3)
    tangent = np.array([0.0, 0.0, 1.0])
    spine = np.zeros(3)
    dR = _rot_around_axis(axis, w * ds)
    dR_half = _rot_around_axis(axis, w * ds / 2)
    for _ in range(N * sub):
        # Midpoint rule (O(ds²)) so the reference converges to the exact screw.
        tangent_mid = dR_half @ tangent
        spine = spine + tangent_mid * ds * BDNA_RISE_PER_BP
        R = dR @ R
        tangent = dR @ tangent
    spine_ref = spine
    spine_c, R_c, _ = _frame(design, N)
    np.testing.assert_allclose(spine_c, spine_ref, atol=1e-5)
    np.testing.assert_allclose(R_c, R, atol=1e-9)


def test_adjacent_nonoverlapping_ops_still_compose_sequentially():
    """Two ops on consecutive (non-overlapping) ranges integrate independently:
    a straight twist segment then a separate bend segment."""
    N = 200
    design = Design(helices=[make_z_helix(N)],
                    deformations=[_twist_op(0, 100, 90.0), _bend_op(100, 200, 60.0)])
    # First half is pure twist → spine stays on the +Z axis.
    spine_mid, _, tangent_mid = _frame(design, 100)
    np.testing.assert_allclose(spine_mid, [0, 0, 100 * BDNA_RISE_PER_BP], atol=1e-9)
    np.testing.assert_allclose(tangent_mid, [0, 0, 1], atol=1e-9)
    # Second half bends → tangent tilts away from +Z by the far plane.
    _, _, tangent_end = _frame(design, 200)
    assert abs(tangent_end[2] - 1.0) > 1e-3


# ── the one groove-sign rule ──────────────────────────────────────────────────


def test_groove_offset_rad_is_the_one_sign_rule():
    """+150 deg on FORWARD-cell helices, -150 on REVERSE, and -150 on unknown.

    The whole geometric layer is built on this sign, and until 2026-08-06 it was
    re-derived at eleven call sites across geometry.py, mrdna_bridge.py,
    oxdna_interface.py and oxdna_surface_strands.py.  They did not all agree, which is
    the point of having one implementation (TD-27).
    """
    from backend.core.geometry import groove_offset_rad

    assert groove_offset_rad(Direction.FORWARD) == BDNA_MINOR_GROOVE_ANGLE_RAD
    assert groove_offset_rad(Direction.REVERSE) == -BDNA_MINOR_GROOVE_ANGLE_RAD


def test_the_unknown_direction_case_follows_the_reverse_branch():
    """Pinned separately because it is where the re-derivations disagreed.

    A helix whose lattice cell type was never resolved has ``direction is None``.  The
    geometric layer and ``atomistic._atom_frame`` both fold that into the REVERSE branch;
    ``oxdna_interface._compute_nuc_geometry`` gave it the OPPOSITE sign until TD-27
    Stage 2.  A caller that means "forward" must say so explicitly.
    """
    from backend.core.geometry import groove_offset_rad

    assert groove_offset_rad(None) == groove_offset_rad(Direction.REVERSE)
    assert groove_offset_rad(None) == -BDNA_MINOR_GROOVE_ANGLE_RAD


def test_the_scalar_and_array_bead_paths_agree():
    """They are deliberately NOT one implementation, so pin that they still match.

    ``nucleotide_positions`` uses ``math.cos``/``math.sin`` on Python floats;
    ``nucleotide_positions_arrays`` uses the numpy pair, and can differ at the last ULP.
    They were left separate for exactly that reason — ``nucleotide_positions_arrays``
    falls back to the scalar path for helices carrying loops/skips, so merging them would
    silently move every skip-bearing design.  Only the groove offset is shared.
    """
    from backend.core.geometry import nucleotide_positions, nucleotide_positions_arrays
    from backend.core.models import Helix, Vec3

    for direction in (Direction.FORWARD, Direction.REVERSE):
        helix = Helix(
            id="h_pin",
            axis_start=Vec3(x=0.0, y=0.0, z=0.0),
            axis_end=Vec3(x=0.0, y=0.0, z=32 * BDNA_RISE_PER_BP),
            phase_offset=0.37,
            twist_per_bp_rad=math.radians(34.3),
            length_bp=32,
            bp_start=0,
            direction=direction,
        )
        scalar = nucleotide_positions(helix)
        arrays = nucleotide_positions_arrays(helix)
        assert len(scalar) == len(arrays["positions"])
        for i, nuc in enumerate(scalar):
            for got, want, name in (
                (arrays["positions"][i], nuc.position, "position"),
                (arrays["base_positions"][i], nuc.base_position, "base_position"),
                (arrays["base_normals"][i], nuc.base_normal, "base_normal"),
            ):
                assert np.allclose(got, want, atol=1e-12), f"{direction} {name} @ {i}"


# ── Python is authoritative; the JS mirrors are pinned to it ──────────────────
#
# Same pattern as test_lattice.py's RELAXED_SPACING_NM twin: JS cannot import Python, so
# it keeps a literal and a test regexes the source.  Nothing pinned these until TD-27.


def _js_const(path: str, name: str) -> float:
    """Read one exported numeric constant out of a JS source file.

    Several of these are written as arithmetic (`1.125 * Math.sqrt(3)`, `3 * 360 / 32`)
    rather than a bare literal, so the value is evaluated rather than parsed.  Only
    `Math.*` and numeric operators are in scope.
    """
    import math as _math
    import pathlib
    import re

    src = pathlib.Path(path).read_text()
    m = re.search(rf"^\s*(?:export\s+)?const\s+{name}\s*=\s*(.+?)\s*(?://.*)?$", src, re.M)
    assert m, f"{name} not found in {path} — did the module move or the constant rename?"
    expr = m.group(1).strip().rstrip(";").replace("Math.", "")
    assert re.fullmatch(r"[-\d.eE+*/() sqrtPIabspow,]+", expr), f"{name}: unparsed {expr!r}"
    env = {"sqrt": _math.sqrt, "PI": _math.pi, "abs": abs, "pow": pow}
    return float(eval(expr, {"__builtins__": {}}, env))  # noqa: S307 - numeric expr only


def test_frontend_bdna_constants_match_the_backend():
    """`frontend/src/constants.js` is a hand-maintained mirror of `constants.py`.

    Its own header says it is "never used for rendering the actual design", which is no
    longer true — several renderers import from it (and several more re-declare the same
    numbers locally, which TD-27 Stage 1b collapses onto this file).  Either way a drift
    here makes the live preview and the server disagree about the same helix.
    """
    js = "frontend/src/constants.js"
    assert _js_const(js, "BDNA_RISE_PER_BP") == BDNA_RISE_PER_BP
    assert _js_const(js, "BDNA_TWIST_PER_BP") == BDNA_TWIST_PER_BP_DEG
    assert _js_const(js, "HELIX_RADIUS") == HELIX_RADIUS
    assert _js_const(js, "HONEYCOMB_LATTICE_RADIUS") == HONEYCOMB_LATTICE_RADIUS
    assert _js_const(js, "HONEYCOMB_HELIX_SPACING") == HONEYCOMB_HELIX_SPACING
    assert _js_const(js, "HONEYCOMB_COL_PITCH") == pytest.approx(HONEYCOMB_COL_PITCH, abs=1e-12)
    assert _js_const(js, "HONEYCOMB_ROW_PITCH") == pytest.approx(HONEYCOMB_ROW_PITCH, abs=1e-12)
    assert _js_const(js, "SQUARE_HELIX_SPACING") == SQUARE_HELIX_SPACING
    assert _js_const(js, "SQUARE_TWIST_PER_BP_DEG") == pytest.approx(
        SQUARE_TWIST_PER_BP_DEG, abs=1e-12)


def test_measured_slab_extent_matches_the_frontend_twin():
    """The slab length is DERIVED from the measured atomistic template, not typed.

    `new_positioning.js` carries a literal copy because JS cannot import Python.  It was
    already stale when this pin was written — 0.6568 against a derived 0.6569 — so the
    slab the app drew was a tenth of a picometre short of the one the backend computes.
    Harmless at that size, and exactly the drift this pin exists to catch before it isn't.
    """
    from backend.core.measured_positioning import MEASURED

    js = _js_const("frontend/src/ui/new_positioning.js", "MEASURED_SLAB_EXTENT")
    assert js == pytest.approx(MEASURED.slab_extent_nm, abs=1e-12)


def test_the_oxdna_fallback_geometry_agrees_with_the_geometric_layer():
    """`_compute_nuc_geometry` is the fallback the oxDNA writer uses for nucleotides the
    geometry list does not carry — overhang bp past `helix.length_bp`, and loop copies.

    It used to re-implement the helix math inline, and had drifted from it twice
    (TD-27 Stage 2, both fixed by delegating to `geometry.py` instead):

      1. The groove sign was INVERTED — `-G` on FORWARD-cell helices where `geometry.py`
         uses `+G`.  FORWARD beads do not depend on the groove so they were right; every
         REVERSE bead sat exactly **1.000 nm** off (two points at r = 1.0 whose placements
         differ by 2x150 deg give a chord of 2*sin(30 deg)).
      2. It indexed by a raw `bp_index - bp_start`, ignoring loop/skip deltas, so on a
         skip-bearing helix the FORWARD bead was half a rise out too.

    The oracle is the STRAIGHT geometric layer — `nucleotide_positions_arrays` — NOT
    `_geometry_for_design`.  That distinction is load-bearing and was got wrong when this
    test was first written: the served geometry carries deformation and cluster
    transforms, which this function deliberately does not apply (its `_extended` helpers
    say so explicitly), so on a clustered design like 6hb_test the served positions differ
    by up to 2.0 nm for entirely legitimate reasons.  Comparing against them would assert
    a bug that isn't there and hide the two that were.
    """
    from pathlib import Path

    from backend.core.geometry import nucleotide_positions_arrays
    from backend.core.models import Design
    from backend.physics.oxdna_interface import (
        _compute_nuc_geometry,
        _compute_nuc_geometry_copy,
    )

    checked = copies_checked = 0
    for stem in ("6hb_test", "Con4", "U6hb"):        # U6hb carries 72 loop/skip sites
        design = Design.model_validate_json(Path(f"Examples/{stem}.nadoc").read_text())
        for helix in design.helices:
            arrs = nucleotide_positions_arrays(helix)
            # Group by (bp, direction): a LOOP puts several nucleotides on one bp_index,
            # and the bare 3-tuple key can only mean the first of them.
            rows: dict[tuple[int, str], list[int]] = {}
            for i, bp in enumerate(arrs["bp_indices"]):
                d = "FORWARD" if arrs["directions"][i] == 0 else "REVERSE"
                rows.setdefault((int(bp), d), []).append(i)

            for (bp, d), idxs in rows.items():
                got = _compute_nuc_geometry(design, helix.id, bp, d)
                if got is None:
                    continue
                checked += 1
                assert np.allclose(
                    got["backbone_position"], arrs["positions"][idxs[0]], atol=1e-12), (
                    f"{stem} {helix.id}:{bp}:{d} backbone")
                assert np.allclose(
                    got["base_normal"], arrs["base_normals"][idxs[0]], atol=1e-12), (
                    f"{stem} {helix.id}:{bp}:{d} base_normal")

                # Every loop copy must come back at its own axial offset, NOT copy 0's.
                for k, i in enumerate(idxs):
                    ck = _compute_nuc_geometry_copy(design, helix.id, bp, d, k, len(idxs))
                    copies_checked += 1
                    assert np.allclose(
                        ck["backbone_position"], arrs["positions"][i], atol=1e-12), (
                        f"{stem} {helix.id}:{bp}:{d} copy {k}")
    assert checked > 1000, "fixtures must actually exercise the fallback"
    assert copies_checked > checked, "U6hb must contribute at least one loop copy"


# ── lattice twist must close over the crossover period ────────────────────────


def test_lattice_twists_are_commensurate_with_their_crossover_periods():
    """A lattice's twist has to be a whole number of turns over its crossover period,
    or the geometry does not REPEAT along the helix — it drifts.

    Honeycomb places crossovers on a 21-bp cycle (offsets 0,6,7,13,14,20) = 2 turns at
    10.5 bp/turn; square on a 32-bp cycle = 3 turns.  Honeycomb used the ROUNDED physical
    constant (34.3, i.e. 360/10.4956) until 2026-08-06, leaving +0.0143 deg/bp.  That is
    tiny per bp and unbounded in aggregate: crossover strain ramped +0.657 oxDNA units per
    1000 bp, so two designs on the SAME lattice disagreed purely because one was longer
    (one crossover class ran 1.069 -> 1.841 units over 1218 bp).  TD-29.

    The physical B-DNA constant is deliberately NOT the lattice value and stays 34.3.
    """
    from backend.core.constants import (
        HONEYCOMB_TWIST_PER_BP_DEG,
        HONEYCOMB_TWIST_PER_BP_RAD,
        SQUARE_TWIST_PER_BP_DEG,
    )

    assert 21 * HONEYCOMB_TWIST_PER_BP_DEG == pytest.approx(720.0, abs=1e-9)
    assert 32 * SQUARE_TWIST_PER_BP_DEG == pytest.approx(1080.0, abs=1e-9)
    assert 21 * HONEYCOMB_TWIST_PER_BP_RAD == pytest.approx(4 * math.pi, abs=1e-12)
    # And the lattice value is NOT the rounded physical one — that is the whole point.
    assert HONEYCOMB_TWIST_PER_BP_DEG != BDNA_TWIST_PER_BP_DEG
    assert HONEYCOMB_TWIST_PER_BP_DEG == pytest.approx(34.285714, abs=1e-6)


def test_honeycomb_crossover_geometry_does_not_drift_along_a_helix():
    """The invariance the commensurate twist buys: a nucleotide's azimuth about its own
    helix axis must be IDENTICAL every 21 bp, not merely close.

    With the rounded twist this drifted 0.3 deg per repeat and accumulated without bound,
    which is what made crossover strain depend on how far along the helix you were.
    """
    from backend.core.geometry import nucleotide_positions_arrays
    from backend.core.models import Helix, Vec3
    from backend.core.constants import HONEYCOMB_TWIST_PER_BP_RAD

    helix = Helix(
        id="h_drift",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=210 * BDNA_RISE_PER_BP),
        phase_offset=0.37,
        twist_per_bp_rad=HONEYCOMB_TWIST_PER_BP_RAD,
        length_bp=210,
        bp_start=0,
        direction=Direction.FORWARD,
    )
    arrs = nucleotide_positions_arrays(helix)
    pos = np.asarray(arrs["positions"])
    az = np.degrees(np.arctan2(pos[0::2, 1], pos[0::2, 0]))      # FORWARD strand
    for k in range(0, 210 - 21, 21):
        d = (az[k + 21] - az[k] + 540.0) % 360.0 - 180.0
        assert abs(d) < 1e-9, f"azimuth drifted {d:+.6f} deg over the 21-bp repeat at bp {k}"


def test_the_atomistic_representation_is_periodic_over_the_21bp_repeat_too():
    """The commensurate honeycomb twist must reach the ALL-ATOM build, not just the beads.

    It does, and by construction rather than by coincidence: both representations take
    their phase from `deformation.effective_helix_for_geometry`, which re-derives it from
    `grid_pos` via `_normalize_helix_for_grid` — so the STORED `twist_per_bp_rad` in a
    saved .nadoc (still 34.3 in every existing file) is ignored for lattice helices and
    the lattice value is used instead.  This pins that, because a future change that made
    the atomistic path read the stored value would silently reintroduce the drift in the
    representation people actually export to MD (TD-29).

    Crossover and domain-end nucleotides are excluded: the build deliberately relocates
    them (junction bridging / terminus handling), so they are not expected to reproduce
    the pure stamp.  Measured on this fixture, every single deviation was one of those.
    """
    import math
    from pathlib import Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.models import Design

    path = Path("workspace/6hbx100_noT.nadoc")
    if not path.exists():
        pytest.skip("workspace/6hbx100_noT.nadoc not present")
    design = Design.model_validate_json(path.read_text())
    helix = design.helices[0]

    relocated = {x.half_a.index for x in design.crossovers if x.half_a.helix_id == helix.id}
    relocated |= {x.half_b.index for x in design.crossovers if x.half_b.helix_id == helix.id}
    for strand in design.strands:
        for dom in strand.domains:
            if dom.helix_id == helix.id:
                relocated |= {dom.start_bp, dom.end_bp}

    model = build_atomistic_model(design, close_backbone=False)
    p_of, res_of = {}, {}
    for atom in model.atoms:
        if (atom.name == "P" and atom.helix_id == helix.id
                and str(atom.direction) == "FORWARD"):
            p_of[atom.bp_index] = (atom.x, atom.y, atom.z)
            res_of[atom.bp_index] = atom.residue

    def azimuth(bp):
        x, y, _ = p_of[bp]
        return math.degrees(math.atan2(y - helix.axis_start.y, x - helix.axis_start.x))

    checked = 0
    for bp in sorted(p_of):
        if bp + 21 not in p_of:
            continue
        if {bp, bp + 21} & relocated:
            continue
        # Compare like with like: the measured templates are per-residue, so two
        # different bases legitimately place their phosphorus a little differently.
        if res_of[bp] != res_of[bp + 21]:
            continue
        checked += 1
        d = (azimuth(bp + 21) - azimuth(bp) + 540.0) % 360.0 - 180.0
        assert abs(d) < 1e-6, f"atomistic azimuth drifted {d:+.6f} deg at bp {bp}"
    assert checked >= 10, f"fixture exercised too few repeats ({checked})"

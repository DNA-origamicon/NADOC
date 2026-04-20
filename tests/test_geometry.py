"""
Tests for backend/core/geometry.py.

All expected values are derived from oxDNA literature and standard B-DNA
crystallographic parameters:
  rise          = 0.334 nm/bp
  twist         = 34.3 deg/bp  →  0.598430… rad/bp
  radius        = 1.0 nm
  minor groove  = 120°  (FORWARD and REVERSE are NOT antipodal)

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
)
from backend.core.geometry import NucleotidePosition, nucleotide_positions, helix_axis_point
from backend.core.models import Direction, Helix, Vec3


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
    With the major/minor groove geometry, REVERSE sits at 120° from FORWARD,
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
    BDNA_MINOR_GROOVE_ANGLE_DEG (120°).
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
    2 × HELIX_RADIUS × sin(MINOR_GROOVE_ANGLE / 2) ≈ 1.732 nm.
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
    With 120° groove angle: backbone pair distance = 2 × sin(60°) ≈ 1.732 nm.
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
    op = DeformationOp(
        type="bend",
        plane_a_bp=plane_a,
        plane_b_bp=plane_b,
        affected_helix_ids=helices_crossing_planes(design, plane_a, plane_b),
        params=BendParams(angle_deg=angle_deg, direction_deg=0.0),
    )
    return design.model_copy(update={"deformations": [op]}, deep=True)


def _collect_positions(design):
    from backend.core.deformation import deformed_nucleotide_positions
    return {
        (nuc.helix_id, nuc.bp_index, nuc.direction): nuc.position
        for h in design.helices
        for nuc in deformed_nucleotide_positions(h, design)
    }



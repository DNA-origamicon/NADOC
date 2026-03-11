"""
Tests for backend.core.crossover_positions.

Validates that valid_crossover_positions() correctly identifies bp index pairs
within geometric reach and returns nothing for helices that are too far apart.
"""

from __future__ import annotations

import pytest

from backend.core.constants import BDNA_RISE_PER_BP, HONEYCOMB_HELIX_SPACING
from backend.core.crossover_positions import (
    MAX_CROSSOVER_REACH_NM,
    CrossoverCandidate,
    valid_crossover_positions,
)
from backend.core.models import Helix, Vec3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _helix_z(offset_x: float = 0.0, offset_y: float = 0.0,
             length_bp: int = 42, phase_offset: float = 0.0) -> Helix:
    """Helix along +Z at (offset_x, offset_y) in XY."""
    return Helix(
        id=f"h_{offset_x}_{offset_y}",
        axis_start=Vec3(x=offset_x, y=offset_y, z=0.0),
        axis_end=Vec3(x=offset_x, y=offset_y, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=phase_offset,
        length_bp=length_bp,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_adjacent_helices_have_candidates():
    """Two helices at honeycomb spacing (2.6 nm) should have valid positions."""
    ha = _helix_z(0.0, 0.0)
    hb = _helix_z(HONEYCOMB_HELIX_SPACING, 0.0)
    candidates = valid_crossover_positions(ha, hb)
    assert len(candidates) > 0, "Expected valid crossover candidates for adjacent helices"


def test_distant_helices_have_no_candidates():
    """Helices 20 nm apart should have no valid crossover positions."""
    ha = _helix_z(0.0, 0.0)
    hb = _helix_z(20.0, 0.0)
    candidates = valid_crossover_positions(ha, hb)
    assert candidates == [], "Expected no candidates for widely separated helices"


def test_all_distances_within_reach():
    """Every returned candidate must have distance ≤ MAX_CROSSOVER_REACH_NM."""
    ha = _helix_z(0.0, 0.0)
    hb = _helix_z(HONEYCOMB_HELIX_SPACING, 0.0)
    candidates = valid_crossover_positions(ha, hb)
    for c in candidates:
        assert c.distance_nm <= MAX_CROSSOVER_REACH_NM, (
            f"Candidate bp_a={c.bp_a}, bp_b={c.bp_b} has distance {c.distance_nm:.4f} nm "
            f"> MAX_CROSSOVER_REACH_NM={MAX_CROSSOVER_REACH_NM}"
        )


def test_pure_function_does_not_modify_helices():
    """valid_crossover_positions must not modify the input Helix objects."""
    ha = _helix_z(0.0, 0.0, length_bp=10)
    hb = _helix_z(HONEYCOMB_HELIX_SPACING, 0.0, length_bp=10)
    ha_id_before = ha.id
    hb_length_before = hb.length_bp
    valid_crossover_positions(ha, hb)
    assert ha.id == ha_id_before
    assert hb.length_bp == hb_length_before


def test_returns_crossover_candidates():
    """Result items are CrossoverCandidate instances with correct fields."""
    ha = _helix_z(0.0, 0.0, length_bp=15)
    hb = _helix_z(HONEYCOMB_HELIX_SPACING, 0.0, length_bp=15)
    candidates = valid_crossover_positions(ha, hb)
    for c in candidates:
        assert isinstance(c, CrossoverCandidate)
        assert 0 <= c.bp_a < ha.length_bp
        assert 0 <= c.bp_b < hb.length_bp
        assert c.distance_nm >= 0.0


def test_same_helix_positions_are_zero_distance():
    """The same helix vs itself should have candidates at every bp (distance ≈ 0)."""
    ha = _helix_z(0.0, 0.0, length_bp=5)
    candidates = valid_crossover_positions(ha, ha)
    # Every bp_a == bp_b should appear (FORWARD vs FORWARD is 0 distance)
    self_pairs = {(c.bp_a, c.bp_b) for c in candidates}
    for bp in range(ha.length_bp):
        assert (bp, bp) in self_pairs, f"Expected self-pair at bp {bp}"


# ── Direction field tests (DTP-4) ──────────────────────────────────────────────

def test_candidates_have_direction_fields():
    """Every CrossoverCandidate must expose direction_a and direction_b."""
    from backend.core.models import Direction
    ha = _helix_z(0.0, 0.0, length_bp=15)
    hb = _helix_z(HONEYCOMB_HELIX_SPACING, 0.0, length_bp=15)
    candidates = valid_crossover_positions(ha, hb)
    assert len(candidates) > 0
    for c in candidates:
        assert isinstance(c.direction_a, Direction)
        assert isinstance(c.direction_b, Direction)
        assert c.direction_a in (Direction.FORWARD, Direction.REVERSE)
        assert c.direction_b in (Direction.FORWARD, Direction.REVERSE)


def test_direction_pair_minimises_distance():
    """The recorded direction pair must achieve the minimum distance at that bp pair.

    For each candidate we verify that no other direction combination at the same
    (bp_a, bp_b) pair produces a *strictly smaller* distance.
    """
    from backend.core.geometry import nucleotide_positions
    from backend.core.models import Direction
    import numpy as np

    ha = _helix_z(0.0, 0.0, length_bp=10)
    hb = _helix_z(HONEYCOMB_HELIX_SPACING, 0.0, length_bp=10)
    candidates = valid_crossover_positions(ha, hb)

    nucs_a = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(ha)}
    nucs_b = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(hb)}
    directions = [Direction.FORWARD, Direction.REVERSE]

    for c in candidates:
        recorded_dist = c.distance_nm
        for da in directions:
            pa = nucs_a.get((c.bp_a, da))
            if pa is None:
                continue
            for db in directions:
                pb = nucs_b.get((c.bp_b, db))
                if pb is None:
                    continue
                d = float(np.linalg.norm(pa - pb))
                # recorded_dist is rounded to 6 decimal places (±5e-7); allow that slack.
                assert d >= recorded_dist - 1e-5, (
                    f"Candidate bp_a={c.bp_a} bp_b={c.bp_b} has recorded dist "
                    f"{recorded_dist:.6f} but dir ({da.value},{db.value}) gives {d:.6f}"
                )


def test_direction_fields_are_consistent_with_distance():
    """The distance stored on the candidate matches the distance between the
    direction_a backbone bead on helix_a and the direction_b bead on helix_b."""
    from backend.core.geometry import nucleotide_positions
    import numpy as np

    ha = _helix_z(0.0, 0.0, length_bp=10)
    hb = _helix_z(HONEYCOMB_HELIX_SPACING, 0.0, length_bp=10)
    candidates = valid_crossover_positions(ha, hb)

    nucs_a = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(ha)}
    nucs_b = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(hb)}

    for c in candidates:
        pa = nucs_a[(c.bp_a, c.direction_a)]
        pb = nucs_b[(c.bp_b, c.direction_b)]
        actual_dist = float(np.linalg.norm(pa - pb))
        assert abs(actual_dist - c.distance_nm) < 1e-4, (
            f"Stored distance {c.distance_nm:.6f} doesn't match recomputed "
            f"{actual_dist:.6f} for bp_a={c.bp_a}, bp_b={c.bp_b}"
        )

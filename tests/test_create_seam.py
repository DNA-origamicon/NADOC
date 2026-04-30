"""Golden-file regression test for the Create Seam Holliday-junction layout.

Reference design: tests/fixtures/10-6-10hb_seamed.nadoc
  — a 10-6-10 honeycomb dumbbell (10 helices, bp 0-167) with the seam already
    applied by the frontend Create Seam handler.

Expected crossover layout (6 Holliday junctions = 12 crossovers):

  Pair                 Type            Interval     HJ bps
  ─────────────────────────────────────────────────────────
  h_0_5 ↔ h_1_5       outer↔outer     [0,  41]     18,19
  h_0_5 ↔ h_1_5       outer↔outer     [126,167]    144,145
  h_1_4 ↔ h_1_3       bridge          [0,  41]     22,23
  h_1_4 ↔ h_1_3       bridge          [126,167]    148,149
  h_1_2 ↔ h_1_1       core↔core       [0, 167]     85,86
  h_0_1 ↔ h_0_2       core↔core       [0, 167]     88,89

  Rails (no crossovers): h_0_4 (outer), h_0_3 (core)

If any of these positions change the Create Seam algorithm has regressed.
"""

from __future__ import annotations

import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Expected crossovers as frozenset of canonical (helix_a, strand_a, bp, helix_b, strand_b) tuples.
# Canonical: helix_a < helix_b lexicographically so order doesn't matter.
# ---------------------------------------------------------------------------

def _canon(ha, sa, bp, hb, sb):
    if ha > hb:
        ha, sa, hb, sb = hb, sb, ha, sa
    return (ha, sa, bp, hb, sb)


EXPECTED_CROSSOVERS = frozenset([
    # outer↔outer left arm
    _canon("h_XY_0_5", "REVERSE", 18,  "h_XY_1_5", "FORWARD"),
    _canon("h_XY_0_5", "REVERSE", 19,  "h_XY_1_5", "FORWARD"),
    # outer↔outer right arm
    _canon("h_XY_0_5", "REVERSE", 144, "h_XY_1_5", "FORWARD"),
    _canon("h_XY_0_5", "REVERSE", 145, "h_XY_1_5", "FORWARD"),
    # bridge left arm
    _canon("h_XY_1_4", "REVERSE", 22,  "h_XY_1_3", "FORWARD"),
    _canon("h_XY_1_4", "REVERSE", 23,  "h_XY_1_3", "FORWARD"),
    # bridge right arm
    _canon("h_XY_1_4", "REVERSE", 148, "h_XY_1_3", "FORWARD"),
    _canon("h_XY_1_4", "REVERSE", 149, "h_XY_1_3", "FORWARD"),
    # core pair 1
    _canon("h_XY_1_2", "REVERSE", 85,  "h_XY_1_1", "FORWARD"),
    _canon("h_XY_1_2", "REVERSE", 86,  "h_XY_1_1", "FORWARD"),
    # core pair 2
    _canon("h_XY_0_1", "REVERSE", 88,  "h_XY_0_2", "FORWARD"),
    _canon("h_XY_0_1", "REVERSE", 89,  "h_XY_0_2", "FORWARD"),
])

EXPECTED_RAILS = {"h_XY_0_4", "h_XY_0_3"}


# ---------------------------------------------------------------------------

def _load_seamed():
    from backend.core.models import Design
    return Design.model_validate_json(
        (FIXTURES / "10-6-10hb_seamed.nadoc").read_text()
    )


def _actual_crossovers(design):
    result = set()
    for xo in design.crossovers:
        result.add(_canon(
            xo.half_a.helix_id, xo.half_a.strand, xo.half_a.index,
            xo.half_b.helix_id, xo.half_b.strand,
        ))
    return frozenset(result)


def _helices_with_crossovers(design):
    ids = set()
    for xo in design.crossovers:
        ids.add(xo.half_a.helix_id)
        ids.add(xo.half_b.helix_id)
    return ids


# ---------------------------------------------------------------------------

class TestCreateSeamReferenceLayout:

    def test_crossover_count(self):
        """6 Holliday junctions = 12 crossovers total."""
        d = _load_seamed()
        assert len(d.crossovers) == 12, (
            f"Expected 12 crossovers (6 HJs), got {len(d.crossovers)}"
        )

    def test_crossover_positions(self):
        """Every crossover must be at the exact expected bp and helix pair."""
        d = _load_seamed()
        actual = _actual_crossovers(d)
        missing = EXPECTED_CROSSOVERS - actual
        extra   = actual - EXPECTED_CROSSOVERS
        assert not missing and not extra, (
            f"Crossover mismatch.\n  Missing: {missing}\n  Extra:   {extra}"
        )

    def test_rails_have_no_crossovers(self):
        """h_0_4 (outer rail) and h_0_3 (core rail) must carry no crossovers."""
        d = _load_seamed()
        active = _helices_with_crossovers(d)
        unexpected = EXPECTED_RAILS & active
        assert not unexpected, (
            f"Rail helices should have no crossovers but do: {unexpected}"
        )

    def test_hj_pairs(self):
        """Verify the six distinct helix pairs that carry Holliday junctions."""
        expected_pairs = {
            ("h_XY_0_5", "h_XY_1_5"),   # outer↔outer (both arms)
            ("h_XY_1_3", "h_XY_1_4"),   # bridge (both arms)
            ("h_XY_1_1", "h_XY_1_2"),   # core pair 1
            ("h_XY_0_1", "h_XY_0_2"),   # core pair 2
        }
        d = _load_seamed()
        actual_pairs = set()
        for xo in d.crossovers:
            pair = tuple(sorted([xo.half_a.helix_id, xo.half_b.helix_id]))
            actual_pairs.add(pair)
        assert actual_pairs == expected_pairs

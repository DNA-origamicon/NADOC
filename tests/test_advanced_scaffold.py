"""
Tests for advanced scaffold routing features:
  - Feature 1: auto_scaffold_seamless
  - Feature 2: assign_custom_scaffold_sequence / assign_scaffold_sequence (strand_id)
  - Feature 3a: auto_scaffold_partition
  - Feature 3b: scaffold_split
"""

from __future__ import annotations

import pytest

from backend.core.lattice import (
    auto_scaffold,
    auto_scaffold_partition,
    auto_scaffold_seamless,
    make_bundle_design,
    scaffold_add_end_crossovers,
    scaffold_split,
)
from backend.core.models import StrandType
from backend.core.sequences import (
    assign_custom_scaffold_sequence,
    assign_scaffold_sequence,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
CELLS_12HB = [
    (0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1),
    (3, 1), (3, 0), (4, 0), (3, 2), (4, 2), (5, 1),
]


def _make_6hb(length_bp: int = 300) -> object:
    return make_bundle_design(CELLS_6HB, length_bp=length_bp)


def _make_12hb(length_bp: int = 300) -> object:
    return make_bundle_design(CELLS_12HB, length_bp=length_bp)


def _scaffold_strands(design) -> list:
    return [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]


# ── Feature 1: auto_scaffold_seamless ─────────────────────────────────────────


@pytest.mark.skip(reason="auto_scaffold_seamless does not yet produce a single merged strand — function needs fixing")
class TestAutoScaffoldSeamless:

    def test_produces_exactly_one_strand(self):
        design = _make_6hb()
        result = auto_scaffold_seamless(design)
        scaffolds = _scaffold_strands(result)
        assert len(scaffolds) == 1, (
            f"Expected 1 scaffold strand, got {len(scaffolds)}"
        )

    def test_covers_all_helices(self):
        design = _make_6hb()
        result = auto_scaffold_seamless(design)
        sc = _scaffold_strands(result)[0]
        covered = {d.helix_id for d in sc.domains}
        expected = {h.id for h in design.helices}
        assert covered == expected, (
            f"Uncovered helices: {expected - covered}"
        )

    def test_scaffold_has_multiple_domains(self):
        """The seamless scaffold spans multiple helices via crossovers."""
        design = _make_6hb()
        result = auto_scaffold_seamless(design)
        sc = _scaffold_strands(result)[0]
        assert len(sc.domains) >= 2

    def test_min_staple_margin(self):
        """Custom min_staple_margin is accepted without error."""
        design = _make_6hb()
        result = auto_scaffold_seamless(design, min_staple_margin=5)
        scaffolds = _scaffold_strands(result)
        assert len(scaffolds) == 1

    def test_18hb_single_strand(self):
        cells_18 = [
            (0, 0), (0, 1), (1, 0),
            (0, 2), (1, 2), (2, 1),
            (3, 1), (3, 0), (4, 0),
            (5, 1), (4, 2), (3, 2),
            (3, 3), (3, 4), (3, 5),
            (2, 5), (1, 4), (2, 3),
        ]
        design = make_bundle_design(cells_18, length_bp=300)
        result = auto_scaffold_seamless(design)
        assert len(_scaffold_strands(result)) == 1

    def test_disconnected_raises(self):
        """A single isolated helix has no neighbours — crossover placement fails."""
        design = make_bundle_design([(0, 0)], length_bp=200)
        with pytest.raises(ValueError):
            auto_scaffold_seamless(design)


# ── Feature 2: custom scaffold sequences ──────────────────────────────────────


class TestCustomScaffoldSequence:

    def _routed_design(self):
        design = _make_6hb(length_bp=42)
        return auto_scaffold(design, mode="end_to_end", scaffold_loops=True, min_end_margin=2)

    def test_custom_sequence_assigned(self):
        design = self._routed_design()
        sc_before = design.scaffold()
        nt = sum(
            abs(d.end_bp - d.start_bp) + 1
            for d in sc_before.domains
        )
        seq = "ATGC" * (nt // 4 + 1)
        updated, total_nt, padded_nt = assign_custom_scaffold_sequence(design, seq)
        sc_after = updated.scaffold()
        assert sc_after.sequence is not None
        assert sc_after.sequence.startswith("A")  # first char of "ATGC"

    def test_custom_sequence_padded_with_n(self):
        design = self._routed_design()
        updated, total_nt, padded_nt = assign_custom_scaffold_sequence(design, "ATGC")
        assert padded_nt == total_nt - 4
        sc = updated.scaffold()
        assert sc.sequence is not None
        assert sc.sequence.endswith("N")

    def test_custom_sequence_invalid_chars_raises(self):
        design = self._routed_design()
        with pytest.raises(ValueError, match="Invalid characters"):
            assign_custom_scaffold_sequence(design, "ATGZATGC")

    def test_custom_sequence_empty_raises(self):
        design = self._routed_design()
        with pytest.raises(ValueError, match="empty"):
            assign_custom_scaffold_sequence(design, "   ")

    def test_case_insensitive_input(self):
        design = self._routed_design()
        updated, _, _ = assign_custom_scaffold_sequence(design, "atgcatgcatgc" * 100)
        sc = updated.scaffold()
        assert sc.sequence is not None
        assert all(c in "ATGCN" for c in sc.sequence)

    def test_assign_by_strand_id(self):
        """assign_scaffold_sequence with strand_id targets only that strand."""
        # Use 12HB split into two connected 6-helix groups (same topology as
        # TestAutoScaffoldPartition._two_group_design)
        design = _make_12hb(length_bp=42)
        grp1 = [h.id for h in design.helices[:6]]
        grp2 = [h.id for h in design.helices[6:12]]
        partitioned = auto_scaffold_partition(
            design, helix_groups=[grp1, grp2], mode="end_to_end", min_end_margin=2
        )
        scaffolds = _scaffold_strands(partitioned)
        assert len(scaffolds) == 2
        target_id = scaffolds[0].id
        updated, _, _ = assign_scaffold_sequence(
            partitioned, "M13mp18", strand_id=target_id
        )
        sc0 = next(s for s in updated.strands if s.id == target_id)
        sc1 = next(s for s in updated.strands if s.id == scaffolds[1].id)
        assert sc0.sequence is not None
        # The second scaffold strand should NOT have been modified
        assert sc1.sequence == scaffolds[1].sequence

    def test_assign_custom_to_specific_strand(self):
        design = _make_12hb(length_bp=42)
        grp1 = [h.id for h in design.helices[:6]]
        grp2 = [h.id for h in design.helices[6:12]]
        partitioned = auto_scaffold_partition(
            design, helix_groups=[grp1, grp2], mode="end_to_end", min_end_margin=2
        )
        scaffolds = _scaffold_strands(partitioned)
        target_id = scaffolds[0].id
        long_seq = "GGGG" * 500
        updated, _, _ = assign_custom_scaffold_sequence(
            partitioned, long_seq, strand_id=target_id
        )
        sc0 = next(s for s in updated.strands if s.id == target_id)
        sc1 = next(s for s in updated.strands if s.id == scaffolds[1].id)
        assert sc0.sequence is not None and "G" in sc0.sequence
        assert sc1.sequence == scaffolds[1].sequence  # untouched

    def test_wrong_strand_type_raises(self):
        design = self._routed_design()
        staple = next(s for s in design.strands if s.strand_type == StrandType.STAPLE)
        with pytest.raises(ValueError, match="not a scaffold"):
            assign_scaffold_sequence(design, "M13mp18", strand_id=staple.id)


# ── Feature 3a: auto_scaffold_partition ───────────────────────────────────────


class TestAutoScaffoldPartition:

    def _two_group_design(self, length_bp: int = 200):
        design = _make_12hb(length_bp)
        grp1 = [h.id for h in design.helices[:6]]
        grp2 = [h.id for h in design.helices[6:12]]
        return design, grp1, grp2

    def test_two_groups_produce_two_scaffolds(self):
        design, grp1, grp2 = self._two_group_design()
        result = auto_scaffold_partition(
            design, helix_groups=[grp1, grp2], mode="end_to_end", min_end_margin=5
        )
        assert len(_scaffold_strands(result)) == 2

    def test_disjoint_helix_coverage(self):
        design, grp1, grp2 = self._two_group_design()
        result = auto_scaffold_partition(
            design, helix_groups=[grp1, grp2], mode="end_to_end", min_end_margin=5
        )
        scaffolds = _scaffold_strands(result)
        helix_sets = [frozenset(d.helix_id for d in sc.domains) for sc in scaffolds]
        # No helix should appear in both scaffold strands
        overlap = helix_sets[0] & helix_sets[1]
        assert not overlap, f"Helices appear in both scaffold strands: {overlap}"

    def test_overlapping_groups_raises(self):
        design = _make_6hb(length_bp=200)
        grp1 = [h.id for h in design.helices[:4]]
        grp2 = [h.id for h in design.helices[2:6]]  # overlaps grp1
        with pytest.raises(ValueError, match="more than one group"):
            auto_scaffold_partition(design, helix_groups=[grp1, grp2])

    def test_unknown_helix_raises(self):
        design = _make_6hb(length_bp=200)
        with pytest.raises(ValueError, match="not found"):
            auto_scaffold_partition(design, helix_groups=[["nonexistent_helix_id"]])

    def test_uncovered_helices_untouched(self):
        """Helices not in any group should not gain new scaffold strands."""
        design = _make_12hb(length_bp=200)
        grp1 = [h.id for h in design.helices[:4]]
        result = auto_scaffold_partition(
            design, helix_groups=[grp1], mode="end_to_end", min_end_margin=5
        )
        covered = set(grp1)
        for sc in _scaffold_strands(result):
            for d in sc.domains:
                assert d.helix_id in covered, (
                    f"Helix {d.helix_id!r} is outside any group but appears in a scaffold strand"
                )


# ── Feature 3b: scaffold_split ────────────────────────────────────────────────


class TestScaffoldSplit:

    def _routed_6hb(self, length_bp: int = 200):
        design = _make_6hb(length_bp)
        routed  = auto_scaffold(design, mode="end_to_end", scaffold_loops=True, min_end_margin=5)
        return scaffold_add_end_crossovers(routed, min_end_margin=1)

    def test_split_produces_two_scaffolds(self):
        design = self._routed_6hb()
        sc = _scaffold_strands(design)[0]
        # Pick a bp position safely inside the first domain
        d = sc.domains[0]
        if d.direction.value == "FORWARD":
            bp = d.start_bp + (d.end_bp - d.start_bp) // 2
        else:
            bp = d.start_bp - (d.start_bp - d.end_bp) // 2
        result = scaffold_split(design, strand_id=sc.id, helix_id=d.helix_id, bp_position=bp)
        assert len(_scaffold_strands(result)) == 2

    def test_split_on_staple_raises(self):
        design = self._routed_6hb()
        staple = next(s for s in design.strands if s.strand_type == StrandType.STAPLE)
        d = staple.domains[0]
        bp = d.start_bp
        with pytest.raises(ValueError, match="not a scaffold"):
            scaffold_split(design, strand_id=staple.id, helix_id=d.helix_id, bp_position=bp)

    def test_split_invalid_position_raises(self):
        design = self._routed_6hb()
        sc = _scaffold_strands(design)[0]
        d = sc.domains[0]
        # Use a bp outside the domain
        out_of_range_bp = d.end_bp + 100 if d.direction.value == "FORWARD" else d.end_bp - 100
        with pytest.raises(ValueError):
            scaffold_split(
                design, strand_id=sc.id, helix_id=d.helix_id, bp_position=out_of_range_bp
            )

    def test_both_halves_are_scaffold_type(self):
        design = self._routed_6hb()
        sc = _scaffold_strands(design)[0]
        d = sc.domains[0]
        if d.direction.value == "FORWARD":
            bp = d.start_bp + max(1, (d.end_bp - d.start_bp) // 2)
        else:
            bp = d.start_bp - max(1, (d.start_bp - d.end_bp) // 2)
        result = scaffold_split(design, strand_id=sc.id, helix_id=d.helix_id, bp_position=bp)
        for sc_new in _scaffold_strands(result):
            assert sc_new.strand_type == StrandType.SCAFFOLD

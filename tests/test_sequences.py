"""
Tests for backend/core/sequences.py — pure helpers + scaffold/staple
sequence assignment orchestrators.

Refactor 07-B: lift coverage of `backend/core/sequences.py` from ~21 % to
≥60 % by exercising the deterministic helpers and the public assignment
entry points. This file is additive — production code is not modified.
"""

from __future__ import annotations

import pytest

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design,
    Direction,
    Domain,
    Helix,
    LatticeType,
    LoopSkip,
    OverhangSpec,
    Strand,
    StrandType,
    Vec3,
)
from backend.core.sequences import (
    M13MP18_SEQUENCE,
    _build_loop_skip_map,
    _resolve_scaffold_strand,
    _strand_nt_with_skips,
    assign_custom_scaffold_sequence,
    assign_scaffold_sequence,
    assign_staple_sequences,
    build_scaffold_base_map,
    build_scaffold_index_map,
    complement_base,
    domain_bp_range,
)
from tests.conftest import make_minimal_design


# ── Shared builders ───────────────────────────────────────────────────────────


def _design_with_loop_skips(modifications: list[tuple[int, int]]) -> Design:
    """make_minimal_design() with loop/skip modifications applied to h0.

    `modifications` is a list of (bp_index, delta) tuples.
    """
    d = make_minimal_design()
    h = d.helices[0]
    new_h = h.model_copy(update={
        "loop_skips": [LoopSkip(bp_index=bp, delta=delta)
                       for bp, delta in modifications]
    })
    return d.model_copy(update={"helices": [new_h] + list(d.helices[1:])})


# ── TestComplementBase ────────────────────────────────────────────────────────


class TestComplementBase:
    def test_a_complement(self):
        assert complement_base("A") == "T"

    def test_t_complement(self):
        assert complement_base("T") == "A"

    def test_g_complement(self):
        assert complement_base("G") == "C"

    def test_c_complement(self):
        assert complement_base("C") == "G"

    def test_n_complement(self):
        assert complement_base("N") == "N"

    def test_lowercase_input_normalised(self):
        # Implementation upper-cases before lookup.
        assert complement_base("a") == "T"
        assert complement_base("g") == "C"

    def test_invalid_returns_n(self):
        # Falls through to default 'N' on unknown bases.
        assert complement_base("X") == "N"
        assert complement_base("") == "N"


# ── TestDomainBpRange ─────────────────────────────────────────────────────────


class TestDomainBpRange:
    def test_forward_yields_ascending_inclusive(self):
        d = Domain(helix_id="h0", start_bp=0, end_bp=4,
                   direction=Direction.FORWARD)
        assert list(domain_bp_range(d)) == [0, 1, 2, 3, 4]

    def test_reverse_yields_descending_inclusive(self):
        d = Domain(helix_id="h0", start_bp=4, end_bp=0,
                   direction=Direction.REVERSE)
        assert list(domain_bp_range(d)) == [4, 3, 2, 1, 0]

    def test_single_bp_domain(self):
        d = Domain(helix_id="h0", start_bp=3, end_bp=3,
                   direction=Direction.FORWARD)
        assert list(domain_bp_range(d)) == [3]


# ── TestLoopSkipMap ───────────────────────────────────────────────────────────


class TestLoopSkipMap:
    def test_empty_design_returns_empty_map(self):
        d = make_minimal_design()
        assert _build_loop_skip_map(d) == {}

    def test_single_loop_recorded(self):
        d = _design_with_loop_skips([(7, +1)])
        m = _build_loop_skip_map(d)
        assert m == {("h0", 7): +1}

    def test_mixed_loop_and_skip(self):
        d = _design_with_loop_skips([(3, +1), (10, -1)])
        m = _build_loop_skip_map(d)
        assert m == {("h0", 3): +1, ("h0", 10): -1}


# ── TestStrandNtWithSkips ─────────────────────────────────────────────────────


class TestStrandNtWithSkips:
    def test_no_modifications_matches_naive_count(self):
        d = make_minimal_design(helix_length_bp=20)
        scaf = d.scaffold()
        ls_map: dict[tuple[str, int], int] = {}
        # 20 bp single domain → 20 nt
        assert _strand_nt_with_skips(scaf, ls_map) == 20

    def test_loop_adds_one_extra_nt(self):
        d = _design_with_loop_skips([(5, +1)])
        scaf = d.scaffold()
        ls_map = _build_loop_skip_map(d)
        # default helix_length_bp=42 → 42 + 1 (loop)
        assert _strand_nt_with_skips(scaf, ls_map) == 42 + 1

    def test_skip_drops_one_nt(self):
        d = _design_with_loop_skips([(5, -1)])
        scaf = d.scaffold()
        ls_map = _build_loop_skip_map(d)
        assert _strand_nt_with_skips(scaf, ls_map) == 42 - 1


# ── TestResolveScaffoldStrand ─────────────────────────────────────────────────


class TestResolveScaffoldStrand:
    def test_explicit_strand_id_returns_it(self):
        d = make_minimal_design()
        result = _resolve_scaffold_strand(d, "scaf")
        assert result.id == "scaf"
        assert result.strand_type == StrandType.SCAFFOLD

    def test_none_auto_picks_scaffold(self):
        d = make_minimal_design()
        result = _resolve_scaffold_strand(d, None)
        assert result.id == "scaf"

    def test_unknown_strand_raises(self):
        d = make_minimal_design()
        with pytest.raises(ValueError, match="not found"):
            _resolve_scaffold_strand(d, "does_not_exist")

    def test_non_scaffold_strand_id_raises(self):
        d = make_minimal_design()
        with pytest.raises(ValueError, match="not a scaffold"):
            _resolve_scaffold_strand(d, "stap")

    def test_no_scaffold_raises(self):
        d = make_minimal_design(with_scaffold=False)
        with pytest.raises(ValueError, match="No scaffold"):
            _resolve_scaffold_strand(d, None)


# ── TestBuildScaffoldBaseMap ──────────────────────────────────────────────────


class TestBuildScaffoldBaseMap:
    def test_no_sequence_returns_empty_map(self):
        d = make_minimal_design(helix_length_bp=10)
        # scaffold.sequence is None by default
        assert build_scaffold_base_map(d) == {}

    def test_with_sequence_keys_match_scaffold_path(self):
        d = make_minimal_design(helix_length_bp=10)
        seq = "ATGCATGCAT"
        d2, total_nt, padded = assign_custom_scaffold_sequence(d, seq)
        bmap = build_scaffold_base_map(d2)
        # Single forward domain on h0, bp 0..9 → 10 entries.
        assert len(bmap) == 10
        for bp, expected in enumerate(seq):
            key = ("h0", bp, Direction.FORWARD.value)
            assert key in bmap
            assert bmap[key] == [expected]

    def test_loop_yields_two_bases_at_position(self):
        d = _design_with_loop_skips([(5, +1)])
        # 42-bp helix + 1 loop → 43 nt; pad with our own letters.
        seq = "A" * 5 + "GG" + "A" * 36   # 43 chars total
        d2, _, _ = assign_custom_scaffold_sequence(d, seq)
        bmap = build_scaffold_base_map(d2)
        # Loop position emits 2 bases.
        assert bmap[("h0", 5, Direction.FORWARD.value)] == ["G", "G"]

    def test_skip_position_absent(self):
        d = _design_with_loop_skips([(5, -1)])
        seq = "A" * 41   # 42 - 1 nt
        d2, _, _ = assign_custom_scaffold_sequence(d, seq)
        bmap = build_scaffold_base_map(d2)
        assert ("h0", 5, Direction.FORWARD.value) not in bmap


# ── TestBuildScaffoldIndexMap ─────────────────────────────────────────────────


class TestBuildScaffoldIndexMap:
    def test_no_sequence_returns_empty_list(self):
        d = make_minimal_design()
        assert build_scaffold_index_map(d) == []

    def test_length_matches_scaffold_nt_count(self):
        d = make_minimal_design(helix_length_bp=15)
        d2, _, _ = assign_custom_scaffold_sequence(d, "A" * 15)
        idx = build_scaffold_index_map(d2)
        assert len(idx) == 15
        # First entry is the 5' base of the scaffold.
        assert idx[0] == ("h0", 0, Direction.FORWARD.value)
        assert idx[-1] == ("h0", 14, Direction.FORWARD.value)

    def test_length_with_loop_and_skip(self):
        d = _design_with_loop_skips([(2, +1), (10, -1)])
        # 42 + 1 - 1 = 42 nt
        d2, _, _ = assign_custom_scaffold_sequence(d, "A" * 42)
        idx = build_scaffold_index_map(d2)
        assert len(idx) == 42


# ── TestAssignScaffoldSequence ────────────────────────────────────────────────


class TestAssignScaffoldSequence:
    def test_assigns_m13_to_minimal_design(self):
        d = make_minimal_design(helix_length_bp=42)
        d2, total_nt, padded = assign_scaffold_sequence(d, "M13mp18")
        scaf = d2.scaffold()
        assert scaf is not None
        assert scaf.sequence is not None
        assert len(scaf.sequence) == 42      # matches scaffold nt count
        assert total_nt == 42
        assert padded == 0
        # First 42 bases match the M13 sequence prefix.
        assert scaf.sequence == M13MP18_SEQUENCE[:42]

    def test_unknown_scaffold_name_raises(self):
        d = make_minimal_design()
        with pytest.raises(ValueError, match="Unknown scaffold"):
            assign_scaffold_sequence(d, "no_such_scaffold")

    def test_no_scaffold_raises(self):
        d = make_minimal_design(with_scaffold=False)
        with pytest.raises(ValueError, match="No scaffold"):
            assign_scaffold_sequence(d, "M13mp18")

    def test_pads_with_n_when_design_longer_than_sequence(self):
        # Build a design whose scaffold is longer than M13 (7249 nt).
        # Use 8000 bp on a single helix.
        big_len = 8000
        helices = [
            Helix(
                id="h0",
                axis_start=Vec3(x=0.0, y=0.0, z=0.0),
                axis_end=Vec3(
                    x=0.0, y=0.0, z=big_len * BDNA_RISE_PER_BP
                ),
                length_bp=big_len,
                bp_start=0,
            )
        ]
        strands = [
            Strand(
                id="scaf",
                strand_type=StrandType.SCAFFOLD,
                domains=[Domain(
                    helix_id="h0",
                    start_bp=0,
                    end_bp=big_len - 1,
                    direction=Direction.FORWARD,
                )],
            )
        ]
        d = Design(helices=helices, strands=strands,
                   lattice_type=LatticeType.HONEYCOMB)
        d2, total_nt, padded = assign_scaffold_sequence(d, "M13mp18")
        assert total_nt == big_len
        assert padded == big_len - len(M13MP18_SEQUENCE)
        scaf = d2.scaffold()
        assert scaf.sequence is not None
        assert scaf.sequence.endswith("N" * padded)


# ── TestAssignCustomScaffoldSequence ──────────────────────────────────────────


class TestAssignCustomScaffoldSequence:
    def test_exact_length_applies(self):
        d = make_minimal_design(helix_length_bp=10)
        seq = "ATGCATGCAT"
        d2, total_nt, padded = assign_custom_scaffold_sequence(d, seq)
        assert total_nt == 10
        assert padded == 0
        assert d2.scaffold().sequence == seq

    def test_too_short_pads_with_n(self):
        # Implementation pads excess positions with 'N' rather than raising.
        d = make_minimal_design(helix_length_bp=10)
        seq = "ATG"
        d2, total_nt, padded = assign_custom_scaffold_sequence(d, seq)
        assert total_nt == 10
        assert padded == 7
        assert d2.scaffold().sequence == "ATG" + "N" * 7

    def test_lowercase_input_uppercased(self):
        d = make_minimal_design(helix_length_bp=4)
        d2, _, _ = assign_custom_scaffold_sequence(d, "atgc")
        assert d2.scaffold().sequence == "ATGC"

    def test_whitespace_stripped(self):
        d = make_minimal_design(helix_length_bp=4)
        d2, _, _ = assign_custom_scaffold_sequence(d, " A T G C\n")
        assert d2.scaffold().sequence == "ATGC"

    def test_invalid_chars_raise(self):
        d = make_minimal_design(helix_length_bp=4)
        with pytest.raises(ValueError, match="Invalid characters"):
            assign_custom_scaffold_sequence(d, "ATGZ")

    def test_empty_sequence_raises(self):
        d = make_minimal_design(helix_length_bp=4)
        with pytest.raises(ValueError, match="empty"):
            assign_custom_scaffold_sequence(d, "   \n  ")


# ── TestAssignStapleSequences ─────────────────────────────────────────────────


class TestAssignStapleSequences:
    def test_complements_scaffold_on_overlap(self):
        # Pass 8-C fixed make_minimal_design()'s REVERSE-staple convention to
        # follow `start_bp > end_bp`; the prior bespoke `_design_with_proper_reverse_staple`
        # workaround helper is no longer needed (consolidated 2026-05-10).
        d = make_minimal_design(helix_length_bp=10)
        # Assign a known scaffold sequence first.
        seq = "ATGCATGCAT"
        d2, _, _ = assign_custom_scaffold_sequence(d, seq)
        d3 = assign_staple_sequences(d2)
        stap = next(s for s in d3.strands if s.id == "stap")
        assert stap.sequence is not None
        assert len(stap.sequence) == 10
        # Staple traverses bp 9..0 REVERSE; scaffold is FORWARD bp 0..9.
        # Pairing is antiparallel: staple[k] pairs with scaffold[9-k].
        expected = "".join(complement_base(seq[9 - k]) for k in range(10))
        assert stap.sequence == expected

    def test_no_scaffold_sequence_raises(self):
        d = make_minimal_design(helix_length_bp=10)
        with pytest.raises(ValueError, match="no sequence"):
            assign_staple_sequences(d)

    def test_no_scaffold_raises(self):
        d = make_minimal_design(with_scaffold=False)
        with pytest.raises(ValueError, match="No scaffold"):
            assign_staple_sequences(d)

    def test_overhang_domain_uses_user_sequence(self):
        # Build a design where the staple has a single overhang-domain
        # (overhang_id set) so the overhang branch in assign_staple_sequences
        # is exercised.
        d = make_minimal_design(helix_length_bp=10)
        d2, _, _ = assign_custom_scaffold_sequence(d, "ATGCATGCAT")
        # Replace staple with one whose only domain is an overhang.
        ov = OverhangSpec(
            id="ov_test",
            helix_id="h0",
            strand_id="stap",
            sequence="GGGGG",   # 5 nt, but domain is 10 bp
        )
        new_stap = Strand(
            id="stap",
            strand_type=StrandType.STAPLE,
            domains=[Domain(
                helix_id="h0",
                start_bp=0,
                end_bp=9,
                direction=Direction.REVERSE,
                overhang_id="ov_test",
            )],
        )
        scaf = next(s for s in d2.strands if s.is_scaffold)
        d3 = d2.model_copy(update={
            "strands": [scaf, new_stap],
            "overhangs": [ov],
        })
        d4 = assign_staple_sequences(d3)
        stap = next(s for s in d4.strands if s.id == "stap")
        # Pad with N to domain length.
        assert stap.sequence == "GGGGG" + "N" * 5

    def test_overhang_no_user_sequence_filled_with_n(self):
        d = make_minimal_design(helix_length_bp=10)
        d2, _, _ = assign_custom_scaffold_sequence(d, "ATGCATGCAT")
        ov = OverhangSpec(
            id="ov_blank",
            helix_id="h0",
            strand_id="stap",
            sequence=None,
        )
        new_stap = Strand(
            id="stap",
            strand_type=StrandType.STAPLE,
            domains=[Domain(
                helix_id="h0",
                start_bp=0,
                end_bp=9,
                direction=Direction.REVERSE,
                overhang_id="ov_blank",
            )],
        )
        scaf = next(s for s in d2.strands if s.is_scaffold)
        d3 = d2.model_copy(update={
            "strands": [scaf, new_stap],
            "overhangs": [ov],
        })
        d4 = assign_staple_sequences(d3)
        stap = next(s for s in d4.strands if s.id == "stap")
        assert stap.sequence == "N" * 10

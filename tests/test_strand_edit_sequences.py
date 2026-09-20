"""Nick/ligation preserve assigned bases and loop-aware 5′→3′ sequence order."""

import pytest

from backend.core.lattice import _ligate, make_bundle_design, make_nick
from backend.core.models import Direction, LoopSkip
from backend.core.sequences import strand_sequence_length


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("assigned", [True, False])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_nick_then_ligate_preserves_sequence(direction, assigned, delta):
    design = make_bundle_design([(0, 0)], length_bp=12)
    strand = next(s for s in design.strands if s.domains[0].direction == direction)
    helix = design.helices[0]
    if delta:
        helix.loop_skips = [LoopSkip(bp_index=3, delta=delta)]
    sequence = "ACGTACGTACGTA"[: 12 + delta] if assigned else None
    strand.sequence = sequence
    nicked = make_nick(design, helix.id, 5, direction)
    left = next(s for s in nicked.strands if s.id == strand.id)
    right = next(
        s for s in nicked.strands if s.id not in {v.id for v in design.strands}
    )
    if assigned:
        split = 6 + delta if direction == Direction.FORWARD else 7
        assert left.sequence == sequence[:split]
        assert right.sequence == sequence[split:]
        assert len(left.sequence) == strand_sequence_length(nicked, left)
        assert len(right.sequence) == strand_sequence_length(nicked, right)
    else:
        assert left.sequence is right.sequence is None
    joined = _ligate(nicked, left, right)
    assert next(s for s in joined.strands if s.id == strand.id).sequence == sequence
    assert strand.sequence == sequence  # input not mutated


@pytest.mark.parametrize("known_left", [True, False])
def test_ligate_keeps_known_half_and_marks_only_unknown_half(known_left):
    design = make_bundle_design([(0, 0)], length_bp=12)
    source = next(
        s for s in design.strands if s.domains[0].direction == Direction.FORWARD
    )
    nicked = make_nick(design, design.helices[0].id, 5, Direction.FORWARD)
    left = next(s for s in nicked.strands if s.id == source.id)
    right = next(
        s for s in nicked.strands if s.id not in {v.id for v in design.strands}
    )
    (left if known_left else right).sequence = "ACGTAC"
    joined = _ligate(nicked, left, right)
    result = next(s for s in joined.strands if s.id == source.id)
    assert result.sequence == ("ACGTACNNNNNN" if known_left else "NNNNNNACGTAC")

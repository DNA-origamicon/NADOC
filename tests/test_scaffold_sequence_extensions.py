"""End-turn growth preserves old assignments without changing route topology."""
import pytest

from backend.core.models import Direction, Domain, LoopSkip, Strand, StrandType
from backend.core.seamed_router import _extend_scaf_domain_hi, _extend_scaf_domain_lo
from backend.core.sequences import strand_sequence_length
from tests.conftest import make_minimal_design


@pytest.mark.parametrize("direction", [Direction.FORWARD, Direction.REVERSE])
@pytest.mark.parametrize("face", ["lo", "hi"])
@pytest.mark.parametrize("sequenced", [False, True])
def test_internal_domain_extension_preserves_flanking_sequence(direction, face, sequenced):
    design = make_minimal_design(helix_length_bp=20)
    middle = Domain(helix_id="h0", start_bp=5 if direction == Direction.FORWARD else 9,
                    end_bp=9 if direction == Direction.FORWARD else 5, direction=direction)
    strand = Strand(id="scaf", strand_type=StrandType.SCAFFOLD, domains=[
        Domain(helix_id="h0", start_bp=0, end_bp=1, direction=Direction.FORWARD),
        middle,
        Domain(helix_id="h0", start_bp=18, end_bp=19, direction=Direction.FORWARD),
    ], sequence="ACGTTGACA" if sequenced else None)
    # Growth by two bp adds three nt: one extra base at the newly included site.
    added_site = 3 if face == "lo" else 11
    helix = design.helices[0].model_copy(update={"loop_skips": [
        LoopSkip(bp_index=added_site, delta=1),
    ]})
    design = design.copy_with(helices=[helix], strands=[strand])
    extend, old, new = (_extend_scaf_domain_lo, 5, 3) if face == "lo" else (_extend_scaf_domain_hi, 9, 11)
    out = extend(design, "h0", old, new)
    actual = out.strands[0]
    if sequenced:
        before = (face == "lo") == (direction == Direction.FORWARD)
        offset = 2 if before else 7
        assert actual.sequence == strand.sequence[:offset] + "NNN" + strand.sequence[offset:]
        assert len(actual.sequence) == strand_sequence_length(out, actual)
    else:
        assert actual.sequence is None
    assert design.strands[0] == strand

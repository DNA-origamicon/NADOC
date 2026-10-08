"""Segment identity must not turn continuous duplex backbone into a junction."""

import pytest

from backend.core.backbone_continuations import backbone_continuation_edges
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import make_bundle_design
from backend.core.models import Design, ForcedLigation, LatticeType
from backend.core.sweep import SweepRequest, build_sweep
from backend.core.topology_integrity import junction_errors


def _swept(end="end", lattice=LatticeType.HONEYCOMB):
    seed = make_bundle_design([(0, 0), (0, 1)], 42, lattice_type=lattice)
    sign = 1 if end == "end" else -1
    return build_sweep(seed, SweepRequest(
        cells=[(0, 0), (0, 1), (1, 1)],
        points_nm=[(0, 0, 0), (0, 0, sign * 21 * BDNA_RISE_PER_BP)],
        source_helix_id=seed.helices[0].id,
        source_end=end,
        ligate_adjacent=False,
    ))


def _record(edge, **kwargs):
    a, b = edge
    return ForcedLigation(
        three_prime_helix_id=a[0], three_prime_bp=a[1], three_prime_direction=a[2],
        five_prime_helix_id=b[0], five_prime_bp=b[1], five_prime_direction=b[2],
        **kwargs,
    )


@pytest.mark.parametrize("end", ["start", "end"])
@pytest.mark.parametrize("lattice", list(LatticeType))
def test_sweep_continues_both_backbones_without_creating_junction_records(end, lattice):
    design = _swept(end, lattice)
    expected = {
        ((a.helix_id, a.end_bp, a.direction.value), (b.helix_id, b.start_bp, b.direction.value))
        for strand in design.strands
        for a, b in zip(strand.domains, strand.domains[1:])
    }
    assert len(expected) == 4  # Two continued duplexes; the added cell has free ends.
    assert backbone_continuation_edges(design) == expected
    assert not design.forced_ligations
    assert junction_errors(design) == []

    restored = Design.from_json(design.to_json())
    assert backbone_continuation_edges(restored) == expected
    assert not restored.crossovers
    assert not restored.forced_ligations
    assert junction_errors(restored) == []


def test_explicit_ligation_remains_authored_when_other_joins_are_normal():
    design = _swept()
    expected = backbone_continuation_edges(design)
    record = _record(min(expected), id="deliberate-segment-join")
    design = design.copy_with(forced_ligations=[record])

    restored = Design.from_json(design.to_json())
    assert restored.forced_ligations == [record]
    assert backbone_continuation_edges(restored) == expected
    assert junction_errors(restored) == []


def test_explicit_same_track_ligation_provides_provenance_without_sweep():
    design = _swept()
    expected = backbone_continuation_edges(design)
    design = design.copy_with(deformations=[], forced_ligations=[_record(e) for e in expected])
    assert backbone_continuation_edges(design) == expected
    assert junction_errors(design) == []


def test_inserted_bases_are_not_plain_continuations():
    design = _swept()
    expected = backbone_continuation_edges(design)
    edge = min(expected)
    design = design.copy_with(forced_ligations=[_record(edge, extra_bases="TT")])
    assert backbone_continuation_edges(design) == expected - {edge}
    assert junction_errors(design) == []  # Still valid through its explicit record.


def test_periodic_metadata_does_not_change_the_backbone_connection():
    design = _swept()
    expected = backbone_continuation_edges(design)
    record = _record(min(expected), is_periodic_seam=True)
    design = design.copy_with(forced_ligations=[record])
    restored = Design.from_json(design.to_json())
    assert backbone_continuation_edges(restored) == expected
    assert restored.forced_ligations == [record]


def test_equal_grid_cells_and_adjacent_bp_alone_do_not_certify_a_connection():
    design = _swept().copy_with(deformations=[])
    assert backbone_continuation_edges(design) == set()
    assert len(junction_errors(design)) == 4


def test_touching_segment_records_do_not_create_unwritten_backbone_edges():
    design = _swept()
    split = []
    for strand in design.strands:
        split.extend(strand.model_copy(update={"id": f"{strand.id}-{i}", "domains": [dm]})
                     for i, dm in enumerate(strand.domains))
    assert backbone_continuation_edges(design.copy_with(strands=split)) == set()


def test_changed_internal_endpoint_is_not_hidden_as_a_normal_continuation():
    design = _swept()
    strand = next(s for s in design.strands if len(s.domains) == 2)
    old = strand.domains[1]
    step = 1 if old.direction.value == "FORWARD" else -1
    changed = old.model_copy(update={"start_bp": old.start_bp + step})
    broken = strand.model_copy(update={"domains": [strand.domains[0], changed]})
    design = design.copy_with(strands=[broken if s.id == strand.id else s for s in design.strands])
    assert len(backbone_continuation_edges(design)) == 3
    assert len(junction_errors(design)) == 1

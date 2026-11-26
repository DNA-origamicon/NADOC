import pytest

from backend.core.corner_routing import DuplexCut, plan_corner_routes
from backend.core.models import Domain, Direction, Strand, StrandType


def domain(helix, start, end):
    return Domain(helix_id=helix, start_bp=start, end_bp=end,
                  direction=Direction.FORWARD if start <= end else Direction.REVERSE)


def pair():
    return [Strand(id='scaffold', strand_type=StrandType.SCAFFOLD, domains=[domain('h', 0, 99)]),
            Strand(id='staple', strand_type=StrandType.STAPLE, domains=[domain('h', 99, 0)])]


@pytest.mark.parametrize('a,b', [(44, 55), (55, 44), (49, 50)])
def test_preserves_both_polarities_and_explicit_junction_ownership(a, b):
    source = pair()
    before = [s.model_dump() for s in source]
    plan = plan_corner_routes(source, [DuplexCut('h', a, b)], 50)
    forward, reverse = plan.strands
    assert [(d.start_bp, d.end_bp, d.side) for d in forward.domains] == [(0, a, 'incoming'), (b, 99, 'outgoing')]
    assert [(d.start_bp, d.end_bp, d.side) for d in reverse.domains] == [(99, b, 'outgoing'), (a, 0, 'incoming')]
    assert [(j.strand_id, j.strand_type) for j in plan.junctions] == [('scaffold', 'scaffold'), ('staple', 'staple')]
    assert [s.model_dump() for s in source] == before


def test_keeps_external_domains_and_crossover_traversal():
    source = pair()
    source[0].domains = [domain('external', 90, 70), *source[0].domains, domain('external2', 12, 4)]
    plan = plan_corner_routes(source, [DuplexCut('h', 45, 54)], 50)
    routed = plan.strands[0]
    assert routed.domains[0].side == routed.domains[-1].side == 'unchanged'
    assert (routed.domains[0].start_bp, routed.domains[-1].end_bp) == (90, 4)
    j, = [j for j in plan.junctions if j.strand_id == 'scaffold']
    assert (j.exit_domain, j.entry_domain) == (1, 2)


def test_local_trim_exposes_a_junction_instead_of_silently_skipping_connectivity():
    source = pair()
    source[1].domains = [domain('h', 99, 60), domain('other', 6, 9), domain('h', 59, 0)]
    plan = plan_corner_routes(source, [DuplexCut('h', 40, 65)], 50)
    staple = plan.strands[1]
    assert [(d.helix_id, d.start_bp, d.end_bp) for d in staple.domains] == [
        ('h', 99, 65), ('other', 6, 9), ('h', 40, 0)]
    assert len([j for j in plan.junctions if j.strand_id == 'staple']) == 2


@pytest.mark.parametrize('a,b', [(45, 54), (55, 44)])
@pytest.mark.parametrize('direction', ['FORWARD', 'REVERSE'])
def test_preserves_nick_at_plane_without_joining_its_strands(a, b, direction):
    source = pair()
    index = 0 if direction == 'FORWARD' else 1
    source[index].domains = [domain('h', 0, 49) if index == 0 else domain('h', 99, 50)]
    source.append(Strand(id='other_end', strand_type=source[index].strand_type,
        domains=[domain('h', 50, 99) if index == 0 else domain('h', 49, 0)]))
    before = [s.model_dump() for s in source]
    plan = plan_corner_routes(source, [DuplexCut('h', a, b)], 50)
    assert len(plan.junctions) == 1
    assert plan.junctions[0].strand_id == source[1-index].id
    ends = [plan.strands[index].domains[0], plan.strands[-1].domains[0]]
    expected = [(0, a, 'incoming'), (b, 99, 'outgoing')] if index == 0 else [
        (99, b, 'outgoing'), (a, 0, 'incoming')]
    assert [(d.start_bp, d.end_bp, d.side) for d in ends] == expected
    assert [s.model_dump() for s in source] == before


def test_rejects_crossover_at_plane_instead_of_guessing_endpoint_matching():
    source = pair()
    source[1].domains = [domain('h', 99, 50), domain('other', 0, 10), domain('h', 49, 0)]
    with pytest.raises(ValueError, match='endpoint matching'):
        plan_corner_routes(source, [DuplexCut('h', 45, 54)], 50)


def test_rejects_duplicate_occupancy_and_overhang_reinterpretation():
    source = pair()
    source.append(Strand(id='overlap', strand_type=StrandType.STAPLE, domains=[domain('h', 80, 20)]))
    with pytest.raises(ValueError, match='overlapping strand'):
        plan_corner_routes(source, [DuplexCut('h', 45, 54)], 50)
    source = pair()
    source[1].domains[0].overhang_id = 'must-remain-overhang'
    with pytest.raises(ValueError, match='overhang'):
        plan_corner_routes(source, [DuplexCut('h', 45, 54)], 50)

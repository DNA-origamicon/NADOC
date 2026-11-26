from dataclasses import replace

import pytest

from backend.core.corner_routing import DuplexCut, plan_corner_routes
from backend.core.corner_topology import corner_output_id, materialize_corner_topology
from backend.core.models import Direction, Domain, Strand, StrandType


def domain(helix, start, end):
    return Domain(helix_id=helix, start_bp=start, end_bp=end,
                  direction=Direction.FORWARD if start <= end else Direction.REVERSE)


def source():
    return [Strand(id='scaf', strand_type=StrandType.SCAFFOLD,
                   domains=[domain('h', 0, 99)], sequence='ACGT' * 25,
                   name='Scaffold', notes='Keep notes', custom_scaffold_length=7249),
            Strand(id='stap', strand_type=StrandType.STAPLE,
                   domains=[domain('h', 99, 0)], sequence='TGCA' * 25,
                   color='#FF0000', name='Staple')]


def materialize(strands, a=44, b=55, **kwargs):
    plan = plan_corner_routes(strands, [DuplexCut('h', a, b)], 50)
    return materialize_corner_topology(strands, plan, operation_id='corner-1',
        outgoing_helix_ids={'h': 'h-mobile'}, bridge_sequences={('scaf', 0): 'NN', ('stap', 0): 'NNN'}, **kwargs)


def test_creates_explicit_antiparallel_seams_and_retains_strand_metadata():
    strands = source()
    before = [s.model_dump() for s in strands]
    result = materialize(strands)
    a, b = result.seam_connections
    assert (a.three_prime_helix_id, a.three_prime_bp, a.five_prime_helix_id, a.five_prime_bp) == ('h', 44, 'h-mobile', 55)
    assert a.three_prime_direction == a.five_prime_direction == Direction.FORWARD
    assert (b.three_prime_helix_id, b.three_prime_bp, b.five_prime_helix_id, b.five_prime_bp) == ('h-mobile', 55, 'h', 44)
    assert b.three_prime_direction == b.five_prime_direction == Direction.REVERSE
    assert (a.extra_bases, b.extra_bases) == ('NN', 'NNN')
    assert result.strands[0].sequence == strands[0].sequence[:45] + strands[0].sequence[55:]
    assert result.strands[1].sequence == strands[1].sequence[:45] + strands[1].sequence[55:]
    assert result.strands[0].custom_scaffold_length == 7249
    assert result.strands[0].notes == 'Keep notes'
    assert result.strands[1].color == '#FF0000'
    assert [s.model_dump() for s in strands] == before
    assert result.domain_map == {('scaf', 0): (0, 1), ('stap', 0): (0, 1)}


def test_overlapping_miter_ranges_belong_to_distinct_helix_arms():
    result = materialize(source(), 55, 44)
    scaffold, staple = result.strands
    assert [(d.helix_id, d.start_bp, d.end_bp) for d in scaffold.domains] == [('h', 0, 55), ('h-mobile', 44, 99)]
    assert [(d.helix_id, d.start_bp, d.end_bp) for d in staple.domains] == [('h-mobile', 99, 44), ('h', 55, 0)]
    assert len(scaffold.sequence) == len(staple.sequence) == 112
    assert result.endpoint_map[('h', 99, 'FORWARD')] == ('h-mobile', 99, 'FORWARD')
    assert result.endpoint_map[('h', 0, 'REVERSE')] == ('h', 0, 'REVERSE')


def test_new_tip_bases_do_not_duplicate_assigned_source_sequence():
    original = source()
    updated = materialize(original, 55, 44, new_tip_sequences=True)
    assert updated.strands[0].sequence == original[0].sequence[:50] + 'N' * 12 + original[0].sequence[50:]
    assert updated.strands[1].sequence == original[1].sequence[:50] + 'N' * 12 + original[1].sequence[50:]
    # Old recorded commands keep their exact earlier sequence behavior.
    legacy = materialize(original, 55, 44)
    assert legacy.strands[0].sequence == original[0].sequence[:56] + original[0].sequence[44:]
    assert legacy.strands[1].sequence == original[1].sequence[:56] + original[1].sequence[44:]


def test_original_nick_endpoint_is_not_claimed_by_the_other_wedges_extension():
    strands = source()
    strands[0].domains = [domain('h', 47, 99)]
    strands[0].sequence = None
    strands.append(Strand(id='before_nick', strand_type=StrandType.SCAFFOLD,
                          domains=[domain('h', 0, 46)]))
    result = materialize(strands, 55, 44)
    assert result.endpoint_map[('h', 47, 'FORWARD')] == ('h', 47, 'FORWARD')
    assert result.endpoint_map[('h', 99, 'FORWARD')] == ('h-mobile', 99, 'FORWARD')


def test_deterministic_identities_do_not_depend_on_sequence_or_iteration_order():
    one, two = materialize(source()), materialize(list(reversed(source())))
    assert {s.id for s in one.seam_connections} == {s.id for s in two.seam_connections}
    assert corner_output_id('operation', 'helix', 'h') != corner_output_id('operation', 'helix', 'h2')
    assert corner_output_id('operation', 'helix', 'h') != corner_output_id('other', 'helix', 'h')


def test_no_implicit_bridge_length_or_sequence():
    strands = source()
    plan = plan_corner_routes(strands, [DuplexCut('h', 44, 55)], 50)
    with pytest.raises(ValueError, match='resolved bridge'):
        materialize_corner_topology(strands, plan, operation_id='corner-1',
            outgoing_helix_ids={'h': 'h-mobile'}, bridge_sequences={})
    with pytest.raises(ValueError, match='uppercase DNA'):
        materialize_corner_topology(strands, plan, operation_id='corner-1',
            outgoing_helix_ids={'h': 'h-mobile'}, bridge_sequences={('scaf', 0): 'tt', ('stap', 0): 'NN'})


def test_cannot_convert_changed_lattice_connection_to_corner_seam():
    strands = source()
    strands[1].sequence = None
    strands[1].domains = [domain('h', 99, 60), domain('other', 6, 9), domain('h', 59, 0)]
    plan = plan_corner_routes(strands, [DuplexCut('h', 40, 65)], 50)
    with pytest.raises(ValueError, match='within-wedge'):
        materialize_corner_topology(strands, plan, operation_id='corner-1',
            outgoing_helix_ids={'h': 'h-mobile'},
            bridge_sequences={(j.strand_id, j.exit_domain): 'NN' for j in plan.junctions})


def test_unaffected_sequence_keeps_loop_copy_positions():
    strands = source()
    strands[0].domains.insert(0, domain('untouched', 0, 2))
    strands[0].sequence = 'ATTC' + strands[0].sequence
    plan = plan_corner_routes(strands, [DuplexCut('h', 44, 55)], 50)
    result = materialize_corner_topology(strands, plan, operation_id='corner-1',
        outgoing_helix_ids={'h': 'h-mobile'}, bridge_sequences={('scaf', 1): 'NN', ('stap', 0): 'NN'},
        loop_skips={('untouched', 1): 1})
    assert result.strands[0].sequence.startswith('ATTCACGT')
    assert result.strands[0].domains[0] == strands[0].domains[0]


def test_rejects_missing_strand_ownership_and_output_identity_collision():
    strands = source()
    plan = plan_corner_routes(strands, [DuplexCut('h', 44, 55)], 50)
    with pytest.raises(ValueError, match='every source strand'):
        materialize_corner_topology(strands, replace(plan, strands=plan.strands[:1]), operation_id='c',
            outgoing_helix_ids={'h': 'new'}, bridge_sequences={})
    with pytest.raises(ValueError, match='distinct new identities'):
        materialize_corner_topology(strands, plan, operation_id='c', outgoing_helix_ids={'h': 'h'},
            bridge_sequences={('scaf', 0): 'NN', ('stap', 0): 'NN'})

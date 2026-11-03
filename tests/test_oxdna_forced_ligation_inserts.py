"""Forced-ligation inserts must survive the native nucleotide/export walk."""
import pytest

from backend.core.models import Design, Domain, ForcedLigation, Helix, Strand, Vec3
from backend.physics import oxdna_interface as ox


def joined_design(same_helix=False):
    target = 'a' if same_helix else 'b'
    design = Design(
        helices=[Helix(id=h, axis_start=Vec3(x=i * 3, y=0, z=0),
                       axis_end=Vec3(x=i * 3, y=0, z=8), length_bp=25)
                 for i, h in enumerate(['a'] if same_helix else ['a', 'b'])],
        strands=[Strand(id='s', sequence='ACGT', domains=[
            Domain(helix_id='a', start_bp=0, end_bp=1, direction='FORWARD'),
            Domain(helix_id=target, start_bp=8, end_bp=7, direction='REVERSE'),
        ])],
        forced_ligations=[ForcedLigation(
            id='join', three_prime_helix_id='a', three_prime_bp=1,
            three_prime_direction='FORWARD', five_prime_helix_id=target,
            five_prime_bp=8, five_prime_direction='REVERSE', extra_bases='TTA',
        )],
    )
    return design


@pytest.mark.parametrize('same_helix', [False, True])
def test_forced_insert_is_ordered_and_bonded_into_owning_strand(same_helix):
    design = joined_design(same_helix)
    rows, strands = ox.topology_rows(design)
    assert strands == 1
    assert ''.join(row[1] for row in rows) == 'ACTTAGT'
    assert [row[2] for row in rows] == [1, 2, 3, 4, 5, 6, -1]
    assert [row[3] for row in rows] == [-1, 0, 1, 2, 3, 4, 5]
    order = ox._strand_nucleotide_order(design)
    assert len(order) == len(set(order)) == 7
    assert ox._extra_base_inserts(design)[(ox._XB_SENTINEL, 'join', 0)][:2] == (
        ('a', 1, 'FORWARD'), ('a' if same_helix else 'b', 8, 'REVERSE'))


@pytest.mark.parametrize('changed_field,value', [
    ('three_prime_direction', 'REVERSE'),
    ('five_prime_direction', 'FORWARD'),
    ('five_prime_bp', 9),
])
def test_forced_insert_requires_both_directed_backbone_endpoints(changed_field, value):
    design = joined_design()
    design.forced_ligations[0] = design.forced_ligations[0].model_copy(update={changed_field: value})
    assert ox.crossover_extra_base_junctions(design) == {}
    assert ''.join(row[1] for row in ox.topology_rows(design)[0]) == 'ACGT'


def test_forced_insert_reciprocal_strands_have_distinct_insert_keys():
    design = joined_design()
    design.strands.append(Strand(id='partner', sequence='GCTA', domains=[
        Domain(helix_id='b', start_bp=7, end_bp=8, direction='FORWARD'),
        Domain(helix_id='a', start_bp=1, end_bp=0, direction='REVERSE'),
    ]))
    design.forced_ligations.append(ForcedLigation(
        id='other', three_prime_helix_id='b', three_prime_bp=8,
        three_prime_direction='FORWARD', five_prime_helix_id='a', five_prime_bp=1,
        five_prime_direction='REVERSE', extra_bases='C',
    ))
    rows, _ = ox.topology_rows(design)
    assert ''.join(r[1] for r in rows if r[0] == 1) == 'ACTTAGT'
    assert ''.join(r[1] for r in rows if r[0] == 2) == 'GCCTA'
    order = ox._strand_nucleotide_order(design)
    assert len(order) == len(set(order)) == 12
    for i, (sid, _, n3, n5) in enumerate(rows):
        if n3 >= 0:
            assert rows[n3][0] == sid and rows[n3][3] == i
        if n5 >= 0:
            assert rows[n5][0] == sid and rows[n5][2] == i

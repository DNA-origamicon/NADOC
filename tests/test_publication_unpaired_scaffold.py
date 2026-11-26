import hashlib
from pathlib import Path

import pymupdf
import pytest

from backend.core.publication_unpaired_scaffold import locate_unpaired_scaffold, _longest_match


def fixture():
    seq = 'ACGTAAGCTTAGCCGT'
    sites = [(0, 0)] + [(19, i) for i in range(14)] + [(0, 1)]
    staple = {'start': [19, 11], 'end': [19, 2], 'sequence': 'GCTAAGCTTA', 'length': 10}
    classified = {'scaf': [{'sites': sites}], 'stap': [
        {'sites': [(19, i) for i in range(11, 1, -1)], 'table_row': staple}], 'unresolved': []}
    alignment = {'resolved': True, 'length_discrepancy': 0,
                 'scaffold_sha256': hashlib.sha256(seq.encode()).hexdigest(),
                 'best': {'reverse': False, 'offset': 0}}
    return classified, {'counts': [], 'unresolved': []}, {'rows': [staple]}, alignment, seq, {'missing_helices': [19]}


def test_loop_runs_preserve_attachments_and_auxiliary_duplex():
    args = fixture()
    result = locate_unpaired_scaffold(*args)
    assert result['resolved']
    assert [r['length'] for r in result['runs']] == [3, 3]
    aux = result['auxiliary_tracks'][0]
    assert aux['paired_bases'] == 10 and aux['unpaired_bases'] == 4
    assert aux['attachment_before'] == (0, 0) and aux['attachment_after'] == (0, 1)
    assert aux['supported_excursion'] and not aux['placement_resolved']


def test_unassigned_complement_vetoes_loop_even_when_other_staples_match():
    args = fixture()
    args[3].update(resolved=False, alignment_resolved=True)
    args[2]['rows'].append({'start': [8, 2], 'end': [8, 0], 'length': 3, 'sequence': 'CGT'})
    result = locate_unpaired_scaffold(*args)
    assert not result['resolved']
    assert result['runs'][0]['longest_match_unassigned_staple']['length'] == 3


def test_unclassified_path_and_wrong_scaffold_do_not_certify_loops():
    args = fixture(); args[0]['unresolved'] = [{'sites': [(7, 0)]}]
    assert not locate_unpaired_scaffold(*args)['resolved']
    args = list(fixture()); args[4] = 'T' * 16
    with pytest.raises(ValueError, match='differs'):
        locate_unpaired_scaffold(*args)


def test_longest_match_reports_reverse_complement_and_witness():
    hit = _longest_match('AAGCTTCC', [(2, 'CCGGAAGCTTAA')])
    assert hit == {'length': 8, 'table_row': 2, 'staple_offset': 2, 'sequence': 'GGAAGCTT'}
    assert _longest_match('AAAA', [(0, 'CCCC')])['length'] == 0


PDF = Path('workspace/Shared Designs/.provenance/D005/twist-supp.pdf')

@pytest.mark.skipif(not PDF.exists(), reason='Local supplement unavailable')
@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_sideways_d006_has_same_routes_loops_and_inset_at_every_quarter_turn(rotation):
    from backend.core.publication_routing import (extract_publication_paths, staple_tables,
        pair_endpoint_table, classify_scaffold, resolve_insertions)
    from backend.core.publication_sequence_search import search_declared_scaffold
    from backend.core.publication_unpaired_scaffold import aligned_unpaired_scaffold
    with pymupdf.open(PDF) as source, pymupdf.open() as rotated:
        page = source[19]
        width, height = page.rect.width, page.rect.height
        target = rotated.new_page(width=height if rotation % 180 else width,
                                  height=width if rotation % 180 else height)
        target.show_pdf_page(target.rect, source, 19, rotate=rotation)
        graph = extract_publication_paths(target)
        table = next(t for t in staple_tables(source) if t['page'] == 39)
    pairing = pair_endpoint_table(graph, table)
    classified = classify_scaffold(pairing)
    insertions = resolve_insertions(pairing, classified, table)
    alignment = search_declared_scaffold(classified, insertions, table)
    assert alignment['resolved'] and alignment['best']['exact_staples'] == 209
    lattice = graph['lattice']
    assert lattice['inset_resolved'] and len(lattice['cells']) == 18
    assert lattice['missing_helices'] == [19] and not lattice['resolved']
    assert graph['normalization_rotation'] == (270 - rotation) % 360
    result = aligned_unpaired_scaffold(classified, insertions, table, alignment, lattice)
    assert result['resolved'] and result['unpaired_bases'] == 46
    assert [r['length'] for r in result['runs']] == [26, 3, 3, 14]
    assert [r['longest_match_any_staple']['length'] for r in result['runs']] == [8, 3, 3, 6]
    assert all(r['longest_match_unassigned_staple']['length'] == 0 for r in result['runs'])
    assert [(a['paired_bases'], a['unpaired_bases']) for a in result['auxiliary_tracks']] == [(49, 29), (49, 17)]
    assert all(a['supported_excursion'] for a in result['auxiliary_tracks'])
    from backend.core.publication_auxiliary_placement import infer_auxiliary_placement
    placement = infer_auxiliary_placement(lattice, classified, result)
    assert placement['tracks'][0]['segments'][0]['best_cells'] == [[0, 5]]
    assert placement['tracks'][0]['segments'][1]['best_cells'] == [[0, 3]]
    assert placement['resolved']


def test_alignment_offset_is_applied_before_loop_sequence_search():
    args = list(fixture())
    original = args[4]
    args[4] = original[-4:] + original[:-4]
    args[3]['scaffold_sha256'] = hashlib.sha256(args[4].encode()).hexdigest()
    args[3]['best']['offset'] = 4
    result = locate_unpaired_scaffold(*args)
    assert [r['sequence'] for r in result['runs']] == [original[:3], original[-3:]]


def test_explicit_insertions_expand_loop_sequence_without_adding_route_sites():
    args = list(fixture())
    args[1]['counts'] = [[19, 0, 3]]
    args[4] = args[4][:2] + 'AAA' + args[4][2:]
    args[3]['scaffold_sha256'] = hashlib.sha256(args[4].encode()).hexdigest()
    result = locate_unpaired_scaffold(*args)
    assert result['runs'][0]['length'] == 6
    assert len(result['runs'][0]['sites']) == 3


def test_auxiliary_track_without_adjacent_return_is_not_a_supported_excursion():
    args = fixture()
    args[0]['scaf'][0]['sites'][-1] = (1, 1)
    result = locate_unpaired_scaffold(*args)
    assert not result['auxiliary_tracks'][0]['supported_excursion']
    assert not result['auxiliary_tracks'][0]['placement_resolved']
def test_terminal_scaffold_admission_excludes_interior_gaps_and_unplaced_tracks():
    from backend.core.publication_unpaired_scaffold import terminal_scaffold_sites
    classified = {'stap':[{'sites':[(0,3),(0,4),(0,6),(0,7),(1,3),(1,7)]}]}
    runs = [
        {'sites':[(0,1),(0,2),(0,5),(0,8),(1,1),(2,1)],
         'supported':True,'placement_resolved':True},
        {'sites':[(0,9)],'supported':False,'placement_resolved':True},
        {'sites':[(0,10)],'supported':True,'placement_resolved':False},
    ]
    assert terminal_scaffold_sites(classified,{'missing_helices':[1]}, {'runs':runs}) == {(0,1),(0,2),(0,8)}

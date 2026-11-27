import json
from pathlib import Path

import pymupdf
import pytest

from backend.core.publication_routing import classify_scaffold, pair_endpoint_table, staple_tables
from backend.core.publication_vector_panels import select_panel_graph
from tools.design_archive.publication_routing_benchmark import compare

ASSETS = Path('experiments/origami_publication_catalog/assets')


@pytest.mark.parametrize(('page_number', 'table_page', 'reference_name', 'orientations'), [
    (7, 15, 'slottedcross', [(1, 0), (1, 0)]),
    (8, 16, 'stackedcross', [(1, 0), (0, 1)]),
    (9, 17, 'doublegear', [(1, 0)]),
])
def test_complete_vector_route_matches_held_out_author_design(page_number, table_page, reference_name, orientations):
    source = ASSETS / 'sources/shapes-supp.pdf'
    if not source.exists():
        pytest.skip('Optional local publication corpus')
    with pymupdf.open(source) as doc:
        table = next(t for t in staple_tables(doc) if t['page'] == table_page)
        graph = select_panel_graph(doc[page_number - 1], table)
    assert [panel['direction'] for panel in graph['panels']] == orientations
    assert not graph['rejected_path_ids']
    pairing = pair_endpoint_table(graph, table)
    assert pairing['all_table_endpoints_matched']
    routed = classify_scaffold(pairing)
    assert len(routed['scaf']) == 1
    assert not routed['unresolved']
    reference = json.loads((ASSETS / f'designs/shapes/{reference_name}.json').read_bytes())
    for kind in ('scaf', 'stap'):
        differences = compare(routed[kind], reference, kind)
        assert not any(differences[k] for k in ('missing_sites', 'extra_sites', 'wrong_pointers'))
    expected_marks = {(h['num'], i) for h in reference['vstrands'] for i, count in enumerate(h['loop']) if count}
    assert set(graph['insertion_annotations']) == expected_marks


def test_d012_recovers_historical_scaffold_and_compiles_continuous_revisits():
    from backend.core.publication_authoring import compile_publication

    source = ASSETS / 'sources/shapes-supp.pdf'
    if not source.exists():
        pytest.skip('Optional local publication corpus')
    recipe, evidence = compile_publication(
        source.read_bytes(), diagram_page=9, table_page=17, name='D012', source_path='shapes-supp.pdf')
    assert evidence['reconstruction_report']['status'] == 'complete'
    assert evidence['sequence_search']['scaffold_name'] == 'pEGFP'
    assert evidence['sequence_search']['best']['mismatches'] == 0
    assert evidence['insertion_representation']['scaffold_loops'][0]['length'] == 71
    assert evidence['staple_precursors']['pen_strokes'] == 54
    ops = recipe['operations']
    boundary = next(i for i, op in enumerate(ops) if op['label'] == 'Connect Staple 1 domains 1/2')
    helix = evidence['helix_ids'][0]
    assert any(op['kind'] == 'nick' and op['params']['helix_id'] == helix and op['params']['bp_index'] == 84
               for op in ops[:boundary])

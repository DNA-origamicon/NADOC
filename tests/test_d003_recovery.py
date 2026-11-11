"""Published image/table regression oracles; no author caDNAno reference."""

import json
from pathlib import Path

import pytest

from experiments.recorded_review_process import ProcessRequired
from tools.design_archive.d003_recipe import compile_recipe, trace_walks, sequence_mapping


@pytest.fixture
def evidence():
    fixture = json.loads((Path(__file__).parent / 'fixtures/d003_figure_routes.json').read_text())
    width = fixture['width']
    helices = {h: dict(num=h, row=h, col=0, scaf=[[-1]*4 for _ in range(width)],
                      stap=[[-1]*4 for _ in range(width)], skip=[0]*width, loop=[0]*width)
               for h in range(88)}
    for kind, routes in fixture['routes'].items():
        for route in routes:
            walk = [(h, b) for h, a, z in route for b in range(a, z + (1 if z > a else -1), 1 if z > a else -1)]
            for i, (h, b) in enumerate(walk):
                helices[h][kind][b] = [*(walk[i-1] if i else (-1, -1)),
                                      *(walk[i+1] if i+1 < len(walk) else (-1, -1))]
    for h, b in fixture['deletions']:
        helices[h]['skip'][b] = -1
    m13 = (Path(__file__).parents[1] / 'backend/core/m13mp18.txt').read_text().strip()
    return {'vstrands': list(helices.values())}, fixture['table_rows'], m13


def test_complete_sequence_mapping_and_exact_bridge_bases(evidence):
    graph, rows, m13 = evidence
    _, mapped, report = sequence_mapping(graph, rows, m13)
    assert report['scaffold_offset_0based'] == 1515
    assert report['sequence_rows_matched'] == 210
    assert report['bridge_junctions'] == 40
    assert report['bridge_bases'] == 226
    assert report['non_poly_t_bridges'] == [{'name': 'Bri-T1R07C2', 'junction': 1, 'sequence': 'ATTTTT'}]
    assert sum(len(s['sequence']) for s in mapped) == 7032


def test_missing_edge_table_refused(evidence):
    graph, rows, m13 = evidence
    with pytest.raises(ProcessRequired, match='166 Table S2'):
        sequence_mapping(graph, [r for r in rows if not r['name'].startswith('Edg')], m13)


def test_one_wrong_table_base_refused(evidence):
    graph, rows, m13 = evidence
    row = next(r for r in rows if r['name'] == 'Reg-T1R01C6')
    row['sequence'] = 'A' + row['sequence'][1:]
    with pytest.raises(ProcessRequired, match='Sequence does not uniquely match'):
        sequence_mapping(graph, rows, m13)


def test_broken_graph_refused(evidence):
    graph, _, _ = evidence
    graph['vstrands'][0]['scaf'][104][0] = 70
    with pytest.raises(ProcessRequired, match='Nonreciprocal'):
        trace_walks(graph, 'scaf')


def test_compilation_is_deterministic_and_contains_only_native_commands(evidence):
    from tools.design_archive.recorded_authoring import BUILDERS
    graph, rows, m13 = evidence
    recipe, report = compile_recipe(graph, rows, m13, [])
    assert compile_recipe(graph, rows, m13, []) == (recipe, report)
    assert report['operation_count'] == 1680
    assert report['crossovers'] == 386
    assert report['forced_ligations'] == 75
    assert {op['kind'] for op in recipe['operations']} <= BUILDERS.keys()
    assert not any('import' in op['kind'] for op in recipe['operations'])
    assert recipe['folded_geometry']['required'] is True

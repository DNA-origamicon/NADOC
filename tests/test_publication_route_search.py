from pathlib import Path
import pytest


def test_d009_search_uses_sources_and_reports_ambiguity():
    source=Path('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf')
    if not source.exists():pytest.skip('Local publication corpus not installed')
    from backend.core.publication_authoring import compile_publication
    recipe,e=compile_publication(source.read_bytes(),diagram_page=6,table_page=14,name='D009',source_path='source.pdf',allow_partial=True)
    from collections import Counter
    assert Counter(r['status'] for r in e['route_search']['rows'])=={'unique':7,'ambiguous':2,'no_match':1}
    assert len(e['classified']['stap'])==194
    assert e['reconstruction_report']['status']=='partial'
    assert len(e['reconstruction_report']['scaffold_sequence_assigned'])==7703
    assert not recipe['unresolved']  # omitted alternatives aren't unresolved executed selections
    assert any(o['kind']=='strand-delete-batch' for o in recipe['operations'])
    assert not e['route_search']['native_reference_consulted']
    assert e['appearance']['helix_order']==list(range(45,33,-1))+list(range(16,22))+list(range(16))+list(range(33,21,-1))
    assert all(c['color'] for c in e['appearance']['staple_colors'])
    assert sum(c['basis']=='source PDF route stroke' for c in e['appearance']['staple_colors'])==187
    assert recipe['operations'][-1]['kind']=='helix-reorder'
    loops=[o['params'] for o in recipe['operations'] if o['kind']=='strand-loop-set']
    assert sorted((p['helix_id'],p['bp_index'],p['length']) for p in loops)==sorted(
        (e['helix_ids'][h],119,39) for h in (30,42))
    assert not any(o['kind']=='loop-skip-insert' for o in recipe['operations'])
    assert e['reconstruction_report']['insertion_representation']['limitation']


def test_search_budget_never_turns_one_candidate_into_a_uniqueness_claim():
    source=Path('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf')
    if not source.exists():pytest.skip('Local publication corpus not installed')
    import pymupdf
    from backend.core.publication_routing import extract_publication_paths,staple_tables,pair_endpoint_table,classify_scaffold,resolve_insertions
    from backend.core.publication_sequence_search import search_declared_scaffold,apply_supported_insertions
    from backend.core.publication_route_search import search_missing_routes
    with pymupdf.open(source) as doc:
        graph=extract_publication_paths(doc[5]);table=next(t for t in staple_tables(doc) if t['page']==14)
    pairing=pair_endpoint_table(graph,table);classified=classify_scaffold(pairing)
    insertions=resolve_insertions(pairing,classified,table)
    alignment=search_declared_scaffold(classified,insertions,table)
    result=search_missing_routes(classified,apply_supported_insertions(insertions,alignment),alignment,table,graph['lattice'],max_states=1)
    assert len(result['rows'])==10
    assert all(r['status']=='budget_exhausted' and not r['search_complete'] for r in result['rows'])

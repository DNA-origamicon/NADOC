from pathlib import Path
import pytest
from backend.core.publication_authoring import compile_publication

ASSETS=Path('experiments/origami_publication_catalog/assets/sources')

@pytest.mark.skipif(not (ASSETS/'twist-supp.pdf').exists(), reason='Local publication corpus not installed')
def test_d005_compiles_native_commands_without_an_import_root():
    recipe,evidence=compile_publication((ASSETS/'twist-supp.pdf').read_bytes(),diagram_page=19,
        table_page=37,name='D005',source_path='Shared Designs/.provenance/D005/twist-supp.pdf')
    assert evidence['sequence_search']['best']['exact_staples']==217
    assert len(evidence['cells'])==60
    assert not evidence['native_reference_consulted']
    ops=recipe['operations']
    assert len(ops)==2041
    assert any(o["kind"]=="strand-delete-batch" for o in ops)
    assert evidence['staple_precursors']['periodic_seams']==60
    assert all('import' not in o['kind'] for o in ops)
    loops=[o['params']['delta'] for o in ops if o['kind']=='loop-skip-insert']
    assert loops.count(144)==1 and loops.count(1)==360
    assert evidence['connections']['forced_ligations'] < evidence['connections']['crossovers']/5

@pytest.mark.skipif(not (ASSETS/'twist-supp.pdf').exists(), reason='Local publication corpus not installed')
def test_d006_compiles_both_independent_loops_with_all_source_sites():
    recipe,evidence=compile_publication((ASSETS/'twist-supp.pdf').read_bytes(),diagram_page=20,
        table_page=39,name='D006',source_path='source.pdf', periodic_staple_seams=True)
    assert len(recipe['operations']) < 2116
    assert evidence['staple_precursors']['pen_strokes'] == 20
    assert evidence['staple_precursors']['periodic_seams'] == 18
    pens = [o for o in recipe['operations'] if o['label'] == 'Draw continuous staple precursor']
    body_ids = {evidence['helix_ids'][h] for h in range(18)}
    assert sum(p['params']['domains'][0]['helix_id'] in body_ids for p in pens) == 18
    seams = [o for o in recipe['operations'] if o['params'].get('is_periodic_seam')]
    assert len(seams) == 18
    assert len(evidence['cells'])==20
    assert evidence['sequence_search']['best']['exact_staples']==209
    assert evidence['unpaired_scaffold']['unpaired_bases']==46
    assert evidence['auxiliary_placement']['resolved']
    segments=[s for s in evidence['helix_sources'].values() if 'source_start' in s]
    assert [(s['source_helix'],s['source_start'][1],s['source_end'][1]) for s in segments]==[(19,256,179),(19,163,98)]
    assert [s['native_viewer_label'] for s in segments]==[18,19]
    assert sum(len(p['sites']) for kind in ('scaf','stap') for p in evidence['classified'][kind])==15362
    assert not any('import' in o['kind'] or 'extension' in o['kind'] for o in recipe['operations'])

@pytest.mark.parametrize('count',[1,39,144,512])
def test_long_loop_is_a_native_count_not_an_extension(count):
    from backend.api.part_native_commands import build_loop
    from backend.api.part_cell_commands import build
    from backend.core.part_history_contract import create_empty_part
    from backend.api.part_routing_edit_inputs import normalize
    design=build('helix-add-at-cell',create_empty_part('loop','HONEYCOMB'),
        {'row':0,'col':0,'length_bp':20,'populate_strands':False,'_helix_id':'00000000-0000-4000-8000-000000000001'})
    params={'_proof_version':1,'helix_id':'00000000-0000-4000-8000-000000000001','bp_index':10,'delta':count}
    assert normalize('loop-skip-insert',params,{})['delta']==count
    updated=build_loop('loop-skip-insert',design,params)
    assert updated.helices[0].loop_skips[0].delta==count
    assert not updated.extensions
    assert not design.helices[0].loop_skips

@pytest.mark.parametrize('count',[-2,513,True,1.5])
def test_loop_count_stays_bounded(count):
    from backend.api.part_native_commands import build_loop
    from backend.api.part_cell_commands import build
    from backend.core.part_history_contract import create_empty_part
    design=build('helix-add-at-cell',create_empty_part('loop','HONEYCOMB'),
        {'row':0,'col':0,'length_bp':20,'populate_strands':False,'_helix_id':'00000000-0000-4000-8000-000000000001'})
    with pytest.raises(ValueError):
        build_loop('loop-skip-insert',design,{'helix_id':'00000000-0000-4000-8000-000000000001','bp_index':10,'delta':count})

@pytest.mark.skipif(not (ASSETS/'shapes-supp.pdf').exists(), reason='Local publication corpus not installed')
@pytest.mark.parametrize('page,table,name',[(6,14,'D009')])
def test_incomplete_shapes_are_not_published_as_complete(page,table,name):
    with pytest.raises(ValueError,match='blocked'):
        compile_publication((ASSETS/'shapes-supp.pdf').read_bytes(),diagram_page=page,
            table_page=table,name=name,source_path='source.pdf')


@pytest.mark.skipif(not (ASSETS/'shapes-supp.pdf').exists(), reason='Local publication corpus not installed')
def test_d007_preserves_bare_scaffold_ends_without_inventing_staples():
    recipe,evidence=compile_publication((ASSETS/'shapes-supp.pdf').read_bytes(),diagram_page=4,
        table_page=12,name='D007',source_path='source.pdf')
    assert len(evidence['terminal_unpaired_scaffold_sites'])==1680
    assert evidence['staple_precursors']=={'pen_strokes':60,'endpoint_nicks':134,'periodic_seams':0}
    assert len(evidence['classified']['stap'])==144
    assert sum(len(p['sites']) for p in evidence['classified']['stap'])==5880
    assert len(evidence['classified']['scaf'][0]['sites'])==7560
    assert len(recipe['operations'])==1298
    assert not any(o['params'].get('is_periodic_seam') for o in recipe['operations'])


@pytest.mark.skipif(not (ASSETS/'shapes-supp.pdf').exists(), reason='Local publication corpus not installed')
def test_d008_recovers_drawn_unlisted_staple_without_filling_bare_ends():
    recipe,evidence=compile_publication((ASSETS/'shapes-supp.pdf').read_bytes(),diagram_page=5,
        table_page=13,name='D008',source_path='source.pdf')
    assert len(recipe['operations']) == 1186
    assert evidence['sequence_search']['best']['exact_staples']==148
    assert len(evidence['classified']['stap'])==149
    assert len(evidence['derived_staples'])==1
    row=evidence['derived_staples'][0]
    assert row['start']==[27,60] and row['end']==[17,55]
    assert row['sequence']=='AAGTAATAAGCCCACAATGAGGGCTTAATTGAAGTACC'
    assert row['sequence_source']=='derived_from_aligned_scaffold'
    assert evidence['unpaired_scaffold']['unpaired_bases']==2545
    assert len(evidence['terminal_unpaired_scaffold_sites'])==2545

@pytest.mark.parametrize('count',[-2,513,True,1.5])
def test_loop_request_refuses_invalid_counts(count):
    from pydantic import ValidationError
    from backend.api.routes_loop_skip import LoopSkipInsertRequest
    with pytest.raises(ValidationError):
        LoopSkipInsertRequest(helix_id='h',bp_index=10,delta=count)


def test_saved_d005_can_initialize_document_history_without_truncating_recipe():
    from backend.core.models import Design
    from backend.core.document_operations import recipe_inputs
    path=Path('workspace/Shared Designs/D005.nadoc')
    if not path.exists():
        pytest.skip('Published native D005 not installed')
    design=Design.model_validate_json(path.read_bytes())
    source=recipe_inputs(design)
    assert len(source['commands'])==2681
    assert source['root']['kind']=='empty'
    assert any(row['kind']=='loop-skip-insert' and row['params']['delta']==144
               for row in source['commands'])


@pytest.mark.skipif(not (ASSETS/'shapes-supp.pdf').exists(), reason='Local publication corpus not installed')
def test_d009_compiler_carries_accepted_loop_counts_without_clearing_route_blocker(monkeypatch):
    import backend.core.publication_authoring as authoring
    original=authoring.aligned_unpaired_scaffold
    captured={}
    def inspect(classified,insertions,*args,**kwargs):
        captured.update(insertions)
        return original(classified,insertions,*args,**kwargs)
    monkeypatch.setattr(authoring,'aligned_unpaired_scaffold',inspect)
    with pytest.raises(ValueError,match='Incomplete directed routing'):
        authoring.compile_publication((ASSETS/'shapes-supp.pdf').read_bytes(),diagram_page=6,
            table_page=14,name='D009',source_path='source.pdf')
    assert sorted(captured['counts'])==[[30,119,39],[42,119,39]]
    assert captured['unresolved']==[]
    assert captured['represented_scaffold_length']==7703
    assert captured['sequence_length_discrepancy']==1

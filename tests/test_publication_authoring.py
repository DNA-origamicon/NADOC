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
    assert len(ops)==2681
    assert all('import' not in o['kind'] for o in ops)
    loops=[o['params']['delta'] for o in ops if o['kind']=='loop-skip-insert']
    assert loops.count(144)==1 and loops.count(1)==360
    assert evidence['connections']['forced_ligations'] < evidence['connections']['crossovers']/5

@pytest.mark.skipif(not (ASSETS/'twist-supp.pdf').exists(), reason='Local publication corpus not installed')
def test_d006_refuses_missing_lattice_instead_of_inventing_placement():
    with pytest.raises(ValueError,match='lattice'):
        compile_publication((ASSETS/'twist-supp.pdf').read_bytes(),diagram_page=20,
            table_page=39,name='D006',source_path='source.pdf')

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
@pytest.mark.parametrize('page,table,name',[(4,12,'D007'),(5,13,'D008'),(6,14,'D009')])
def test_incomplete_shapes_are_not_published_as_complete(page,table,name):
    with pytest.raises(ValueError,match='blocked'):
        compile_publication((ASSETS/'shapes-supp.pdf').read_bytes(),diagram_page=page,
            table_page=table,name=name,source_path='source.pdf')

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

import pytest
from backend.core.publication_insertion_loops import insertion_plan


@pytest.mark.parametrize('sites,direction', [([(0,0),(0,1),(0,2)],'FORWARD'), ([(0,2),(0,1),(0,0)],'REVERSE')])
def test_scaffold_only_loop_uses_directed_anchor(sites, direction):
    classified={'scaf':[{'sites':sites}], 'stap':[]}
    plan=insertion_plan({'counts':[(0,1,39)]},classified,{(0,1):(19,1)})
    assert not plan['duplex_insertions']
    assert plan['scaffold_loops'][0] | {'basis':None} == {
        'source_helix':0,'source_bp':1,'helix':19,'bp_index':1,
        'length':39,'direction':direction,'basis':None}


def test_paired_and_single_base_insertions_keep_duplex_semantics():
    classified={'scaf':[{'sites':[(0,0),(0,1),(0,2)]}], 'stap':[{'sites':[(0,1)]}]}
    counts=[(0,0,1),(0,1,39)]
    assert insertion_plan({'counts':counts},classified,{})['duplex_insertions']==counts


def test_terminal_loop_is_not_silently_reinterpreted():
    with pytest.raises(ValueError,match='following nucleotide'):
        insertion_plan({'counts':[(0,1,39)]},{'scaf':[{'sites':[(0,0),(0,1)]}],'stap':[]},{})


def test_recorded_loop_preserves_complement_and_replays(tmp_path):
    from tools.design_archive.recorded_authoring import construct
    from scripts.agent_structure_guard import publish, audit
    from backend.core.models import Design
    from backend.core.strand_loops import strand_entries
    from uuid import uuid4
    h,s,t=map(str,(uuid4(),uuid4(),uuid4()))
    def op(kind,params):return {'kind':kind,'label':kind,'params':params,'evidence':['loop integration regression']}
    recipe={'version':1,'name':'Loop integration','lattice':'HONEYCOMB','unresolved':[], 'operations':[
        op('helix-add-at-cell',{'row':0,'col':0,'length_bp':21,'populate_strands':False,'_helix_id':h}),
        op('strand-add',{'_strand_id':s,'strand_type':'scaffold','domains':[{'helix_id':h,'start_bp':0,'end_bp':20,'direction':'FORWARD'}]}),
        op('strand-add',{'_strand_id':t,'strand_type':'staple','domains':[{'helix_id':h,'start_bp':20,'end_bp':0,'direction':'REVERSE'}]}),
        op('strand-loop-set',{'strand_id':s,'helix_id':h,'bp_index':10,'direction':'FORWARD','length':39}),
        op('strand-sequence',{'strand_id':s,'sequence':'A'*11+'T'*39+'C'*10}),
        op('strand-sequence',{'strand_id':t,'sequence':'G'*10+'T'*11}),
    ]}
    design=construct(recipe)
    path=tmp_path/'loop.nadoc';publish(design,path)
    saved=Design.model_validate_json(path.read_bytes())
    assert audit(saved)['status']=='verified'
    scaffold=next(x for x in saved.strands if x.is_scaffold)
    staple=next(x for x in saved.strands if not x.is_scaffold)
    assert len(list(strand_entries(saved,scaffold)))==60
    assert len(list(strand_entries(saved,staple)))==21
    assert scaffold.sequence=='A'*11+'T'*39+'C'*10
    assert not saved.helices[0].loop_skips and not staple.loops

import copy
import pytest
from backend.core.image_crossover_register import square_register_scores, translate_square_indices
from backend.core.image_reconstruction import cadnano_summary


def draft():
    vs=[]
    for num,col in [(0,0),(1,1)]:
        vs.append(dict(num=num,row=0,col=col,scaf=[[-1]*4 for _ in range(32)],stap=[[-1]*4 for _ in range(32)],loop=[0]*32,skip=[0]*32,stap_colors=[]))
    # Right-neighbor scaffold pair at4/5; staple pair at31/0.
    for kind,bp in [('scaf',4),('scaf',5),('stap',31),('stap',0)]:
        vs[0][kind][bp]=[-1,-1,1,bp];vs[1][kind][bp]=[0,bp,-1,-1]
    return {'name':'oracle','vstrands':vs}


def test_register_joint_scaffold_staple_evidence_has_unique_best():
    scores=square_register_scores(draft())
    assert scores[0]['shift']==0
    assert scores[0]['total']==4
    assert scores[1]['total']<4


def test_translation_preserves_graph_and_indels_without_mutation():
    d=draft();d['vstrands'][0]['loop'][4]=2;d['vstrands'][1]['skip'][5]=-1;d['vstrands'][0]['stap_colors']=[[0,123]]
    before=copy.deepcopy(d);t=translate_square_indices(d,29)
    assert d==before
    assert len(t['vstrands'][0]['scaf'])==64
    assert t['vstrands'][0]['scaf'][33]==[-1,-1,1,33]
    assert t['vstrands'][0]['loop'][33]==2
    assert t['vstrands'][1]['skip'][34]==-1
    assert t['vstrands'][0]['stap_colors']==[[29,123]]
    assert cadnano_summary(t)['counts']==cadnano_summary(d)['counts']
    assert cadnano_summary(t)['connectivity_problems']==[]


@pytest.mark.parametrize('shift',[-1,.5,True])
def test_invalid_translation_rejected(shift):
    with pytest.raises(ValueError):translate_square_indices(draft(),shift)

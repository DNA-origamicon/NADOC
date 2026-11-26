"""Unlisted drawn strands and agreement between repeated lattice insets."""
from copy import deepcopy
from pathlib import Path
import pytest
from backend.core.publication_missing_staples import recover_unlisted_staples
from backend.core.publication_lattice_insets import consensus_insets


def fixture(monkeypatch):
    import backend.core.sequences as sequences
    monkeypatch.setattr(sequences,'SCAFFOLD_LIBRARY',[('unit',8,'ACGTGGCA')])
    classified={'scaf':[{'sites':[(0,b) for b in range(8)]}],
                'stap':[{'sites':[(0,b) for b in range(3,-1,-1)]}],
                'unresolved':[{'path_id':9,'sites':[(0,b) for b in range(4,8)]}]}
    return classified, {'counts':[],'unresolved':[]}, {'resolved':True,'length_discrepancy':0,
                    'best':{'reverse':False,'offset':0},'scaffold_name':'unit'}


def test_derive_only_existing_drawn_route_without_counting_as_table_evidence(monkeypatch):
    args=fixture(monkeypatch);original=deepcopy(args)
    result,derived=recover_unlisted_staples(*args)
    assert args==original
    assert not result['unresolved']
    assert result['stap'][-1]['sites']==[(0,b) for b in range(7,3,-1)]
    assert derived[0]['sequence']=='TGCC'
    assert derived[0]['sequence_source']=='derived_from_aligned_scaffold'


@pytest.mark.parametrize('sites',[[(0,b) for b in range(3,8)],[(0,b) for b in range(6,10)],
                                  [(0,4),(0,5),(0,7),(0,6)]])
def test_overlap_unmapped_or_conflicting_direction_remains_unresolved(monkeypatch,sites):
    args=fixture(monkeypatch);args[0]['unresolved'][0]['sites']=sites
    result,derived=recover_unlisted_staples(*args)
    assert not derived and result['unresolved']


@pytest.mark.parametrize('field,value',[('resolved',False),('length_discrepancy',1)])
def test_incomplete_alignment_never_supplies_an_oligo(monkeypatch,field,value):
    args=fixture(monkeypatch);args[2][field]=value
    assert not recover_unlisted_staples(*args)[1]


def fit(circles,labels):
    if set(circles)!=set(labels):return {'resolved':False}
    origin=min(p[0] for p in circles.values())
    return {'resolved':True,'cells':{k:[round(x-origin),round(y)] for k,(x,y,r) in circles.items()}}


def test_translated_insets_require_full_agreement():
    observations=[(i,(x+shift,0,1)) for shift in (0,20) for i,x in enumerate((0,2,4))]
    result=consensus_insets(observations,range(3),fit)
    assert result['resolved'] and result['inset_copies']==2
    observations[-1],observations[-2]=(1,(24,0,1)),(2,(22,0,1))
    assert not consensus_insets(observations,range(3),fit)['resolved']
    assert not consensus_insets(observations[:-1],range(3),fit)['resolved']


def test_duplicate_labels_in_same_inset_remain_blocked():
    assert not consensus_insets([(0,(0,0,1)),(0,(2,0,1))],range(2),fit)['resolved']


@pytest.mark.skipif(not Path('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf').exists(),reason='Local corpus absent')
def test_d009_all_five_insets_agree():
    import pymupdf
    from backend.core.publication_routing import extract_publication_paths
    with pymupdf.open('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf') as doc:
        result=extract_publication_paths(doc[5])['lattice']
    assert result['resolved'] and result['inset_copies']==5 and len(result['cells'])==46

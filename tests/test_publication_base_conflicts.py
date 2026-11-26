import itertools
import pytest
from backend.core.publication_base_conflicts import resolve_base_evidence


@pytest.mark.parametrize('first,second',list(itertools.combinations('TACG',2)))
def test_equal_evidence_uses_preference_in_either_source_order(first,second):
    for table,image in ((first,second),(second,first)):
        r=resolve_base_evidence([{'source':'table','base':table},{'source':'image','base':image}])
        assert r['selected_base']==first and r['severity']=='notice'
        assert r['selection_reason']=='preference_tie_break'
        assert {e['base'] for e in r['evidence']}=={first,second}


def test_stronger_evidence_overrides_preference_and_duplicate_labels_are_not_extra_votes():
    r=resolve_base_evidence([{'source':'table','base':'G','weight':2},
                            *[{'source':'image','base':'T'}]*10])
    assert r['selected_base']=='G' and r['selection_reason']=='stronger_evidence'
    assert r['support']=={'T':1.,'G':2}


def test_absent_image_and_matching_sources_are_not_conflicts():
    for sources in (['table'],['table','image']):
        r=resolve_base_evidence([{'source':s,'base':'C'} for s in sources])
        assert r['selected_base']=='C' and not r['conflict']
    assert resolve_base_evidence([])['selected_base'] is None


@pytest.mark.parametrize('weight',[0,-1,float('nan'),float('inf'),True])
def test_invalid_weights_are_rejected(weight):
    with pytest.raises(ValueError):resolve_base_evidence([{'source':'table','base':'T','weight':weight}])

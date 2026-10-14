"""Ring-mode selection excludes rigid modes and handles mass and sign conventions."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_coupled_ring import ranked_modes


def inventory():
    q=np.eye(6)
    q[:,0]=[1,0,0,1,0,0]
    q[:,1]=[-1,0,0,1,0,0]
    q[:,2]=[0,0,0,0,1,0]
    return q,[1.,4.],['V','V','V','T','R','R'],[0],np.eye(6)


def test_mass_conversion_ranking_and_canonical_sign():
    rows=ranked_modes(*inventory())
    assert [r['mode_column'] for r in rows]==[0,1,2]
    assert rows[0]['ring_participation']==pytest.approx(.8)
    assert rows[1]['ring_participation']==pytest.approx(.8)
    d=np.asarray(rows[1]['direction']).ravel()
    assert d[0]>0 and d[3]<0
    assert np.linalg.norm(d)==pytest.approx(1)
    assert rows[1]['curvature_hartree_bohr2']==pytest.approx(1)


def test_mode_sign_choice_does_not_change_selected_pair():
    args=list(inventory());before=ranked_modes(*args)
    args[0]=args[0].copy();args[0][:,:3]*=-1
    assert before==ranked_modes(*args)


def test_nonpositive_internal_mode_is_not_clipped():
    args=list(inventory());args[-1]=-np.eye(6)
    with pytest.raises(ValueError,match='Nonpositive'):
        ranked_modes(*args)


@pytest.mark.parametrize('index,value',[(1,[0.,4.]),(3,[0,0]),(2,['T']*6)])
def test_invalid_or_insufficient_inventory_rejected(index,value):
    args=list(inventory());args[index]=value
    with pytest.raises(ValueError):ranked_modes(*args)

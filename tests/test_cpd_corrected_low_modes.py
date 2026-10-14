import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_core_low_modes import coupled_subspace


def test_cartesian_directions_recover_coupled_mass_weighted_hessian():
    rng=np.random.default_rng(19)
    mass_sqrt=np.repeat(np.sqrt([1.,12.]),3)
    modes=np.linalg.qr(rng.normal(size=(6,6)))[0][:,:4]
    d=modes/mass_sqrt[:,None]
    norms=np.linalg.norm(d,axis=0)
    q=(d/norms).T
    block=np.diag([.01,.02,.03,.04]);block[0,1]=block[1,0]=.002
    h=(modes@block@modes.T)*mass_sqrt[:,None]*mass_sqrt[None,:]
    hv=np.array([(h@q.T).T]*2)
    result=coupled_subspace(q,norms,hv,1.)
    for scale in result['scales']:
        assert np.allclose(scale['raw_mass_weighted_block'],block,atol=1e-14)
        assert np.allclose(scale['eigenvalues_mass_weighted'],np.linalg.eigvalsh(block))
    assert result['step_difference_spectral_norm']==0
    assert not result['minimum_certified']


def test_negative_coupled_mode_is_retained_without_clipping():
    q=np.eye(4);norms=np.ones(4)
    # Positive diagonals alone do not establish a positive coupled subspace.
    block=np.eye(4);block[0,1]=block[1,0]=2.
    result=coupled_subspace(q,norms,[block,block],1.)
    assert result['scales'][0]['signed_frequencies_cm_inverse'][0]==pytest.approx(-1.)
    assert not result['minimum_certified']


def test_nonfinite_or_unnormalized_directions_are_rejected():
    with pytest.raises(ValueError,match='Invalid Cartesian'):
        coupled_subspace(np.eye(4)*2,np.ones(4),np.ones((2,4,4)),1.)
    with pytest.raises(ValueError,match='Invalid Cartesian'):
        coupled_subspace(np.eye(4),np.ones(4),np.full((2,4,4),np.nan),1.)

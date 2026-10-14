"""Check force signs, units and role isolation before the native core fit."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_core_bonded_fit import (
    role_group,coordinate_gradient,basis,finite_hessian,internal_basis,
)


@pytest.mark.parametrize('ids',[(0,1),(0,1,2)])
def test_internal_coordinate_gradient_matches_energy_difference(ids):
    x=np.array([[1.2,.3,.1],[0.,0.,0.],[-.2,1.1,.4]])
    _,g=coordinate_gradient(x,ids)
    numerical=np.zeros_like(x)
    for j in range(x.size):
        step=np.zeros_like(x);step.ravel()[j]=1e-6
        numerical.ravel()[j]=(coordinate_gradient(x+step,ids)[0]-coordinate_gradient(x-step,ids)[0])/2e-6
    assert np.max(abs(numerical-g))<1e-9
    assert np.max(abs(g.sum(axis=0)))<1e-14
    assert np.max(abs(np.cross(x,g).sum(axis=0)))<1e-14


def test_exchange_ties_do_not_conflate_weld_and_intrabase_bonds():
    weld=role_group(['1:C5','2:C6'])
    assert weld==role_group(['1:C6','2:C5'])
    assert weld!=role_group(['1:C5','1:C6'])
    assert role_group(['1:N1','1:C6','2:C5'])==role_group(['1:C5','2:C6','2:N1'])
    assert role_group(['1:N1','1:C6','2:C5'])!=role_group(['1:C6','1:N1','2:C5'])


def test_equilibrium_shift_response_retains_native_half_k_convention():
    x=np.array([[1.2,.3,.1],[0.,0.,0.],[-.2,1.1,.4]])
    terms=[dict(indices=[0,1],k=600.,equilibrium=1.1),dict(indices=[0,1,2],k=80.,equilibrium=1.5)]
    groups=[dict(scale=.02,terms=[terms[0]]),dict(scale=np.radians(4),terms=[terms[1]])]
    z=np.array([.8,-.6]);e,gb=basis(x,groups)
    before=after=0.;dg=np.zeros_like(x)
    for group,delta in zip(groups,z,strict=True):
        t=group['terms'][0];c,g=coordinate_gradient(x,t['indices']);r=t['equilibrium'];dr=delta*group['scale']
        before+=.5*t['k']*(c-r)**2;after+=.5*t['k']*(c-r-dr)**2
        dg+=t['k']*((c-r-dr)-(c-r))*g
    constant=sum(.5*g['terms'][0]['k']*((g['terms'][0]['equilibrium']+v*g['scale'])**2-g['terms'][0]['equilibrium']**2) for g,v in zip(groups,z,strict=True))
    assert after-before==pytest.approx(e@z+constant,abs=1e-12)
    assert np.max(abs(dg.ravel()-gb@z))<1e-12


def test_internal_projection_and_finite_hessian_preserve_harmonic_curvature():
    x=np.array([[0.,0.,0.],[1.,.1,.2],[.2,1.,.3],[.1,.4,1.]])
    q=internal_basis(x)
    assert q.shape==(12,6)
    assert np.max(abs(q.T@q-np.eye(6)))<1e-14
    rng=np.random.default_rng(3);matrix=rng.normal(size=(12,12));matrix=matrix.T@matrix
    h,asym=finite_hessian(lambda y:matrix@y.ravel(),x)
    assert np.max(abs(h-matrix))<1e-9 and asym<1e-9
    # Tensor-valued derivatives must retain parameter as the final axis.
    hh,_=finite_hessian(lambda y:np.stack([matrix@y.ravel(),2*matrix@y.ravel()],axis=1),x)
    assert hh.shape==(12,12,2) and np.max(abs(hh[:,:,1]-2*matrix))<1e-9


def test_degenerate_coordinates_rejected():
    with pytest.raises(ValueError):coordinate_gradient(np.zeros((3,3)),[0,1])
    with pytest.raises(ValueError):coordinate_gradient(np.array([[1.,0.,0.],[0.,0.,0.],[-1.,0.,0.]]),[0,1,2])

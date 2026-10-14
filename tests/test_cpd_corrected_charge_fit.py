"""Charge fitting uses checked energy units and an explicit squared penalty weight."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_core_charge_fit import water_terms,radial_minimum,evaluate
from backend.parameterization.photoproduct_nonbonded_fit import _interaction_row


def test_vectorized_contact_energy_matches_scalar_reference():
    xyz=np.array([[0.,0.,0.],[0.,1.,0.]])
    lj=np.array([[-.12,1.8],[-.02,.5]])
    water=np.array([[[3.,0.,0.],[2.1,0.,0.],[3.2,.9,0.]],[[4.,0.,0.],[3.1,0.,0.],[4.2,.9,0.]]])
    wlj=np.array([[-.1521,1.7682],[-.046,.2245],[-.046,.2245]])
    rows,energies=water_terms(xyz,lj,water,wlj)
    nb={t:dict(epsilon_kcal_mol=v[0],rmin_half_angstrom=v[1]) for t,v in zip(['OGTIP3','HGTIP3'],wlj)}
    for i in range(2):
        r,e=_interaction_row(xyz,[dict(epsilon_kcal_mol=v[0],rmin_half_angstrom=v[1]) for v in lj],water[i],nb)
        assert np.allclose(rows[i],r,rtol=0,atol=1e-12)
        assert energies[i]==pytest.approx(e,abs=1e-12)


@pytest.mark.parametrize('value',[0,float('nan')])
def test_invalid_contact_rejected(value):
    with pytest.raises(ValueError):water_terms(np.zeros((1,3)),np.array([[-.1,1.]]),np.full((1,3,3),value),np.ones((3,2)))


def test_mm_radial_minimum_and_unbracketed_endpoint():
    r=np.arange(1.1,5.01,.02)
    x,e,bracketed=radial_minimum(r,4*(r-1.854)**2-5)
    assert bracketed and x==pytest.approx(1.854) and e==pytest.approx(-5)
    assert radial_minimum(r,-r)[2] is False


def test_regularization_coefficient_is_point_two_in_squared_objective():
    r=np.array([1.7,1.9,2.1]);curves=[dict(site=str(i),target_energy_kcal_mol=-5,target_distance_angstrom=1.9) for i in range(6)]
    meta=dict(atom_keys=[str(i) for i in range(36)],curves=curves)
    a=dict(q0=np.zeros(36),mapping=np.eye(36,10),mm_distances=r,rows=np.zeros((6,3,36)),lj_energy=np.tile((r-1.9)**2-5,(6,1)),xyz=np.zeros((36,3)),dipole_target=np.zeros(3),esp_matrix=np.zeros((2,36)),esp_values=np.ones(2))
    residual,_=evaluate(np.full(10,.1),meta,a)
    assert residual@residual==pytest.approx(.2)
    data_only,_=evaluate(np.full(10,.1),meta,a,False)
    assert data_only@data_only==pytest.approx(0,abs=1e-25)

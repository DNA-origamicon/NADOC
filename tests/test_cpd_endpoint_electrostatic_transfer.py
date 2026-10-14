"""Unit/identity guards for the finite sugar-endpoint charge diagnostic."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_endpoint_electrostatic_transfer import (
    BOHR, electrostatic_metrics, transfer_charges,
)


def test_neutral_dipole_and_esp_have_correct_units_and_translation_invariance():
    xyz = np.array([[0.,0.,0.], [1.,0.,0.]])
    q = np.array([-1.,1.])
    grid = np.array([[2.,0.,0.], [3.,0.,0.]])
    esp = BOHR * np.array([.5, 1./6])
    dipole = np.array([1./BOHR, 0., 0.])
    masks = {'all':[True,True], 'near':[True,False]}
    a = electrostatic_metrics(xyz,q,grid,esp,dipole,masks)
    b = electrostatic_metrics(xyz+17,q,grid+17,esp,dipole,masks)
    assert a == b
    assert a['dipole_vector_error_debye'] < 1e-14
    assert a['mm_dipole_magnitude_debye'] == pytest.approx(4.80320467,rel=1e-7)
    assert a['esp_regions']['all']['rmse_au'] < 1e-14


@pytest.mark.parametrize('charge,grid', [([0.,1.],[[2.,0.,0.]]),
                                       ([-1.,1.],[[0.,0.,0.]]),
                                       ([-1.,1.],[[float('nan'),0.,0.]])])
def test_invalid_physical_comparisons_rejected(charge,grid):
    with pytest.raises(ValueError):
        electrostatic_metrics([[0.,0.,0.],[1.,0.,0.]],charge,grid,[0.],[0.,0.,0.],{'all':[True]})


def test_transfer_preserves_core_and_sugar_even_with_distracting_template_entries():
    core={'1:N1':-.4, '2:N1':.4}
    sugar={"C1'":{'charge_e':.16},"H1'":{'charge_e':-.16},'N1':{'charge_e':9.}}
    q=transfer_charges(['1:N1',"1:C1'",'2:N1',"1:H1'"],core,sugar)
    assert q.tolist() == [-.4,.16,.4,-.16]


@pytest.mark.parametrize('keys', [['1:N1','1:N1'],['1:UNKNOWN'],["2:C1'"]])
def test_transfer_rejects_duplicate_unknown_or_unplanned_sugar(keys):
    with pytest.raises(ValueError):
        transfer_charges(keys,{'1:N1':0.},{"C1'":{'charge_e':0.}})

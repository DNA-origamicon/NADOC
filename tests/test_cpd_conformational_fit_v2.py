"""Reference identity and Fourier conventions for the isolated campaign fit."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.conformational_fit_v2 import relative, features, energy_summary


def test_shared_reference_retains_energy_gap_between_branches():
    records=[dict(case_id='original',reference_case_id='lower',branch='original',qm_relative_kcal_mol=3.),
             dict(case_id='lower',reference_case_id='lower',branch='lower',qm_relative_kcal_mol=0.),
             dict(case_id='remote',reference_case_id='lower',branch='remote',qm_relative_kcal_mol=-4.)]
    np.testing.assert_allclose(relative([103.,100.,96.],records),[3.,0.,-4.])
    assert energy_summary([103.,100.,96.],records)['energy_passed']
    assert not energy_summary([100.,100.,100.],records)['energy_passed']


def test_reference_identity_not_independently_chosen_mm_minimum():
    records=[dict(case_id='a',reference_case_id='a'),dict(case_id='b',reference_case_id='a')]
    np.testing.assert_allclose(relative([3.,0.],records),[0.,-3.])
    with pytest.raises(KeyError): relative([3.], [dict(case_id='b',reference_case_id='absent')])


def test_matrix_and_energy_references_are_identical():
    records=[dict(case_id='a',reference_case_id='b'),dict(case_id='b',reference_case_id='b')]
    matrix=np.array([[1.,2.],[3.,4.]])
    shifts=np.array([.2,-.7])
    np.testing.assert_allclose(relative(matrix@shifts,records),relative(matrix,records)@shifts)


def test_zero_pi_phase_cosines_and_absent_endpoint():
    x=np.array([[0.,1.,0.],[0.,0.,0.],[1.,0.,0.],[1.,0.,1.]])
    names=['a','b','c','d']
    variables=[dict(names=names,periodicity=i) for i in (1,2,3)]
    variables.append(dict(names=['e','f','g','h'],periodicity=1))
    np.testing.assert_allclose(features(x,names,variables),[0.,-1.,0.,0.],atol=1e-14)
    reversed_vars=[dict(names=names[::-1],periodicity=i) for i in (1,2,3)]
    np.testing.assert_allclose(features(x,names,reversed_vars),[0.,-1.,0.],atol=1e-14)

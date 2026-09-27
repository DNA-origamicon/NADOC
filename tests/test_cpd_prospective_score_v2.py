"""Scientific scoring invariants: common references and complete membership."""
import pytest
from experiments.cpd_anti_additive.score_prospective_v2 import aggregate, score_energy, EH


def test_registered_reference_preserves_signed_relative_energies():
    ref=dict(case_id='fixed-reference',qm_energy_hartree=-100.,mm_energy_kcal=34.)
    score=score_energy(-100.-2/EH,31.,ref)
    assert score['qm_relative_kcal']==pytest.approx(-2.)
    assert score['mm_relative_kcal']==-3.
    assert score['residual_kcal']==pytest.approx(-1.)
    assert score['reference_case_id']=='fixed-reference'


def test_partial_or_failed_target_cannot_disappear_from_acceptance():
    ids=['a','b','c','d']
    rows=[dict(case_id=k,state='scored',energy=dict(residual_kcal=0.),branch_descriptor_match=True) for k in ids]
    assert aggregate(rows,ids)['energy_passed']
    assert not aggregate(rows[:-1],ids)['all_four_scored']
    rows[-1]=dict(case_id='d',state='MM_failed')
    assert not aggregate(rows,ids)['energy_passed']


def test_maximum_residual_and_geometry_are_independent_gates():
    ids=['a','b','c','d']
    rows=[dict(case_id=k,state='scored',energy=dict(residual_kcal=0.),branch_descriptor_match=True) for k in ids]
    rows[0]['branch_descriptor_match']=False
    assert aggregate(rows,ids)['energy_passed']
    assert not aggregate(rows,ids)['geometry_descriptors_passed']
    rows[0]['energy']['residual_kcal']=2.01
    assert not aggregate(rows,ids)['energy_passed']


def test_duplicate_unknown_and_nonfinite_targets_are_rejected():
    row=dict(case_id='a',state='scored',energy=dict(residual_kcal=float('nan')),branch_descriptor_match=True)
    with pytest.raises(ValueError):aggregate([row],['a'])
    with pytest.raises(ValueError):aggregate([row,row],['a'])
    with pytest.raises(ValueError):aggregate([row],['b'])
    with pytest.raises(ValueError):score_energy(float('nan'),0.,dict(case_id='r',qm_energy_hartree=0.,mm_energy_kcal=0.))

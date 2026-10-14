"""Guard torsion projection and conformer descriptors for fixed-angle MM."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_mm_endpoint_profile import (
    torsion_jacobian,projected_metrics,heavy_torsions,descriptors,
)


@pytest.mark.parametrize('epsilon',[0.,1e-8,-1e-8,.4])
def test_projection_removes_normal_force_even_across_angle_wrap(epsilon):
    x=np.array([[1.,0.,0.],[0.,0.,0.],[0.,0.,1.],[-1.,epsilon,1.]])
    jac=torsion_jacobian(x,[0,1,2,3])
    assert np.linalg.norm(jac)<10
    assert np.max(abs(jac.sum(axis=0)))<1e-8
    gradient=2*jac+np.tile([.1,.2,.3],(4,1))
    metrics=projected_metrics(x,gradient,[0,1,2,3])
    assert metrics['max_projected_atom_gradient_kcal_mol_angstrom']==pytest.approx(np.sqrt(.14),abs=1e-8)
    assert abs(metrics['tangent_dot_normal'])<1e-12
    assert projected_metrics(x,7*jac,[0,1,2,3])['max_projected_atom_gradient_kcal_mol_angstrom']<1e-12


def test_heavy_proper_inventory_is_deduplicated_and_excludes_hydrogens():
    fixture=dict(atom_keys=['A','B','C','D','H'],elements=['C','C','C','C','H'],bonds=[[0,1],[1,2],[2,3],[2,4]])
    assert heavy_torsions(fixture)==[(0,1,2,3)]


def test_descriptors_detect_local_torsion_change_after_global_alignment():
    fixture=dict(atom_keys=['A','B','C','D'],elements=['C']*4,bonds=[[0,1],[1,2],[2,3]])
    x=np.array([[1.,0.,0.],[0.,0.,0.],[0.,0.,1.],[-1.,0.,1.]])
    y=x.copy();y[3]=[0.,-1.,1.]
    report=descriptors(x,y+5,fixture,heavy_torsions(fixture))
    assert report['maximum_heavy_proper_change_degrees']==pytest.approx(90.)
    assert not report['descriptor_match']


def test_invalid_projection_rejected():
    with pytest.raises(ValueError):torsion_jacobian(np.zeros((4,3)),[0,1,1,3])
    with pytest.raises(ValueError):torsion_jacobian(np.full((4,3),np.nan),[0,1,2,3])


def test_tuple_and_list_atom_indices_have_identical_projection():
    x=np.array([[1.,0.,0.],[0.,0.,0.],[0.,0.,1.],[-1.,.2,1.]])
    assert np.array_equal(torsion_jacobian(x,(0,1,2,3)),torsion_jacobian(x,[0,1,2,3]))

"""Geometry diagnostics must preserve handedness and coordinate units."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_bonded_baseline import (
    proper_rmsd, angle_degrees, geometry_differences,
)


def test_proper_alignment_removes_translation_rotation_but_not_reflection():
    x=np.array([[0.,0.,0.],[1.,0.,0.],[0.,2.,0.],[0.,0.,3.]])
    rotation=np.array([[0.,1.,0.],[-1.,0.,0.],[0.,0.,1.]])
    assert proper_rmsd(x,x@rotation+7,['C']*4)<1e-14
    assert proper_rmsd(x,x*np.array([-1,1,1]),['C']*4)>.5


def test_heavy_alignment_excludes_hydrogen_motion():
    x=np.array([[0.,0.,0.],[1.,0.,0.],[0.,2.,0.],[0.,0.,3.],[9.,9.,9.]])
    y=x.copy();y[-1]+=42
    assert proper_rmsd(x,y,['C','C','N','O','H'])<1e-14


def test_geometry_differences_report_actual_bond_and_angle_units():
    x=np.array([[1.,0.,0.],[0.,0.,0.],[0.,1.,0.]])
    y=np.array([[1.1,0.,0.],[0.,0.,0.],[.5,np.sqrt(.75),0.]])
    fixture=dict(atom_keys=['1:C','1:N','1:O'],elements=['C','N','O'],bonds=[[0,1],[1,2]],angles=[[0,1,2]])
    result=geometry_differences(x,y,fixture)
    assert result['max_bond_error_angstrom']==pytest.approx(.1)
    assert result['angles'][0]['error_degrees']==pytest.approx(-30.)


def test_degenerate_angle_rejected():
    with pytest.raises(ValueError):angle_degrees(np.zeros((3,3)),[0,1,2])

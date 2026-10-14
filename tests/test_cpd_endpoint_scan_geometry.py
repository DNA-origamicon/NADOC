import numpy as np
import pytest
from experiments.cpd_anti_additive.endpoint_scan_geometry import rotate_sugar,torsion,wrapped,constraint_metrics


def test_rotation_moves_only_cut_component_and_keeps_bonds():
    x=np.array([[0.,1.,0.],[0.,0.,0.],[1.,0.,0.],[1.,0.,1.]])
    y,ids=rotate_sugar(x,[(0,1),(1,2),(2,3)],[0,1,2,3],-15)
    assert ids==[0,1]
    np.testing.assert_allclose(y[2:],x[2:])
    assert wrapped(torsion(y,[0,1,2,3])-torsion(x,[0,1,2,3]))==pytest.approx(-15)


def test_ring_axis_is_rejected():
    x=np.array([[0.,1.,0.],[0.,0.,0.],[1.,0.,0.],[1.,0.,1.]])
    with pytest.raises(ValueError,match='ring-bond'):
        rotate_sugar(x,[(0,1),(1,2),(2,3),(3,0)],[0,1,2,3],15)


def test_reaction_force_removed_but_constraint_error_cannot_pass():
    x=np.array([[0.,1.,0.],[0.,0.,0.],[1.,0.,0.],[1.,0.,1.]])
    spec=dict(indices=[0,1,2,3],target_degrees=torsion(x,[0,1,2,3]))
    _,normal=constraint_metrics(x,np.zeros_like(x),spec)
    report,_=constraint_metrics(x,normal,spec)
    assert report['passed'] and report['max_atom_gradient_au']<1e-10
    report,_=constraint_metrics(x,np.zeros_like(x),{**spec,'target_degrees':spec['target_degrees']+1})
    assert not report['passed']

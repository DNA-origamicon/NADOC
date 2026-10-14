"""Released core forces must enter the stationarity gate."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.alternate_qm_release_constraints import geometry_constraints, stationarity
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion, constraint_metrics


def fixture():
    x=np.array([[1.,.2,.7],[0.,0.,0.],[.1,1.1,0.],[.2,1.3,1.2],[2.,1.,1.]])
    spec=dict(indices=[0,1,2,3],target_degrees=torsion(x,[0,1,2,3]),tolerance_degrees=.01)
    return x,spec


def test_core_coordinate_motion_is_allowed_but_chi_change_is_rejected():
    x,spec=fixture();trial=x.copy();trial[4,0]+=.2
    assert geometry_constraints(trial,x,[],spec)['fixed_atom_count']==0
    trial[3,0]+=.1
    with pytest.raises(ValueError,match='chi target'):geometry_constraints(trial,x,[],spec)


def test_released_force_is_counted_and_matches_independent_chi_projection():
    x,spec=fixture();g=np.zeros_like(x);g[4,0]=.001
    result=stationarity(x,g,[],list(range(len(x))),spec)
    independent,_=constraint_metrics(x,g,spec)
    assert not result['passed']
    assert result['max_free_projected_atom_gradient_au']==pytest.approx(.001)
    assert result['rms_free_projected_atom_gradient_au']==pytest.approx(.001/np.sqrt(5))
    assert result['max_free_projected_atom_gradient_au']==pytest.approx(independent['max_atom_gradient_au'])


def test_attempt_to_retain_hidden_fixed_atoms_or_omit_force_components_fails():
    x,spec=fixture();g=np.zeros_like(x)
    with pytest.raises(ValueError,match='must not fix'):geometry_constraints(x,x,[4],spec)
    for fixed,free in [([4],[0,1,2,3]),([],[0,1,2,3])]:
        with pytest.raises(ValueError,match='All endpoint atoms'):stationarity(x,g,fixed,free,spec)


def test_nonfinite_geometry_is_rejected():
    x,spec=fixture();trial=x.copy();trial[4,0]=np.nan
    with pytest.raises(ValueError,match='Invalid'):geometry_constraints(trial,x,[],spec)

"""Independent Cartesian projection when core atoms and chi are constrained."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_fixed_core_boundary import free_projection
from experiments.cpd_anti_additive.corrected_mm_endpoint_profile import torsion_jacobian


def geometry():
    return np.array([[1.,.2,.7],[0.,0.,0.],[.1,1.1,0.],[.2,1.3,1.2],[2.,1.,1.]])


def test_fixed_components_and_chi_normal_are_removed_without_changing_tangent():
    x=geometry();fixed=[2,3];chi=[0,1,2,3]
    g=np.arange(15,dtype=float).reshape(5,3);original=g.copy()
    projected=free_projection(x,g,fixed,chi)
    normal=torsion_jacobian(x,chi);normal[fixed]=0.
    assert np.array_equal(g,original)
    assert np.max(abs(projected[fixed]))==0.
    assert abs(np.sum(projected*normal))<1e-12
    assert np.max(abs(free_projection(x,projected,fixed,chi)-projected))<1e-12
    # An unrelated free atom retains all three of its force components.
    assert np.array_equal(projected[4],g[4])


def test_projection_matches_full_constraint_nullspace():
    x=geometry();fixed=[2,3];chi=[0,1,2,3]
    rows=[torsion_jacobian(x,chi).ravel()]
    for i in fixed:
        for axis in range(3):
            row=np.zeros_like(x);row[i,axis]=1.;rows.append(row.ravel())
    _,s,v=np.linalg.svd(rows,full_matrices=True);q=v[len(s):].T
    g=np.sin(np.arange(15)).reshape(5,3)
    assert np.max(abs(free_projection(x,g,fixed,chi).ravel()-q@(q.T@g.ravel())))<1e-12


def test_large_fixed_forces_do_not_change_free_stationarity():
    x=geometry();g=np.zeros_like(x);g[[2,3]]=1e8
    assert np.max(abs(free_projection(x,g,[2,3],[0,1,2,3])))==0.


def test_redundant_or_invalid_constraints_rejected():
    x=geometry();g=np.zeros_like(x)
    for fixed in ([2,2],[-1],[5],[0,1,2,3]):
        with pytest.raises(ValueError):free_projection(x,g,fixed,[0,1,2,3])

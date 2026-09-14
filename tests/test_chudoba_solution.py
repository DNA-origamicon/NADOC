import numpy as np
import pytest

from experiments.peg_chudoba.solution import (
    initial_solution,molecular_pressure,nonbonded_energy,NA,R_KJ,
)


@pytest.mark.parametrize('zero_tail',[False,True])
def test_molecular_virial_is_volume_derivative(zero_tail):
    xyz,box=initial_solution(9,4,40,77)
    n=9;t=294
    chains=xyz.reshape(-1,n,3);centers=chains.mean(axis=1)
    offsets=chains-centers[:,None,:]
    h=1e-5
    def energy(log_volume):
        scale=np.exp(log_volume/3)
        positions=(centers[:,None,:]*scale+offsets).reshape(-1,3)
        return nonbonded_energy(positions,n,box*scale,t,zero_tail=zero_tail)
    derivative=(energy(h)-energy(-h))/(2*h)
    expected=(4*R_KJ*t-derivative)/box**3*1e27/NA
    assert molecular_pressure(xyz,n,box,t,zero_tail=zero_tail)==pytest.approx(expected,rel=2e-7)


def test_packing_preserves_bonds_and_angles():
    xyz,box=initial_solution(18,8,50,91)
    bonds=np.diff(xyz.reshape(-1,18,3),axis=1)
    assert np.allclose(np.linalg.norm(bonds,axis=2),.33)
    assert np.allclose(-np.sum(bonds[:,:-1]*bonds[:,1:],axis=2)/.33**2,np.cos(np.deg2rad(130)))

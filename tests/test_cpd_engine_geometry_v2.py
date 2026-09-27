"""Check chirality and broken-bond detection with OpenMM mass units."""

from types import SimpleNamespace as NS

import numpy as np
from openmm import unit as u

from experiments.cpd_anti_additive.prepare_engine_v2 import geometry_check


def tetrahedron():
    atoms = [NS(idx=i, mass=(12.011 if i==0 else 1.008)*u.dalton) for i in range(5)]
    psf = NS(bond_list=[NS(atom1=atoms[0], atom2=a) for a in atoms[1:]])
    xyz = np.array([[0, 0, 0], [1, 1, 1], [-1, -1, 1], [-1, 1, -1], [1, -1, -1]])/np.sqrt(3)
    return psf, xyz


def test_preserves_rigid_geometry_and_rejects_chirality_inversion():
    psf, xyz = tetrahedron()
    unchanged = geometry_check(psf, xyz, xyz+[2., 3., 4.])
    assert unchanged['stereo_preserved'] and unchanged['graph_distances_passed']
    reflected = geometry_check(psf, xyz, xyz*[1, 1, -1])
    assert not reflected['stereo_preserved'] and reflected['graph_distances_passed']


def test_rejects_broken_bonds_without_requiring_inversion():
    psf, xyz = tetrahedron()
    stretched = geometry_check(psf, xyz, xyz*2)
    assert stretched['stereo_preserved'] and not stretched['graph_distances_passed']

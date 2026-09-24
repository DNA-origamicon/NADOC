"""Sugar audit rejects wrong stereoisomers even when they match a starting seed."""
import numpy as np
import pytest

from experiments.cpd_drude_recovery.audit_repaired_fragment_qm import sugar_checks


def fixture():
    names = [f'1:{n}' for n in ["O4'", "C2'", 'N1', "H1'", "C4'", "O3'", "H3'", "C3'", "C5'", "H4'"]]
    xyz = np.random.default_rng(17).normal(size=(len(names), 3))
    references = []
    for center, neighbors in [("C1'", [0,1,2,3]), ("C3'", [1,4,5,6]), ("C4'", [0,7,8,9])]:
        a,b,c,d = xyz[neighbors]
        references.append({'center':f'1:{center}', 'reference_volume':float(np.linalg.det(np.array([b-a,c-a,d-a])))})
    return xyz, names, references


def test_native_source_chirality_is_rotation_invariant():
    xyz, names, refs = fixture()
    rotated = xyz @ np.array([[0,1,0],[-1,0,0],[0,0,1]]) + 5
    assert all(r['preserved'] for r in sugar_checks(rotated,names,1,refs))


def test_inherited_mirror_fails_despite_seed_continuity():
    xyz, names, refs = fixture()
    wrong_seed = xyz.copy()
    wrong_seed[:,0] *= -1
    optimized = wrong_seed.copy()
    assert np.array_equal(optimized,wrong_seed)
    assert not any(r['preserved'] for r in sugar_checks(optimized,names,1,refs))


def test_planar_center_and_nonfinite_coordinates_fail():
    xyz, names, refs = fixture()
    xyz[3] = xyz[0]
    assert not sugar_checks(xyz,names,1,refs)[0]['preserved']
    xyz[3,0] = np.nan
    with pytest.raises(ValueError,match='Invalid coordinates'):
        sugar_checks(xyz,names,1,refs)

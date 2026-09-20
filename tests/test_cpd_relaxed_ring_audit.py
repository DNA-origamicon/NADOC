"""Geometry audit must distinguish constrained geometry from chirality retention."""

import numpy as np
import pytest

from backend.parameterization.photoproduct_bonded_fit_plan import _dihedral
from experiments.cpd_drude_recovery.audit_relaxed_ring import geometry_checks


def fixture_geometry():
    xyz = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [1.0, 1.0, 1.0]])
    names = ["a", "b", "c", "d"]
    stereo = [
        {
            "stereocenter": "a",
            "ordered_atoms_candidate": names,
            "observed_signed_volume": 1.0,
        }
    ]
    return xyz, names, stereo


def test_reference_and_periodic_angle_equivalence():
    xyz, names, stereo = fixture_geometry()
    result = geometry_checks(
        xyz,
        xyz,
        names,
        [(0, 1), (1, 2), (2, 3)],
        stereo,
        [0, 1, 2, 3],
        _dihedral(*xyz) + 360,
    )
    assert result["constraint_satisfied"]
    assert result["all_stereo_preserved"]
    assert result["maximum_reference_bond_change_angstrom"] == 0


def test_mirror_can_meet_torsion_but_fails_stereochemistry():
    xyz, names, stereo = fixture_geometry()
    mirror = xyz.copy()
    mirror[:, 2] *= -1
    result = geometry_checks(
        mirror, xyz, names, [(0, 1)], stereo, [0, 1, 2, 3], _dihedral(*mirror)
    )
    assert result["constraint_satisfied"]
    assert not result["all_stereo_preserved"]


def test_nonfinite_geometry_is_rejected():
    xyz, names, stereo = fixture_geometry()
    bad = xyz.copy()
    bad[0, 0] = np.nan
    with pytest.raises(ValueError, match="Invalid relaxed geometry"):
        geometry_checks(bad, xyz, names, [(0, 1)], stereo, [0, 1, 2, 3], 90)

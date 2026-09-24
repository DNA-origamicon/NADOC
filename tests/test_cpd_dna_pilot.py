"""Units and geometry checks for the isolated DNA pilot's input and analysis."""

import numpy as np

from backend.core.namd_solvate import _Water
from experiments.cpd_published_comparator.dna_replicas import ideal_water
from experiments.cpd_published_comparator.analyze_dna_replicas import (
    aligned_rmsd,
    signed_volume,
)


def test_spc_water_is_converted_to_charmm_tip3p_geometry():
    water = ideal_water(_Water(1, 2, 3, 1.1, 2, 3, 0.96667, 2.09428, 3))
    oxygen = np.array([water.ox, water.oy, water.oz])
    a = np.array([water.h1x, water.h1y, water.h1z]) - oxygen
    b = np.array([water.h2x, water.h2y, water.h2z]) - oxygen
    np.testing.assert_array_equal(oxygen, [1, 2, 3])
    np.testing.assert_allclose(
        [np.linalg.norm(a), np.linalg.norm(b)], 0.09572, atol=1e-12
    )
    np.testing.assert_allclose(
        np.degrees(np.arccos(a @ b / np.linalg.norm(a) / np.linalg.norm(b))),
        104.52,
        atol=1e-10,
    )


def test_alignment_removes_rigid_motion_but_does_not_hide_mirror_inversion():
    x = np.array([[0.0, 0, 0], [1, 0, 0], [0, 2, 0], [0, 0, 3]])
    rotation = np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]])
    assert aligned_rmsd(x @ rotation + 12, x) < 1e-12
    mirror = x * [-1, 1, 1]
    assert aligned_rmsd(mirror, x) > 0.1
    assert signed_volume(x, [0, 1, 2, 3]) * signed_volume(mirror, [0, 1, 2, 3]) < 0

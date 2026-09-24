import numpy as np
from experiments.cpd_published_comparator.localize_dna_drift import fit, torsion


def test_subset_fit_retains_distal_deformation():
    ref = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [4, 4, 4]])
    x = ref.copy()
    x[-1, 0] += 2
    rotation = np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]])
    result = fit(x @ rotation + 12, ref, np.arange(4))
    np.testing.assert_allclose(result[:4], ref[:4], atol=1e-12)
    np.testing.assert_allclose(result[-1] - ref[-1], [2, 0, 0], atol=1e-12)


def test_signed_torsion_distinguishes_mirror():
    x = np.array([[0.0, 1, 0], [0, 0, 0], [1, 0, 0], [1, 0, 1]])
    assert abs(torsion(x)) == 90
    assert torsion(x) == -torsion(x * [1, 1, -1])

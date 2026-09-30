import numpy as np

from tools.trajectory_padding_audit import envelope, rotation


def test_alignment_removes_rigid_rotation_without_changing_shape():
    reference = np.random.default_rng(7).normal(size=(100, 3))
    reference -= reference.mean(0)
    angle = .7
    turn = np.array([[np.cos(angle), -np.sin(angle), 0],
                     [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    moving = reference @ turn
    np.testing.assert_allclose(moving @ rotation(moving, reference), reference, atol=1e-12)


def test_three_sigma_padding_adds_fluctuations_to_solvent_gap():
    mean = np.array([[-10., -20., -30.], [10., 20., 30.]])
    # Sample stddev exactly 2 Angstrom on each coordinate.
    result = envelope(mean, np.full((2, 3), 4. * 9), 10, mean)
    np.testing.assert_allclose(result['fluctuation_padding_per_axis_nm'], [.6]*3)
    np.testing.assert_allclose(result['padding_from_mean_for_4nm_gap_nm'], [2.6]*3)
    np.testing.assert_allclose(result['box_for_4nm_gap_nm'], [7.2, 9.2, 11.2])

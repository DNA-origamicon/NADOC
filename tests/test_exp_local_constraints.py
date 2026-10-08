"""Independent derivative oracle for rigid bond/angle reconstruction."""

import numpy as np
from backend.core.exp_local_constraints import objective, coordinates


def test_rigid_objective_gradient_matches_coordinate_finite_differences():
    ri = np.repeat(np.arange(2), 3)
    centers = np.array([[0.0, 0.0, 0.0], [0.4, 0.1, 0.1]])
    offsets = np.array(
        [
            [-0.1, 0, 0],
            [0.1, 0, 0],
            [0, 0.1, 0.1],
            [-0.1, 0, 0],
            [0.1, 0, 0],
            [0, 0.1, 0.1],
        ]
    )
    bonds = np.array([[1, 3]])
    angles = np.array([[0, 1, 3], [1, 3, 4]])
    target = np.cos(np.radians([120.0, 110.0]))
    pairs = np.array([[2, 3]])
    p = np.array(
        [[0.02, -0.03, 0.01, 0.11, -0.08, 0.09], [-0.02, 0.01, -0.01, -0.1, 0.07, 0.04]]
    ).ravel()
    args = (offsets, ri, centers, bonds, angles, target, pairs)
    _, actual = objective(p, *args)
    expected = []
    for i in range(len(p)):
        step = np.zeros_like(p)
        step[i] = 1e-6
        expected.append(
            (objective(p + step, *args)[0] - objective(p - step, *args)[0]) / 2e-6
        )
    np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-7)


def test_rigid_projection_never_changes_internal_distances_or_chirality():
    ri = np.repeat(np.arange(2), 4)
    tetra = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0], [0, 0, 0.1]])
    offsets = np.tile(tetra, (2, 1))
    centers = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    p = np.array([[1, 2, 3, 0.4, 0.2, -0.3], [-1, 0, 2, 0.1, -0.5, 0.7]])
    xyz, _ = coordinates(p, offsets, ri, centers)
    for i in range(2):
        q = xyz[ri == i]
        assert np.linalg.det(q[1:] - q[0]) > 0
        np.testing.assert_allclose(
            np.linalg.norm(q[:, None] - q[None, :], axis=-1),
            np.linalg.norm(tetra[:, None] - tetra[None, :], axis=-1),
            atol=1e-14,
        )


def test_deepsnupi_c1_observable_preserves_native_offset_and_rigid_motion():
    from scipy.spatial.transform import Rotation
    from tools.evaluate_exp_local import decorate_prediction

    initial = np.array(
        [
            [0, 0, 0, 0, 0, 0],
            [1, 0, 0, 0.2, 0, 0],
            [0, 1, 0, 0, 0.3, 0],
            [0, 0, 1, 0, 0, 0.4],
        ],
        dtype=float,
    )
    native = initial[:, :3] + [0.08, 0.03, -0.04]
    np.testing.assert_allclose(
        decorate_prediction(initial, initial, native, initial[:, :3]),
        native,
        atol=1e-14,
    )
    rot = Rotation.from_rotvec([0.3, -0.2, 0.1])
    delta = np.array([2.0, 3.0, 4.0])
    prediction = initial.copy()
    prediction[:, :3] = rot.apply(initial[:, :3]) + delta
    prediction[:, 3:] = (rot * Rotation.from_rotvec(initial[:, 3:])).as_rotvec()
    np.testing.assert_allclose(
        decorate_prediction(initial, prediction, native, initial[:, :3]),
        rot.apply(native) + delta,
        atol=1e-14,
    )

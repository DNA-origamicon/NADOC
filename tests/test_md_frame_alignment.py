"""Always-on numerical contracts, independent of local multi-GB MD fixtures."""
import numpy as np
import pytest

from backend.core.md_frame_alignment import align_md_frame


def context(reference, mask=None):
    mask = np.ones(len(reference), dtype=bool) if mask is None else mask
    centroid = reference[mask].mean(axis=0)
    centered = reference - centroid
    centered[~mask] = 0
    return dict(eq_positions=reference, eq_valid=np.ones(len(reference), dtype=bool),
                rigid_mask=mask, eq_centered=centered, eq_centroid=centroid)


@pytest.mark.parametrize('frame_idx', [0, 1, 40])
def test_rigid_alignment_preserves_distances_and_recovers_known_pose(frame_idx):
    reference = np.random.default_rng(42).normal(size=(24, 3))
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    mobile = reference @ rotation.T + [3, -2, 5]
    before = mobile.copy()
    ctx = context(reference)
    ctx.update(R_prev=np.eye(3), prev_frame_idx=0)
    result = align_md_frame(mobile, ctx, frame_idx)
    np.testing.assert_allclose(result.positions, reference, atol=1e-14)
    np.testing.assert_array_equal(mobile, before)
    assert np.linalg.det(result.rotation) == pytest.approx(1)
    assert ctx['prev_frame_idx'] == frame_idx


def test_nonrigid_coordinates_do_not_bias_the_fitted_pose():
    reference = np.random.default_rng(13).normal(size=(24, 3))
    mask = np.arange(24) < 16
    mobile = reference + [8, 3, -2]
    mobile[~mask] += [100, -70, 10]
    result = align_md_frame(mobile, context(reference, mask), 0)
    np.testing.assert_allclose(result.positions[mask], reference[mask], atol=1e-13)
    np.testing.assert_allclose(result.positions[~mask], reference[~mask] + [100, -70, 10], atol=1e-13)


def test_missing_reference_leaves_coordinates_and_history_untouched():
    mobile = np.array([[1., 2., 3.]])
    ctx = {'prev_frame_idx': 4}
    result = align_md_frame(mobile, ctx, 5)
    assert result.positions is mobile
    assert result.rotation is None
    assert ctx == {'prev_frame_idx': 4}


def test_readers_keep_independent_rotation_history():
    reference = np.random.default_rng(3).normal(size=(24, 3))
    live, playback = context(reference), context(reference)
    align_md_frame(reference + 1, live, 17)
    assert 'R_prev' not in playback
    result = align_md_frame(reference - 5, playback, 0)
    np.testing.assert_allclose(result.positions, reference, atol=1e-14)
    assert live['prev_frame_idx'] == 17


def test_sequential_inlier_guard_rejects_an_outlier_driven_rotation_jump():
    rng = np.random.default_rng(0)
    reference = rng.normal(size=(32, 3))
    mobile = reference.copy()
    mobile[:5] += rng.normal(size=(5, 3)) * 20
    initial = align_md_frame(mobile, context(reference), 1)
    guarded = align_md_frame(mobile, dict(context(reference), R_prev=np.eye(3), prev_frame_idx=0), 1)
    angle = np.degrees(np.arccos(np.clip((np.trace(initial.rotation) - 1) / 2, -1, 1)))
    assert angle > 60
    np.testing.assert_allclose(guarded.rotation, np.eye(3), atol=1e-14)
    # The guard centers the inlier subset on the full reference centroid.
    # Internal geometry is preserved even when outliers shift that centroid.
    np.testing.assert_allclose(np.diff(guarded.positions[5:], axis=0),
                               np.diff(reference[5:], axis=0), atol=1e-14)
    # A random seek does not inherit the sequential continuity constraint.
    seek = align_md_frame(mobile, dict(context(reference), R_prev=np.eye(3), prev_frame_idx=-20), 1)
    np.testing.assert_array_equal(seek.rotation, initial.rotation)

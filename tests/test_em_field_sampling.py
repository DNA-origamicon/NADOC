"""Manufactured fields verify refinement follows measured values, not geometry."""
import numpy as np
import pytest

from backend.physics.em_field_sampling import refine_field
from backend.physics.em_volume_archive import VolumeArchive, read_frame


def seed():
    points = np.stack(np.meshgrid(*[np.arange(4) - 1.5]*3, indexing='ij'), axis=-1).reshape(-1, 3)
    return points, np.ones_like(points)


def test_uniform_field_is_not_refined():
    points, sizes = seed()
    def sample(p):
        return np.full(len(p), 20.), np.ones(len(p), bool)
    values, outside = sample(points)
    result = refine_field(points, sizes, values, outside, sample, 25)
    np.testing.assert_array_equal(result[0], points)
    assert result[-1]['field_refinement']['rounds'] == 0
    assert not result[-1]['field_refinement']['limit_reached']


@pytest.mark.parametrize('target', [[.5,.5,.5], [-.5,-.5,-.5]])
def test_hotspot_moves_refinement_and_preserves_exact_samples(target, tmp_path):
    points, sizes = seed()
    target = np.array(target)
    def sample(p):
        return 1 + 100*np.exp(-np.sum((p-target)**2, axis=1)/.36), np.ones(len(p), bool)
    values, outside = sample(points)
    p, widths, intensity, mask, info = refine_field(points, sizes, values, outside, sample, 25)
    assert len(p) > len(points)
    assert len(p) <= len(points) + 25**3
    np.testing.assert_allclose(np.prod(widths, axis=1).sum(), 64)
    np.testing.assert_array_equal(intensity, sample(p)[0])
    assert mask.all()
    near = np.linalg.norm(p-target, axis=1) < .5
    far = np.linalg.norm(p-target, axis=1) > 2
    assert widths[near].max() < widths[far].max()
    assert info['field_refinement']['refined_cells'] > 0
    archive = VolumeArchive(tmp_path / 'field-refined')
    archive.append(dict(shape=[len(p)], sampling={'layout': 'octree', **info},
                        sample_positions_nm=p, cell_sizes_nm=widths,
                        intensity=intensity, outside=mask), frame_index=0)
    archive.finish()
    loaded = read_frame(archive.path, 0)
    np.testing.assert_array_equal(loaded['sample_positions_nm'], p)
    np.testing.assert_array_equal(loaded['intensity'], intensity)
    assert loaded['sampling']['field_refinement'] == info['field_refinement']


def test_steep_variation_refines_and_mask_is_not_a_false_zero_field():
    points, sizes = seed()
    def sample(p):
        return np.exp(2*p[:, 0]), np.ones(len(p), bool)
    values, outside = sample(points)
    result = refine_field(points, sizes, values, outside, sample, 25)
    assert len(result[0]) > len(points)
    # A masked half-volume beside a constant field must not create a gradient.
    mask = points[:, 0] > 0
    def constant(p):
        outside = p[:, 0] > 0
        return outside.astype(float), outside
    result = refine_field(points, sizes, mask.astype(float), mask, constant, 25)
    assert len(result[0]) == len(points)


def test_nonfinite_child_fields_are_rejected():
    points, sizes = seed()
    def invalid(p):
        return np.full(len(p), np.nan), np.ones(len(p), bool)
    with pytest.raises(ValueError, match='Non-finite'):
        refine_field(points, sizes, np.exp(2*points[:,0]), np.ones(len(points), bool), invalid, 25)

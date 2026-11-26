"""Geometry-driven refinement: coverage, concentration, bounds and persistence."""
import numpy as np
import pytest

from backend.physics.em_sampling import adaptive_grid
from backend.physics.em_volume_archive import VolumeArchive, read_frame


def grid(resolution=25, **options):
    return adaptive_grid(np.array([[-11., 0, 0], [11., 0, 0]]), np.array([10., 10.]),
                         np.zeros(2), [-31, -20, -20], [31, 20, 20], resolution, **options)


def test_surface_refinement_partition_and_budget():
    points, sizes, info = grid()
    assert len(points) <= 4 * 25**3
    np.testing.assert_allclose(np.prod(sizes, axis=1).sum(), 62 * 40 * 40)
    assert np.all(points - sizes / 2 >= [-31, -20, -20])
    assert np.all(points + sizes / 2 <= [31, 20, 20])
    # Cells in the narrow central gap are finer than distant water cells.
    gap = (abs(points[:, 0]) < 1) & (np.linalg.norm(points[:, 1:], axis=1) < 3)
    far = (abs(points[:, 1]) > 17) & (abs(points[:, 2]) > 17)
    assert gap.sum() > 10
    assert sizes[gap].max(axis=1).mean() < sizes[far].max(axis=1).mean() / 2
    assert info['layout'] == 'octree'
    other = grid()
    np.testing.assert_array_equal(points, other[0])


def test_quality_refines_and_archive_preserves_geometry(tmp_path):
    points, sizes, info = grid(33)
    _, coarse, _ = grid(25)
    assert sizes.min() <= coarse.min()
    expected = dict(shape=[len(points)], sampling=info, sample_positions_nm=points,
                    cell_sizes_nm=sizes, intensity=np.ones(len(points)), outside=np.ones(len(points), bool))
    archive = VolumeArchive(tmp_path / 'adaptive')
    archive.append(expected, frame_index=0)
    archive.finish()
    loaded = read_frame(archive.path, 0)
    for key in ('sample_positions_nm', 'cell_sizes_nm', 'intensity', 'outside'):
        np.testing.assert_array_equal(loaded[key], expected[key])
    invalid = {**expected, 'cell_sizes_nm': -sizes}
    archive = VolumeArchive(tmp_path / 'invalid')
    with pytest.raises(ValueError, match='positive'):
        archive.append(invalid, frame_index=0)


def test_gap_refinement_adds_four_children_per_selected_cell():
    original, original_sizes, _ = grid(refine_gaps=False)
    points, sizes, info = grid()
    assert info['gap_refined_cells'] > 0
    assert len(points) == len(original) + 3 * info['gap_refined_cells']
    # A narrow box inside the central gap gains at least twice as many samples.
    def in_gap(p):
        return (abs(p[:, 0]) < 1) & (abs(p[:, 1]) < 2) & (abs(p[:, 2]) < 2)
    assert in_gap(points).sum() >= 2 * in_gap(original).sum() > 0
    np.testing.assert_allclose(np.prod(sizes, axis=1).sum(), np.prod(original_sizes, axis=1).sum())
    # A single sphere cannot trigger interparticle refinement.
    _, _, single = adaptive_grid(np.zeros((1, 3)), np.array([10.]), np.zeros(1),
                                 [-20]*3, [20]*3, 25)
    assert single['gap_refined_cells'] == 0

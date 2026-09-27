"""Independent dense oracle for halo coverage, seam welding, and physical sampling."""

import math
import numpy as np
import pytest
from scipy.ndimage import binary_closing
from scipy.spatial import cKDTree
from skimage.measure import marching_cubes
from backend.core.surface import _sphere_struct, _stamp_spheres
from backend.core.surface_field import continuous_surface_field, CONTINUOUS_SIGMA_NM
from backend.core.surface_tiled import continuous_cloud_surface
from backend.core.surface_quality import surface_quality


@pytest.mark.parametrize("probe", [0.0, 0.14, 0.24])
def test_tiles_match_dense_field_without_seams(monkeypatch, probe):
    monkeypatch.setenv("NADOC_SURFACE_GPU", "0")
    gs = 0.05
    positions = np.array(
        [
            [0, 0, 0],
            [0.21, 0.02, 0.01],
            [0.37, 0.18, 0.04],
            [0.61, 0.21, 0.13],
            [0.91, 0.16, 0.07],
        ]
    )
    radii = np.array([0.17, 0.152, 0.18, 0.17, 0.17])
    seeds = np.rint(positions / gs).astype(int)
    margin = (
        math.ceil(radii.max() / gs)
        + 2 * math.ceil(probe / gs)
        + int(3 * CONTINUOUS_SIGMA_NM / gs + 0.5)
        + 2
    )
    lo, hi = seeds.min(axis=0) - margin, seeds.max(axis=0) + margin
    occupancy = np.zeros(tuple(hi - lo + 1), bool)
    for pos, radius in zip(seeds, radii):
        _stamp_spheres(occupancy, (pos - lo)[None, :], radius / gs)
    if probe:
        occupancy = binary_closing(occupancy, structure=_sphere_struct(probe / gs))
    field = continuous_surface_field(occupancy, grid_spacing=gs)
    v, f, _, _ = marching_cubes(field, 0.5, allow_degenerate=False)
    reference = (v.astype(float) + lo) * gs
    for tile in [16, 23, 96]:
        m = continuous_cloud_surface(
            positions,
            radii,
            grid_spacing=gs,
            probe_radius=probe,
            tile_cells=tile,
            strand_ids=["a"] * len(radii),
            nuc_ids=["n"] * len(radii),
        )
        assert len(m.faces) == len(f)
        assert len(m.vertices) == len(v)
        assert cKDTree(reference).query(m.vertices)[0].max() < 5e-6
        assert cKDTree(m.vertices).query(reference)[0].max() < 5e-6
        q = surface_quality(m)
        assert (
            q["boundary_edges"] == q["nonmanifold_edges"] == q["degenerate_faces"] == 0
        )
        assert set(m.vertex_strand_ids) == {"a"} and set(m.vertex_nuc_ids) == {"n"}


def test_sampling_is_invariant_under_integer_grid_translation(monkeypatch):
    monkeypatch.setenv("NADOC_SURFACE_GPU", "0")
    p = np.array([[0.0, 0.0, 0.0], [0.2, 0.1, 0.0], [0.4, 0.1, 0.0], [0.6, 0.1, 0.0]])
    a = continuous_cloud_surface(p, np.full(4, 0.17), tile_cells=9)
    shift = np.array([2.0, -3.0, 4.0])
    b = continuous_cloud_surface(p + shift, np.full(4, 0.17), tile_cells=9)
    assert len(a.faces) == len(b.faces)
    assert cKDTree(a.vertices).query(b.vertices - shift)[0].max() < 5e-6


def test_filter_width_is_fixed_in_physical_units(monkeypatch):
    from backend.core import surface_field

    sigmas = []

    def capture(grid, **kwargs):
        sigmas.append(kwargs["sigma"])
        return grid

    monkeypatch.setattr(surface_field, "gaussian_filter", capture)
    for spacing in [0.05, 0.1, 0.12]:
        surface_field.continuous_surface_field(
            np.zeros((3, 3, 3)), grid_spacing=spacing
        )
    np.testing.assert_allclose(np.array(sigmas) * [0.05, 0.1, 0.12], 0.0425)


def test_optimized_weld_preserves_exact_unique_order_and_first_occurrence():
    from backend.core.surface_tiled import weld_key_indices

    rng = np.random.default_rng(19)
    keys = rng.integers(-8, 9, (1000, 4))
    keys = np.concatenate([keys, keys[::3], keys[::7]])
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    actual_first, actual_inverse = weld_key_indices(keys)
    np.testing.assert_array_equal(actual_first, first)
    np.testing.assert_array_equal(actual_inverse, inverse)

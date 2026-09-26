"""Exact lattice parity: optimization must not alter either surface definition."""

import numpy as np
import pytest
from scipy.ndimage import binary_dilation
from backend.core import surface as sf


def _dense_stamp(grid, indices, radius):
    seeds = np.zeros_like(grid)
    if len(indices):
        seeds[tuple(indices.T)] = True
    grid |= binary_dilation(seeds, structure=sf._sphere_struct(radius))


@pytest.mark.parametrize("radius", [0, 0.49, 1, np.sqrt(2), 2.5, 3.6, 8.1])
@pytest.mark.parametrize("shape", [(1, 2, 3), (17, 21, 19)])
def test_stamp_matches_dense_dilation_at_boundaries_and_overlaps(radius, shape):
    rng = np.random.default_rng(710)
    seeds = rng.integers(0, shape, (180, 3))
    seeds = np.concatenate([seeds, seeds[:20], [[0, 0, 0]], [np.array(shape) - 1]])
    actual = rng.random(shape) < 0.01  # existing sphere unions must survive
    expected = actual.copy()
    _dense_stamp(expected, seeds, radius)
    sf._stamp_spheres(actual, seeds, radius)
    np.testing.assert_array_equal(actual, expected)


def test_empty_stamp_is_noop():
    grid = np.ones((2, 3, 4), bool)
    sf._stamp_spheres(grid, np.empty((0, 3), int), 2)
    assert grid.all()


@pytest.mark.parametrize("split", [False, True])
def test_complete_mesh_and_identity_exact_with_dense_reference(monkeypatch, split):
    rng = np.random.default_rng(2026)
    pos = rng.normal(size=(120, 3))
    radii = np.resize([0.17, 0.152, 0.18, 0.155], len(pos))
    sids = ["b", "a", None] * 40  # interleaved and unassigned; first-appearance order
    nucs = [f"n{i}" for i in range(len(pos))]

    def build():
        if split:
            return sf.compute_split_surfaces_from_cloud(
                pos, radii, sids, grid_spacing=0.1, smooth=4, nuc_ids=nucs
            )
        return sf.smooth_mesh(
            sf.compute_surface_from_cloud(
                pos, radii, sids, grid_spacing=0.2, nuc_ids=nucs
            )
        )

    actual = build()
    monkeypatch.setattr(sf, "_stamp_spheres", _dense_stamp)
    expected = build()
    np.testing.assert_array_equal(actual.vertices, expected.vertices)
    np.testing.assert_array_equal(actual.faces, expected.faces)
    assert actual.vertex_strand_ids == expected.vertex_strand_ids
    assert actual.vertex_nuc_ids == expected.vertex_nuc_ids


def test_stamp_multiple_bounded_scatter_batches():
    seeds = np.indices((23, 23, 23)).reshape(3, -1).T + 5
    actual = np.zeros((34, 34, 34), bool)
    expected = actual.copy()
    _dense_stamp(expected, seeds, 3.6)
    sf._stamp_spheres(actual, seeds, 3.6)
    np.testing.assert_array_equal(actual, expected)


def test_object_surface_matches_dense_reference_and_atom_owner_keys(monkeypatch):
    from scipy.spatial import cKDTree

    beads = [
        sf.make_cg_bead(
            i * 0.13,
            (i % 3) * 0.11,
            0.0,
            strand_id=f"s{i % 2}",
            helix_id="h",
            bp_index=i,
            direction="FORWARD",
        )
        for i in range(24)
    ]
    actual = sf.cg_surface_mesh(beads)
    monkeypatch.setattr(sf, "_stamp_spheres", _dense_stamp)
    expected = sf.cg_surface_mesh(beads)
    np.testing.assert_array_equal(actual.vertices, expected.vertices)
    np.testing.assert_array_equal(actual.faces, expected.faces)
    assert actual.vertex_strand_ids == expected.vertex_strand_ids
    assert actual.vertex_nuc_ids == expected.vertex_nuc_ids
    # Ownership is assigned before smoothing; use the raw surface for the
    # independent original nearest-atom key oracle.
    raw = sf.compute_surface(beads)
    _, nearest = cKDTree([[a.x, a.y, a.z] for a in beads]).query(raw.vertices)
    assert raw.vertex_nuc_ids == [sf._nuc_key(beads[i]) for i in nearest]
    assert raw.vertex_strand_ids == [beads[i].strand_id for i in nearest]

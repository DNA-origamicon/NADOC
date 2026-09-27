"""Uniform physical sampling for the Figure quality display surface.

Tiles own disjoint marching-cubes cells, share boundary samples, and include the
full closing/filter dependency halo. Voxel memory is bounded without coarsening
long strands. All strands sample the same world-aligned lattice. Mesh output still
scales with surface area; tiling bounds working grids, not final mesh size.
"""

from __future__ import annotations

from itertools import product
import math

import numpy as np
from scipy.spatial import cKDTree
from skimage.measure import marching_cubes

from backend.core.surface_field import CONTINUOUS_SIGMA_NM, continuous_surface_field
from backend.core.surface_progress import report

TILE_CELLS = 96


def weld_key_indices(keys):
    """Same sorted keys / first occurrence as np.unique(axis=0), without record sorting."""
    order = np.lexsort(keys.T[::-1])
    sorted_keys = keys[order]
    starts = np.r_[True, np.any(sorted_keys[1:] != sorted_keys[:-1], axis=1)]
    inverse = np.empty(len(keys), dtype=np.int64)
    inverse[order] = np.cumsum(starts) - 1
    return order[starts], inverse


def continuous_cloud_surface(
    positions,
    radii,
    strand_ids=None,
    *,
    grid_spacing=0.05,
    probe_radius=0.06,
    nuc_ids=None,
    tile_cells=TILE_CELLS,
):
    from backend.core.surface import SurfaceMesh, _sphere_struct, _stamp_spheres
    from backend.core.surface_acceleration import close_volume

    if grid_spacing <= 0 or probe_radius < 0 or tile_cells < 1:
        raise ValueError("Positive spacing/tile size and nonnegative probe required")
    positions = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    radii = np.asarray(radii, dtype=np.float64)
    if not len(positions):
        return SurfaceMesh(np.empty((0, 3), np.float32), np.empty((0, 3), np.int32), [])
    # Global integer coordinates, independent of strand bbox/role and tile size.
    seeds = np.rint(positions / grid_spacing).astype(np.int64)
    max_atom = int(math.ceil(float(radii.max()) / grid_spacing))
    probe_cells = int(math.ceil(probe_radius / grid_spacing))
    filter_cells = int(3 * CONTINUOUS_SIGMA_NM / grid_spacing + 0.5)
    # Closing is dilation followed by erosion: information can travel 2*r.
    halo = 2 * probe_cells + filter_cells + 1
    margin = max_atom + halo + 1
    low, high = seeds.min(axis=0) - margin, seeds.max(axis=0) + margin
    tree = cKDTree(seeds)
    rounded = np.round(radii, 6)
    struct = _sphere_struct(probe_radius / grid_spacing) if probe_radius else None
    vertices, faces, keys = [], [], []
    offset = 0
    # Fill the same working-voxel budget with aspect-aware tiles. Thin/long
    # staples often fit in one block, avoiding repeated halos and GPU transfers.
    tile_shape = high - low
    voxel_budget = (tile_cells + 2 * halo + 1) ** 3
    while int(np.prod(tile_shape + 2 * halo + 1)) > voxel_budget:
        axis = int(np.argmax(tile_shape))
        tile_shape[axis] = (tile_shape[axis] + 1) // 2
    ranges = [range(int(low[a]), int(high[a]), int(tile_shape[a])) for a in range(3)]
    total_tiles = math.prod(len(r) for r in ranges)
    for tile_id, corner in enumerate(product(*ranges)):
        report("Extracting surface tiles", tile_id, total_tiles)
        begin = np.asarray(corner, dtype=np.int64)
        end = np.minimum(begin + tile_shape, high)
        outer_low, outer_high = begin - halo, end + halo
        center = (outer_low + outer_high) * 0.5
        rows = np.asarray(
            tree.query_ball_point(
                center,
                float(np.max((outer_high - outer_low) * 0.5) + max_atom),
                p=np.inf,
            ),
            dtype=int,
        )
        if not len(rows):
            continue
        keep = np.all(
            (seeds[rows] >= outer_low - max_atom)
            & (seeds[rows] <= outer_high + max_atom),
            axis=1,
        )
        rows = rows[keep]
        if not len(rows):
            continue
        grid = np.zeros(tuple(outer_high - outer_low + 1), dtype=bool)
        for radius in np.unique(rounded[rows]):
            ids = rows[rounded[rows] == radius]
            _stamp_spheres(grid, seeds[ids] - outer_low, radius / grid_spacing)
        if struct is not None:
            grid = close_volume(grid, struct)
        field = continuous_surface_field(grid, grid_spacing=grid_spacing)
        core = field[tuple(slice(halo, halo + int(n) + 1) for n in end - begin)]
        if core.min() >= 0.5 or core.max() <= 0.5:
            continue
        v, f, _, _ = marching_cubes(core, 0.5, allow_degenerate=False)
        world_voxels = v.astype(np.float64) + begin
        # Marching cubes vertices on shared cell edges get the SAME topological
        # key, avoiding seams from float32 coordinate rounding in different tiles.
        nearest = np.rint(world_voxels)
        integral = np.abs(world_voxels - nearest) <= 1e-5
        n_integral = integral.sum(axis=1)
        key = np.zeros((len(v), 4), np.int64)
        key[:, :3] = np.where(integral, nearest, np.floor(world_voxels)).astype(
            np.int64
        )
        key[:, 3] = np.argmin(integral, axis=1)  # varying grid-edge axis
        key[n_integral == 3, 3] = 3  # exactly at a grid vertex
        interior = n_integral < 2  # Lewiner cell-interior vertices are tile-local
        key[interior] = np.column_stack(
            (
                np.full(interior.sum(), tile_id),
                np.flatnonzero(interior),
                np.zeros(interior.sum(), int),
                np.full(interior.sum(), 4),
            )
        )
        vertices.append(world_voxels * grid_spacing)
        keys.append(key)
        faces.append(f.astype(np.int64) + offset)
        offset += len(v)
    report("Extracting surface tiles", total_tiles, total_tiles)
    report("Joining surface tiles")
    if not vertices:
        return SurfaceMesh(np.empty((0, 3), np.float32), np.empty((0, 3), np.int32), [])
    first, inverse = weld_key_indices(np.concatenate(keys))
    verts = np.concatenate(vertices)[first].astype(np.float32)
    faces = inverse[np.concatenate(faces)]
    # Snapping exact lattice vertices can collapse vanishingly small triangles.
    keep = (
        (faces[:, 0] != faces[:, 1])
        & (faces[:, 1] != faces[:, 2])
        & (faces[:, 2] != faces[:, 0])
    )
    faces = faces[keep].astype(np.int32)
    report("Assigning surface identity")
    _, nearest_atom = cKDTree(positions).query(verts, workers=-1)
    return SurfaceMesh(
        verts,
        faces,
        [strand_ids[i] if strand_ids is not None else "" for i in nearest_atom],
        [nuc_ids[i] if nuc_ids is not None else "" for i in nearest_atom],
    )

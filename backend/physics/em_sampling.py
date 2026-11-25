"""Bounded surface-distance octree sampling, independent of the Maxwell solution.

Leaves partition the entire box. Values are point samples at cell centers, not
cell averages; cell volumes are supplied for downstream spatial weighting.
"""
import heapq
import itertools

import numpy as np


def adaptive_grid(centers, radii, thicknesses, lower, upper, resolution, *, refine_gaps=True):
    centers, radii = np.asarray(centers), np.asarray(radii)
    lower, upper = np.asarray(lower), np.asarray(upper)
    budget = resolution**3
    floor = .25 * 33 / resolution
    coarse = float(np.max(upper - lower)) / 8
    offsets = np.array(list(itertools.product((-1, 1), repeat=3)))
    heap, serial = [], itertools.count()

    def insert(cell_centers, size, depth):
        distance = np.linalg.norm(cell_centers[:, None, :] - centers[None, :, :], axis=2)
        diagonal = np.linalg.norm(size) / 2
        # Do not spend the budget subdividing cells entirely inside masked metal.
        interior = np.any(distance + diagonal <= radii + .05, axis=1)
        surface = np.minimum(np.min(np.abs(distance - radii), axis=1),
                             np.min(np.abs(distance - radii - thicknesses), axis=1))
        nearest = np.maximum(0., surface - diagonal)
        target = np.minimum(coarse, floor + .4 * nearest)
        scores = np.where(interior | (depth >= 12), 0., np.max(size) / target)
        for center, score in zip(cell_centers, scores):
            heapq.heappush(heap, (-float(score), next(serial), center, size, depth))

    insert(np.array([(lower + upper) / 2]), upper - lower, 0)
    while len(heap) + 7 <= budget and -heap[0][0] > 1:
        _, _, center, size, depth = heapq.heappop(heap)
        insert(center + offsets * size / 4, size / 2, depth + 1)
    # Stable spatial ordering helps compression and repeatable exports.
    leaves = sorted(heap, key=lambda row: tuple(row[2]))
    points = np.array([row[2] for row in leaves])
    sizes = np.array([row[3] for row in leaves])
    refined = np.zeros(len(points), dtype=bool)
    if refine_gaps:
        # Refine whole cells intersecting the narrow neck between facing metal
        # surfaces. The extra samples cannot be displaced by the surface budget.
        diagonal = np.linalg.norm(sizes, axis=1) / 2
        interior = np.any(np.linalg.norm(points[:, None, :] - centers, axis=2)
                          + diagonal[:, None] <= radii + .05, axis=1)
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                separation = np.linalg.norm(centers[j] - centers[i])
                gap = separation - radii[i] - radii[j]
                if not 0 < gap <= 10:
                    continue
                axis = (centers[j] - centers[i]) / separation
                start = centers[i] + radii[i] * axis
                delta = points - start
                along = delta @ axis
                radial = np.linalg.norm(delta - along[:, None] * axis, axis=1)
                neck = np.sqrt(min(radii[i], radii[j]) * gap)
                refined |= ((along + diagonal >= 0) & (along - diagonal <= gap)
                            & (radial <= neck + diagonal) & ~interior)
    refined_count = int(refined.sum())
    if refined_count:
        # Four samples per original gap cell, bisecting its two longest axes.
        # Reserve this refinement beyond the surface budget so it is guaranteed.
        child_sizes = sizes[refined].copy()
        axes = np.argsort(-child_sizes, axis=1, kind='stable')[:, :2]
        shifts = []
        rows = np.arange(refined_count)
        for signs in itertools.product((-1, 1), repeat=2):
            shift = np.zeros_like(child_sizes)
            for dimension in range(2):
                axis = axes[:, dimension]
                shift[rows, axis] = signs[dimension] * sizes[refined][rows, axis] / 4
            shifts.append(shift)
        for dimension in range(2):
            child_sizes[rows, axes[:, dimension]] /= 2
        points = np.concatenate([points[~refined], *[points[refined] + shift for shift in shifts]])
        sizes = np.concatenate([sizes[~refined], *[child_sizes] * 4])
        order = np.lexsort(points.T[::-1])
        points, sizes = points[order], sizes[order]
    return points, sizes, {
        'layout': 'octree', 'criterion': 'distance to metal and dielectric-shell surfaces',
        'sample_count': len(points), 'sample_budget': 4 * budget if refine_gaps else budget,
        'base_sample_budget': budget, 'gap_refined_cells': refined_count,
        'gap_sampling_multiplier': 4 if refine_gaps else 1, 'close_gap_threshold_nm': 10.,
        'requested_surface_spacing_nm': floor,
        'minimum_cell_width_nm': float(sizes.min()),
        'maximum_cell_width_nm': float(sizes.max()),
        'budget_limited': bool(-heap[0][0] > 1),
        'values': 'cell-center point samples, not cell averages',
    }

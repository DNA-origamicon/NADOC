"""Bounded field-driven refinement of a geometric seed partition.

Neighbor differences estimate variation in log10(1 + intensity), not a certified
field-error bound. New leaf values always come from the Maxwell evaluator.
"""
import itertools

import numpy as np
from scipy.spatial import cKDTree


def refine_field(points, sizes, values, outside, sample, resolution):
    seed_count = len(points)
    extra_budget = resolution**3
    limit = seed_count + extra_budget
    minimum = .125 * 33 / resolution
    offsets = np.array(list(itertools.product((-1, 1), repeat=3)))
    refined_count = rounds = evaluations = 0
    remaining = width_limited = 0
    for iteration in range(4):
        active = np.flatnonzero(outside)
        scores = np.zeros(len(points))
        if len(active) > 1:
            positions, intensity = points[active], values[active]
            distance, neighbors = cKDTree(positions).query(positions, k=min(9, len(active)))
            contrast = np.abs(np.log10(1 + intensity[neighbors[:, 1:]])
                              - np.log10(1 + intensity[:, None]))
            gradient = np.max(contrast / np.maximum(distance[:, 1:], 1e-12), axis=1)
            variation = gradient * np.max(sizes[active], axis=1)
            # Bright uniform volumes are not localized hotspots.
            hot_threshold = max(10., .25 * float(intensity.max()), 2 * float(np.median(intensity)))
            hotspot = np.where(intensity > hot_threshold, intensity / hot_threshold, 0.)
            scores[active] = np.maximum(variation / .1, hotspot)
        width_limited = int(np.sum((scores > 1) & (np.max(sizes, axis=1) <= minimum)))
        candidates = np.flatnonzero((scores > 1) & (np.max(sizes, axis=1) > minimum))
        remaining = len(candidates)
        if not remaining or iteration == 3:
            break
        # Reserve work for successive re-estimates rather than spending everything
        # on the first set of gradients. Each split adds seven leaves/eight solves.
        count = min(remaining, (limit - len(points)) // 7, max(1, extra_budget // 21))
        if count <= 0:
            break
        chosen = candidates[np.argsort(-scores[candidates], kind='stable')[:count]]
        children = (points[chosen, None, :] + offsets * sizes[chosen, None, :] / 4).reshape(-1, 3)
        child_sizes = np.repeat(sizes[chosen] / 2, 8, axis=0)
        child_values, child_outside = sample(children)
        if not np.all(np.isfinite(child_values)):
            raise ValueError('Non-finite electric field encountered during adaptive refinement.')
        keep = np.ones(len(points), bool)
        keep[chosen] = False
        points = np.concatenate([points[keep], children])
        sizes = np.concatenate([sizes[keep], child_sizes])
        values = np.concatenate([values[keep], child_values])
        outside = np.concatenate([outside[keep], child_outside])
        refined_count += count
        evaluations += int(np.sum(child_outside))
        rounds += 1
    order = np.lexsort(points.T[::-1])
    return points[order], sizes[order], values[order], outside[order], {
        'criterion': 'calculated log-intensity variation and hotspots, with surface/gap seed',
        'field_refinement': {'algorithm': 'log-intensity-neighbors-v1', 'rounds': rounds, 'refined_cells': refined_count,
            'additional_field_evaluations': evaluations, 'seed_sample_count': seed_count,
            'log_variation_target': .1, 'remaining_candidates': remaining,
            'limit_reached': bool(remaining or width_limited),
            'minimum_width_limited_cells': width_limited, 'minimum_target_width_nm': minimum,
            'metric': 'neighbor gradient of log10(1+I) times cell width; bright localized regions'},
        'sample_count': len(points), 'sample_budget': limit,
        'minimum_cell_width_nm': float(sizes.min()), 'maximum_cell_width_nm': float(sizes.max()),
    }

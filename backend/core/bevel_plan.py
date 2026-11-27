"""Continuous plane/axis intersection for terminal material removal."""
import numpy as np


def intersect_bevel_plane(bps, points, center, normal):
    """Find a single forward crossing, counting an on-plane sample once.

    An endpoint within numerical tolerance belongs to the plane, not also to
    the neighboring sign-changing interval. No physical coordinates are moved.
    """
    distances = (points - center) @ normal
    on_plane = np.abs(distances) < 1e-9
    if np.any(on_plane[:-1] & on_plane[1:]):
        raise ValueError('A helix path lies in the bevel plane.')
    roots = [(float(bps[i]), points[i]) for i in np.flatnonzero(on_plane)]
    for i in range(len(bps) - 1):
        a, b = distances[i:i + 2]
        if not on_plane[i] and not on_plane[i + 1] and a * b < 0:
            fraction = a / (a - b)
            roots.append((float(bps[i] + fraction * (bps[i + 1] - bps[i])),
                          points[i] + fraction * (points[i + 1] - points[i])))
    if len(roots) != 1:
        raise ValueError('Each helix must cross the bevel plane exactly once; move the plane or reduce the angle.')
    station, point = roots[0]
    if not bps[0] < station < bps[-1]:
        raise ValueError('Bevel needs material on both sides of the cutting plane.')
    if distances[0] >= 0 or distances[-1] <= 0:
        raise ValueError('Helix path traversal disagrees with the bevel frame.')
    return station, point

"""Exact-order hot-loop primitives for the approved Corner fit.

No fast-math or reordered reductions: preserve each repeated-index addition
and each cross-product expression used by the inspected NumPy calculation.
"""

import numpy as np
from numba import njit


@njit(cache=True)
def scatter_add(target, indices, values):
    for row in range(len(indices)):
        for axis in range(3):
            target[indices[row], axis] += values[row, axis]


@njit(cache=True)
def clearance_gradient(xyz, pairs, gradient):
    """Same pair order and separate i/j scatter passes as the NumPy oracle."""
    penetration = np.empty(len(pairs))
    values = np.empty((len(pairs), 3))
    for row in range(len(pairs)):
        i, j = pairs[row]
        x, y, z = xyz[i, 0]-xyz[j, 0], xyz[i, 1]-xyz[j, 1], xyz[i, 2]-xyz[j, 2]
        distance = np.sqrt((x*x + y*y) + z*z)
        p = min(distance-.20, 0.)
        penetration[row] = p
        scale = 2*p / max(distance, 1e-12)
        values[row, 0], values[row, 1], values[row, 2] = scale*x, scale*y, scale*z
    for row in range(len(pairs)):
        for axis in range(3):
            gradient[pairs[row, 0], axis] += values[row, axis]
    for row in range(len(pairs)):
        for axis in range(3):
            gradient[pairs[row, 1], axis] += -values[row, axis]
    return penetration


def cross(a, b):
    result = np.empty_like(a)
    result[..., 0] = a[..., 1]*b[..., 2] - a[..., 2]*b[..., 1]
    result[..., 1] = a[..., 2]*b[..., 0] - a[..., 0]*b[..., 2]
    result[..., 2] = a[..., 0]*b[..., 1] - a[..., 1]*b[..., 0]
    return result

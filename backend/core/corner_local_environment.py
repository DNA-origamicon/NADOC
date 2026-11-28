"""Exact local broad phase for Corner clearance; no bounded optimizer domain.

Retain the entire, ordered environment for dependency fingerprints. A local tree
and a Verlet-style candidate list only accelerate discovery: rebuild when any
query moves beyond its skin, including rejected line-search trials. No atom that
can contribute to the original 0.20 nm objective is omitted.
"""

import numpy as np
from numba import njit
from scipy.spatial import cKDTree

from backend.core.corner_seam_math import scatter_add

_SKIN = 0.125
_RADIUS = 0.20


@njit(cache=True)
def outside_skin(points, centers):
    for i in range(len(points)):
        for k in range(3):
            if abs(points[i, k] - centers[i, k]) > _SKIN:
                return True
    return False


@njit(cache=True)
def candidate_gradient(xyz, movable, environment, candidates, offsets, gradient):
    own = np.empty(len(candidates), np.int64)
    other = np.empty(len(candidates), np.int64)
    n = 0
    for i in range(len(movable)):
        a = movable[i]
        for j in range(offsets[i], offsets[i + 1]):
            b = candidates[j]
            dx = xyz[a, 0] - environment[b, 0]
            dy = xyz[a, 1] - environment[b, 1]
            dz = xyz[a, 2] - environment[b, 2]
            if (dx * dx + dy * dy) + dz * dz <= _RADIUS * _RADIUS:
                own[n], other[n] = a, b
                n += 1
    # Preserve the reference's neighbour ordering, norm, dot and scatter. In
    # particular, do not sum costs as candidates are discovered.
    delta = xyz[own[:n]] - environment[other[:n]]
    distance = np.sqrt(np.sum(delta * delta, axis=1))
    penetration = distance - _RADIUS
    cost = np.dot(penetration, penetration)
    scatter_add(
        gradient,
        own[:n],
        (2 * penetration / np.maximum(distance, 1e-12)).reshape(-1, 1) * delta,
    )
    return cost


class LocalEnvironment:
    def __init__(self, data):
        self.data = np.asarray(data, dtype=float).reshape(-1, 3)
        if not np.isfinite(self.data).all():
            raise ValueError("Corner environment coordinates must be finite.")
        self.n = len(self.data)
        self.bounds = None
        self.centers = None

    def _neighbours(self, points, radius):
        lo, hi = points.min(axis=0) - radius, points.max(axis=0) + radius
        if (
            self.bounds is None
            or np.any(lo <= self.bounds[0])
            or np.any(hi >= self.bounds[1])
        ):
            self.bounds = np.array([lo - 0.5, hi + 0.5])
            self.indices = np.flatnonzero(
                np.all(
                    (self.data >= self.bounds[0]) & (self.data <= self.bounds[1]),
                    axis=1,
                )
            )
            self.tree = cKDTree(self.data[self.indices])
        rows = self.tree.query_ball_point(points, radius, return_sorted=True)
        return [self.indices[row] for row in rows]

    def accumulate(self, xyz, movable, gradient):
        if not self.n or not len(movable):
            return 0.0
        points = xyz[movable]
        if self.centers is None or outside_skin(points, self.centers):
            # The per-axis displacement bound permits sqrt(3)*skin Euclidean
            # motion. Overfetch slightly; the compiled narrow phase keeps the
            # original exact radius. Remote trials grow/rebuild the search.
            rows = self._neighbours(points, _RADIUS + np.sqrt(3) * _SKIN + 1e-12)
            self.centers = points.copy()
            self.candidates = np.concatenate(rows).astype(np.int64)
            self.offsets = np.r_[0, np.cumsum([len(row) for row in rows])]
        return candidate_gradient(
            xyz, movable, self.data, self.candidates, self.offsets, gradient
        )

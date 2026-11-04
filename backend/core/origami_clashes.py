"""Conservative planar rigid-body clearance for the experimental origami fit.

Convex envelopes of occupied helix axes, expanded by the existing helix radius,
exclude inter-body tube overlap. This is a geometric constraint, not atomistic
sterics. It deliberately excludes contacts within a rigid body.
"""

from itertools import combinations

import numpy as np
from scipy.spatial import ConvexHull

from backend.core.constants import HELIX_RADIUS_NM


class PlanarBodyClearance:
    def __init__(self, axes, groups, centers, plane):
        self.centers = centers
        self.plane = plane
        self.required_gap_nm = 2 * HELIX_RADIUS_NM + 0.05
        self.pairs = list(combinations(range(len(groups)), 2))
        self.hulls = []
        for i, group in enumerate(groups):
            points = np.unique(np.concatenate([axes[h] for h in group]), axis=0)
            xy = points @ plane.T
            if (
                len(points) > 2
                and np.linalg.matrix_rank(xy - xy.mean(0), tol=1e-8) == 2
            ):
                points = points[ConvexHull(xy).vertices]
            elif len(points) > 1:
                direction = np.linalg.svd(xy - xy.mean(0), full_matrices=False)[2][0]
                projection = xy @ direction
                points = points[[projection.argmin(), projection.argmax()]]
            self.hulls.append(points - centers[i])

    def gaps(self, rotations, translations):
        polygons = [
            (rotations[i].apply(hull) + self.centers[i] + translations[i])
            @ self.plane.T
            for i, hull in enumerate(self.hulls)
        ]
        gaps = []
        for a, b in self.pairs:
            p, q = polygons[a], polygons[b]
            edges = np.concatenate(
                (np.roll(p, 1, axis=0) - p, np.roll(q, 1, axis=0) - q)
            )
            # Tangents also cover line/point envelopes. Every tested direction
            # is a valid separating direction; extra axes cannot hide overlap.
            directions = np.concatenate((edges, edges[:, ::-1] * [1, -1], np.eye(2)))
            lengths = np.linalg.norm(directions, axis=1)
            directions = directions[lengths > 1e-10] / lengths[lengths > 1e-10, None]
            pp, qq = p @ directions.T, q @ directions.T
            gaps.append(
                np.max(np.maximum(pp.min(0) - qq.max(0), qq.min(0) - pp.max(0)))
            )
        return np.asarray(gaps)

    def summary(self, rotations, translations):
        gaps = self.gaps(rotations, translations)
        return {
            "overlapping_body_pairs": int(
                np.count_nonzero(gaps < 2 * HELIX_RADIUS_NM - 1e-6)
            ),
            "minimum_axis_envelope_gap_nm": float(gaps.min()),
            "required_gap_nm": self.required_gap_nm,
            "max_clearance_deficit_nm": float(
                max(0, self.required_gap_nm - gaps.min())
            ),
        }

"""Read-only clearance measurements and a guarded shared-workflow entry point."""

from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from backend.core.design_geometry import _geometry_for_design


def segment_distance(p, q):
    """Exact 3-D segment distance: interior stationary point or boundary minimum."""
    u, v, w = p[1] - p[0], q[1] - q[0], p[0] - q[0]
    a, b, c, d, e = u @ u, u @ v, v @ v, u @ w, v @ w
    candidates = []
    for point in p:
        projection = q[0] + np.clip((point - q[0]) @ v / max(c, 1e-30), 0, 1) * v
        candidates.append((point, projection))
    for point in q:
        projection = p[0] + np.clip((point - p[0]) @ u / max(a, 1e-30), 0, 1) * u
        candidates.append((projection, point))
    denom = a * c - b * b
    if denom > 1e-12 * max(a * c, 1):
        s, t = (b * e - c * d) / denom, (a * e - b * d) / denom
        if 0 <= s <= 1 and 0 <= t <= 1:
            candidates.append((p[0] + s * u, q[0] + t * v))
    x, y = min(candidates, key=lambda pair: np.linalg.norm(pair[0] - pair[1]))
    return float(np.linalg.norm(x - y)), (x + y) / 2


def audit(design):
    geometry = _geometry_for_design(design)
    owner = {h: i for i, c in enumerate(design.cluster_transforms) for h in c.helix_ids}
    segments = {}
    for h in design.helices:
        xyz = np.array(
            [b["helical_site"]["axis_point"] for b in geometry if b["helix_id"] == h.id]
        )
        axis = np.linalg.svd(xyz - xyz.mean(0), full_matrices=False)[2][0]
        t = xyz @ axis
        segments[h.id] = xyz[[t.argmin(), t.argmax()]]
    distances, hits = [], []
    for a, b in combinations(segments, 2):
        if owner[a] == owner[b]:
            continue
        distance, point = segment_distance(segments[a], segments[b])
        distances.append(distance)
        if distance < 2.0 - 1e-6:
            hits.append(point.tolist())
    points = np.array([b["backbone_position"] for b in geometry])
    close = cKDTree(points).query_pairs(0.5)
    close = [
        (a, b)
        for a, b in close
        if owner[geometry[a]["helix_id"]] != owner[geometry[b]["helix_id"]]
    ]
    return (
        {
            "interbody_helix_pairs_below_2nm": len(hits),
            "minimum_interbody_axis_distance_nm": min(distances, default=None),
            "interbody_backbone_pairs_below_0_5nm": len(close),
        },
        hits,
        geometry,
        segments,
        owner,
    )


def run(folder):
    """Compatibility entry point; rejects legacy source histories before fitting."""
    from tools.design_archive.shared_pipeline import run as shared_run
    return shared_run(design_id='D003', run_id='recorded-clash-fit',
                      source_part=Path(folder) / 'D003_rigid_clusters_verified.nadoc', relax=True)


if __name__ == '__main__':
    run(Path('workspace/Experimental/D003'))

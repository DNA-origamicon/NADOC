"""Opt-in surface diagnostics; never changes display geometry or adds render latency.

Angles measure turns between adjacent face normals (0 = locally flat). Report
length-weighted distributions and sharp-edge length per surface area alongside
mesh size: raw counts alone reward coarser tessellation. Thresholds are diagnostic,
not a scientific validity gate. Separate strand-shell intersections are not detected.
"""

from __future__ import annotations

import numpy as np


def surface_quality(mesh, *, hotspot_limit: int = 20) -> dict:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64).reshape(-1, 3)
    if not np.isfinite(vertices).all():
        raise ValueError("Surface contains non-finite vertices")
    triangles = vertices[faces]
    cross = np.cross(
        triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    )
    double_area = np.linalg.norm(cross, axis=1)
    valid = double_area > 1e-14
    normals = np.zeros_like(cross)
    normals[valid] = cross[valid] / double_area[valid, None]
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    owners = np.tile(np.arange(len(faces)), 3)
    edges.sort(axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges, owners = edges[order], owners[order]
    starts = np.r_[0, np.flatnonzero(np.any(np.diff(edges, axis=0), axis=1)) + 1]
    if not len(edges):
        starts = np.empty(0, dtype=int)
    counts = np.diff(np.r_[starts, len(edges)])
    paired = starts[counts == 2]
    left, right = owners[paired], owners[paired + 1]
    good = valid[left] & valid[right]
    paired, left, right = paired[good], left[good], right[good]
    shared = edges[paired]
    lengths = np.linalg.norm(vertices[shared[:, 1]] - vertices[shared[:, 0]], axis=1)
    angle = np.degrees(
        np.arccos(np.clip(np.einsum("ij,ij->i", normals[left], normals[right]), -1, 1))
    )
    total_length = float(lengths.sum())
    area = float(double_area.sum() / 2)
    sorted_angles = np.argsort(angle)
    cumulative = np.cumsum(lengths[sorted_angles])

    def percentile(p):
        if not total_length:
            return None
        row = min(int(np.searchsorted(cumulative, p * total_length)), len(angle) - 1)
        return float(angle[sorted_angles[row]])

    result = {
        "vertices": len(vertices),
        "faces": len(faces),
        "area_nm2": area,
        "boundary_edges": int(np.count_nonzero(counts == 1)),
        "nonmanifold_edges": int(np.count_nonzero(counts > 2)),
        "degenerate_faces": int(np.count_nonzero(~valid)),
        "measured_edges": len(shared),
        "measured_edge_length_nm": total_length,
        "normal_turn_p95_deg": percentile(0.95),
        "normal_turn_p99_deg": percentile(0.99),
        "normal_turn_max_deg": float(angle.max()) if len(angle) else None,
        "thresholds": {},
        "hotspots": [],
        "limitations": "Adjacent faces only; does not detect intersections between independent strand shells. Compare matched grid/probe/geometry; sharp features can be legitimate.",
    }
    for threshold in (30, 60, 90):
        selected = angle > threshold
        length = float(lengths[selected].sum())
        result["thresholds"][str(threshold)] = {
            "edges": int(selected.sum()),
            "length_nm": length,
            "edge_length_percent": 100 * length / total_length if total_length else 0.0,
            "length_per_area_nm_inverse": length / area if area else 0.0,
        }
    for i in sorted_angles[-max(0, hotspot_limit) :][::-1] if hotspot_limit > 0 else []:
        a, b = shared[i]
        result["hotspots"].append(
            {
                "normal_turn_deg": float(angle[i]),
                "edge_length_nm": float(lengths[i]),
                "position_nm": ((vertices[a] + vertices[b]) / 2).tolist(),
                "vertex_indices": [int(a), int(b)],
                "face_indices": [int(left[i]), int(right[i])],
                "strand_id": mesh.vertex_strand_ids[a]
                if len(mesh.vertex_strand_ids) == len(vertices)
                else None,
            }
        )
    return result

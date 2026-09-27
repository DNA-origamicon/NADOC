"""Conforming local refinement of sharp display-surface patches.

Split only edges around >=60 degree normal turns, then relax interior patch
vertices within 0.01 nm of the reference mesh. Patch boundaries stay fixed.
This is bounded mesh regularization, not a new analytical solvent surface.
Molecular coordinates and independent shell ownership are never changed.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree
from backend.core.surface_progress import report


def _edge_table(faces):
    edges = np.sort(
        np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1
    )
    # Integer keys avoid NumPy's expensive structured row sorting on millions
    # of edges. Vertex indices fit int32 in the mesh wire format.
    stride = int(faces.max()) + 1
    keys = edges[:, 0] * stride + edges[:, 1]
    # One stable ordering supplies unique edges, face ownership, and inverse
    # indices. Previously np.unique plus argsort(inverse) sorted these twice.
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    starts = np.r_[0, np.flatnonzero(sorted_keys[1:] != sorted_keys[:-1]) + 1]
    counts = np.diff(np.r_[starts, len(keys)])
    unique_keys = sorted_keys[starts]
    unique = np.column_stack([unique_keys // stride, unique_keys % stride])
    inverse = np.empty(len(keys), dtype=np.int64)
    inverse[order] = np.repeat(np.arange(len(starts)), counts)
    paired = np.flatnonzero(counts == 2)
    owners = np.tile(np.arange(len(faces)), 3)[order]
    adjacent = np.column_stack([owners[starts[paired]], owners[starts[paired] + 1]])
    return unique, inverse.reshape(3, -1).T, paired, adjacent


def _normals(vertices, faces):
    tri = vertices[faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    size = np.linalg.norm(cross, axis=1)
    return cross / np.maximum(size[:, None], 1e-30), size


def remesh_sharp_patches(
    mesh, *, threshold_deg=60.0, max_displacement=0.01, iterations=8
):
    """Conforming red/green refinement with bounded, non-flipping relaxation.

    Only accept relaxation steps that reduce length-weighted squared normal turn
    above the threshold. Return the original mesh if no such improvement exists.
    Ownership for new/moved points is assigned to the nearest original vertex.
    """
    from backend.core.surface import SurfaceMesh

    if not len(mesh.faces):
        return mesh
    report("Detecting sharp surface edges")
    original = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges, face_edges, paired, adjacent = _edge_table(faces)
    normals, _ = _normals(original, faces)
    cosines = np.einsum("ij,ij->i", normals[adjacent[:, 0]], normals[adjacent[:, 1]])
    sharp = paired[cosines <= np.cos(np.deg2rad(threshold_deg))]
    if not len(sharp):
        return mesh
    # Refine complete triangles touching a sharp edge. Neighbor triangles receive
    # matching edge splits (green refinement), so no hanging nodes or cracks.
    report("Refining sharp patches")
    selected_faces = np.any(np.isin(face_edges, sharp), axis=1)
    split_ids = np.unique(face_edges[selected_faces])
    split_edges = edges[split_ids]
    midpoint_ids = np.full(len(edges), -1, dtype=np.int64)
    midpoint_ids[split_ids] = len(original) + np.arange(len(split_ids))
    vertices = np.concatenate([original, original[split_edges].mean(axis=1)])
    mids = midpoint_ids[face_edges]
    changed = np.any(mids >= 0, axis=1)
    refined = []
    for (a, b, c), (ab, bc, ca) in zip(faces[changed], mids[changed]):
        count = int(ab >= 0) + int(bc >= 0) + int(ca >= 0)
        if count == 3:
            refined.extend([(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)])
        elif count == 1:
            if bc >= 0:
                a, b, c, ab = b, c, a, bc
            elif ca >= 0:
                a, b, c, ab = c, a, b, ca
            refined.extend([(a, ab, c), (ab, b, c)])
        else:
            # Rotate so the unsplit edge is ca.
            if ab < 0:
                a, b, c, ab, bc = b, c, a, bc, ca
            elif bc < 0:
                a, b, c, ab, bc = c, a, b, ca, ab
            refined.extend([(ab, b, bc), (a, ab, c), (ab, bc, c)])
    new_faces = np.concatenate([faces[~changed], np.asarray(refined)])
    # Local relaxation includes original sharp endpoints and new edge midpoints;
    # all other vertices (including the patch rim) remain exactly unchanged.
    active = np.unique(
        np.r_[edges[sharp].ravel(), np.arange(len(original), len(vertices))]
    )
    local_face_mask = np.any(np.isin(new_faces, active), axis=1)
    # Include a fixed face ring so the objective sees turns across the patch rim.
    rim = np.unique(new_faces[local_face_mask])
    local_face_mask = np.any(np.isin(new_faces, rim), axis=1)
    local_faces_global = new_faces[local_face_mask]
    local_ids, inv = np.unique(local_faces_global, return_inverse=True)
    local_faces = inv.reshape(-1, 3)
    reference = vertices[local_ids].copy()
    current = reference.copy()
    moving = np.isin(local_ids, active)
    le, _, lp, la = _edge_table(local_faces)
    row = np.r_[le[:, 0], le[:, 1]]
    col = np.r_[le[:, 1], le[:, 0]]
    adj = csr_matrix(
        (np.ones(len(row)), (row, col)), shape=(len(local_ids), len(local_ids))
    )
    degree = np.asarray(adj.sum(axis=1)).ravel()
    ref_normals, ref_area = _normals(reference, local_faces)

    def score(v):
        n, _ = _normals(v, local_faces)
        angle = np.degrees(
            np.arccos(np.clip(np.einsum("ij,ij->i", n[la[:, 0]], n[la[:, 1]]), -1, 1))
        )
        length = np.linalg.norm(v[le[lp, 0]] - v[le[lp, 1]], axis=1)
        return float(np.sum(length * np.maximum(angle - threshold_deg, 0) ** 2))

    initial_score = best_score = score(current)
    for iteration in range(iterations):
        report(f"Relaxing sharp patches (pass {iteration + 1}, up to {iterations})")
        delta = 0.35 * (adj @ current / degree[:, None] - current)
        delta[~moving] = 0
        accepted = False
        for scale in (1.0, 0.5, 0.25, 0.125):
            candidate = current + scale * delta
            displacement = candidate - reference
            length = np.linalg.norm(displacement, axis=1)
            candidate = (
                reference
                + displacement
                * np.minimum(1, max_displacement / np.maximum(length, 1e-30))[:, None]
            )
            n, area = _normals(candidate, local_faces)
            if np.any(np.einsum("ij,ij->i", n, ref_normals) < 0.2) or np.any(
                area < ref_area * 0.1
            ):
                continue
            candidate_score = score(candidate)
            if candidate_score < best_score:
                current, best_score = candidate, candidate_score
                accepted = True
                break
        if not accepted:
            break
    if best_score >= initial_score:
        return mesh
    vertices[local_ids] = current
    # Only query affected/new vertices; unchanged ownership stays byte-identical.
    lookup = cKDTree(original).query(vertices[active], workers=-1)[1]

    def owners(values):
        if not values:
            return []
        result = list(values) + [""] * len(split_ids)
        for dst, src in zip(active, lookup):
            result[dst] = values[src]
        return result

    return SurfaceMesh(
        vertices.astype(np.float32),
        new_faces.astype(np.int32),
        owners(mesh.vertex_strand_ids),
        owners(mesh.vertex_nuc_ids),
    )

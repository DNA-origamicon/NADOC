"""Measured nucleotide base frames for the NAMD Full trajectory transport.

Only display coordinates are derived here; no atom, design, or simulation input
is moved. The caller supplies the phosphate-derived display rotation and anchors.
"""
from __future__ import annotations

import numpy as np

_RING_NAMES = {"N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4"}


def base_frame_layout(ctx):
    """Cache residue-ring indices for P-bearing bases and recovered O5' termini."""
    cached = ctx.get("full_base_layout")
    if cached is not None:
        return cached
    u = ctx["universe"]
    anchors = list(ctx["dna_p_idx"]) + [s[1] for s in ctx.get("term_specs", [])]
    rings = []
    for anchor in anchors:
        atoms = u.atoms[int(anchor)].residue.atoms
        rings.append(np.asarray([int(a.index) for a in atoms if str(a.name) in _RING_NAMES]))
    # Group by ring size so centers/least-squares planes are batched per frame.
    groups = []
    for size in sorted({len(r) for r in rings if len(r) >= 5}):
        rows = np.asarray([i for i, r in enumerate(rings) if len(r) == size])
        groups.append((rows, np.stack([rings[i] for i in rows])))
    cached = (np.asarray(anchors, dtype=np.int64), groups)
    ctx["full_base_layout"] = cached
    return cached


def measured_base_frames(raw_nm, anchor_indices, groups, aligned_anchors, rotation, box_nm):
    """Ring centroids and plane normals in the caller's exact display frame.

    Image every ring atom relative to its own residue anchor BEFORE averaging:
    averaging wrapped positions first loses the ring when it straddles a cell face.
    Missing/degenerate rings remain NaN so consumers can use their legacy fallback.
    """
    n = len(anchor_indices)
    centers = np.full((n, 3), np.nan)
    tangents = np.full((n, 3), np.nan)
    rotation = np.eye(3) if rotation is None else rotation
    for rows, indices in groups:
        delta = raw_nm[indices] - raw_nm[anchor_indices[rows], None, :]
        if box_nm is not None:
            good = np.asarray(box_nm) > 0
            delta[..., good] -= np.round(delta[..., good] / box_nm[good]) * box_nm[good]
        delta = delta @ rotation.T
        center = delta.mean(axis=1)
        centers[rows] = aligned_anchors[rows] + center
        _, singular, axes = np.linalg.svd(delta - center[:, None, :], full_matrices=False)
        normal = axes[:, -1, :]
        # Resolve SVD's arbitrary sign from the ordered measured ring itself.
        orient = np.cross(delta[:, 1] - delta[:, 0], delta[:, 2] - delta[:, 0])
        normal *= np.where((normal * orient).sum(axis=1) < 0, -1, 1)[:, None]
        valid = singular[:, 1] > 1e-8
        tangents[rows[valid]] = normal[valid]
    return centers, tangents

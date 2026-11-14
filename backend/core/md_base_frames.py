"""Measured nucleotide base frames for the NAMD Full trajectory transport.

Only display coordinates are derived here; no atom, design, or simulation input
is moved. The caller supplies the phosphate-derived display rotation and anchors.
"""
from __future__ import annotations

import numpy as np

_RING_NAMES = {"N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4"}


def ordered_ring_indices(atoms):
    """Chemical ring order, independent of PSF/PDB atom storage order."""
    names = ("N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4") if "N9" in atoms else (
        "N1", "C2", "N3", "C4", "C5", "C6")
    return np.asarray([atoms[name] for name in names if name in atoms], dtype=np.int64)


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
        rings.append(ordered_ring_indices({str(a.name): int(a.index) for a in atoms}))
    # Group by ring size so centers/least-squares planes are batched per frame.
    groups = []
    for size in sorted({len(r) for r in rings if len(r) >= 5}):
        rows = np.asarray([i for i, r in enumerate(rings) if len(r) == size])
        groups.append((rows, np.stack([rings[i] for i in rows])))
    cached = (np.asarray(anchors, dtype=np.int64), groups)
    ctx["full_base_layout"] = cached
    return cached


def measured_base_frames(raw_nm, anchor_indices, groups, aligned_anchors, rotation, box_nm,
                         *, inward_out=None):
    """Ring centroids and plane normals in the caller's exact display frame.

    Image every ring atom relative to its own residue anchor BEFORE averaging:
    averaging wrapped positions first loses the ring when it straddles a cell face.
    Missing/degenerate rings remain NaN so consumers can use their legacy fallback.
    If inward_out is supplied, groups must use ordered_ring_indices; complete
    rings replace its fallback vectors with measured in-plane chemical directions.
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
        if inward_out is not None and indices.shape[1] in (6, 9):
            # N1→C4 (pyrimidine), N9→C6 (purine): a named ring span.
            # P→C1' can be almost perpendicular to a puckered CPD base plane;
            # projecting that sugar vector produces arbitrary in-plane rotations.
            opposite = 3 if indices.shape[1] == 6 else 4
            inward = delta[:, opposite] - delta[:, 0]
            inward -= (inward * normal).sum(axis=1)[:, None] * normal
            length = np.linalg.norm(inward, axis=1)
            good = valid & (length > 1e-8)
            inward_out[rows[good]] = inward[good] / length[good, None]
    return centers, tangents


def apply_measured_display_frames(ctx, positions, rotation, box_nm, *, raw_positions_ang=None):
    """Enrich live MD rows without changing their shared backbone display affine.

    Missing/degenerate rings retain the caller's coarse fallback. Read the injected
    live frame when supplied, never a potentially stale Universe timestep.
    """
    anchors, groups = base_frame_layout(ctx)
    count = min(len(positions), len(anchors))
    if not count or not groups:
        return
    groups = [(rows[rows < count], rings[rows < count]) for rows, rings in groups
              if np.any(rows < count)]
    if not groups:
        return
    last = max(int(anchors[:count].max()), max(int(rings.max()) for _, rings in groups))
    raw = (ctx["universe"].atoms[:last + 1].positions if raw_positions_ang is None
           else raw_positions_ang[:last + 1]) / 10.0
    aligned = np.asarray([[p["x"], p["y"], p["z"]] for p in positions[:count]])
    inward = np.asarray([[p.get("nx", 0), p.get("ny", 0), p.get("nz", 1)]
                         for p in positions[:count]], dtype=float)
    centers, planes = measured_base_frames(raw, anchors[:count], groups, aligned,
                                           rotation, box_nm, inward_out=inward)
    for i, row in enumerate(positions[:count]):
        if not (np.isfinite(centers[i]).all() and np.isfinite(planes[i]).all()):
            continue
        row.update(zip(("bx", "by", "bz"), map(float, centers[i])))
        row.update(zip(("tx", "ty", "tz"), map(float, planes[i])))
        row.update(zip(("nx", "ny", "nz"), map(float, inward[i])))
        row["measured_base"] = True


def display_row_key(row) -> str:
    """Frontend base key (scene/base_ref.js baseKey) for one live display row.

    Crossover inserts arrive as ``("__xb__", crossover_id, k)`` rows, which this
    formats as the canonical ``__xb__:<crossover_id>:<k>`` extra-base key.
    """
    copy = int(row.get("copy", 0) or 0)
    key = f"{row['helix_id']}:{row['bp_index']}:{row['direction']}"
    return f"{key}:{copy}" if copy and row["helix_id"] != "__xb__" else key


def measured_residue_atoms(ctx, positions, rotation, box_nm, keys, *, raw_positions_ang=None):
    """Exact heavy atoms of the requested residues in the live display frame.

    Each atom is imaged relative to its residue anchor (P, or O5' for a 5'
    terminus), rotated by the frame's display rotation and added to the anchor's
    displayed position: the same transform as the measured ring centres, so the
    atoms sit on the displayed Full model. Coordinates come from the trajectory;
    no atom is reconstructed. Returns ``[[base_key, atom_name, x, y, z], ...]`` (nm).
    """
    wanted = {str(k) for k in keys or ()}
    if not wanted:
        return []
    anchors, _ = base_frame_layout(ctx)
    count = min(len(positions), len(anchors))
    rows = [(i, display_row_key(positions[i])) for i in range(count)]
    rows = [(i, key) for i, key in rows if key in wanted]
    if not rows:
        return []
    u = ctx["universe"]
    rotation = np.eye(3) if rotation is None else np.asarray(rotation, float)
    good = None if box_nm is None else np.asarray(box_nm, float) > 0
    out = []
    for i, key in rows:
        residue = [a for a in u.atoms[int(anchors[i])].residue.atoms
                   if not str(a.name).startswith("H") and not str(a.name)[:1].isdigit()]
        indices = np.asarray([int(a.index) for a in residue] + [int(anchors[i])])
        raw = (u.atoms[indices].positions if raw_positions_ang is None
               else np.asarray(raw_positions_ang)[indices]) / 10.0
        delta = raw[:-1] - raw[-1]
        if good is not None and good.any():
            box = np.asarray(box_nm, float)
            delta[:, good] -= np.round(delta[:, good] / box[good]) * box[good]
        anchor = np.asarray([positions[i]["x"], positions[i]["y"], positions[i]["z"]], float)
        placed = anchor + delta @ rotation.T
        out.extend([key, str(a.name), *map(float, p)] for a, p in zip(residue, placed))
    return out

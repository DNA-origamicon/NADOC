"""Accelerate Corner's clearance query while retaining native report order.

The native spatial-hash traversal is the oracle, including its report cap.
Only candidate discovery uses a tree; exclusions, distances and ordering retain
the native calculation. This changes no clearance thresholds or atom placement.
"""

import numpy as np
from scipy.spatial import cKDTree
from numba import njit


@njit(cache=True)
def nonbonded_candidates(pairs, bonds, atom_count):
    """Check one/two-bond exclusions only for spatial candidates, in order."""
    offsets = np.zeros(atom_count + 1, dtype=np.int64)
    for a, b in bonds:
        offsets[a + 1] += 1
        offsets[b + 1] += 1
    offsets = np.cumsum(offsets)
    cursor = offsets.copy()
    neighbours = np.empty(2 * len(bonds), dtype=np.int64)
    for a, b in bonds:
        neighbours[cursor[a]] = b
        cursor[a] += 1
        neighbours[cursor[b]] = a
        cursor[b] += 1
    keep = np.ones(len(pairs), dtype=np.bool_)
    for i in range(len(pairs)):
        a, b = pairs[i]
        for p in range(offsets[a], offsets[a + 1]):
            c = neighbours[p]
            if c == b:
                keep[i] = False
                break
            for q in range(offsets[c], offsets[c + 1]):
                if neighbours[q] == b:
                    keep[i] = False
                    break
            if not keep[i]:
                break
    return pairs[keep]


def find_clashes(pos, finite, bonds, clash_nm, max_report):
    indices = np.flatnonzero(finite)
    if len(indices) < 2:
        return []
    # Do the floor division and conversion once for the whole array. Keep the
    # original atom order and tuple keys: they determine capped report order.
    cell_rows = (pos[indices] // clash_nm).astype(int)
    cells = dict(zip(map(int, indices), map(tuple, cell_rows)))
    ranks = {}
    for cell in cells.values():
        if cell not in ranks:
            ranks[cell] = len(ranks)
    # Slightly overfetch at the boundary, then use the exact native norm below.
    pairs = cKDTree(pos[indices]).query_pairs(clash_nm * (1 + 1e-12), output_type='ndarray')
    pairs = nonbonded_candidates(indices[pairs], np.asarray(bonds, dtype=np.int64).reshape(-1, 2), len(pos))
    ordered = [tuple(map(int, pair)) for pair in pairs]
    ordered.sort(key=lambda pair: (ranks[cells[pair[0]]], pair[0], cells[pair[1]], pair[1]))
    out = []
    for a, b in ordered:
        distance = float(np.linalg.norm(pos[a]-pos[b]))
        if distance < clash_nm:
            out.append({'serials': [a, b], 'distance_nm': round(distance, 4)})
            if len(out) >= max_report:
                break
    return out

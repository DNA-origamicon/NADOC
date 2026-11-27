"""Accelerate Corner's clearance query while retaining native report order.

The native spatial-hash traversal is the oracle, including its report cap.
Only candidate discovery uses a tree; exclusions, distances and ordering retain
the native calculation. This changes no clearance thresholds or atom placement.
"""

import numpy as np
from scipy.spatial import cKDTree


def find_clashes(pos, finite, bonds, clash_nm, max_report):
    indices = np.flatnonzero(finite)
    if len(indices) < 2:
        return []
    neighbours = {}
    excluded = set()
    for i, j in bonds:
        excluded.add(tuple(sorted((i, j))))
        neighbours.setdefault(i, set()).add(j)
        neighbours.setdefault(j, set()).add(i)
    for row in neighbours.values():
        ordered = sorted(row)
        for offset, i in enumerate(ordered):
            excluded.update((i, j) for j in ordered[offset+1:])
    cells = {int(i): tuple((pos[i] // clash_nm).astype(int)) for i in indices}
    ranks = {}
    for cell in cells.values():
        if cell not in ranks:
            ranks[cell] = len(ranks)
    # Slightly overfetch at the boundary, then use the exact native norm below.
    pairs = cKDTree(pos[indices]).query_pairs(clash_nm * (1 + 1e-12), output_type='ndarray')
    ordered = [(int(indices[a]), int(indices[b])) for a, b in pairs
               if (int(indices[a]), int(indices[b])) not in excluded]
    ordered.sort(key=lambda pair: (ranks[cells[pair[0]]], pair[0], cells[pair[1]], pair[1]))
    out = []
    for a, b in ordered:
        distance = float(np.linalg.norm(pos[a]-pos[b]))
        if distance < clash_nm:
            out.append({'serials': [a, b], 'distance_nm': round(distance, 4)})
            if len(out) >= max_report:
                break
    return out

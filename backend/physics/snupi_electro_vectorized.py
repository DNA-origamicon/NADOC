"""Vectorized equivalent of the existing Debye-Huckel pair assembly.

Same cutoff, inter-helix exclusion, near-coincidence threshold and tangent.
Bounded typed COO batches replace unbounded Python scalar triplet lists.
"""

import numpy as np
from scipy.sparse import csr_matrix, coo_matrix
from scipy.spatial import cKDTree


def electro_sparse(
    helix_ids, positions, prm, *, scale=1.0, axial_only=False, batch_size=32768
):
    pos = np.asarray(positions, dtype=float)
    count = len(pos)
    shape = (6 * count, 6 * count)
    result = csr_matrix(shape, dtype=float)
    force = np.zeros(6 * count)
    if scale == 0 or count < 2:
        return result, force
    pairs = cKDTree(pos).query_pairs(prm.r_cut, output_type="ndarray")
    # Encode IDs once; avoid an object comparison for every candidate neighbor.
    codes = {}
    hid = np.array([codes.setdefault(h, len(codes)) for h in helix_ids])
    offsets = np.arange(3)
    for first in range(0, len(pairs), batch_size):
        pair = pairs[first : first + batch_size]
        pair = pair[hid[pair[:, 0]] != hid[pair[:, 1]]]
        if not len(pair):
            continue
        delta = pos[pair[:, 1]] - pos[pair[:, 0]]
        r = np.linalg.norm(delta, axis=1)
        keep = r >= 1e-9
        pair, delta, r = pair[keep], delta[keep], r[keep]
        if not len(pair):
            continue
        direction = delta / r[:, None]
        exponential = np.exp(-r / prm.lambda_d)
        dpi = -prm.prefactor * exponential * (1 / (r * r) + 1 / (r * prm.lambda_d))
        d2pi = (
            prm.prefactor
            * exponential
            * (2 / r**3 + 2 / (r * r * prm.lambda_d) + 1 / (r * prm.lambda_d**2))
        )
        outer = direction[:, :, None] * direction[:, None, :]
        block = d2pi[:, None, None] * outer
        if not axial_only:
            block += (dpi / r)[:, None, None] * (np.eye(3) - outer)
        block *= scale
        f = (-dpi * scale)[:, None] * direction
        ii = pair[:, 0, None] * 6 + offsets
        jj = pair[:, 1, None] * 6 + offsets
        np.add.at(force, jj, f)
        np.add.at(force, ii, -f)
        rows = np.concatenate(
            [
                np.broadcast_to(x[:, :, None], block.shape).ravel()
                for x in (jj, ii, jj, ii)
            ]
        )
        cols = np.concatenate(
            [
                np.broadcast_to(x[:, None, :], block.shape).ravel()
                for x in (jj, ii, ii, jj)
            ]
        )
        values = np.concatenate(
            [block.ravel(), block.ravel(), -block.ravel(), -block.ravel()]
        )
        keep = values != 0
        result += coo_matrix(
            (values[keep], (rows[keep], cols[keep])), shape=shape
        ).tocsr()
    return result, force

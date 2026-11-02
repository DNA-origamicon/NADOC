"""Bounded batches of the existing centroid-fan segment/ring intersection.

Precompute each ring's triangles once. All tolerances, neighbour radius,
shared-atom exclusion, first intersected fan triangle and hit order are retained.
"""
import numpy as np
from scipy.spatial import cKDTree

_BOND_BATCH = 512
_PAIR_BATCH = 4096


def scan(positions, bonds, rings, *, max_report, search_nm, progress=None, cancelled=None):
    def checkpoint(done):
        if cancelled and cancelled():
            raise InterruptedError('Piercing check cancelled')
        if progress:
            progress(done, len(bonds))

    checkpoint(0)
    if not bonds or not rings:
        if bonds:
            checkpoint(len(bonds))
        return []
    positions = np.asarray(positions, dtype=float)
    sizes = np.asarray([len(row[2]) for row in rings])
    width = int(sizes.max())
    serials = np.full((len(rings), width), -1, dtype=int)
    centres = np.empty((len(rings), 3))
    e1 = np.zeros((len(rings), width, 3))
    e2 = np.zeros_like(e1)
    for size in np.unique(sizes):
        ids = np.flatnonzero(sizes == size)
        indices = np.asarray([rings[i][2] for i in ids], dtype=int)
        points = positions[indices]
        centres[ids] = points.mean(axis=1)
        serials[ids, :size] = indices
        if size >= 3:
            e1[ids, :size] = points - centres[ids, None, :]
            e2[ids, :size] = np.roll(points, -1, axis=1) - centres[ids, None, :]
    tree = cKDTree(centres)
    bond_arr = np.asarray(bonds, dtype=int)
    hits = []
    for start in range(0, len(bonds), _BOND_BATCH):
        if cancelled and cancelled():
            raise InterruptedError('Piercing check cancelled')
        end = min(len(bonds), start + _BOND_BATCH)
        block = bond_arr[start:end]
        mids = .5 * (positions[block[:, 0]] + positions[block[:, 1]])
        near = tree.query_ball_point(mids, r=search_nm, return_sorted=True)
        lengths = np.fromiter((len(row) for row in near), dtype=int, count=len(near))
        bi = np.repeat(np.arange(start, end), lengths)
        ri = np.concatenate(near).astype(int) if lengths.sum() else np.empty(0, dtype=int)
        for offset in range(0, len(ri), _PAIR_BATCH):
            if cancelled and cancelled():
                raise InterruptedError('Piercing check cancelled')
            rb = ri[offset:offset + _PAIR_BATCH]
            bb = bi[offset:offset + _PAIR_BATCH]
            pairs = bond_arr[bb]
            shared = ((serials[rb] == pairs[:, 0, None]) | (serials[rb] == pairs[:, 1, None])).any(axis=1)
            rb, bb, pairs = rb[~shared], bb[~shared], pairs[~shared]
            if not len(rb):
                continue
            p0 = positions[pairs[:, 0]]
            d = positions[pairs[:, 1]] - p0
            first, second = e1[rb], e2[rb]
            h = np.cross(d[:, None, :], second)
            a = np.einsum('nij,nij->ni', first, h)
            ok = np.abs(a) > 1e-14
            f = np.zeros_like(a)
            f[ok] = 1.0 / a[ok]
            s = p0 - centres[rb]
            u = f * np.einsum('nj,nij->ni', s, h)
            ok &= (u >= 0.0) & (u <= 1.0)
            q = np.cross(s[:, None, :], first)
            v = f * np.einsum('nj,nij->ni', d, q)
            ok &= (v >= 0.0) & (u + v <= 1.0)
            t = f * np.einsum('nij,nij->ni', second, q)
            ok &= (t > 1e-9) & (t < 1.0 - 1e-9)
            for k in np.flatnonzero(ok.any(axis=1)):
                if len(hits) >= max_report:
                    return hits
                i, j = map(int, pairs[k])
                label, kind, ring_serials = rings[rb[k]]
                first_hit = int(np.argmax(ok[k]))
                hits.append({'bond_serials': [i, j], 'ring_serials': list(ring_serials),
                    'ring_kind': kind, 'ring': label, 't': round(float(t[k, first_hit]), 3),
                    'bond_len_nm': round(float(np.linalg.norm(positions[i] - positions[j])), 4)})
        checkpoint(end)
    return hits

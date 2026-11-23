"""Bounded-memory linear rigid-motion projection and population RMSF."""

import numpy as np


def linear_rmsf(frames, ref, batch_size=16):
    ref_c = ref - ref.mean(axis=0)
    rigid = np.column_stack(
        [np.tile(axis, (len(ref), 1)).ravel() for axis in np.eye(3)]
        + [np.cross(axis, ref_c).ravel() for axis in np.eye(3)]
    )
    basis, singular, _ = np.linalg.svd(rigid, full_matrices=False)
    tol = singular.max() * max(rigid.shape) * np.finfo(float).eps
    basis = basis[:, singular > tol]
    mean = np.zeros(ref.size)
    m2 = np.zeros(ref.size)
    count = 0
    for start in range(0, len(frames), batch_size):
        block = (np.asarray(frames[start : start + batch_size], dtype=float) - ref).reshape(-1, ref.size)
        block -= (block @ basis) @ basis.T
        n = len(block)
        block_mean = block.mean(axis=0)
        delta = block_mean - mean
        block -= block_mean
        m2 += np.einsum("ij,ij->j", block, block) + delta**2 * (count * n / (count + n))
        mean += delta * n / (count + n)
        count += n
    return np.sqrt((m2 / count).reshape(-1, 3).sum(axis=1))

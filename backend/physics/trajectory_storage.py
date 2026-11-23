"""Allocate sampled trajectories once, without a list-to-array peak copy."""
import numpy as np


def allocate_samples(q, n_steps, n_equil, sample_every):
    """Match the integrators' sampling indices, including empty trajectories."""
    if sample_every <= 0:
        raise ValueError("sample_every must be positive")
    first = n_equil + max(0, (-n_equil + sample_every - 1) // sample_every) * sample_every
    count = max(0, (n_steps - first + sample_every - 1) // sample_every)
    # Preserve the legacy empty-list conversion shape.
    return np.empty((count, *np.shape(q)) if count else (0,), dtype=float)

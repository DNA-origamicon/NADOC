"""Corner duplex stamping with the original per-atom BLAS operations.

Do not replace these matrix-vector calls with one matrix-matrix product: last
bit changes can alter the downstream minimizer trajectory. No fast math.
"""

from functools import lru_cache

import numpy as np
from numba import njit


@lru_cache(maxsize=8)
def local_coordinates(residue, direction):
    from backend.core.atomistic import _native_local_defs
    return np.array([row[2:] for row in _native_local_defs(residue, direction)])


@njit(cache=True)
def stamp(origin, rotation, local):
    world = np.empty_like(local)
    for i in range(len(local)):
        world[i] = origin + rotation @ local[i]
    return world

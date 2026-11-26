"""Optional compiled integer domain lookup; NumPy remains the portable oracle.

Only row ownership and opposite-strand occupancy are assigned here. Coordinate,
slab, deformation and topology authorities are unchanged.
"""
from functools import lru_cache
import ctypes
import os
from pathlib import Path

import numpy as np


def assign_domains_numpy(bp, direction, domains):
    owner = np.full(len(bp), -1, dtype=np.int64)
    opposite = np.zeros(len(bp), dtype=np.uint8)
    for index, (lo, hi, strand_direction) in enumerate(domains):
        interval = (bp >= lo) & (bp <= hi)
        owner[interval & (direction == strand_direction)] = index
        opposite[interval & (direction != strand_direction)] = 1
    return owner, opposite.astype(bool)


@lru_cache(maxsize=1)
def _kernel():
    if os.environ.get('NADOC_NATIVE_DOMAINS', '1') == '0':
        return None
    path = Path(os.environ.get('NADOC_NATIVE_DOMAIN_LIBRARY',
                               str(Path(__file__).with_name('_domain_assignment_native.so'))))
    try:
        library = ctypes.CDLL(str(path))
        fn = library.nadoc_assign_domains_v1
    except (OSError, AttributeError):
        return None
    pointer = np.ctypeslib.ndpointer(dtype=np.int64, flags='C_CONTIGUOUS')
    byte_pointer = np.ctypeslib.ndpointer(dtype=np.uint8, flags='C_CONTIGUOUS')
    fn.argtypes = [pointer, pointer, ctypes.c_int64, pointer, ctypes.c_int64, pointer, byte_pointer]
    fn.restype = None
    return fn


def native_domains_available():
    return _kernel() is not None


def assign_domains(bp, direction, domains):
    """Return exact last matching domain and opposite occupancy for each row."""
    bp = np.ascontiguousarray(bp, dtype=np.int64)
    direction = np.ascontiguousarray(direction, dtype=np.int64)
    domains = np.ascontiguousarray(domains, dtype=np.int64).reshape(-1, 3)
    if bp.ndim != 1 or direction.shape != bp.shape:
        raise ValueError('Domain assignment requires aligned one-dimensional rows')
    fn = _kernel()
    if fn is None:
        return assign_domains_numpy(bp, direction, domains)
    owner = np.empty(len(bp), dtype=np.int64)
    opposite = np.empty(len(bp), dtype=np.uint8)
    fn(bp, direction, len(bp), domains, len(domains), owner, opposite)
    return owner, opposite.astype(bool)

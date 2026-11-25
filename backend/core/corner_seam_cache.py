"""Small cache of exact numerical Corner fits, independent of operation UUIDs.

Every coordinate, environment atom, constraint and iteration limit participates
in the key. No rounding, symmetry assumption or approximate reuse is allowed.
"""

from collections import OrderedDict
import hashlib
import threading

import numpy as np


_lock = threading.Lock()
_entries = OrderedDict()
_MAX_ENTRIES = 128
_MAX_BYTES = 16 * 1024**2


def fit_key(problem, max_iterations):
    digest = hashlib.sha256(b'approved-corner-closure-v1')
    arrays = [problem.original, problem.bridges, problem.free, problem.pairs,
              np.asarray(problem.branches, dtype=np.int64), *problem.bodies]
    if problem.environment is not None:
        arrays.append(problem.environment.data)
    digest.update(str((max_iterations, len(problem.bodies), problem.environment is not None)).encode())
    for array in arrays:
        array = np.ascontiguousarray(array)
        digest.update(str((array.shape, array.dtype.str)).encode())
        digest.update(array.tobytes())
    return digest.digest()


def get_fit(key):
    with _lock:
        entry = _entries.get(key)
        if entry is not None:
            _entries.move_to_end(key)
            xyz, report = entry
            return xyz.copy(), dict(report)
    return None


def put_fit(key, xyz, report):
    with _lock:
        _entries[key] = xyz.copy(), dict(report)
        _entries.move_to_end(key)
        while len(_entries) > _MAX_ENTRIES or sum(row[0].nbytes for row in _entries.values()) > _MAX_BYTES:
            _entries.popitem(last=False)


def clear_fit_cache():
    with _lock:
        _entries.clear()


def export_fits():
    """Private worker transport; preserve exact double values and ownership."""
    with _lock:
        return [(key.hex(), xyz.tolist(), dict(report)) for key, (xyz, report) in _entries.items()]


def import_fits(rows):
    for key, xyz, report in rows:
        put_fit(bytes.fromhex(key), np.asarray(xyz, dtype=float), report)

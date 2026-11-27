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
_MAX_ENTRIES = 512
_MAX_BYTES = 16 * 1024**2


def fit_key(problem, max_iterations, *, include_environment=True):
    digest = hashlib.sha256(b'approved-corner-closure-v1')
    arrays = [problem.original, problem.bridges, problem.free, problem.pairs,
              np.asarray(problem.branches, dtype=np.int64), *problem.bodies]
    if include_environment and problem.environment is not None:
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
    from backend.core.corner_seam_dependencies import clear_dependencies
    with _lock:
        _entries.clear()
    clear_dependencies()


def export_fits():
    """Private worker transport; preserve exact double values and ownership."""
    from backend.core.corner_seam_dependencies import export_dependencies
    with _lock:
        rows = [(key.hex(), xyz.tolist(), dict(report)) for key, (xyz, report) in _entries.items()]
    return rows + export_dependencies()


def import_fits(rows):
    from backend.core.corner_seam_dependencies import import_dependency
    for row in rows:
        if row[0] == 'dependency-v1':
            import_dependency(row)
        else:
            key, xyz, report = row
            put_fit(bytes.fromhex(key), np.asarray(xyz, dtype=float), report)

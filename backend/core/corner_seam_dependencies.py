"""Exact reuse of fits whose entire evaluated environment is unchanged.

Record a bounding box covering every clearance query in an optimizer trajectory,
including rejected line-search trials. Equal, ordered environment coordinates
inside that box imply equal objective values and gradients at every trial, hence
the same deterministic trajectory. Changes outside cannot contribute. This is
not a distance heuristic around the final seam or an approximate fit.
"""
from collections import OrderedDict
import hashlib
import threading
import weakref
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar

import numpy as np

_lock = threading.Lock()
_entries = OrderedDict()
_MAX_ENTRIES = 512
_MAX_BYTES = 16 * 1024**2
_trace = ContextVar('corner_dependency_trace', default=None)
_model_traces = OrderedDict()


def remember_model_dependencies(model, trace):
    from backend.core.memory_sizes import retained_bytes
    if not trace['fits'] or not trace['complete']:
        return
    charge = retained_bytes(trace) + 32 * len(trace['protected'])
    if charge > _MAX_BYTES:
        return
    identity = id(model)
    def released(reference):
        with _lock:
            row = _model_traces.get(identity)
            if row is not None and row[0] is reference:
                _model_traces.pop(identity, None)
    with _lock:
        _model_traces[identity] = weakref.ref(model, released), deepcopy(trace), charge
        while len(_model_traces) > 16 or sum(row[2] for row in _model_traces.values()) > _MAX_BYTES:
            _model_traces.popitem(last=False)


def model_dependencies(model):
    with _lock:
        row = _model_traces.get(id(model))
        return deepcopy(row[1]) if row is not None and row[0]() is model else {
            'complete': False, 'fits': 0, 'boxes': [], 'protected': set()}


@contextmanager
def capture_dependencies():
    result = {'complete': True, 'boxes': [], 'fits': 0, 'protected': set()}
    token = _trace.set(result)
    try:
        yield result
    finally:
        _trace.reset(token)


def trace_box(bounds, *, fit=False):
    result = _trace.get()
    if result is None:
        return
    if bounds is None:
        result['complete'] = False
        return
    bounds = np.asarray(bounds, dtype=float)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
        result['complete'] = False
        return
    result['boxes'].append(bounds + np.array([[-1.], [1.]]) * (.20 * (1 + 1e-12)))
    result['fits'] += int(fit)


def trace_clearance(positions, flexible, rows, cap, threshold):
    result = _trace.get()
    if result is None:
        return
    if not np.isfinite(positions).all():
        result['complete'] = False
        return
    if len(rows) >= cap:
        # Preserve the complete capped prefix AND each primary cell's first
        # atom. Deleting other atoms then cannot change native cell order or
        # expose a previously unreported contact ahead of that prefix.
        cells = (positions // threshold).astype(int)
        wanted = {tuple(cells[row['serials'][0]]) for row in rows}
        result['protected'].update(i for row in rows for i in row['serials'])
        for i, cell in enumerate(cells):
            key = tuple(cell)
            if key in wanted:
                result['protected'].add(i)
                wanted.remove(key)
                if not wanted:
                    break
    points = positions[list(flexible)]
    trace_box(np.array([points.min(axis=0), points.max(axis=0)]))


def _environment_digest(problem, bounds):
    points = problem.environment.data
    selected = points[np.all((points >= bounds[0]) & (points <= bounds[1]), axis=1)]
    # Preserve order, signed zeros and every bit. The objective's neighbour
    # arrays are sorted in environment order, so sorting coordinates is unsafe.
    return hashlib.sha256(selected.tobytes()).digest()


def find_dependency(problem, max_iterations):
    from backend.core.corner_seam_cache import fit_key
    if problem.environment is None:
        return None
    key = fit_key(problem, max_iterations, include_environment=False)
    with _lock:
        candidates = [(identity, row) for identity, row in _entries.items() if identity[0] == key]
    for identity, (bounds, digest, xyz, report) in reversed(candidates):
        if _environment_digest(problem, bounds) == digest:
            with _lock:
                if identity in _entries:
                    _entries.move_to_end(identity)
            return xyz.copy(), dict(report)
    return None


def _put(key, bounds, digest, xyz, report):
    identity = key, digest, bounds.tobytes()
    with _lock:
        _entries[identity] = bounds.copy(), digest, xyz.copy(), dict(report)
        _entries.move_to_end(identity)
        while len(_entries) > _MAX_ENTRIES or sum(
                row[0].nbytes + row[2].nbytes + 512 for row in _entries.values()) > _MAX_BYTES:
            _entries.popitem(last=False)


def remember_dependency(problem, max_iterations, xyz, report):
    from backend.core.corner_seam_cache import fit_key
    bounds = getattr(problem, 'query_bounds', None)
    if problem.environment is None or bounds is None or not np.isfinite(bounds).all():
        return
    # Conservative padding also covers floating-point boundary tests in KDTree.
    bounds = bounds + np.array([[-1.], [1.]]) * (.20 * (1 + 1e-12))
    key = fit_key(problem, max_iterations, include_environment=False)
    _put(key, bounds, _environment_digest(problem, bounds), xyz, report)


def clear_dependencies():
    with _lock:
        _entries.clear()
        _model_traces.clear()


def export_dependencies():
    with _lock:
        return [('dependency-v1', key.hex(), bounds.tolist(), digest.hex(), xyz.tolist(), dict(report))
                for (key, _, _), (bounds, digest, xyz, report) in _entries.items()]


def import_dependency(row):
    _, key, bounds, digest, xyz, report = row
    _put(bytes.fromhex(key), np.asarray(bounds, dtype=float), bytes.fromhex(digest),
         np.asarray(xyz, dtype=float), report)

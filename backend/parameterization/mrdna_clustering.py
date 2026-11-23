"""Exact scalar single-linkage clustering for mrDNA's bead-size grouping.

Only the current model-building thread is adapted; unrelated SciPy calls retain
their original implementation. No external mrDNA checkout is edited.
"""
from contextlib import contextmanager
import threading

import numpy as np

_LOCK = threading.RLock()


def scalar_distance_clusters(data, threshold):
    """Single-linkage distance cut on finite scalar observations (labels arbitrary).

In one dimension, connected components of the threshold graph are separated
exactly by adjacent sorted gaps. Avoid the quadratic condensed-distance array.
"""
    values = np.asarray(data, dtype=np.float64).reshape(-1)
    order = np.argsort(values, kind="stable")
    gaps = np.diff(values[order])
    # Match Euclidean pdist's sqrt(delta * delta), including threshold rounding.
    np.square(gaps, out=gaps)
    np.sqrt(gaps, out=gaps)
    labels = np.empty(len(values), dtype=np.int32)
    labels[order] = np.r_[1, 1 + np.cumsum(gaps > threshold)]
    return labels


@contextmanager
def bead_size_clustering():
    """Adapt only mrDNA's scalar distance-cut calls; restore SciPy on every exit."""
    import scipy.cluster.hierarchy as hierarchy

    with _LOCK:
        original = hierarchy.fclusterdata
        owner = threading.get_ident()

        def dispatch(X, t, criterion="inconsistent", metric="euclidean", depth=2,
                     method="single", R=None):
            data = np.asarray(X)
            if (threading.get_ident() == owner and criterion == "distance"
                    and metric == "euclidean" and method == "single" and R is None
                    and data.ndim == 2 and data.shape[1] == 1 and len(data) >= 2
                    and np.isfinite(data).all() and np.isfinite(t) and t >= 0):
                return scalar_distance_clusters(data, t)
            return original(X, t, criterion=criterion, metric=metric, depth=depth,
                            method=method, R=R)

        hierarchy.fclusterdata = dispatch
        try:
            yield
        finally:
            hierarchy.fclusterdata = original

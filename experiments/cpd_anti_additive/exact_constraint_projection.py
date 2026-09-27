"""Exact Cartesian convergence projection for the registered single torsion.

This replaces only the convergence metric in an explicitly isolated worker.
It does not change the QM model, optimizer steps, or acceptance thresholds.
"""

import numpy as np


def exact_gradient_projection(internals, xyz, gradient):
    if internals.rigid or len(internals.Prims.cPrims) != 1:
        raise ValueError('This diagnostic supports exactly one constraint and no rigid fragments')
    normal = np.asarray(internals.Prims.cPrims[0].derivative(np.asarray(xyz).reshape(-1, 3))).ravel()
    gradient = np.asarray(gradient).ravel()
    if normal.shape != gradient.shape or not np.isfinite(normal).all() or not np.isfinite(gradient).all():
        raise ValueError('Invalid Cartesian constraint gradient')
    denominator = float(normal @ normal)
    if denominator <= 1e-20:
        raise ValueError('Degenerate constraint normal')
    return gradient-normal*float(normal @ gradient)/denominator

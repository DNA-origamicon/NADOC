"""Bounded conservative plain-GJF timestep selection.

For A=M**(-1/2) K M**(-1/2), any strictly positive vector v gives
rho(A) <= rho(abs(A)) <= max_i (abs(A) v)_i/v_i. Fixed positive
power updates tighten this bound without relying on eigenvalue convergence.
K must be the real symmetric linear tangent, including any anchor springs.
No topology, stiffness, mass, force or integrator changes are made here.
"""

import math
import numpy as np
from scipy.sparse import csr_matrix


def round_down(value, digits=2):
    """Round a positive timestep downward, never above the stability estimate."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timestep must be finite and positive")
    unit = 10.0 ** (math.floor(math.log10(value)) - digits + 1)
    return min(value, math.floor(value / unit) * unit)


def mass_scaled(stiffness, mass):
    """Symmetric scaling in bounded row chunks; caller arrays remain unchanged."""
    a = csr_matrix(stiffness, dtype=np.float64, copy=True)
    mass = np.asarray(mass, dtype=np.float64)
    if a.shape[0] != a.shape[1] or mass.shape != (a.shape[0],) or not len(mass):
        raise ValueError(
            "expected a nonempty square tangent and matching diagonal mass"
        )
    if not np.all(np.isfinite(mass)) or np.any(mass <= 0):
        raise ValueError("mass must be finite and positive")
    a.sum_duplicates()
    scale = 1.0 / np.sqrt(mass)
    for row in range(0, len(mass), 8192):
        end = min(row + 8192, len(mass))
        lo, hi = a.indptr[row], a.indptr[end]
        a.data[lo:hi] *= scale[a.indices[lo:hi]]
        a.data[lo:hi] *= np.repeat(scale[row:end], np.diff(a.indptr[row : end + 1]))
        if not np.all(np.isfinite(a.data[lo:hi])):
            raise ValueError("mass-scaled tangent must be finite")
    return a


def frequency_bound(a, iterations=8, progress=None):
    """Return an upper bound on squared angular frequency in fixed work.

    Input is already mass-scaled. abs() owns a copy; signed input is retained.
    A small row-length-dependent floating point margin protects sparse sums.
    """
    if not isinstance(iterations, int) or not 0 <= iterations <= 32:
        raise ValueError("iterations must be an integer in [0, 32]")
    b = abs(a)
    v = np.ones(a.shape[0])
    upper = float("inf")
    margin = 1 + max(1e-12, 8 * np.finfo(float).eps * int(np.diff(b.indptr).max()))
    for step in range(iterations + 1):
        y = b @ v
        candidate = float(np.max(y / v))
        if not math.isfinite(candidate):
            raise ValueError("nonfinite frequency bound")
        upper = min(upper, candidate * margin)
        if progress:
            progress(step + 1, iterations + 1, upper)
        if candidate == 0:
            break
        # Positive weights keep disconnected/zero rows valid and avoid division by zero.
        v = np.maximum(y / float(np.max(y)), 1e-12)
    return upper


def estimate_timestep(
    stiffness, mass, *, dt_cap=0.005, tail_omega_max=0.0, iterations=8, progress=None
):
    if not math.isfinite(dt_cap) or dt_cap <= 0:
        raise ValueError("dt_cap must be finite and positive")
    if not math.isfinite(tail_omega_max) or tail_omega_max < 0:
        raise ValueError("tail frequency must be finite and nonnegative")
    a = mass_scaled(stiffness, mass)
    upper = frequency_bound(a, iterations, progress)
    omega = max(math.sqrt(upper), tail_omega_max)
    raw = min(dt_cap, 0.8 / omega) if omega else dt_cap
    return {
        "dt_ns": round_down(raw),
        "unrounded_dt_ns": raw,
        "core_lambda_upper": upper,
        "iterations_limit": iterations + 1,
        "method": "positive-weight-row-bound",
    }

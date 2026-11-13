"""Box-frame statistics and tentative scalar restraint updates (Å, kcal/mol)."""

import numpy as np
from scipy.spatial.transform import Rotation

KB = 0.00198720425864083


def box_coordinates(x, box):
    lo, hi = np.asarray(box["min_corner"]), np.asarray(box["max_corner"])
    rotation = np.asarray(box["rotation"], dtype=float)
    if (
        lo.shape != (3,)
        or hi.shape != (3,)
        or rotation.shape != (4,)
        or not np.isfinite(np.r_[lo, hi, rotation]).all()
        or np.any(hi <= lo)
        or not np.isclose(np.linalg.norm(rotation), 1)
    ):
        raise ValueError("Invalid oriented box")
    return (np.asarray(x) - 10 * (lo + hi) / 2) @ Rotation.from_quat(
        rotation
    ).as_matrix()


def register(x, reference, anchors):
    """Proper rigid fit only: no scale/shear, and no fitting of the crossover core."""
    x, reference = np.asarray(x, float), np.asarray(reference, float)
    if x.shape != reference.shape or not np.isfinite(x).all():
        raise ValueError("Invalid coordinate arrays")
    a, b = x[anchors], reference[anchors]
    if (
        len(a) < 3
        or min(
            np.linalg.matrix_rank(a - a.mean(0)), np.linalg.matrix_rank(b - b.mean(0))
        )
        < 2
    ):
        raise ValueError("Alignment anchors are degenerate")
    left, _, right = np.linalg.svd((a - a.mean(0)).T @ (b - b.mean(0)))
    correction = np.diag([1, 1, np.linalg.det(left @ right)])
    aligned = (x - a.mean(0)) @ left @ correction @ right + b.mean(0)
    rmsd = np.sqrt(np.mean(np.sum((aligned[anchors] - b) ** 2, axis=1)))
    return aligned, float(rmsd)


def moments(samples):
    x = np.asarray(samples, float)
    if x.ndim != 3 or x.shape[-1] != 3 or len(x) < 4 or not np.isfinite(x).all():
        raise ValueError("Need at least four finite coordinate samples")
    mean = x.mean(axis=0)
    delta = x - mean
    covariance = np.einsum("tni,tnj->nij", delta, delta) / (len(x) - 1)
    split = len(x) // 2
    drift = np.linalg.norm(x[:split].mean(0) - x[split:].mean(0), axis=1)
    return mean, covariance, drift


def scalar_update(
    target_cov, trial_cov, current_k, temperature, gain=0.25, bounds=(0.0, 0.5)
):
    """Tentative relative update, NOT inverse covariance added as a new potential.

    Isotropic Gaussian approximation: U=k*r² => k_total=3*kBT/(2*RMSF²).
    Existing forces remain in the trial; use the difference in total stiffness.
    Coupling/non-Gaussian effects require iterative simulation validation.
    """
    target = np.trace(target_cov, axis1=-2, axis2=-1)
    trial = np.trace(trial_cov, axis1=-2, axis2=-1)
    current = np.broadcast_to(np.asarray(current_k, float), target.shape)
    if (
        target.shape != trial.shape
        or np.any(target <= 1e-8)
        or np.any(trial <= 1e-8)
        or not np.isfinite(
            np.r_[target, trial, current, temperature, gain, bounds]
        ).all()
        or temperature <= 0
        or not 0 < gain <= 1
        or bounds[0] < 0
        or bounds[1] <= bounds[0]
        or np.any(current < 0)
    ):
        raise ValueError("Invalid or zero-variance calibration inputs")
    raw = current + gain * 1.5 * KB * temperature * (1 / target - 1 / trial)
    return np.clip(raw, *bounds), raw

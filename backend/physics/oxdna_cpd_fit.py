"""Explicit atom-to-particle mapping and conditional CPD weld fitting.

This estimates an effective interaction in the sampled motif, not an isolated
chemical potential or a melting parameterization. Coordinates use oxDNA units.
"""

import numpy as np
from scipy.optimize import lsq_linear
from scipy.spatial.transform import Rotation

SITES = np.array(
    [[0.0, 0.0, 0.0], [0.35, 0.0, 0.0], [0.0, 0.35, 0.0], [0.0, 0.0, 0.35]]
)
ATOM_NAMES = ("N1", "C2", "N3", "C4", "C5", "C6", "C1'")
ANGSTROM_PER_UNIT = 8.518


def particle_frame(atoms):
    """Map a thymine ring and sugar attachment (Angstrom) to a rigid frame.

    a1 points from C1' toward the six-membered ring centroid. a3 uses the
    negative ordered N1-C2-C6 normal, orthogonalized against a1. The base
    centroid is the oxDNA BASE site (CM + 0.4 a1). No atoms are modified.
    """
    atoms = np.asarray(atoms, float)
    if atoms.shape != (7, 3) or not np.isfinite(atoms).all():
        raise ValueError("Expected seven finite thymine landmarks")
    centre = atoms[:6].mean(axis=0)
    a1 = centre - atoms[6]
    a1 /= np.linalg.norm(a1)
    a3 = -np.cross(atoms[1] - atoms[0], atoms[5] - atoms[0])
    a3 -= a3.dot(a1) * a1
    if np.linalg.norm(a3) < 1e-8:
        raise ValueError("Degenerate thymine frame")
    a3 /= np.linalg.norm(a3)
    rotation = np.column_stack((a1, np.cross(a3, a1), a3))
    return centre / ANGSTROM_PER_UNIT - 0.4 * a1, rotation


def relative_pose(first, second):
    x, a = first
    y, b = second
    return (y - x) @ a, a.T @ b


def distances(position, rotation):
    other = SITES @ rotation.T + position
    return np.linalg.norm(other[None, :, :] - SITES[:, None, :], axis=-1).reshape(-1)


def fit(positions, rotations, temperature=300.0):
    positions, rotations = np.asarray(positions), np.asarray(rotations)
    if len(positions) < 50 or rotations.shape != (len(positions), 3, 3):
        raise ValueError("Insufficient mapped samples")
    p = positions.mean(axis=0)
    r = Rotation.from_matrix(rotations).mean().as_matrix()
    residuals = np.column_stack(
        (positions - p, Rotation.from_matrix(rotations @ r.T).as_rotvec())
    )
    covariance = np.cov(residuals.T)
    eigenvalues = np.linalg.eigvalsh(covariance)
    if eigenvalues.min() <= 0:
        raise ValueError("Singular pose covariance")
    target = (temperature / 3000.0) * np.linalg.inv(covariance)
    eps = 1e-5
    columns = []
    for axis in range(6):
        delta = np.eye(6)[axis] * eps
        plus = distances(p + delta[:3], Rotation.from_rotvec(delta[3:]).as_matrix() @ r)
        minus = distances(
            p - delta[:3], Rotation.from_rotvec(-delta[3:]).as_matrix() @ r
        )
        columns.append((plus - minus) / (2 * eps))
    jacobian = np.array(columns).T
    basis = np.array([np.outer(j, j).ravel() for j in jacobian]).T
    # A small explicitly reported positive floor removes rank-deficient NNLS
    # solutions without pretending that poorly resolved modes were measured.
    floor = 1e-4 * np.trace(target) / np.trace(jacobian.T @ jacobian)
    solution = lsq_linear(
        basis, target.ravel(), bounds=(floor, np.inf), tol=1e-12, max_iter=1000
    )
    if not solution.success:
        raise ValueError("Bounded stiffness fit did not converge")
    stiffness = solution.x
    error = np.linalg.norm(basis @ stiffness - target.ravel())
    hessian = jacobian.T @ np.diag(stiffness) @ jacobian
    if np.linalg.eigvalsh(hessian).min() <= 0:
        raise ValueError("The spring fit leaves an unconstrained rigid-body mode")
    return {
        "sites": SITES.tolist(),
        "lengths": distances(p, r).tolist(),
        "stiffness": stiffness.tolist(),
        "mean_position": p.tolist(),
        "mean_rotation": r.tolist(),
        "covariance": covariance.tolist(),
        "hessian": hessian.tolist(),
        "relative_hessian_fit_error": float(error / np.linalg.norm(target)),
        "stiffness_floor": float(floor),
        "regularization": "positive spring floor at 1e-4 of isotropic trace scale",
        "sample_count": len(positions),
        "temperature_K": temperature,
    }

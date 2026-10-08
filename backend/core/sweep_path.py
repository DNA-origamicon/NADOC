"""Interpolating sweep paths and rotation-minimizing cross-section transport.

Coordinates are nm. Arc length is measured on a densely sampled cubic spline;
frames are transported on that same table, independent of the caller's sampling.
No curvature feasibility or loop/skip synthesis is performed here.
"""
from functools import lru_cache
import numpy as np
from scipy.interpolate import CubicSpline
from scipy.spatial.transform import Rotation, Slerp


def rotation_between(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    cross = np.cross(a, b)
    sine, cosine = np.linalg.norm(cross), float(np.clip(a @ b, -1, 1))
    if sine < 1e-10:
        if cosine > 0:
            return np.eye(3)
        axis = np.eye(3)[np.argmin(np.abs(a))]
        axis = np.cross(a, axis)
        return Rotation.from_rotvec(axis / np.linalg.norm(axis) * np.pi).as_matrix()
    return Rotation.from_rotvec(cross / sine * np.arctan2(sine, cosine)).as_matrix()


@lru_cache(maxsize=32)
def path_table(points, initial_tangent=None):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or not 2 <= len(p) <= 256 or not np.isfinite(p).all():
        raise ValueError('Sweep requires 2–256 finite XYZ points')
    distances = np.linalg.norm(np.diff(p, axis=0), axis=1)
    if np.any(distances < 1e-6):
        raise ValueError('Consecutive sweep points must be distinct')
    knots = np.r_[0, np.cumsum(distances)]
    if initial_tangent is None:
        boundary = 'natural'
    else:
        t = np.asarray(initial_tangent, dtype=float)
        boundary = ((1, t / np.linalg.norm(t)), (2, np.zeros(3)))
    spline = CubicSpline(knots, p, axis=0, bc_type=boundary)
    # Include each interpolation knot exactly. Fixed nm resolution bounds the
    # length error, with a per-span floor for short, sharply curved paths.
    counts = np.maximum(64, np.ceil(distances / .05).astype(int))
    if counts.sum() > 200_000:
        raise ValueError('Sweep path is too long')
    u = np.concatenate([np.linspace(a, b, n, endpoint=False)
                        for a, b, n in zip(knots[:-1], knots[1:], counts)] + [knots[-1:]])
    positions = spline(u)
    tangents = spline(u, 1)
    norms = np.linalg.norm(tangents, axis=1)
    if np.any(norms < 1e-8):
        raise ValueError('Sweep has a stationary cusp; adjust the neighboring points')
    tangents /= norms[:, None]
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(positions, axis=0), axis=1))]
    rotations = np.empty((len(u), 3, 3))
    rotations[0] = np.eye(3)
    for i in range(1, len(u)):
        rotations[i] = rotation_between(tangents[i-1], tangents[i]) @ rotations[i-1]
    return spline, u, arc, tangents, Slerp(arc, Rotation.from_matrix(rotations))


def sample_path(points, distances, initial_tangent=None):
    points = tuple(tuple(float(v) for v in p) for p in points)
    initial_tangent = None if initial_tangent is None else tuple(initial_tangent)
    spline, u, arc, tangents, rotations = path_table(points, initial_tangent)
    distances = np.asarray(distances, dtype=float)
    bounded = np.clip(distances, 0, arc[-1])
    parameters = np.interp(bounded, arc, u)
    positions = spline(parameters)
    tangent = spline(parameters, 1)
    tangent /= np.linalg.norm(tangent, axis=-1, keepdims=True)
    positions += (distances - bounded)[..., None] * tangent
    return positions, rotations(bounded).as_matrix(), tangent


def sweep_frames(op, local_bps, arm_min_bp, centroid, canonical_tangent):
    """Evaluate one persisted sweep in its owning cluster's rest frame."""
    p = op.params
    bps = np.asarray(local_bps, dtype=float) + arm_min_bp
    step = bps - op.plane_a_bp if p.direction == 1 else op.plane_b_bp - bps
    distances = (step + p.start_step) * p.path_length_nm / p.steps
    points = tuple(tuple(v for v in point) for point in p.points_nm)
    initial = tuple(p.initial_tangent) if p.initial_tangent is not None else None
    positions, transported, tangents = sample_path(points, distances, initial)
    first_tangent = path_table(points, initial)[3][0]
    base = np.asarray(p.initial_rotation).reshape(3, 3)
    align = rotation_between(base @ canonical_tangent * p.direction, first_tangent)
    matrices = transported @ align @ base
    return positions + np.asarray(p.origin_nm), matrices, tangents * p.direction

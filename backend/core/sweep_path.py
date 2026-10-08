"""Interpolating sweep paths and rotation-minimizing cross-section transport.

Coordinates are nm. Arc length is measured on a densely sampled cubic spline;
frames are transported on that same table, independent of the caller's sampling.
No curvature feasibility or loop/skip synthesis is performed here.
"""
from functools import lru_cache
import numpy as np
from scipy.interpolate import CubicSpline, CubicHermiteSpline
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
def path_table(points, initial_tangent=None, point_frames=None):
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
    if point_frames and any(frame is not None for frame in point_frames):
        derivatives = spline(knots, 1)
        for i, frame in enumerate(point_frames):
            if frame is not None:
                direction = np.asarray(frame).reshape(3, 3)[:, 2]
                if i == 0 and initial_tangent is not None and not np.allclose(direction, t / np.linalg.norm(t), atol=1e-6):
                    raise ValueError('The attached origin direction must match its source end')
                derivatives[i] = direction * max(np.linalg.norm(derivatives[i]), 1.)
        spline = CubicHermiteSpline(knots, p, derivatives, axis=0)
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


def sample_path(points, distances, initial_tangent=None, point_frames=None):
    points = tuple(tuple(float(v) for v in p) for p in points)
    initial_tangent = None if initial_tangent is None else tuple(initial_tangent)
    spline, u, arc, tangents, rotations = path_table(points, initial_tangent, point_frames)
    distances = np.asarray(distances, dtype=float)
    bounded = np.clip(distances, 0, arc[-1])
    parameters = np.interp(bounded, arc, u)
    positions = spline(parameters)
    tangent = spline(parameters, 1)
    tangent /= np.linalg.norm(tangent, axis=-1, keepdims=True)
    positions += (distances - bounded)[..., None] * tangent
    matrices = rotations(bounded).as_matrix()
    if point_frames and any(f is not None for f in point_frames):
        flat = matrices.reshape(-1, 3, 3)
        old = flat @ tangents[0]
        target = tangent.reshape(-1, 3)
        cross = np.cross(old, target)
        sine = np.linalg.norm(cross, axis=1)
        cosine = np.clip(np.einsum('ij,ij->i', old, target), -1, 1)
        vectors = cross * (np.arctan2(sine, cosine) / np.maximum(sine, 1e-15))[:, None]
        flat[:] = Rotation.from_rotvec(vectors).as_matrix() @ flat
        for i in np.flatnonzero((sine < 1e-10) & (cosine < 0)):
            flat[i] = rotation_between(old[i], target[i]) @ flat[i]
    return positions, matrices, tangent


def frame_key(frames):
    return None if frames is None else tuple(None if f is None else tuple(f) for f in frames)


def canonical_basis(normal):
    normal = np.asarray(normal, dtype=float)
    right = np.array([0., 1., 0.]) if abs(normal[0]) > .9 else np.array([1., 0., 0.])
    return np.column_stack([right, np.cross(normal, right), normal])


def oriented_sample(points, distances, initial, base, normal, point_frames=None):
    """Return canonical-to-world frames, honoring full authored frames at knots."""
    points = tuple(tuple(v for v in p) for p in points)
    initial = None if initial is None else tuple(initial)
    point_frames = frame_key(point_frames)
    table = path_table(points, initial, point_frames)
    positions, transported, tangent = sample_path(points, distances, initial, point_frames)
    align = rotation_between(base @ normal, table[3][0])
    matrices = transported @ align @ base
    if point_frames and any(f is not None for f in point_frames):
        knots = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        arc_knots = np.interp(knots, table[1], table[2])
        indices = [i for i, f in enumerate(point_frames) if f is not None]
        _, knot_transport, knot_tangent = sample_path(points, arc_knots[indices], initial, point_frames)
        right = canonical_basis(normal)[:, 0]
        reference = (knot_transport @ align @ base) @ right
        desired = np.array([np.asarray(point_frames[i]).reshape(3, 3)[:, 0] for i in indices])
        angles = np.unwrap(np.arctan2(np.einsum('ij,ij->i', knot_tangent, np.cross(reference, desired)),
                                     np.einsum('ij,ij->i', reference, desired)))
        roll_knots = arc_knots[indices]
        if indices[0] != 0:
            roll_knots = np.r_[0, roll_knots]
            angles = np.r_[0, angles]
        # Constant outside authored controls; linear roll avoids spline overshoot.
        roll = np.interp(np.clip(distances, 0, table[2][-1]), roll_knots, angles)
        turns = Rotation.from_rotvec((tangent * np.asarray(roll)[..., None]).reshape(-1, 3)).as_matrix()
        matrices = (turns @ matrices.reshape(-1, 3, 3)).reshape(matrices.shape)
    return positions, matrices, tangent


def sweep_frames(op, local_bps, arm_min_bp, centroid, canonical_tangent):
    """Evaluate one persisted sweep in its owning cluster's rest frame."""
    p = op.params
    bps = np.asarray(local_bps, dtype=float) + arm_min_bp
    step = bps - op.plane_a_bp if p.direction == 1 else op.plane_b_bp - bps
    distances = (step + p.start_step) * p.path_length_nm / p.steps
    positions, matrices, tangents = oriented_sample(p.points_nm, distances, p.initial_tangent,
        np.asarray(p.initial_rotation).reshape(3, 3), np.asarray(canonical_tangent) * p.direction, p.point_frames)
    return positions + np.asarray(p.origin_nm), matrices, tangents * p.direction

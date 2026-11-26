"""Read-only miter planning for Corner's cylinder guide.

This is not a molecular builder. Continuous axis intersections are not nucleotide
endpoints, and the distance between axes is not a backbone bond length. Routing
must quantize and phase-check the ends and author explicit unpaired junction
domains before a Full preview can be advertised or a Corner can be committed.

The caller supplies *current*, posed axis samples with explicit bp stations and
the current material frame (including twist). No global lattice spacing or
production molecular placement is changed here.
"""

from dataclasses import dataclass
import math

import numpy as np


def _vector(value, label):
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{label} must be a finite three-component vector.")
    return result


def _unit(value, label):
    value = _vector(value, label)
    norm = np.linalg.norm(value)
    if norm < 1e-10:
        raise ValueError(f"{label} must be nonzero.")
    return value / norm


@dataclass(frozen=True)
class CornerParameters:
    position_bp: int
    angle_deg: float
    direction_deg: float

    def __post_init__(self):
        if type(self.position_bp) is not int or abs(self.position_bp) > 2**53 - 1:
            raise ValueError("Plane position must be a safe integer bp.")
        if not math.isfinite(self.angle_deg) or not 0 <= self.angle_deg < 180:
            raise ValueError("Corner angle must be at least 0° and less than 180°.")
        if not math.isfinite(self.direction_deg):
            raise ValueError("Corner direction must be finite.")
        object.__setattr__(self, "direction_deg", self.direction_deg % 360)


@dataclass(frozen=True)
class AxisPath:
    """Explicit global bp stations, in increasing order, in current world space."""

    helix_id: str
    stations_bp: tuple[float, ...]
    points_nm: tuple[tuple[float, float, float], ...]

    def arrays(self):
        bps = np.asarray(self.stations_bp, dtype=float)
        points = np.asarray(self.points_nm, dtype=float)
        if (not self.helix_id or bps.ndim != 1 or len(bps) < 2
                or points.shape != (len(bps), 3)
                or not np.isfinite(bps).all() or not np.isfinite(points).all()
                or np.any(np.diff(bps) <= 0)
                or np.any(np.linalg.norm(np.diff(points, axis=0), axis=1) < 1e-10)):
            raise ValueError("Corner needs finite, nondegenerate, ordered axis samples.")
        return bps, points

    def point(self, station):
        bps, points = self.arrays()
        if not bps[0] <= station <= bps[-1]:
            raise ValueError("Corner plane lies outside a selected helix path.")
        return np.array([np.interp(station, bps, points[:, i]) for i in range(3)])

    def clipped(self, start, end):
        """Keep occupied material, with exact interpolated boundary stations."""
        bps, points = self.arrays()
        if not bps[0] <= start < end <= bps[-1]:
            raise ValueError('Corner occupancy lies outside its native axis path.')
        inside = (bps > start) & (bps < end)
        return AxisPath(self.helix_id, tuple([start, *bps[inside], end]),
                        _tuples(np.vstack((self.point(start), points[inside], self.point(end)))))


@dataclass(frozen=True)
class MiterCut:
    helix_id: str
    incoming_bp: float
    outgoing_bp: float
    incoming_nm: tuple[float, float, float]
    outgoing_nm: tuple[float, float, float]
    incoming_path_nm: tuple[tuple[float, float, float], ...]
    outgoing_path_nm: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class CornerGuide:
    center_nm: tuple[float, float, float]
    plane_normal: tuple[float, float, float]
    rotation: tuple[tuple[float, float, float], ...]
    cuts: tuple[MiterCut, ...]


def _tuples(points):
    return tuple(tuple(float(v) for v in point) for point in points)


def _intersection(bps, points, center, normal):
    distances = (points - center) @ normal
    roots = []
    for i in range(len(bps) - 1):
        a, b = distances[i:i + 2]
        if abs(a) < 1e-9 and abs(b) < 1e-9:
            raise ValueError("A helix path lies in the corner plane.")
        if abs(a) < 1e-9:
            roots.append((float(bps[i]), points[i]))
        elif a * b < 0:
            t = a / (a - b)
            roots.append((float(bps[i] + t * (bps[i + 1] - bps[i])),
                          points[i] + t * (points[i + 1] - points[i])))
    if abs(distances[-1]) < 1e-9:
        roots.append((float(bps[-1]), points[-1]))
    if len(roots) != 1:
        raise ValueError("Each helix must cross the corner plane exactly once; "
                         "move the plane or reduce the angle.")
    station, point = roots[0]
    if not bps[0] < station < bps[-1]:
        raise ValueError("Corner needs helix material on both sides of its miter.")
    # The retained prefix must lie on the incoming side and the suffix on the
    # outgoing side. A reversed traversal would swap fixed/mobile arms.
    if distances[0] >= 0 or distances[-1] <= 0:
        raise ValueError("Helix path traversal disagrees with the corner frame.")
    return station, point


def plan_corner_guide(paths, parameters, *, axis_dir, frame_right, frame_up):
    """Intersect both wedge faces, then rigidly pose the outgoing path suffix.

    The bisector normal is (incoming axis + outgoing axis), normalized. For a
    straight bundle this gives incoming z=-x*tan(angle/2), outgoing
    z=+x*tan(angle/2). Rotating the outgoing cut about the common center makes
    both cuts coincide. Curved source paths are intersected as supplied, never
    straightened or silently clipped. Their cut endpoints need not coincide;
    that residual remains visible for the subsequent junction calculation.
    """
    paths = tuple(paths)
    if not paths or len({p.helix_id for p in paths}) != len(paths):
        raise ValueError("Corner requires a nonempty set of unique helix paths.")
    tangent = _unit(axis_dir, "Axis direction")
    right = _unit(frame_right, "Frame right")
    up = _unit(frame_up, "Frame up")
    frame = np.column_stack((right, up, tangent))
    if (not np.allclose(frame.T @ frame, np.eye(3), atol=1e-6)
            or not np.isclose(np.linalg.det(frame), 1, atol=1e-6)):
        raise ValueError("Corner requires a right-handed orthonormal material frame.")
    center = np.mean([p.point(parameters.position_bp) for p in paths], axis=0)
    direction = math.radians(parameters.direction_deg)
    toward = math.cos(direction) * right + math.sin(direction) * up
    hinge = np.cross(tangent, toward)
    x, y, z = hinge
    skew = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
    theta = math.radians(parameters.angle_deg)
    rotation = np.eye(3) + math.sin(theta) * skew + (1 - math.cos(theta)) * skew @ skew
    normal = _unit(tangent + rotation @ tangent, "Miter plane normal")
    cuts = []
    for path in paths:
        bps, points = path.arrays()
        moved = (points - center) @ rotation.T + center
        incoming_bp, incoming = _intersection(bps, points, center, normal)
        outgoing_bp, outgoing = _intersection(bps, moved, center, normal)
        prefix = np.vstack((points[bps < incoming_bp], incoming))
        suffix = np.vstack((outgoing, moved[bps > outgoing_bp]))
        cuts.append(MiterCut(path.helix_id, incoming_bp, outgoing_bp,
                             tuple(incoming), tuple(outgoing), _tuples(prefix), _tuples(suffix)))
    return CornerGuide(tuple(center), tuple(normal), _tuples(rotation), tuple(cuts))

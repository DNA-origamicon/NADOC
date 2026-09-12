"""Rigid, engine-independent surface geometry in nm.

Normals point toward the allowed half-space: signed distance >= 0. Geometry
contains no force constants or material assumptions. Apply the SAME transform
to DNA, PEG beads, graft sites and the surface; do not recenter each separately.
"""
from copy import deepcopy
from dataclasses import dataclass

import numpy as np


def _vector(value, name):
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite 3-vector")
    return result


def _unit(value, name):
    result = _vector(value, name)
    length = np.linalg.norm(result)
    if not np.isfinite(length) or length < 1e-12:
        raise ValueError(f"{name} must be nonzero")
    return result / length


@dataclass(frozen=True)
class RigidTransform:
    """Active transform p' = R p + t; translations are nm, rotations proper."""

    rotation: tuple = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    translation_nm: tuple = (0., 0., 0.)

    def __post_init__(self):
        r = np.asarray(self.rotation, dtype=float)
        if (r.shape != (3, 3) or not np.isfinite(r).all()
                or not np.allclose(r.T @ r, np.eye(3), atol=1e-10, rtol=0)
                or not np.isclose(np.linalg.det(r), 1, atol=1e-10, rtol=0)):
            raise ValueError("rotation must be a proper orthonormal 3x3 matrix")
        object.__setattr__(self, "rotation", tuple(map(tuple, r)))
        object.__setattr__(self, "translation_nm", tuple(_vector(self.translation_nm, "translation_nm")))

    def points(self, points_nm):
        points = np.asarray(points_nm, dtype=float)
        if points.shape == (0,):
            points = points.reshape(0, 3)
        if points.ndim < 1 or points.shape[-1] != 3 or not np.isfinite(points).all():
            raise ValueError("points must be finite with final dimension 3")
        return points @ np.asarray(self.rotation).T + self.translation_nm

    def direction(self, direction):
        return np.asarray(self.rotation) @ _vector(direction, "direction")

    def inverse(self):
        r = np.asarray(self.rotation).T
        return RigidTransform(r, -r @ np.asarray(self.translation_nm))

    def then(self, following):
        """Compose in application order: self, then following."""
        return RigidTransform(
            np.asarray(following.rotation) @ np.asarray(self.rotation),
            following.points(self.translation_nm),
        )


@dataclass(frozen=True)
class SurfaceFrame:
    """Oriented plane and registered tangent axis for graphene/PEG patches."""

    point_nm: tuple
    normal: tuple
    tangent_u: tuple | None = None

    def __post_init__(self):
        n = _unit(self.normal, "normal")
        if self.tangent_u is None:
            trial = np.eye(3)[int(np.argmin(np.abs(n)))]
            u = _unit(np.cross(n, trial), "tangent_u")
        else:
            u = _unit(self.tangent_u, "tangent_u")
            if abs(float(u @ n)) > 1e-10:
                raise ValueError("tangent_u must be perpendicular to normal")
        object.__setattr__(self, "point_nm", tuple(_vector(self.point_nm, "point_nm")))
        object.__setattr__(self, "normal", tuple(n))
        object.__setattr__(self, "tangent_u", tuple(u))

    @property
    def tangent_v(self):
        return np.cross(self.normal, self.tangent_u)

    def signed_distance(self, points_nm):
        points = RigidTransform().points(points_nm)
        return (points - self.point_nm) @ np.asarray(self.normal)

    def project(self, points_nm):
        points = np.asarray(points_nm, dtype=float)
        return points - np.asarray(self.signed_distance(points))[..., None] * self.normal

    def transformed(self, transform):
        return SurfaceFrame(transform.points(self.point_nm), transform.direction(self.normal),
                            transform.direction(self.tangent_u))

    def oxdna_plane(self, nm_to_oxdna):
        """Return dir·r + position = 0 in oxDNA length units, no force policy."""
        if not np.isfinite(nm_to_oxdna) or nm_to_oxdna <= 0:
            raise ValueError("nm_to_oxdna must be finite and positive")
        return {"dir": list(self.normal),
                "position": -float(np.dot(self.normal, self.point_nm)) * nm_to_oxdna}

    def namd_plane(self):
        """Geometry in Å; this does not configure a NAMD force or atomistic slab."""
        return {"normal": list(self.normal),
                "point_angstrom": (np.asarray(self.point_nm) * 10).tolist()}


def _is_cartesian(normal, axis):
    expected = np.zeros(3)
    expected[axis] = np.sign(normal[axis])
    return np.allclose(normal, expected, atol=1e-10, rtol=0)


def surface_frame(spec):
    """Read explicit planes or legacy Cartesian dir/position_nm descriptors.

    Oblique planes require plane_point_nm: a dominant-axis coordinate alone is
    ambiguous. An explicit tangent_u preserves an existing patch orientation.
    """
    normal = _unit(spec["dir"], "dir")
    point = spec.get("plane_point_nm")
    if point is None:
        axis = int(np.argmax(np.abs(normal)))
        if not _is_cartesian(normal, axis):
            raise ValueError("oblique surfaces require plane_point_nm")
        point = np.zeros(3)
        point[axis] = spec["position_nm"]
    return SurfaceFrame(point, normal, spec.get("tangent_u"))


def transform_surface(spec, transform):
    """Copy a descriptor, transforming only its declared geometric fields.

    Supports a registered pore center, world-space graft sites and PEG bead
    coordinates. Metadata (material, stiffness, local patch dimensions, particle
    identities) is copied unchanged. Unrecognized coordinate fields are NOT moved.
    """
    frame = surface_frame(spec).transformed(transform)
    result = deepcopy(spec)
    result.update(dir=list(frame.normal), plane_point_nm=list(frame.point_nm),
                  tangent_u=list(frame.tangent_u))
    axis = int(np.argmax(np.abs(frame.normal)))
    if _is_cartesian(frame.normal, axis):
        result["position_nm"] = float(frame.point_nm[axis])
    else:
        result.pop("position_nm", None)
    for key in ("pore_center_nm", "graft_sites_nm", "peg_positions_nm",
                "periodic_cell_origin_nm", "_first_site_nm"):
        if key in spec:
            result[key] = transform.points(spec[key]).tolist()
    if "periodic_cell_vectors_nm" in spec:
        vectors = RigidTransform().points(spec["periodic_cell_vectors_nm"])
        result["periodic_cell_vectors_nm"] = (
            vectors @ np.asarray(transform.rotation).T
        ).tolist()
    # These writer diagnostics are in engine units and cannot be carried through
    # a frame change without their unit conversion/particle extent. Re-resolve.
    result.pop("position", None)
    result.pop("min_proj", None)
    return result


def deposition_surface_descriptor(run_config):
    """Copy a resolved deposited surface for the NAMD handoff, retaining features."""
    config = run_config or {}
    if config.get('kind') != 'surface_deposition':
        return None
    spec = config.get('surface') or {}
    if spec.get('plane_point_nm') is None and spec.get('position_nm') is None:
        return None
    result = transform_surface(spec, RigidTransform())
    result.setdefault('stiff', 0.)
    result['source'] = 'oxdna_surface_deposition'
    return result

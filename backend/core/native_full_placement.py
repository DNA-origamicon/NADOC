"""The only native Full bead/base placement, in each residue's transported frame.

Helical sites are geometric frames, not drawable nucleotide positions. This
boundary discards their provisional construction points and projects the sole
O5′ / ring-centroid landmark definition. It never infers a frame from beads or
from a helix endpoint chord, and never retains provisional points on failure.
"""

from __future__ import annotations

import math

import numpy as np

from backend.core.measured_positioning import FULL_REP


SOURCE = "native-full-o5-v1"


class NativePlacementError(ValueError):
    """DNA placement cannot be represented faithfully; do not render a fallback."""

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


def require_native_full_option(value: bool | None) -> None:
    """Reject direct calls requesting the deleted native placement mode."""
    if value is not None and value is not True:
        raise NativePlacementError(
            "Legacy bead/slab placement has been removed. Native Full has one "
            "O5′ placement; remove the measured_positioning=False request."
        )


def _numeric_array(value, field, context=None):
    try:
        return np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as error:
        raise NativePlacementError(f"Native Full has nonnumeric {field}.",
            details={"identity": context, "field": field, "actual": value}) from error


def positions_in_native_frame(
    origin: np.ndarray, x: np.ndarray, z: np.ndarray, reverse: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project the only landmark definition into already validated local frames.

    Base normals use a hypothetical partner in the SAME residue frame. A real
    partner may have moved independently; its pose must never change this
    residue's internal sugar/base geometry.
    """
    origin, x, z = (_numeric_array(value, field) for value, field in
                    ((origin, "frame_origin"), (x, "frame_x"), (z, "frame_z")))
    if (any(value.shape[-1:] != (3,) or not np.all(np.isfinite(value)) for value in (origin, x, z))
            or np.any(np.abs(np.linalg.norm(x, axis=-1) - 1) > 1e-6)
            or np.any(np.abs(np.linalg.norm(z, axis=-1) - 1) > 1e-6)
            or np.any(np.abs(np.sum(x * z, axis=-1)) > 1e-6)):
        raise NativePlacementError("Native Full requires a finite orthonormal local frame.")
    y = np.cross(z, x)

    def at(site):
        angle = site.azimuth_rad()
        return (origin + site.radius_nm * (math.cos(angle) * x + math.sin(angle) * y)
                + site.axial_nm * z)

    bb_f, bb_r = at(FULL_REP.backbone_fwd), at(FULL_REP.backbone_rev)
    bs_f, bs_r = at(FULL_REP.base_fwd), at(FULL_REP.base_rev)
    cross = bs_r - bs_f
    norm = np.linalg.norm(cross, axis=-1, keepdims=True)
    if np.any(~np.isfinite(norm)) or np.any(norm < 1e-12):
        raise NativePlacementError("Native Full base landmark frame is degenerate.")
    normal = cross / norm
    mask = np.asarray(reverse)[..., None]
    return np.where(mask, bb_r, bb_f), np.where(mask, bs_r, bs_f), np.where(mask, -normal, normal)


def place_native_full(arrs: dict) -> dict:
    """Place every row from its own canonical helical site or raise an error.

    Input rows are paired FORWARD/REVERSE sites. Axis points, tangents and
    radial hats have already followed bend/twist and domain/cluster transforms.
    Azimuths retain construction-frame angles, allowing a reverse residue to
    recover its own forward-reference direction without borrowing its partner's
    spatial frame. Even split partners therefore use precisely the same chemical
    placement as an undeformed duplex.
    """
    context = f"helix {arrs.get('helix_id', '<unknown>')}"
    required = ("axis_points", "radial_hats", "axis_tangents", "azimuths", "directions", "bp_indices")
    missing = [key for key in required if key not in arrs]
    if missing:
        raise NativePlacementError(f"Native Full {context}: missing canonical site fields {missing}.")
    if arrs.get("placement_source") is not None:
        raise NativePlacementError(f"Native Full {context}: refusing to place an already projected array.")
    origin = _numeric_array(arrs["axis_points"], "axis_points", context)
    radial = _numeric_array(arrs["radial_hats"], "radial_hats", context)
    tangent = _numeric_array(arrs["axis_tangents"], "axis_tangents", context)
    azimuth = _numeric_array(arrs["azimuths"], "azimuths", context)
    direction = _numeric_array(arrs["directions"], "directions", context)
    bps = _numeric_array(arrs["bp_indices"], "bp_indices", context)
    if bps.ndim != 1:
        raise NativePlacementError(f"Native Full {context}: malformed nucleotide identities.")
    count = len(bps)
    if (count % 2 or direction.shape != (count,) or bps.shape != (count,)
            or azimuth.shape != (count,)
            or any(v.shape != (count, 3) for v in (origin, radial, tangent))):
        raise NativePlacementError(f"Native Full {context}: malformed paired canonical site arrays.")
    if (not np.array_equal(direction, np.tile([0, 1], count // 2))
            or not np.array_equal(bps[0::2], bps[1::2])):
        raise NativePlacementError(f"Native Full {context}: nonmatching FORWARD/REVERSE site identities.")
    if any(not np.all(np.isfinite(v)) for v in (origin, radial, tangent, azimuth, bps)):
        raise NativePlacementError(f"Native Full {context}: nonfinite canonical site coordinates.")
    if np.any(bps != np.floor(bps)):
        raise NativePlacementError(f"Native Full {context}: nucleotide identities must be integer base-pair indices.")
    radial_len = np.linalg.norm(radial, axis=1)
    tangent_len = np.linalg.norm(tangent, axis=1)
    if (np.any(np.abs(radial_len - 1) > 1e-6)
            or np.any(np.abs(tangent_len - 1) > 1e-6)
            or np.any(np.abs(np.sum(radial * tangent, axis=1)) > 1e-6)):
        raise NativePlacementError(f"Native Full {context}: canonical site frame is not orthonormal.")

    delta = np.zeros(count)
    delta[1::2] = azimuth[1::2] - azimuth[0::2]
    x = np.cos(delta)[:, None] * radial - np.sin(delta)[:, None] * np.cross(tangent, radial)
    bb, bs, normal = positions_in_native_frame(origin, x, tangent, direction == 1)
    out = dict(arrs)
    out.update(positions=bb, base_positions=bs, base_normals=normal, placement_source=SOURCE)
    return out

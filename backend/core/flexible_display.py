"""Display overrides for flexible ssDNA segments.

The NADOC full/beads representation draws marked flexible ssDNA as a bowed
bead/slab arc, not on the rigid helix. Heavy display representations should be
a visual preflight for the same geometry, so this module mirrors
``frontend/src/scene/flexible_arcs.js`` and exposes those arc frames to the
atomistic/surface builders.
"""

from __future__ import annotations

import math

import numpy as np

from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.geometry import NucleotidePosition
from backend.core.models import Design, Direction

SLAB_DISTANCE = 0.55
OBST_RADIUS = 12.0
Y_HAT = np.array([0.0, 1.0, 0.0])
X_HAT = np.array([1.0, 0.0, 0.0])


def _normalise(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _fallback_bow(d_hat: np.ndarray) -> np.ndarray:
    bow = np.cross(d_hat, Y_HAT)
    if float(np.dot(bow, bow)) < 1e-6:
        bow = np.cross(d_hat, X_HAT)
    return _normalise(bow)


def _closest_on_seg(p: np.ndarray, p0: np.ndarray, p1: np.ndarray) -> np.ndarray:
    ab = p1 - p0
    den = float(np.dot(ab, ab)) or 1.0
    t = max(0.0, min(1.0, float(np.dot(p - p0, ab)) / den))
    return p0 + t * ab


def _arc_points(
    a: np.ndarray, b: np.ndarray, contour_nm: float, n: int, bow_dir: np.ndarray
) -> list[np.ndarray]:
    """Port of flexible_arcs.js _arcPoints for display parity."""
    if n <= 0:
        return []
    d = b - a
    c = float(np.linalg.norm(d))
    if c < 1e-6 or c >= contour_nm:
        return [a + d * (i / (n + 1)) for i in range(1, n + 1)]

    ratio = c / contour_nm
    lo, hi = 1e-4, math.pi - 1e-4
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if math.sin(mid) / mid > ratio:
            lo = mid
        else:
            hi = mid
    theta = (lo + hi) / 2.0
    radius = contour_nm / (2.0 * theta)
    midpt = (a + b) * 0.5
    center = midpt + bow_dir * (-radius * math.cos(theta))
    ua = _normalise(a - center)
    ub = _normalise(b - center)
    axis = np.cross(ua, ub)
    if float(np.dot(axis, axis)) < 1e-9:
        axis = np.cross(_normalise(d), bow_dir)
    axis = _normalise(axis)
    ang = math.acos(max(-1.0, min(1.0, float(np.dot(ua, ub)))))

    pts: list[np.ndarray] = []
    for i in range(1, n + 1):
        t = ang * (i / (n + 1))
        v = (
            ua * math.cos(t)
            + np.cross(axis, ua) * math.sin(t)
            + axis * float(np.dot(axis, ua)) * (1.0 - math.cos(t))
        )
        pts.append(v * radius + center)
    return pts


def _geo_key(anchor, strands_by_id: dict):
    strand = strands_by_id.get(anchor.strand_id)
    if strand is None or anchor.domain_index >= len(strand.domains):
        return None
    domain = strand.domains[anchor.domain_index]
    return (domain.helix_id, anchor.bp_index, anchor.direction.value)


def _obstacle_segments(design: Design) -> list[tuple[np.ndarray, np.ndarray]]:
    segs: list[tuple[np.ndarray, np.ndarray]] = []
    for axis in deformed_helix_axes(design):
        start = axis.get("start")
        end = axis.get("end")
        if start is None or end is None:
            continue
        segs.append((np.asarray(start, dtype=float), np.asarray(end, dtype=float)))
    return segs


def _bow_dir(
    a: np.ndarray, b: np.ndarray, obstacles: list[tuple[np.ndarray, np.ndarray]]
) -> np.ndarray:
    d = b - a
    d_hat = _normalise(d)
    mid = (a + b) * 0.5
    rep = np.zeros(3, dtype=float)
    for p0, p1 in obstacles:
        cp = _closest_on_seg(mid, p0, p1)
        v = mid - cp
        dist = float(np.linalg.norm(v))
        if dist < 1e-3 or dist > OBST_RADIUS:
            continue
        rep += (v / dist) * (1.0 / (dist * dist))
    rep = rep - d_hat * float(np.dot(rep, d_hat))
    if float(np.dot(rep, rep)) > 1e-9:
        return _normalise(rep)
    return _fallback_bow(d_hat)


def flexible_segment_atomistic_frame_overrides(
    design: Design,
) -> dict[tuple[str, int, str], NucleotidePosition]:
    """Return NADOC-full-representation frames for flexible ssDNA display."""
    if not design.flexible_connections:
        return {}

    geometry = _geometry_for_design(design)
    pos_by_key = {
        (n["helix_id"], int(n["bp_index"]), n["direction"]): np.asarray(
            n["backbone_position"], dtype=float
        )
        for n in geometry
    }
    raw_by_key = {
        (n["helix_id"], int(n["bp_index"]), n["direction"]): n for n in geometry
    }
    strands_by_id = {s.id: s for s in design.strands}
    obstacles = _obstacle_segments(design)
    out: dict[tuple[str, int, str], NucleotidePosition] = {}

    for conn in design.flexible_connections:
        ka = _geo_key(conn.anchor_a, strands_by_id)
        kb = _geo_key(conn.anchor_b, strands_by_id)
        bead_keys = [_geo_key(k, strands_by_id) for k in conn.segment_bead_keys]
        if ka is None or kb is None or any(k is None for k in bead_keys):
            continue
        p_a = pos_by_key.get(ka)
        p_b = pos_by_key.get(kb)
        if p_a is None or p_b is None:
            continue

        bow = _bow_dir(p_a, p_b, obstacles)
        beads = _arc_points(p_a, p_b, conn.contour_length_nm, len(bead_keys), bow)
        pts = [p_a, *beads, p_b]
        plane_n = np.cross(_normalise(p_b - p_a), bow)
        if float(np.dot(plane_n, plane_n)) < 1e-9:
            plane_n = _fallback_bow(_normalise(p_b - p_a))
        plane_n = _normalise(plane_n)

        for i, key in enumerate(bead_keys):
            raw = raw_by_key.get(key)
            if raw is None:
                continue
            tan = _normalise(pts[i + 2] - pts[i])
            bn = _normalise(np.cross(plane_n, tan))
            if float(np.dot(bn, bow)) > 0.0:
                bn = -bn
            direction = Direction(key[2])
            stored_tan = tan if direction == Direction.FORWARD else -tan
            position = beads[i]
            out[key] = NucleotidePosition(
                helix_id=key[0],
                bp_index=key[1],
                direction=direction,
                position=position,
                base_position=position + SLAB_DISTANCE * bn,
                base_normal=bn,
                axis_tangent=stored_tan,
            )

    return out

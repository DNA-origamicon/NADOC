"""Solid lattice platforms supporting three or four fixed gold particles.

Fit the center plane, orient the helix axis in that plane, then cover the
projected positions with complete lattice rows and axial attachment margins.
Choose the most complete layers that an actually routed 7249/8064 scaffold
allows. Construction subsequently verifies each duplex's reach and gold-core
clearance; fitting the plane alone is not evidence that an attachment is viable.
"""

from copy import deepcopy
import math

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import LatticeType
from backend.core.two_np_generator import (
    RodCandidate,
    _routed,
    _section,
    gold_particles,
    plan_rods,
    scaffold_nt,
)


def platform_frame(centers, angle_deg=0):
    """Best-fit plane; local Y is its normal, X/Z span the solid platform."""
    _, singular, axes = np.linalg.svd(centers - centers.mean(0), full_matrices=True)
    if singular[1] < 1e-6:
        raise ValueError(
            "A platform needs at least three non-collinear particle centers."
        )
    y = axes[-1].copy()
    if y[np.argmax(np.abs(y))] < 0:
        y *= -1
    z = axes[0].copy()
    if z[np.argmax(np.abs(z))] < 0:
        z *= -1
    x = np.cross(y, z)
    angle = math.radians(angle_deg)
    z = math.cos(angle) * z + math.sin(angle) * x
    return np.column_stack((np.cross(y, z), y, z))


def plan_platforms(source, settings):
    particles, centers, distance = gold_particles(source, (3, 4))
    lattice = source.lattice_type
    frame = platform_frame(centers, settings.roll_deg)
    local = (centers - centers.mean(0)) @ frame
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    minimum_bp = (
        math.ceil((np.ptp(local[:, 2]) / BDNA_RISE_PER_BP + 2 * period) / period)
        * period
    )
    width = float(np.ptp(local[:, 0])) + 6.0
    # Complete rows and columns, with no trimmed edge helices. HC keeps its
    # staggered lattice outline; square footprints are complete rectangles.
    sections = []
    for rows in range(2, 9):
        for cols in range(4, 65, 2):
            if rows * cols > 128:
                break
            section = _section(
                [(r, c) for r in range(rows) for c in range(cols)],
                lattice,
                f"{rows} layers × {cols} columns",
            )
            if section["width_nm"] >= width:
                section["layers"] = rows
                sections.append(section)
                break
    sections.sort(key=lambda s: s["layers"], reverse=True)
    best = {}
    for size, name in ((7249, "M13mp18"), (8064, "p8064")):
        for section in sections:
            count = section["helix_count"]
            if count * minimum_bp > size:
                continue
            cells = tuple(tuple(p) for p in section["cells"])
            try:
                routed = _routed(lattice, cells, minimum_bp)
            except ValueError:
                continue
            used = scaffold_nt(routed)
            if used > size:
                continue
            length = minimum_bp
            if settings.extend_rod:
                for extra in range((size - used) // (count * period), 0, -1):
                    try:
                        extended = _routed(lattice, cells, minimum_bp + extra * period)
                    except ValueError:
                        continue
                    if scaffold_nt(extended) <= size:
                        routed, length, used = (
                            extended,
                            minimum_bp + extra * period,
                            scaffold_nt(extended),
                        )
                        break
            axial = [p.z for h in routed.helices for p in (h.axis_start, h.axis_end)]
            summary = {
                **section,
                "shape": "platform",
                "scaffold_name": name,
                "scaffold_size": size,
                "scaffold_used_nt": used,
                "unused_scaffold_nt": size - used,
                "nominal_length_bp": length,
                "length_bp": max(h.bp_start + h.length_bp for h in routed.helices)
                - min(h.bp_start for h in routed.helices),
                "length_nm": max(axial) - min(axial),
            }
            best[size] = RodCandidate(routed, summary)
            break
    if not best:
        raise ValueError(
            "Neither 7249 nor 8064 can route a complete solid platform covering these particle positions. The centers were not moved."
        )
    chosen = best.get(7249) or best[8064]
    if 8064 in best and best[8064].summary["layers"] > chosen.summary["layers"]:
        chosen = best[8064]
    reason = (
        "8064 enables a thicker complete platform."
        if chosen.summary["scaffold_size"] == 8064 and 7249 in best
        else "7249 is sufficient; 8064 does not add a complete layer."
        if chosen.summary["scaffold_size"] == 7249
        else "Only 8064 fits a supported routed platform."
    )
    return RodCandidate(
        chosen.design.model_copy(deep=True), deepcopy(chosen.summary)
    ), {
        "shape": "platform",
        "lattice_type": lattice.value,
        "particle_ids": [p.id for p in particles],
        "centers_nm": centers.tolist(),
        "center_distance_nm": distance,
        "plane_deviation_nm": float(np.max(np.abs(local[:, 1]))),
        "selected": deepcopy(chosen.summary),
        "alternatives": [
            deepcopy(best[n].summary)
            if n in best
            else {"scaffold_size": n, "feasible": False}
            for n in (7249, 8064)
        ],
        "axis": frame[:, 2].tolist(),
        "side_normal": frame[:, 1].tolist(),
        "reason": reason,
        "settings": settings.model_dump(),
        "qualification": "Geometric layout; stiffness and RMSF have not been simulated.",
    }


def plan_generated(source, settings):
    particles, _, _ = gold_particles(source)
    return (
        plan_rods(source, settings)
        if len(particles) == 2
        else plan_platforms(source, settings)
    )

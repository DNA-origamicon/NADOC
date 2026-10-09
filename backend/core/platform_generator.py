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


ALIGNMENT_TOLERANCE_DEG = 5.0


def _plane_frame(centers):
    """PCA supplies the plane normal, not the platform's perimeter direction."""
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
    return np.column_stack((np.cross(y, z), y, z))


def rotate_platform_frame(frame, angle_deg):
    x, y, z = frame.T
    angle = math.radians(angle_deg)
    z = math.cos(angle) * z + math.sin(angle) * x
    return np.column_stack((np.cross(y, z), y, z))


def _perimeter(centers, frame):
    """Convex hull in the fitted plane; exclude diagonals and interior particles."""
    points = ((centers - centers.mean(0)) @ frame)[:, [0, 2]]
    ordered = sorted(range(len(points)), key=lambda i: tuple(points[i]))
    scale = max(float(np.ptp(points, axis=0).max()), 1.0)

    def turn(i, j, k):
        a, b = points[j] - points[i], points[k] - points[j]
        return a[0] * b[1] - a[1] * b[0]

    def chain(indices):
        result = []
        for i in indices:
            while (
                len(result) >= 2 and turn(result[-2], result[-1], i) <= 1e-12 * scale**2
            ):
                result.pop()
            result.append(i)
        return result

    hull = chain(ordered)[:-1] + chain(ordered[::-1])[:-1]
    edges = [(i, hull[(k + 1) % len(hull)]) for k, i in enumerate(hull)]
    vectors = np.array([points[j] - points[i] for i, j in edges])
    return edges, vectors


def perimeter_alignment(centers, frame):
    edges, vectors = _perimeter(centers, frame)
    components = np.abs(vectors)
    errors = np.degrees(np.arctan2(components.min(1), components.max(1)))
    return {
        "target_edges": 1 if len(centers) == 3 else 2,
        "tolerance_deg": ALIGNMENT_TOLERANCE_DEG,
        "aligned_edges": int(np.sum(errors <= ALIGNMENT_TOLERANCE_DEG + 1e-8)),
        "edges": [
            {"particle_indices": [i, j], "error_deg": float(error)}
            for (i, j), error in zip(edges, errors)
        ],
    }


def _perimeter_frames(centers):
    plane = _plane_frame(centers)
    _, edges = _perimeter(centers, plane)
    lengths = np.linalg.norm(edges, axis=1)
    angles = np.arctan2(edges[:, 0], edges[:, 1])
    candidates = list(angles)
    if len(centers) == 4:
        # A rectangle's parallel AND perpendicular edges share a direction
        # modulo 90 degrees. Fit noisy edge pairs/all edges in that space.
        groups = [list(range(len(edges)))] + [
            [i, j] for i in range(len(edges)) for j in range(i)
        ]
        for group in groups:
            mean = np.sum(lengths[group] * np.exp(4j * angles[group]))
            if abs(mean) > 1e-10 * lengths.sum():
                candidates.append(float(np.angle(mean) / 4))
    ranked = []
    seen = set()
    for angle in candidates:
        key = round(float(angle % (math.pi / 2)), 10)
        if key in seen:
            continue
        seen.add(key)
        frame = rotate_platform_frame(plane, math.degrees(angle))
        local = (centers - centers.mean(0)) @ frame
        span = np.ptp(local[:, [0, 2]], axis=0)
        # Prefer the longer footprint direction along helices, but retain the
        # swapped orientation as a routing/budget fallback with equal alignment.
        if span[0] > span[1] + 1e-8:
            frame = rotate_platform_frame(frame, 90)
        if frame[np.argmax(np.abs(frame[:, 2])), 2] < 0:
            frame[:, [0, 2]] *= -1
        _, projected = _perimeter(centers, frame)
        components = np.abs(projected)
        errors = np.degrees(np.arctan2(components.min(1), components.max(1)))
        aligned = errors <= ALIGNMENT_TOLERANCE_DEG + 1e-8
        count = int(aligned.sum())
        coverage = len(set(np.argmax(components[aligned], axis=1)))
        target = 1 if len(centers) == 3 else 2
        area = float(np.prod(span))
        # Triangles keep one edge exact, then minimize footprint. Four-particle
        # layouts prioritize two edge directions and overall perimeter agreement.
        score = (
            max(0, target - count),
            -coverage,
            -count,
            area
            if len(centers) == 3
            else float(
                np.average(errors**2, weights=np.linalg.norm(projected, axis=1))
            ),
            area,
        )
        ranked.append((score, frame))
    ranked.sort(key=lambda item: item[0])
    return [
        frame for _, base in ranked for frame in (base, rotate_platform_frame(base, 90))
    ]


def platform_frame(centers, angle_deg=0):
    """Perimeter-aligned platform, with a user rotation inside the fitted plane."""
    return rotate_platform_frame(_perimeter_frames(centers)[0], angle_deg)


def _plan_platforms_in_frame(source, settings, base_frame):
    particles, centers, distance = gold_particles(source, (3, 4))
    lattice = source.lattice_type
    frame = rotate_platform_frame(base_frame, settings.roll_deg)
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
                "base_frame": base_frame.tolist(),
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
            "Neither 7249 nor 8064 can route a complete solid platform covering these particle positions. "
            "Try Curved rod under Design shape. The centers were not moved."
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
        "perimeter_alignment": perimeter_alignment(centers, frame),
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


def plan_platforms(source, settings):
    _, centers, _ = gold_particles(source, (3, 4))
    failure = None
    for base_frame in _perimeter_frames(centers):
        try:
            return _plan_platforms_in_frame(source, settings, base_frame)
        except ValueError as exc:
            failure = exc
    raise failure


def plan_generated(source, settings, *, use_sweeps=True):
    particles, _, _ = gold_particles(source)
    if settings.shape == "curved-rod":
        from backend.core.curved_rod_generator import plan_curved_rods

        if settings.mechanics != "legacy":
            from backend.core.generator_reinforcement import optimize_reinforcement

            candidate, report = plan_curved_rods(
                source,
                settings.model_copy(update={"extend_rod": False}),
                use_sweeps=True,
            )
            return optimize_reinforcement(source, settings, candidate, report)
        return plan_curved_rods(source, settings, use_sweeps=use_sweeps)
    if settings.mechanics != "legacy":
        raise ValueError("Mechanical sizing currently requires a curved rod.")
    if settings.shape == "platform" and len(particles) < 3:
        raise ValueError("A platform needs three or four nanoparticles.")
    return (
        plan_rods(source, settings)
        if len(particles) == 2
        else plan_platforms(source, settings)
    )

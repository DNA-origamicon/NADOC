"""Planar paths encoded with ordinary bends or an editable sweep."""

from copy import deepcopy
from itertools import permutations
import math

import numpy as np
from scipy.interpolate import CubicSpline

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import BendParams, DeformationOp, LatticeType
from backend.core.platform_generator import _plane_frame
from backend.core.two_np_generator import (
    RodCandidate,
    _routed,
    cross_sections,
    gold_particles,
    pair_frame,
    scaffold_nt,
    _section,
)


def path_options(source, settings, bend_extent_nm=3.25):
    if settings.roll_deg != 0:
        raise ValueError(
            "Curved paths follow the fitted particle plane; set rotation to 0 and adjust the visit order instead."
        )
    particles, centers, _ = gold_particles(source)
    if len(particles) < 3:
        raise ValueError(
            "A curved path needs three or four nanoparticles. Use the straight rod for two."
        )
    ids = [p.id for p in particles]
    if settings.particle_order is not None:
        if len(settings.particle_order) != len(ids) or set(
            settings.particle_order
        ) != set(ids):
            raise ValueError(
                "Path order must contain each gold nanoparticle exactly once."
            )
        orders = [tuple(ids.index(i) for i in settings.particle_order)]
    else:
        orders = [p for p in permutations(range(len(ids))) if p[0] < p[-1]]
    try:
        plane = _plane_frame(centers)
    except ValueError:
        delta = np.linalg.norm(centers[:, None] - centers[None, :], axis=-1)
        i, j = np.unravel_index(np.argmax(delta), delta.shape)
        plane = pair_frame(centers[[i, j]])
    origin = centers.mean(0)
    projected = (centers - origin) @ plane
    target_points = projected[:, [0, 2]].copy()
    radial = target_points / np.maximum(
        np.linalg.norm(target_points, axis=1)[:, None], 1e-12
    )
    displacement = np.zeros(len(particles))
    if settings.pathing != "colocalized":
        # Leave approximately half a duplex between the rod surface and gold.
        # The native attachment fit remains the final reach/clearance authority.
        displacement = (
            np.array([p.diameter_nm / 2 for p in particles])
            + bend_extent_nm
            + settings.duplex_bp * RISE / 2
        )
        if settings.pathing == "interior" and np.any(
            displacement >= np.linalg.norm(target_points, axis=1) - 1
        ):
            raise ValueError(
                "Insufficient interior space for this cross-section and attachments."
            )
        target_points += (
            radial
            * displacement[:, None]
            * (-1 if settings.pathing == "interior" else 1)
        )
    station_world = (
        origin + target_points[:, :1] * plane[:, 0] + target_points[:, 1:] * plane[:, 2]
    )
    side_vectors = np.tile(plane[:, 1], (len(particles), 1))
    if settings.pathing != "colocalized":
        side_vectors = radial[:, :1] * plane[:, 0] + radial[:, 1:] * plane[:, 2]
        side_vectors *= 1 if settings.pathing == "interior" else -1
    paths = []
    for order in orders:
        points = target_points[list(order)]
        chords = np.linalg.norm(np.diff(points, axis=0), axis=1)
        if min(chords) < 1e-5:
            continue
        knots = np.r_[0.0, np.cumsum(chords)]
        curve = CubicSpline(knots, points, axis=0)
        t = np.linspace(0, knots[-1], 1201)
        xy = curve(t)
        distance = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        tangent = curve(t, 1)
        speed = np.linalg.norm(tangent, axis=1)
        if min(speed) < 1e-5:
            continue
        angle = np.unwrap(np.arctan2(tangent[:, 0], tangent[:, 1]))
        derivative = curve(t, 2)
        curvature = (
            tangent[:, 1] * derivative[:, 0] - tangent[:, 0] * derivative[:, 1]
        ) / speed**3
        first = tangent[0] / speed[0]
        z = plane[:, 0] * first[0] + plane[:, 2] * first[1]
        normal = plane[:, 1]
        frame = np.column_stack((np.cross(normal, z), normal, z))
        station = np.interp(knots, t, distance)
        paths.append(
            dict(
                order=list(order),
                pathing=settings.pathing,
                station_points_world=station_world.tolist(),
                attachment_directions=side_vectors.tolist(),
                particle_ids=[ids[i] for i in order],
                length_nm=float(distance[-1]),
                max_curvature=float(np.max(np.abs(curvature))),
                sample_s=distance,
                sample_angle=angle - angle[0],
                station_s={i: float(s) for i, s in zip(order, station)},
                frame=frame.tolist(),
                origin=(
                    origin + plane @ np.array([points[0, 0], 0, points[0, 1]])
                ).tolist(),
            )
        )
    paths.sort(
        key=lambda p: (p["length_nm"] * (1 + 3 * p["max_curvature"]), p["order"])
    )
    if not paths:
        raise ValueError(
            "The projected particle positions cannot form a regular planar path. Try a different order or use a platform."
        )
    return paths


def bend_operations(path, start_bp, helix_ids, scale=1.0):
    # Seven-bp windows match the insertion/deletion cells. Integrating each
    # signed angle increment gives a smooth, continuous transported rod frame.
    end = int(math.ceil(path["length_nm"] / RISE / 7) * 7)
    ops = []
    for a in range(0, end, 7):
        b = min(a + 7, end)
        angles = np.interp(
            np.array([a, b]) * RISE, path["sample_s"], path["sample_angle"]
        )
        curvature = float(np.degrees(angles[1] - angles[0]) / (b - a)) * scale
        if abs(curvature) < 1e-7:
            continue
        ops.append(
            DeformationOp(
                type="bend",
                plane_a_bp=start_bp + a,
                plane_b_bp=start_bp + b,
                affected_helix_ids=list(helix_ids),
                params=BendParams(curvature_deg_per_bp=curvature, direction_deg=0),
            )
        )
    return ops


def encode_curvature(design, ops):
    """Use existing insertion/deletion rules; include them in scaffold budgets."""
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        sq_lattice_periodic_skips,
        relocate_marks_off_forbidden,
        _active_intervals_for_helices,
        _cells_from_active_intervals,
        _helix_cross_section_offset,
        validate_loop_skip_limits,
    )
    from backend.core.deformation import _bundle_centroid_and_tangent
    from backend.core.models import LoopSkip

    mods = (
        sq_lattice_periodic_skips(design)
        if design.lattice_type == LatticeType.SQUARE
        else {}
    )
    helices = list(design.helices)
    centroid, tangent = _bundle_centroid_and_tangent(helices)
    for helix in helices:
        offset = _helix_cross_section_offset(helix, centroid, tangent)[0]
        intervals = _active_intervals_for_helices(design, {helix.id})
        requested, emitted = 0.0, 0
        for op in ops:
            for a, b in _cells_from_active_intervals(
                intervals, op.plane_a_bp, op.plane_b_bp
            ):
                # The ordinary bend rule is Δbp = -r * Δangle / rise.
                # Carry fractional changes across windows: rounding each short
                # window independently would erase gentle curvature entirely.
                requested -= (
                    offset
                    * math.radians(op.params.curvature_deg_per_bp * (b - a))
                    / RISE
                )
                count = round(requested) - emitted
                validate_loop_skip_limits(
                    max(0, -count), max(0, count), label="curved rod"
                )
                emitted += count
                for j in range(abs(count)):
                    mods.setdefault(helix.id, []).append(
                        LoopSkip(
                            bp_index=a + j * (b - a) // abs(count),
                            delta=1 if count > 0 else -1,
                        )
                    )

    return apply_loop_skips(design, relocate_marks_off_forbidden(mods, design))


def physical_scaffold_nt(design):
    from backend.core.sequences import domain_bp_range

    marks = {
        (h.id, mark.bp_index): mark.delta
        for h in design.helices
        for mark in h.loop_skips
    }
    return sum(
        max(0, 1 + marks.get((d.helix_id, bp), 0))
        for s in design.scaffolds()
        if not s.is_reference
        for d in s.domains
        for bp in domain_bp_range(d)
    )


def check_path_geometry(design, rod_ids, radius):
    from backend.core.deformation import _precompute_arm_frames

    helices = [h for h in design.helices if h.id in rod_ids]
    start = min(h.bp_start for h in helices)
    end = max(h.bp_start + h.length_bp - 1 for h in helices)
    bp = np.arange(start, end + 1, 4)
    spines, _, _ = _precompute_arm_frames(design, helices, start, end - start)
    points = spines[bp - start]
    separation = abs(bp[:, None] - bp[None, :]) * RISE
    distance = np.linalg.norm(points[:, None] - points[None, :], axis=-1)
    if np.any((separation > 6 * radius) & (distance < 2 * radius + 1)):
        raise ValueError(
            "The curved rod intersects itself or its extended tails. Try another particle order or a platform."
        )


def plan_curved_rods(source, settings, *, use_sweeps=True):
    lattice = source.lattice_type
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    sections = deepcopy(list(cross_sections(lattice)))
    if lattice == LatticeType.SQUARE:
        # The bend is in local XZ; a tall rectangle can be stiffer without
        # increasing the inner/outer arc-length difference along X.
        sections += [
            _section(
                [(c, r) for r, c in s["cells"]],
                lattice,
                f"{max(c for _, c in s['cells']) + 1} × {max(r for r, _ in s['cells']) + 1}",
            )
            for s in list(sections)
            if s["width_nm"] != s["height_nm"]
        ]
    sections.sort(key=lambda s: s["section_score"], reverse=True)
    from backend.core.lattice import honeycomb_position, square_position

    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    for section in sections:
        xy = np.array([position(*cell) for cell in section["cells"]])
        centered = xy - xy.mean(0)
        section["radius_nm"] = float(np.linalg.norm(centered, axis=1).max() + 1)
        section["bend_extent_nm"] = float(np.abs(centered[:, 0]).max() + 1)
    best, paths_by_extent = {}, {}
    for size, name in ((7249, "M13mp18"), (8064, "p8064")):
        for section in sections:
            radius, extent = section["radius_nm"], section["bend_extent_nm"]
            key = extent if settings.pathing != "colocalized" else 0
            if key not in paths_by_extent:
                try:
                    paths_by_extent[key] = path_options(source, settings, extent)
                except ValueError:
                    if settings.pathing == "colocalized":
                        raise
                    paths_by_extent[key] = []
            for path in paths_by_extent[key]:
                minimum = int(
                    math.ceil((path["length_nm"] / RISE + 2 * period) / period) * period
                )
                if (
                    section["helix_count"] * minimum > size
                    or path["max_curvature"] * extent > 0.35
                ):
                    continue
                cells = tuple(tuple(c) for c in section["cells"])
                try:
                    routed = _routed(lattice, cells, minimum).model_copy(deep=True)
                    max_length = (
                        minimum
                        + max(
                            0,
                            (size - scaffold_nt(routed))
                            // (section["helix_count"] * period),
                        )
                        * period
                        if settings.extend_rod
                        else minimum
                    )
                    for length in range(max_length, minimum - 1, -period):
                        routed = _routed(lattice, cells, length).model_copy(deep=True)
                        start = int((length - path["length_nm"] / RISE) / 2 // 7 * 7)
                        ops = bend_operations(
                            path, start, [h.id for h in routed.helices]
                        )
                        sweep = None
                        if use_sweeps and len(ops) > len(path["particle_ids"]):
                            from backend.core.generated_sweep import (
                                sweep_request,
                                routed_sweep,
                            )

                            sweep = sweep_request(
                                lattice, list(cells), length, path, start, source=source
                            )
                            bent = routed_sweep(lattice, sweep)
                        else:
                            bent = encode_curvature(
                                routed.copy_with(deformations=ops), ops
                            )
                        used = physical_scaffold_nt(bent)
                        if max(used, scaffold_nt(routed)) > size:
                            continue
                        try:
                            check_path_geometry(
                                bent, {h.id for h in bent.helices}, radius
                            )
                        except ValueError:
                            continue
                        summary = {
                            **section,
                            "cells": list(sweep.cells) if sweep else section["cells"],
                            "shape": "curved-rod",
                            "scaffold_name": name,
                            "scaffold_size": size,
                            "scaffold_used_nt": used,
                            "unused_scaffold_nt": size - used,
                            "nominal_length_bp": length,
                            "length_bp": length,
                            "length_nm": length * RISE,
                            "path_start_bp": start,
                            "path_feature": "sweep" if sweep else "bends",
                            "bend_count": len(ops),
                            "sweep_request": sweep.model_dump(mode="json")
                            if sweep
                            else None,
                            "path": path,
                        }
                        best[size] = RodCandidate(routed, summary)
                        break
                except ValueError:
                    continue
                if size in best:
                    break
            if size in best:
                break
    if not best:
        raise ValueError(
            "No supported curved rod fits the path, bend limits, and 7249/8064 scaffold budgets. Try another order, wider particle spacing, or a platform."
        )
    chosen = best.get(7249) or best[8064]
    if (
        8064 in best
        and best[8064].summary["section_score"] > chosen.summary["section_score"] + 1e-8
    ):
        chosen = best[8064]

    def public(summary):
        return {k: v for k, v in summary.items() if k not in ("path", "sweep_request")}

    particles, centers, distance = gold_particles(source)
    return RodCandidate(chosen.design, deepcopy(chosen.summary)), {
        "shape": "curved-rod",
        "lattice_type": lattice.value,
        "centers_nm": centers.tolist(),
        "particle_ids": [p.id for p in particles],
        "center_distance_nm": distance,
        "path_particle_ids": chosen.summary["path"]["particle_ids"],
        "path_length_nm": chosen.summary["path"]["length_nm"],
        "pathing": settings.pathing,
        "selected": public(chosen.summary),
        "alternatives": [
            public(best[n].summary)
            if n in best
            else {"scaffold_size": n, "feasible": False}
            for n in (7249, 8064)
        ],
        "side_normal": np.array(chosen.summary["path"]["frame"])[:, 1].tolist(),
        "reason": "Maximize weakest-axis bending rigidity among feasible complete sections and paths; prefer 7249 when rigidity is equal.",
        "settings": settings.model_dump(),
        "qualification": "Planar geometric path with encoded bend insertions/deletions; stiffness and RMSF have not been simulated.",
    }

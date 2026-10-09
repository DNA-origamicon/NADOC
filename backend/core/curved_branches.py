"""Planar fork geometry with independently sized lattice sections.

A bounded planar fork family, not a general graph optimizer. Each junction is
straight and crosslinked before its two branch sections curve apart. Curvature
is encoded with loop/skips after routing; crossovers cannot bridge the split.
"""

from copy import deepcopy
from functools import lru_cache
import math
import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import CrossoverConstraint, DeformationOp, LatticeType
from backend.core.sweep_model import SweepParams
from backend.core.lattice import honeycomb_position, square_position
from backend.core.two_np_generator import RodCandidate, gold_particles
from backend.core.platform_generator import _perimeter_frames, rotate_platform_frame

FACE_A = [(r, c) for r in range(2) for c in range(1, 4)]
FACE_B = [(r + 1, c + 3) for r, c in FACE_A]


def validate_fork_junctions(design):
    """Check actual curved axes and both scaffold/staple bridges, not proximity alone."""
    from backend.core.deformation import deformed_nucleotide_arrays

    for rule in design.crossover_constraints:
        ids = set(rule.helix_ids_a + rule.helix_ids_b)
        axes = {}
        for hid in ids:
            array = deformed_nucleotide_arrays(design.find_helix(hid), design)
            axes[hid] = dict(zip(array["bp_indices"], array["axis_points"]))
        links = [
            xo
            for xo in design.crossovers
            if (
                xo.half_a.helix_id in rule.helix_ids_a
                and xo.half_b.helix_id in rule.helix_ids_b
            )
            or (
                xo.half_b.helix_id in rule.helix_ids_a
                and xo.half_a.helix_id in rule.helix_ids_b
            )
        ]
        for lo, hi in rule.allowed_bp_intervals:
            here = [xo for xo in links if lo <= xo.half_a.index <= hi]
            scaffold = [
                xo
                for xo in here
                if xo.half_a.strand == design.find_helix(xo.half_a.helix_id).direction
            ]
            if len(scaffold) < 2 or len(here) == len(scaffold):
                raise ValueError(
                    "A curved fork junction needs both scaffold and staple bridges before the split."
                )
        for xo in links:
            a, b = xo.half_a, xo.half_b
            if a.index not in axes[a.helix_id] or b.index not in axes[b.helix_id]:
                raise ValueError(
                    "A curved junction crossover has no geometric nucleotide site."
                )
            gap = np.linalg.norm(axes[a.helix_id][a.index] - axes[b.helix_id][b.index])
            if abs(gap - 2.25) > 0.05:
                raise ValueError(
                    "A curved fork stretches a junction crossover outside lattice spacing."
                )


@lru_cache(maxsize=512)
def _path(radius, stem_bp, arc_bp, tail_bp, double, mirror):
    tail = tail_bp * RISE
    stem = stem_bp * RISE
    points, frames = [], []

    def add(x, z, angle):
        points.append([mirror * x, 0.0, z])
        frames.append(
            Rotation.from_euler("y", mirror * angle).as_matrix().ravel().tolist()
        )

    if double:
        add(-radius - tail, 0, math.pi / 2)
        add(-radius, 0, math.pi / 2)
        for angle in np.linspace(0, math.pi / 2, 17)[1:]:
            add(
                -radius + radius * math.sin(angle),
                radius * (1 - math.cos(angle)),
                math.pi / 2 - angle,
            )
        z0 = radius
    else:
        add(0, -tail, 0)
        add(0, 0, 0)
        z0 = 0
    # Explicit straight controls keep the junctions at identical frames in both arms.
    for s in np.linspace(0, stem, max(3, math.ceil(stem / (7 * RISE)) + 1))[1:]:
        add(0, z0 + s, 0)
    for angle in np.linspace(0, math.pi / 2, 17)[1:]:
        add(
            -radius * (1 - math.cos(angle)),
            z0 + stem + radius * math.sin(angle),
            -angle,
        )
    add(-radius - tail, z0 + stem + radius, -math.pi / 2)
    origin = np.array(points[0])
    points = np.array(points) - origin
    from backend.core.sweep_path import path_table, frame_key

    length = float(
        path_table(tuple(map(tuple, points)), None, frame_key(frames))[2][-1]
    )
    steps = (
        stem_bp + (arc_bp + tail_bp) * (2 if double else 1) + (0 if double else tail_bp)
    )
    return dict(
        points_nm=points.tolist(),
        point_frames=frames,
        origin_offset=origin.tolist(),
        path_length_nm=length,
        steps=steps,
    )


def apply_fork_geometry(seed, summary):
    position = (
        honeycomb_position
        if seed.lattice_type == LatticeType.HONEYCOMB
        else square_position
    )
    ids = {h.grid_pos: h.id for h in seed.helices}
    groups = [[ids[tuple(c)] for c in face] for face in summary["fork_faces"]]
    ops = []
    for i, (face, path) in enumerate(zip(summary["fork_faces"], summary["fork_paths"])):
        xy = np.mean([position(*c) for c in face], axis=0)
        origin = np.r_[xy, 0.0] + path["origin_offset"]
        params = SweepParams(
            points_nm=path["points_nm"],
            point_frames=path["point_frames"],
            origin_nm=origin.tolist(),
            initial_rotation=path["point_frames"][0],
            steps=path["steps"],
            path_length_nm=path["path_length_nm"],
            auto_loop_skips=True,
        )
        ops.append(
            DeformationOp(
                id=f"generated_fork_sweep_{i}",
                type="sweep",
                plane_a_bp=0,
                plane_b_bp=path["steps"],
                affected_helix_ids=groups[i],
                params=params,
            )
        )
    specs = summary.get(
        "fork_rule_specs", [(0, 1, summary["fork_crossover_intervals"])]
    )
    constraints = [
        CrossoverConstraint(
            helix_ids_a=groups[a], helix_ids_b=groups[b], allowed_bp_intervals=intervals
        )
        for a, b, intervals in specs
    ]
    return seed.copy_with(deformations=ops, crossover_constraints=constraints)


def _candidate(
    local,
    frame,
    double,
    faces=None,
    lattice=LatticeType.HONEYCOMB,
    junction_periods=None,
    tail_bp=21,
):
    faces = faces or (FACE_A, FACE_B)
    face_a, face_b = faces
    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    tick = 7 if lattice == LatticeType.HONEYCOMB else 8
    ordered = np.argsort(local[:, 2])
    low = ordered[:2] if double else ordered[:1]
    high = ordered[2:] if double else ordered[1:]
    groups = [
        sorted(low, key=lambda i: local[i, 0]),
        sorted(high, key=lambda i: local[i, 0]),
    ]
    if any(np.ptp(local[g, 2]) > 3 for g in groups):
        raise ValueError(
            "Particle pairs need approximately aligned axial stations (within 3 nm)."
        )
    widths = [np.ptp(local[g, 0]) for g in groups if len(g) == 2]
    if max(widths) - min(widths) > 3:
        raise ValueError(
            "The two particle pairs need similar transverse separation (within 3 nm)."
        )
    if abs(np.mean(local[groups[0], 0]) - np.mean(local[groups[1], 0])) > 3:
        raise ValueError(
            "The two fork stations need approximately aligned midpoints (within 3 nm)."
        )
    centers = np.array(
        [np.mean([position(*c) for c in face], axis=0) for face in faces]
    )
    separation = centers[1, 0] - centers[0, 0]
    desired_radius = (float(np.mean(widths)) - separation) / 2
    # A 6HB outer fiber must not demand more than the existing curvature limit.
    extent = max(
        max(abs(position(*c)[0] - center[0]) for c in face)
        for face, center in zip(faces, centers)
    )
    if desired_radius < max(10, extent / 0.35):
        raise ValueError(
            f"These branch cross-sections need a turn radius of at least {max(10, extent / 0.35):.1f} nm; increase paired-particle separation."
        )
    arc_bp = math.ceil(desired_radius * math.pi / 2 / RISE / tick) * tick
    radius = arc_bp * RISE * 2 / math.pi
    span = float(np.mean(local[groups[1], 2]) - np.mean(local[groups[0], 2]))
    stem_bp = round((span - radius * (2 if double else 1)) / RISE)
    # Use a third crossover period when the trunk has room. This leaves staple
    # sites outside the scaffold seam's exclusion margin at either fork phase.
    junction_bp = period * (
        junction_periods
        or (3 if stem_bp >= 3 * period * (2 if double else 1) + period else 2)
    )
    if stem_bp < junction_bp * (2 if double else 1) + period:
        raise ValueError(
            "Not enough axial room for the junction regions and a distinct trunk. Increase the separation between fork stations."
        )
    paths = [
        _path(radius, stem_bp, arc_bp, tail_bp, double, mirror) for mirror in (1, -1)
    ]
    steps = paths[0]["steps"]
    first_split = tail_bp + arc_bp if double else tail_bp
    last_split = first_split + stem_bp
    intervals = ([[0, first_split + junction_bp]] if double else []) + [
        [last_split - junction_bp, steps]
    ]
    joins = ([[first_split + 7, first_split + junction_bp - 7]] if double else []) + [
        [last_split - junction_bp + 7, last_split - 7]
    ]
    crossover_intervals = (
        [[first_split, first_split + junction_bp]] if double else []
    ) + [[last_split - junction_bp, last_split]]
    trunk = [dict(cell=list(c), interval=[0, steps]) for c in face_a]
    windows = [[dict(cell=list(c), interval=iv) for c in face_b] for iv in intervals]
    tracks = [dict(cell=list(c), intervals=[[0, steps]]) for c in face_a] + [
        dict(cell=list(c), intervals=intervals) for c in face_b
    ]
    stations = [None] * len(local)
    for end, group in enumerate(groups):
        bp = tail_bp if end == 0 else steps - tail_bp
        for side, i in enumerate(group):
            stations[int(i)] = dict(face=side, bp=bp)
            if len(group) == 1:
                # The six-helix trunk lies to one side of the 12HB junction's
                # center. Prefer its cargo-facing edge at a single-particle end.
                stations[int(i)]["target_x"] = float(centers[:, 0].mean() + local[i, 0])
    actual_span = stem_bp * RISE + radius * (2 if double else 1)
    # Single-particle end stays on the six-helix trunk, away from its end cap.
    if not double:
        stations[int(groups[0][0])]["bp"] = tail_bp
    return dict(
        shape="branched",
        branch_geometry="curved",
        base_frame=frame.tolist(),
        cells=[list(c) for c in list(face_a) + list(face_b)],
        nominal_length_bp=steps + 1,
        branch_tracks=tracks,
        branch_trunk=trunk,
        branch_windows=windows,
        branch_junction_intervals=joins,
        fork_faces=[[list(c) for c in f] for f in faces],
        fork_crossover_intervals=crossover_intervals,
        fork_paths=paths,
        fork_stations=stations,
        radius_nm=radius,
        center_local=[
            float(centers[:, 0].mean()),
            float(centers[:, 1].mean()),
            actual_span / 2,
        ],
        section=f"{len(face_a)}HB trunk · {len(face_a) + len(face_b)}HB junctions · {len(face_a)}/{len(face_b)}HB curved arms",
        helix_count=len(face_a) + len(face_b),
        branch_count=4 if double else 3,
        trunk_helix_count=len(face_a),
        junction_helix_count=len(face_a) + len(face_b),
        junction_length_bp=junction_bp,
        arm_helix_count=[len(face_a), len(face_b)],
        stem_start_bp=first_split,
        stem_end_bp=last_split,
        tail_bp=tail_bp,
        length_nm=actual_span,
        nominal_scaffold_nt=sum(
            hi - lo + 1 for t in tracks for lo, hi in t["intervals"]
        ),
    )


def plan_curved_branches(source, settings):
    if settings.branch_sizing == "optimized":
        from backend.core.branch_optimizer import plan_optimized_branches

        return plan_optimized_branches(source, settings)
    from backend.core.branched_generator import branch_seed, route_branches
    from backend.core.generated_sweep import encode_sweep
    from backend.core.curved_rod_generator import physical_scaffold_nt

    particles, centers, distance = gold_particles(source, (3, 4))
    if source.lattice_type != LatticeType.HONEYCOMB:
        raise ValueError(
            "Curved 6HB branches require the honeycomb lattice. Choose straight lattice branches for a square lattice."
        )
    if (
        settings.mechanics != "legacy"
        or settings.pathing != "colocalized"
        or settings.particle_order
    ):
        raise ValueError(
            "Curved branches choose their own fork stations; curved-rod path settings do not apply."
        )
    failure = "No compatible planar fork layout was found."
    choices = []
    frames = _perimeter_frames(centers)
    if max(abs((centers - centers.mean(0)) @ frames[0][:, 1])) > 2:
        raise ValueError(
            "Curved branches currently require particle centers within 2 nm of one plane."
        )
    for base in frames:
        for sign in (1, -1):
            frame = rotate_platform_frame(base, settings.roll_deg)
            frame[:, [0, 2]] *= sign
            local = (centers - centers.mean(0)) @ frame
            local[:, [0, 2]] -= (local[:, [0, 2]].min(0) + local[:, [0, 2]].max(0)) / 2
            try:
                summary = _candidate(local, frame, len(particles) == 4)
                # Rotation has already been included in this frame.
                summary["base_frame"] = rotate_platform_frame(
                    frame, -settings.roll_deg
                ).tolist()
                if summary["nominal_scaffold_nt"] > 8064:
                    raise ValueError(
                        "Curved arms exceed the 8064-base scaffold budget."
                    )
                routed, _ = route_branches(
                    branch_seed(source.lattice_type, summary), summary
                )
                encoded = encode_sweep(routed)
                used = physical_scaffold_nt(encoded)
                if used > 8064:
                    raise ValueError(
                        "Routed curved arms exceed the 8064-base scaffold budget."
                    )
                size = 7249 if used <= 7249 else 8064
                summary.update(
                    scaffold_used_nt=used,
                    scaffold_size=size,
                    scaffold_name="M13mp18" if size == 7249 else "p8064",
                    unused_scaffold_nt=size - used,
                )
                choices.append(RodCandidate(encoded, summary))
            except ValueError as exc:
                failure = str(exc)
    if not choices:
        raise ValueError(
            "No curved 6HB fork fits this arrangement. "
            + failure
            + " Straight lattice branches remain available."
        )
    chosen = min(choices, key=lambda c: c.summary["scaffold_used_nt"])
    public = {
        k: v
        for k, v in chosen.summary.items()
        if k
        not in (
            "branch_tracks",
            "branch_trunk",
            "branch_windows",
            "fork_paths",
            "fork_faces",
            "fork_stations",
            "cells",
            "base_frame",
            "center_local",
        )
    }
    return chosen, dict(
        shape="branched",
        branch_geometry="curved",
        lattice_type=source.lattice_type.value,
        particle_ids=[p.id for p in particles],
        centers_nm=centers.tolist(),
        center_distance_nm=distance,
        selected=deepcopy(public),
        alternatives=[public],
        settings=settings.model_dump(),
        reason="Shortest routed supported curved fork; 6HB trunk, straight 12HB junction regions and separate swept 6HB arms.",
        qualification="Experimental planar 6HB forks. Curvature uses loop/skips; crossover constraints protect each split. Attachment fitting and CanDo validation run during generation.",
    )

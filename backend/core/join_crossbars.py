"""Continuous NP-pair crossbars for a stem joined at two T junctions."""

import math

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.lattice import honeycomb_position, square_position
from backend.core.models import LatticeType


def _unit(vector):
    vector = np.asarray(vector, float)
    length = np.linalg.norm(vector)
    if length < 1e-8:
        raise ValueError("A continuous Join crossbar has a zero-length direction.")
    return vector / length


def _frames(tangents):
    tangents = np.asarray(tangents)
    y = np.tile([0.0, 1.0, 0.0], (len(tangents), 1))
    return np.stack([np.cross(y, tangents), y, tangents], axis=-1)


def _line(start, end, steps):
    points = np.linspace(start, end, steps + 1)
    return points, np.tile(_unit(end - start), (steps + 1, 1))


def _curve(start, end, initial, final, outer_radius, max_strain):
    """Choose a smooth cubic with bounded strain and no reversal along its chord."""
    chord = np.asarray(end) - start
    length = np.linalg.norm(chord)
    if length < RISE:
        raise ValueError(
            "A crossbar needs more room between its particle and junction."
        )
    u = np.linspace(0, 1, 513)
    v = 1 - u
    best = None
    for fraction in (0.35, 0.45, 0.55, 0.65, 0.75):
        handles = np.array(
            [
                start,
                start + initial * length * fraction,
                end - final * length * fraction,
                end,
            ]
        )
        points = (
            v[:, None] ** 3 * handles[0]
            + 3 * (v * v * u)[:, None] * handles[1]
            + 3 * (v * u * u)[:, None] * handles[2]
            + u[:, None] ** 3 * handles[3]
        )
        first = (
            3 * v[:, None] ** 2 * (handles[1] - handles[0])
            + 6 * (v * u)[:, None] * (handles[2] - handles[1])
            + 3 * u[:, None] ** 2 * (handles[3] - handles[2])
        )
        second = 6 * v[:, None] * (handles[2] - 2 * handles[1] + handles[0]) + 6 * u[
            :, None
        ] * (handles[3] - 2 * handles[2] + handles[1])
        speed = np.linalg.norm(first, axis=1)
        if np.min(first @ _unit(chord)) <= 0 or min(speed) < 1e-8:
            continue
        strain = float(
            max(np.linalg.norm(np.cross(first, second), axis=1) / speed**3)
            * outer_radius
        )
        arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        if best is None or strain < best[0]:
            best = strain, points, first / speed[:, None], arc
    if best is None or best[0] > max_strain:
        raise ValueError(
            "The continuous crossbar exceeds its outer-fiber strain limit."
        )
    strain, points, tangent, arc = best
    steps = max(1, math.ceil(arc[-1] / RISE))
    stations = np.linspace(0, arc[-1], steps + 1)
    sampled = np.column_stack(
        [np.interp(stations, arc, points[:, k]) for k in range(3)]
    )
    tangent = np.column_stack(
        [np.interp(stations, arc, tangent[:, k]) for k in range(3)]
    )
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    return sampled, tangent, strain


def crossbar_summary(
    source,
    centers,
    layout,
    stem_hb,
    arm_hb,
    tail_bp=21,
    gap_nm=1.5,
    max_outer_strain=0.35,
    central_bp=14,
):
    """Describe canonical +Z seeds and explicit centerlines in generator coordinates.

    A section's optional ``path`` has ``start``, ``positions`` and flattened
    ``frames`` suitable for indexed SweepParams. Crossbar cluster poses are
    identity: their sweep positions already contain the full local placement.
    ``join_attachments.bp`` indexes each NP station before cluster poses; its
    ``target_x`` is a canonical lattice coordinate. Increasing tail_bp extends
    terminal duplexes without moving particles or either T-junction.

    This is geometry only. The caller routes each section, applies curvature
    marks, selects native Join bridges, and fills the physical scaffold budget.
    """
    from backend.core.platform_generator import _plane_frame

    centers = np.asarray(centers, float)
    tail_counts = [tail_bp] if isinstance(tail_bp, (int, np.integer)) else list(tail_bp)
    if (
        not tail_counts
        or any(not isinstance(n, (int, np.integer)) or n < 1 for n in tail_counts)
        or central_bp < 2
        or central_bp % 2
        or gap_nm <= 0
    ):
        raise ValueError(
            "Crossbar tails, an even central span, and a positive gap are required."
        )
    lattice = source.lattice_type
    if lattice not in (LatticeType.HONEYCOMB, LatticeType.SQUARE):
        raise ValueError(
            "Continuous Join crossbars require a honeycomb or square lattice."
        )
    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    y = _plane_frame(centers)[:, 1]
    z = np.asarray(layout["stem_end"]) - layout["stem_start"]
    z = _unit(z - y * (z @ y))
    frame = np.column_stack([np.cross(y, z), y, z])
    origin = centers.mean(0)
    projected = (centers - origin) @ frame
    origin = origin + frame @ np.array(
        [
            (projected[:, 0].min() + projected[:, 0].max()) / 2,
            0,
            (projected[:, 2].min() + projected[:, 2].max()) / 2,
        ]
    )
    local = (centers - origin) @ frame
    if max(abs(local[:, 1])) > 2:
        raise ValueError(
            "Continuous Join crossbars require centers within 2 nm of one plane."
        )
    local[:, 1] = 0
    start, end = [
        (np.asarray(layout[k]) - origin) @ frame for k in ("stem_start", "stem_end")
    ]
    start[1] = end[1] = 0
    particles = [p for p in source.nanoparticles if p.kind == "gold_nanosphere"]
    if len(particles) != len(centers):
        raise ValueError("Particle centers do not match the continuous Join source.")
    attachments = [
        dict(particle_id=p.id, cluster_id="branch_cluster_0") for p in particles
    ]

    def cells_for(hb):
        from backend.core.two_np_generator import cross_sections

        if hb == 12:
            return [[r, c] for r in range(4) for c in range(1, 4)]
        candidates = [s for s in cross_sections(lattice) if s["helix_count"] == hb]
        if not candidates:
            raise ValueError(f"No established {hb}HB cross-section is available.")
        selected = max(candidates, key=lambda s: s["section_score"])
        return [list(cell) for cell in selected["cells"]]

    arm_cells = cells_for(arm_hb)
    arm_xy = np.array([position(*cell) for cell in arm_cells])
    arm_center = arm_xy.mean(0)
    outer_radius = float(max(abs(arm_xy[:, 0] - arm_center[0])))
    groups = []
    for arm in layout["arms"]:
        junction = (np.asarray(arm["junction"]) - origin) @ frame
        junction[1] = 0
        group = next(
            (g for g in groups if np.allclose(g[0], junction, atol=1e-8)), None
        )
        if group is None:
            group = [junction, []]
            groups.append(group)
        group[1].append(arm["particle_index"])
    if any(len(indices) != 2 for _, indices in groups):
        raise ValueError(
            "Every continuous crossbar needs exactly two nanoparticle arms."
        )
    sections, crossbars, trim = [], [], {}
    if len(tail_counts) not in (1, len(groups)):
        raise ValueError("Supply one tail length or one per crossbar.")
    for index, (junction, indices) in enumerate(groups, 1):
        tail = int(tail_counts[0] if len(tail_counts) == 1 else tail_counts[index - 1])
        a, b = local[indices]
        tangent = _unit(b - a)
        normal = np.cross([0.0, 1.0, 0.0], tangent)
        transverse = abs(normal @ np.array([0, 0, 1]))
        if transverse < 0.2:
            raise ValueError("A crossbar is too parallel to the middle stem.")
        trim[
            "start"
            if np.linalg.norm(junction - start) < np.linalg.norm(junction - end)
            else "end"
        ] = (outer_radius + 1.0) / transverse + gap_nm
        outward_a, outward_b = _unit(a - junction), _unit(b - junction)
        shoulder_a = junction - tangent * (central_bp / 2) * RISE
        shoulder_b = junction + tangent * (central_bp / 2) * RISE
        left, left_tangent, strain_a = _curve(
            a, shoulder_a, -outward_a, tangent, outer_radius, max_outer_strain
        )
        right, right_tangent, strain_b = _curve(
            shoulder_b, b, tangent, outward_b, outer_radius, max_outer_strain
        )
        initial_steps = 2 * tail + len(left) - 1 + central_bp + len(right) - 1
        length_bp = initial_steps + 1
        parts = [
            _line(a + outward_a * tail * RISE, a, tail),
            (left, left_tangent),
            _line(shoulder_a, shoulder_b, central_bp),
            (right, right_tangent),
            _line(b, b + outward_b * tail * RISE, tail),
        ]
        points = np.concatenate(
            [p if j == 0 else p[1:] for j, (p, _) in enumerate(parts)]
        )
        tangents = np.concatenate(
            [t if j == 0 else t[1:] for j, (_, t) in enumerate(parts)]
        )
        if length_bp > 2016:
            raise ValueError(
                "A continuous crossbar exceeds the supported base-pair span."
            )
        bp_a = tail
        join_bp = tail + len(left) - 1 + central_bp // 2
        bp_b = tail + len(left) - 1 + central_bp + len(right) - 1
        identifier = f"branch_cluster_{index}"
        path = dict(
            start=0,
            positions=points.tolist(),
            frames=_frames(tangents).reshape(-1, 9).tolist(),
        )
        sections.append(
            dict(
                id=identifier,
                cells=arm_cells,
                length_bp=length_bp,
                position=[*arm_center, 0.0],
                rotation=[0.0, 0.0, 0.0, 1.0],
                path=path,
            )
        )
        crossbars.append(
            dict(
                cluster_id=identifier,
                junction=junction.tolist(),
                particle_indices=indices,
                join_bp=join_bp,
                join_interval=[join_bp - central_bp // 2, join_bp + central_bp // 2],
                outer_strain=max(strain_a, strain_b),
            )
        )
        for particle_index, bp in zip(indices, (bp_a, bp_b)):
            attachments[particle_index].update(
                cluster_id=identifier, bp=int(bp), target_x=float(arm_center[0])
            )

    stem_cells = cells_for(stem_hb)
    stem_xy = np.mean([position(*cell) for cell in stem_cells], axis=0)
    stem_start = start + np.array([0.0, 0.0, trim.get("start", -tail_counts[0] * RISE)])
    stem_end = end - np.array([0.0, 0.0, trim.get("end", -tail_counts[0] * RISE)])
    span = float(stem_end[2] - stem_start[2])
    length = math.floor(span / RISE + 1) - 14
    if length < 3 * period:
        raise ValueError(
            "The two crossbars leave too little space for a solid middle stem."
        )
    # Reserve cap routing space; the caller recenters the actual routed stem.
    stem_position = (stem_start + stem_end) / 2 - np.array(
        [0.0, 0.0, (length - 1) * RISE / 2]
    )
    stem = dict(
        id="branch_cluster_0",
        cells=stem_cells,
        length_bp=length,
        position=stem_position.tolist(),
        rotation=[0.0, 0.0, 0.0, 1.0],
        fit_center=((stem_start + stem_end) / 2).tolist(),
        span_nm=span,
    )
    sections.insert(0, stem)
    for index in layout.get("stem_particles", []):
        attachments[index].update(
            bp=int(round((local[index, 2] - stem_position[2]) / RISE)),
            target_x=float(stem_xy[0]),
        )
    nominal = sum(len(s["cells"]) * s["length_bp"] for s in sections)
    return dict(
        shape="branched",
        branch_geometry="join",
        join_curved=True,
        join_sections=sections,
        join_crossbars=crossbars,
        join_attachments=attachments,
        join_setback=layout["setback"],
        base_frame=frame.tolist(),
        center_local=[0.0, 0.0, 0.0],
        cells=[c for s in sections for c in s["cells"]],
        nominal_length_bp=max(s["length_bp"] for s in sections),
        nominal_scaffold_nt=nominal,
        helix_count=sum(len(s["cells"]) for s in sections),
        trunk_helix_count=stem_hb,
        arm_helix_count=arm_hb,
        branch_count=len(crossbars),
        length_nm=span,
        section=f"{stem_hb}HB middle stem + {len(crossbars)} continuous {arm_hb}HB crossbars",
        bending_proxy=float(
            span**3 / stem_hb**2
            + sum((s["length_bp"] * RISE) ** 3 / arm_hb**2 for s in sections[1:])
        ),
    )

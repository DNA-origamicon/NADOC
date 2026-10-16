"""Continuous particle-directed bundles assembled with native end-to-side Join."""

from copy import deepcopy
from functools import lru_cache
import math

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import ClusterRigidTransform, Design, LatticeType
from backend.core.seamed_router import auto_scaffold_seamed_bounded

QUALIFICATION = (
    "Continuous nanoparticle-pair bundles joined to a solid middle stem with "
    "short native ssDNA bridges. Exact scaffold budgets include curvature "
    "insertions/deletions and connectors. Routing and fixed-center attachments "
    "are checked for this first pass; mechanical refinement is separate."
)


class BranchBudgetError(ValueError):
    """The native scaffold, including connectors, exceeds its budget."""


def _frame(axis):
    z = np.asarray(axis, float).copy()
    z[1] = 0
    z /= np.linalg.norm(z)
    y = np.array([0.0, 1.0, 0.0])
    return np.column_stack([np.cross(y, z), y, z])


def _summary(source, centers, layout, stem_hb, arm_hb):
    from backend.core.platform_generator import _plane_frame

    plane = _plane_frame(centers)
    y = plane[:, 1]
    z = np.asarray(layout["stem_end"]) - layout["stem_start"]
    z -= y * (z @ y)
    z /= np.linalg.norm(z)
    frame = np.column_stack([np.cross(y, z), y, z])
    origin = centers.mean(0)
    projected = (centers - origin) @ frame
    origin += frame @ np.array(
        [
            (projected[:, 0].min() + projected[:, 0].max()) / 2,
            0,
            (projected[:, 2].min() + projected[:, 2].max()) / 2,
        ]
    )
    local = (centers - origin) @ frame
    if max(abs(local[:, 1])) > 2:
        raise ValueError(
            "Join generation requires particle centers within 2 nm of one plane."
        )
    start, end = [
        (np.asarray(layout[k]) - origin) @ frame for k in ("stem_start", "stem_end")
    ]
    start[1] = end[1] = 0
    period = 21 if source.lattice_type == LatticeType.HONEYCOMB else 32

    def section(index, hb, span, position, axis):
        length = max(3 * period, math.ceil(span / RISE / period) * period)
        return dict(
            id=f"branch_cluster_{index}",
            cells=[[r, c] for r in range(hb // 3) for c in range(1, 4)],
            length_bp=length,
            position=np.asarray(position).tolist(),
            rotation=Rotation.from_matrix(_frame(axis)).as_quat().tolist(),
        )

    # Junctions sit inside the stem, leaving usable side edges beyond both splits.
    sections = [
        section(
            0,
            stem_hb,
            np.linalg.norm(end - start) + 16,
            start - np.array([0.0, 0.0, 8.0]),
            [0, 0, 1],
        )
    ]
    attachments = [
        dict(particle_id=p.id, cluster_id="branch_cluster_0")
        for p in source.nanoparticles
        if p.kind == "gold_nanosphere"
    ]
    arms = []
    for index, arm in enumerate(layout["arms"], 1):
        particle_index = arm["particle_index"]
        junction = (np.asarray(arm["junction"]) - origin) @ frame
        junction[1] = 0
        target = local[particle_index].copy()
        target[1] = 0
        direction = target - junction
        if (
            np.linalg.norm(direction[[0, 2]]) < 6
            or abs(direction[0]) / np.linalg.norm(direction) < 0.2
        ):
            raise ValueError("A particle branch is too short or parallel to the stem.")
        # Park unjoined arms apart. Each Join authors its final rigid pose.
        sections.append(
            section(
                index,
                arm_hb,
                np.linalg.norm(direction) + 10,
                [1000 * index, 0, 0],
                [0, 0, 1],
            )
        )
        arms.append(
            dict(
                cluster_id=sections[-1]["id"],
                junction=junction.tolist(),
                target=target.tolist(),
                particle_index=particle_index,
            )
        )
        attachments[particle_index]["cluster_id"] = sections[-1]["id"]
    return dict(
        shape="branched",
        branch_geometry="join",
        join_sections=sections,
        join_arms=arms,
        join_attachments=attachments,
        join_setback=layout["setback"],
        base_frame=frame.tolist(),
        center_local=[0.0, 0.0, 0.0],
        cells=[c for s in sections for c in s["cells"]],
        nominal_length_bp=max(s["length_bp"] for s in sections),
        nominal_scaffold_nt=sum(len(s["cells"]) * s["length_bp"] for s in sections),
        helix_count=sum(len(s["cells"]) for s in sections),
        trunk_helix_count=stem_hb,
        arm_helix_count=arm_hb,
        branch_count=len(arms),
        length_nm=float(np.linalg.norm(end - start)),
        section=f"{stem_hb}HB stem + {len(arms)} × {arm_hb}HB directed branches",
        bending_proxy=float(
            np.linalg.norm(end - start) ** 3 / stem_hb**2
            + sum(
                np.linalg.norm(np.asarray(a["target"]) - a["junction"]) ** 3 / arm_hb**2
                for a in arms
            )
        ),
    )


def joined_seed(lattice, summary):
    from backend.core.lattice import make_bundle_design

    parts, clusters, deformations = [], [], []
    for index, spec in enumerate(summary["join_sections"]):
        part = make_bundle_design(
            spec["cells"], spec["length_bp"], lattice_type=lattice
        )
        ids = {
            obj.id: f"branch_{index}_{obj.id}" for obj in [*part.helices, *part.strands]
        }

        def rename(value):
            if isinstance(value, str):
                return ids.get(value, value)
            if isinstance(value, list):
                return [rename(v) for v in value]
            if isinstance(value, dict):
                return {k: rename(v) for k, v in value.items()}
            return value

        part = Design.model_validate(rename(part.model_dump()))
        xy = np.mean([h.axis_start.to_array() for h in part.helices], axis=0)
        xy[2] = 0
        rotation = Rotation.from_quat(spec["rotation"]).as_matrix()
        clusters.append(
            ClusterRigidTransform(
                id=spec["id"],
                name="Middle stem" if index == 0 else f"Particle crossbar {index}",
                helix_ids=[h.id for h in part.helices],
                rotation=spec["rotation"],
                translation=(np.asarray(spec["position"]) - rotation @ xy).tolist(),
            )
        )
        if spec.get("path"):
            deformations.append(joined_path_operation(
                [h.id for h in part.helices], spec["path"], f"generated_join_sweep_{index}"))
        # Distinct lattice addresses keep future staple routing inside each
        # independent bundle, with parity and canonical physical axes retained.
        part = part.copy_with(
            helices=[
                h.model_copy(
                    update={"grid_pos": (h.grid_pos[0], h.grid_pos[1] + 1000 * index)}
                )
                for h in part.helices
            ]
        )
        parts.append(part)
    return Design(
        lattice_type=lattice,
        helices=[h for p in parts for h in p.helices],
        strands=[s for p in parts for s in p.strands],
        cluster_transforms=clusters,
        deformations=deformations,
    )


def joined_path_operation(helix_ids, path, identity):
    """Pack the native indexed path; its samples are evaluated builder output."""
    from backend.core.models import DeformationOp
    from backend.core.sweep_model import SweepParams

    positions, frames = path["positions"], path["frames"]
    steps = len(positions) - 1
    return DeformationOp(
        id=identity, type="sweep", plane_a_bp=0, plane_b_bp=steps,
        affected_helix_ids=helix_ids,
        params=SweepParams(points_nm=[positions[0], positions[-1]], origin_nm=[0, 0, 0],
            initial_rotation=frames[0], steps=steps, path_length_nm=steps * RISE,
            bp_positions_nm=positions, bp_frames=frames, auto_loop_skips=True),
    )


@lru_cache(maxsize=4096)
def _section_route_stats(lattice, cells, length, encoded=False):
    """Measure real bounded end turns before spending time on Join geometry."""
    from backend.core.lattice import make_bundle_design
    from backend.core.two_np_generator import scaffold_nt

    part, result = auto_scaffold_seamed_bounded(
        make_bundle_design(cells, length, lattice_type=lattice)
    )
    if not result.valid or len(part.scaffolds()) != 1:
        raise ValueError("A continuous Join section cannot be routed.")
    used = scaffold_nt(part)
    if encoded and lattice == LatticeType.SQUARE:
        from backend.core.curved_rod_generator import physical_scaffold_nt
        from backend.core.loop_skip_calculator import (
            relocate_marks_off_forbidden,
            sq_lattice_periodic_skips,
        )

        # Swept crossbars carry square de-twist skips even when straight. Match
        # the flat-path encoding before filtering possible scaffold budgets.
        marks = relocate_marks_off_forbidden(sq_lattice_periodic_skips(part), part)
        part = part.copy_with(
            helices=[
                h.model_copy(update={"loop_skips": marks.get(h.id, [])})
                for h in part.helices
            ]
        )
        used = physical_scaffold_nt(part)
    return (
        used,
        min(h.axis_start.z for h in part.helices),
        max(h.axis_end.z for h in part.helices),
    )


def _fit_stem(summary, lattice):
    """Keep actual routed stem end turns inside the two crossbar clearances."""
    stem = summary["join_sections"][0]
    if "fit_center" not in stem:
        return
    cells = tuple(map(tuple, stem["cells"]))
    candidates = []
    ideal = math.floor(stem["span_nm"] / RISE) + 1
    for length in range(ideal, max(62, ideal - 35), -1):
        nt, lo, hi = _section_route_stats(lattice, cells, length)
        if hi - lo <= stem["span_nm"] + 1e-8:
            candidates.append((hi - lo, length, lo, hi))
            if len(candidates) >= 3:
                break
    if not candidates:
        raise ValueError("No bounded scaffold end turns fit the middle stem.")
    _, length, lo, hi = max(candidates)
    old_position = stem["position"]
    stem["length_bp"] = length
    stem["position"] = (
        np.asarray(stem["fit_center"]) - np.array([0, 0, (lo + hi) / 2])
    ).tolist()
    for station in summary["join_attachments"]:
        if station["cluster_id"] == stem["id"]:
            # The singleton on a three-particle T follows the same straight stem.
            station["bp"] += int(round((old_position[2] - stem["position"][2]) / RISE))
    summary["nominal_scaffold_nt"] = sum(
        len(s["cells"]) * s["length_bp"] for s in summary["join_sections"]
    )


def _attach_crossbar(design, spec, *, identity_seed=None, fixed_cluster_id=None):
    """Keep the authored curve fixed while finding short native bridge pairs."""
    from backend.core.cluster_join_free import propose_free_cluster_join

    best, errors, clashing_offsets = None, [], set()
    placements = [(reach, 0.0) for reach in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)]
    # Register opposing lattice layers before accepting a one-pair hinge.
    # A small normal shift preserves both NP-directed terminal projections.
    placements += [(reach, dy) for reach in (3.0, 4.0, 5.0) for dy in (1.125, -1.125)]
    for reach, dy in placements:
        if dy in clashing_offsets:
            continue
        body = dict(
            mode="free",
            moving_cluster_id=spec["cluster_id"],
            fixed_cluster_id=(design.cluster_transforms[0].id
                              if fixed_cluster_id is None else fixed_cluster_id),
            reach_nm=reach,
            world_translation=[0.0, dy, 0.0],
            expected_design_id=design.id,
            expected_revision=0,
        )
        try:
            result, report = propose_free_cluster_join(design, body, identity_seed=identity_seed)
        except ValueError as exc:
            errors.append(str(exc))
            if str(exc).startswith("Placement clashes with existing DNA"):
                clashing_offsets.add(dy)
            continue
        best = result, body, report
        # Two separated pairs restrain more rotational freedom than a lone pair.
        # Stop at the shortest reach which can supply that redundancy.
        if report["connection_count"] >= 2:
            break
    if best is None:
        raise ValueError(
            "No short end-to-side Join reaches this curved crossbar. "
            + (errors[-1] if errors else "No compatible scaffold ports.")
        )
    return best


def _attach_arm(design, spec, *, identity_seed=None, fixed_cluster_id=None):
    from backend.core.cluster_join import _geometry, _ports
    from backend.core.cluster_join_free import propose_free_cluster_join

    stem, moving = (
        (design.cluster_transforms[0] if fixed_cluster_id is None
         else next(c for c in design.cluster_transforms if c.id == fixed_cluster_id)),
        next(c for c in design.cluster_transforms if c.id == spec["cluster_id"]),
    )
    geo = _geometry(design, set(stem.helix_ids))
    junction, target = np.array(spec["junction"]), np.array(spec["target"])
    direction = target - junction
    direction /= np.linalg.norm(direction)
    ports = [
        p
        for p in _ports(design, stem, geo, dense=True)
        if p["kind"] == "side" and np.dot(p["normal"], direction) > 0.35
    ]
    ports.sort(
        key=lambda p: (np.linalg.norm(np.asarray(p["position"]) - junction), p["_bp"])
    )
    helices = [h for h in design.helices if h.id in set(moving.helix_ids)]
    center = np.mean([h.axis_start.to_array() for h in helices], axis=0)
    # Use the actual routed near face, not the precursor's nominal bp zero.
    center[2] = min(h.axis_start.z for h in helices)
    errors = []
    for gap in (3.0, 4.5, 6.0):
        for port in ports[:8]:
            root = np.asarray(port["position"]).copy()
            root[1] = 0
            outward = target - root
            outward[1] = 0
            outward /= np.linalg.norm(outward)
            root += outward * gap
            rotation = _frame(target - root)
            translation = root - rotation @ center
            old_rotation = Rotation.from_quat(moving.rotation).as_matrix()
            delta = rotation @ old_rotation.T
            body = dict(
                mode="free",
                moving_cluster_id=moving.id,
                fixed_cluster_id=stem.id,
                world_rotation=Rotation.from_matrix(delta).as_quat().tolist(),
                world_translation=(
                    translation - delta @ np.asarray(moving.translation)
                ).tolist(),
                reach_nm=min(10.0, gap + 3),
                expected_design_id=design.id,
                expected_revision=0,
            )
            try:
                result, report = propose_free_cluster_join(design, body, identity_seed=identity_seed)
                return result, body, report
            except ValueError as exc:
                errors.append(str(exc))
    raise ValueError(
        "No collision-free end-to-side Join reaches this particle branch. "
        + (errors[-1] if errors else "No outward-facing stem port.")
    )


def route_joined_branches(seed, summary, record=None):
    from backend.core.curved_rod_generator import physical_scaffold_nt

    def check_budget(design):
        if physical_scaffold_nt(design) > summary.get(
            "routing_budget", summary.get("scaffold_size", 8064)
        ):
            raise BranchBudgetError(
                "The routed Join branches exceed the scaffold budget."
            )

    routed = []
    for cluster in seed.cluster_transforms:
        ids = set(cluster.helix_ids)
        part = Design(
            lattice_type=seed.lattice_type,
            helices=[h for h in seed.helices if h.id in ids],
            strands=[
                s for s in seed.strands if all(d.helix_id in ids for d in s.domains)
            ],
            deformations=[
                op for op in seed.deformations if set(op.affected_helix_ids) <= ids
            ],
        )
        part, result = auto_scaffold_seamed_bounded(part)
        if not result.valid or len(part.scaffolds()) != 1:
            raise ValueError("An independent Join branch could not be routed.")
        routed.append(part)
    design = seed.copy_with(
        helices=[h for p in routed for h in p.helices],
        strands=[s for p in routed for s in p.strands],
        crossovers=[c for p in routed for c in p.crossovers],
    )
    if summary.get("join_curved"):
        from backend.core.generated_sweep import encode_sweep

        design = encode_sweep(design)
    check_budget(design)
    if record:
        record(
            seed,
            design,
            "auto-scaffold-seamed",
            "Route independent branch scaffolds",
            {},
            "branch-scaffolds",
        )
    reports = []
    for index, spec in enumerate(
        summary.get("join_crossbars", summary.get("join_arms", []))
    ):
        before = design
        attach = _attach_crossbar if summary.get("join_curved") else _attach_arm
        design, body, report = attach(design, spec)
        reports.append(report)
        check_budget(design)
        if record:
            record(
                before,
                design,
                "cluster-join",
                f"Join particle crossbar {index + 1}",
                body,
                f"branch-join:{index}",
            )
    if len(design.scaffolds()) != 1:
        raise ValueError("Join branches did not form one scaffold.")
    summary.update(
        join_count=len(reports),
        bridge_pair_counts=[r["connection_count"] for r in reports],
        connector_nt=sum(r["added_connector_nt"] for r in reports),
        max_connector_nt=max(
            (b["extra_bases"] for r in reports for b in r["bridges"]), default=0
        ),
    )
    return design, result


def _continuous_layouts(centers):
    """Keep the opposed-T pairings, relaxing setback before overbending a bar."""
    from backend.core.join_branch_layouts import join_branch_layouts

    layouts = join_branch_layouts(centers)
    for original in layouts[::2]:
        for setback in (0.05, 0.1, 0.0, 0.25):
            layout = deepcopy(original)
            if len(centers) == 4:
                first = [a["particle_index"] for a in original["arms"][:2]]
                second = [a["particle_index"] for a in original["arms"][2:]]
                a, b = centers[first].mean(0), centers[second].mean(0)
                start = a + (b - a) * setback / 2
                end = b - (b - start) * setback
            else:
                start = centers[original["stem_particles"][0]]
                b = centers[[a["particle_index"] for a in original["arms"]]].mean(0)
                end = b - (b - start) * setback
            layout.update(
                stem_start=start.tolist(), stem_end=end.tolist(), setback=setback
            )
            for i, arm in enumerate(layout["arms"]):
                arm["junction"] = (
                    start if len(centers) == 4 and i < 2 else end
                ).tolist()
            yield layout


def _extend_crossbar_tails(summary, extras):
    """Add paired terminal duplex, preserving NP stations and T-junction poses."""
    from backend.core.join_crossbars import extend_crossbar_path

    s = deepcopy(summary)
    for spec, extra in zip(s["join_sections"][1:], extras):
        if not extra:
            continue
        left, right = extra // 2, extra - extra // 2
        spec["path"] = extend_crossbar_path(spec["path"], left, right)
        if "path_recipe" in spec:
            spec["path_recipe"]["extra_left_bp"] += left
            spec["path_recipe"]["extra_right_bp"] += right
        spec["length_bp"] += extra
        for station in s["join_attachments"]:
            if station["cluster_id"] == spec["id"]:
                station["bp"] += left
        for bar in s["join_crossbars"]:
            if bar["cluster_id"] == spec["id"]:
                bar["join_bp"] += left
                bar["join_interval"] = [bp + left for bp in bar["join_interval"]]
    s["nominal_length_bp"] = max(x["length_bp"] for x in s["join_sections"])
    s["nominal_scaffold_nt"] = sum(
        len(x["cells"]) * x["length_bp"] for x in s["join_sections"]
    )
    s["tail_extension_bp"] = list(extras)
    return s


def plan_joined_branches(source, settings):
    from itertools import product
    from backend.core.join_crossbars import crossbar_summary
    from backend.core.branch_optimizer import section_moment, trim_to_budget
    from backend.core.curved_rod_generator import physical_scaffold_nt
    from backend.core.two_np_generator import RodCandidate, gold_particles

    particles, centers, distance = gold_particles(source, (3, 4))
    if source.lattice_type not in (LatticeType.HONEYCOMB, LatticeType.SQUARE):
        raise ValueError("Join branches require a honeycomb or square lattice.")
    if (
        settings.roll_deg
        or settings.mechanics != "legacy"
        or settings.pathing != "colocalized"
        or settings.particle_order
    ):
        raise ValueError(
            "Join branches choose their own particle-directed axes; rod rotation and path settings do not apply."
        )
    budgets = (
        (7249, 8064)
        if settings.branch_scaffold_size == "auto"
        else (int(settings.branch_scaffold_size),)
    )
    lattice = source.lattice_type
    failures, accepted = [], []
    attempted = 0
    # Enlarge viable, compact cross-sections first. Short terminal extensions
    # supply the remaining duplex; ssDNA is never added as budget filler.
    section_sizes = (
        (24, 18, 14, 12, 10, 6)
        if lattice == LatticeType.HONEYCOMB
        else (24, 20, 16, 12, 8, 6)
    )
    layouts = list(_continuous_layouts(centers))
    for topology in range(0, len(layouts), 4):
        trials = {budget: [] for budget in budgets}
        for layout in layouts[topology : topology + 4]:
            for stem_hb, arm_hb in product(section_sizes, repeat=2):
                try:
                    base = crossbar_summary(
                        source, centers, layout, stem_hb, arm_hb, tail_bp=7, gap_nm=0.8
                    )
                    minimum = base["nominal_scaffold_nt"]
                    if lattice == LatticeType.SQUARE:
                        minimum -= math.ceil(minimum / 32)
                    if minimum > max(budgets) + 21:
                        continue
                    _fit_stem(base, lattice)
                    sections = base["join_sections"]
                    stem_cost = _section_route_stats(
                        lattice,
                        tuple(map(tuple, sections[0]["cells"])),
                        sections[0]["length_bp"],
                    )[0]
                    moments = [section_moment(s["cells"], lattice) for s in sections]
                    base["sizing_proxy"] = sum(
                        (spec["length_bp"] * RISE) ** 3 / moment
                        for spec, moment in zip(sections, moments)
                    )
                    options = []
                    for spec in sections[1:]:
                        cells = tuple(map(tuple, spec["cells"]))
                        options.append(
                            [
                                (
                                    _section_route_stats(
                                        lattice,
                                        cells,
                                        spec["length_bp"] + extra,
                                        encoded=True,
                                    )[0],
                                    extra,
                                )
                                for extra in range(43)
                            ]
                        )
                    for tails in product(*options):
                        cost = stem_cost + sum(t[0] for t in tails)
                        extras = tuple(t[1] for t in tails)
                        proxy = (sections[0]["length_bp"] * RISE) ** 3 / moments[
                            0
                        ] + sum(
                            ((spec["length_bp"] + extra) * RISE) ** 3 / moment
                            for spec, extra, moment in zip(
                                sections[1:], extras, moments[1:]
                            )
                        )
                        for budget in budgets:
                            # Actual connector and curvature counts decide feasibility.
                            if budget - 110 <= cost <= budget:
                                trials[budget].append(
                                    (
                                        proxy,
                                        abs(cost + 36 * len(tails) - budget - 10),
                                        base,
                                        extras,
                                    )
                                )
                except ValueError as exc:
                    failures.append(str(exc))
        for budget in budgets:
            trials[budget].sort(
                key=lambda t: (
                    t[2]["join_setback"] == 0,
                    t[2]["sizing_proxy"],
                    t[1],
                    max(t[3]),
                    t[0],
                )
            )
            # Find one feasible first pass per budget; mechanical refinement is
            # separate from initial generation.
            # Stem clocking changes end-turn registration without changing axes.
            poses = (
                (trial, roll)
                for trial in trials[budget]
                for roll in ((0, 180) if len(particles) == 4 else (0,))
            )
            seen, section_attempts, geometry_attempts = (
                set(),
                {},
                {},
            )
            for (proxy, _, base, extras), roll in poses:
                if attempted >= 64 or len(seen) >= 32:
                    break
                curved = base["join_setback"] != 0
                if geometry_attempts.get(curved, 0) >= 16:
                    continue
                section_key = (
                    base["trunk_helix_count"],
                    base["arm_helix_count"],
                    base["join_setback"],
                )
                if section_attempts.get(section_key, 0) >= 8:
                    continue
                key = (*section_key, extras, roll)
                if key in seen:
                    continue
                seen.add(key)
                section_attempts[section_key] = section_attempts.get(section_key, 0) + 1
                geometry_attempts[curved] = geometry_attempts.get(curved, 0) + 1
                summary = _extend_crossbar_tails(base, extras)
                summary["join_sections"][0]["rotation"] = (
                    Rotation.from_euler("z", roll, degrees=True).as_quat().tolist()
                )
                summary.update(
                    scaffold_size=budget,
                    scaffold_name="M13mp18" if budget == 7249 else "p8064",
                    routing_budget=budget + 21,
                    bending_proxy=proxy,
                    stem_clocking_deg=roll,
                )
                attempted += 1
                try:
                    routed, _ = route_joined_branches(
                        joined_seed(lattice, summary), summary
                    )
                    used = physical_scaffold_nt(routed)
                    if (
                        not budget <= used <= budget + 21
                        or min(summary["bridge_pair_counts"]) < 2
                    ):
                        continue
                    prepared = trim_to_budget(routed, budget)
                    summary.update(
                        scaffold_used_nt=budget,
                        unused_scaffold_nt=0,
                        scaffold_utilization=1.0,
                        budget_trim_nt=used - budget,
                        budget_pre_staple_nt=budget,
                    )
                    accepted.append(RodCandidate(prepared, summary))
                    break
                except ValueError as exc:
                    failures.append(str(exc))
                if len(seen) >= 64:
                    break
        if accepted:
            break
        if attempted >= 64:
            break
    if not accepted:
        raise ValueError(
            "No continuous two-T Join layout can use the complete selected scaffold with short connectors. "
            + (
                failures[-1]
                if failures
                else "No exact-budget terminal dimensions were routable."
            )
        )
    accepted.sort(key=lambda c: (c.summary["bending_proxy"], c.summary["connector_nt"]))
    chosen = accepted[0]
    chosen.summary["sizing_candidates"] = [deepcopy(c.summary) for c in accepted[1:]]
    hidden = {
        "cells",
        "base_frame",
        "center_local",
        "join_sections",
        "join_arms",
        "join_crossbars",
        "join_attachments",
        "sizing_candidates",
    }
    public = lambda c: {k: deepcopy(v) for k, v in c.summary.items() if k not in hidden}
    return chosen, dict(
        shape="branched",
        lattice_type=lattice.value,
        particle_ids=[p.id for p in particles],
        centers_nm=centers.tolist(),
        center_distance_nm=distance,
        selected=public(chosen),
        alternatives=[public(c) for c in accepted],
        search=dict(routing_attempts=attempted, rejected=len(failures)),
        settings=settings.model_dump(),
        reason="Continuous nanoparticle-pair bundles minimize Join count; enlarge sections and fit terminal duplexes to use the entire scaffold.",
        qualification=QUALIFICATION,
    )

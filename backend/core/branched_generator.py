"""Bounded search for planar lattice trunks and crosslinked branch sections.

This first family shares one lattice across its junctions. It is not a network
of arbitrarily angled 6HBs. The scaffold router splices closed section routes
with reciprocal double crossovers; ordinary autostapling supplies duplex links.
"""

from copy import deepcopy
import math

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.lattice import make_bundle_design, honeycomb_position, square_position
from backend.core.models import Direction, LatticeType
from backend.core.platform_generator import _perimeter_frames, rotate_platform_frame
from backend.core.two_np_generator import RodCandidate, gold_particles, scaffold_nt


QUALIFICATION = (
    "Experimental planar lattice branches, not angled 6HB arms. Ranked by a geometric "
    "bending proxy; junction mechanics are not optimized. Actual routing is budgeted. "
    "Attachment fitting and CanDo validation run during generation."
)


def branch_seed(lattice, summary):
    """Build sparse duplex tracks; gaps contain neither scaffold nor staples."""
    seed = make_bundle_design(
        summary["cells"],
        summary["nominal_length_bp"],
        lattice_type=lattice,
        name="Generated branched origami",
    )
    by_cell = {tuple(p["cell"]): p["intervals"] for p in summary["branch_tracks"]}
    helices = {h.id: h for h in seed.helices}
    strands = []
    for strand in seed.strands:
        domain = strand.domains[0]
        for i, (lo, hi) in enumerate(by_cell[helices[domain.helix_id].grid_pos]):
            forward = domain.direction == Direction.FORWARD
            d = domain.model_copy(
                update={
                    "start_bp": lo if forward else hi,
                    "end_bp": hi if forward else lo,
                }
            )
            strands.append(
                strand.model_copy(
                    update={
                        "id": f"{strand.id}_b{i}",
                        "domains": [d],
                        "routing_seed": [d],
                    }
                )
            )
    seed = seed.copy_with(strands=strands)
    if summary.get("branch_geometry") == "curved":
        from backend.core.curved_branches import apply_fork_geometry
        seed = apply_fork_geometry(seed, summary)
    if summary.get("branch_geometry") == "connectivity":
        from backend.core.connectivity_generator import apply_connectivity_geometry
        seed = apply_connectivity_geometry(seed, summary)
    return seed


def route_branches(seed, summary):
    from backend.core.section_router import route_sections
    from backend.core.validator import validate_design

    ids = {h.grid_pos: h.id for h in seed.helices}

    def sections(records):
        return {ids[tuple(p["cell"])]: tuple(p["interval"]) for p in records}

    partition = (
        sections(summary["branch_trunk"]),
        [sections(w) for w in summary["branch_windows"]],
    )
    result = route_sections(seed, partition=partition,
                            splice_intervals=summary.get("branch_junction_intervals"),
                            splice_parents=[{ids[tuple(c)] for c in summary['connectivity_faces'][j['parent']]}
                                for j in sorted(summary['connectivity_junctions'],key=lambda j:j['child'])]
                            if summary.get('branch_geometry')=='connectivity' else None)
    if result is None or not result[1].valid:
        raise ValueError(
            "The branched sections could not be spliced into one scaffold."
        )
    design = result[0]
    if len(design.scaffolds()) != 1 or not validate_design(design).passed:
        raise ValueError("Branched scaffold topology did not validate as one strand.")
    # Routing may extend a face for phase, but must never bridge an empty axial gap.
    for track in summary["branch_tracks"]:
        intervals = track["intervals"]
        for (_, end), (start, _) in zip(intervals, intervals[1:]):
            midpoint = (end + start) // 2
            hid = ids[tuple(track["cell"])]
            if any(
                d.helix_id == hid
                and min(d.start_bp, d.end_bp) <= midpoint <= max(d.start_bp, d.end_bp)
                for s in design.scaffolds()
                for d in s.domains
            ):
                raise ValueError(
                    "Routing filled a branch gap; this candidate was rejected."
                )
    return design, result[1]


def _layout(local, lattice, rows, trunk_cols, band_periods, trunk_fraction):
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    pitch = position(0, 1)[0] - position(0, 0)[0]
    width = float(np.ptp(local[:, 0])) + 6.0
    cols = max(trunk_cols + 4, 2 * math.ceil((width / pitch + 1) / 2))
    if rows * cols > 128:
        raise ValueError("Branch footprint exceeds the bounded search size.")
    length = (
        math.ceil((np.ptp(local[:, 2]) / RISE + (band_periods + 2) * period) / period)
        * period
    )
    if length > 2016:
        raise ValueError("Branch span exceeds the supported length.")
    cells = [(r, c) for r in range(rows) for c in range(cols)]
    xy = np.array([position(*c) for c in cells])
    center = np.r_[(xy.min(0) + xy.max(0)) / 2, (length - 1) * RISE / 2]
    x = local[:, 0] + center[0]
    z = local[:, 2] / RISE + center[2] / RISE
    axis_x = float(np.quantile(x, trunk_fraction))
    first = int(
        np.clip(
            2 * round((axis_x / pitch - (trunk_cols - 1) / 2) / 2), 0, cols - trunk_cols
        )
    )
    last = first + trunk_cols - 1
    # Nearby attachment stations share a crossbar. Leave a full period between
    # distinct bands so phase-compatible end turns cannot silently fill the gap.
    bands = []
    for i in np.argsort(z):
        lo = max(0, int(round((z[i] - band_periods * period / 2) / period)) * period)
        hi = min(length - 1, lo + band_periods * period - 1)
        left = max(0, 2 * math.floor((x[i] / pitch - 1.5) / 2))
        right = min(cols - 1, 2 * math.ceil((x[i] / pitch + 1.5) / 2) - 1)
        if bands and lo - bands[-1][1] <= 2 * period:
            old = bands.pop()
            bands.append((old[0], hi, min(left, old[2]), max(right, old[3])))
        else:
            bands.append((lo, hi, left, right))
    trunk = [
        dict(cell=[r, c], interval=[0, length - 1])
        for r in range(rows)
        for c in range(first, last + 1)
    ]
    windows = []
    for lo, hi, left, right in bands:
        for start, end in ((left, first - 1), (last + 1, right)):
            if end < start:
                continue
            windows.append(
                [
                    dict(cell=[r, c], interval=[lo, hi])
                    for r in range(rows)
                    for c in range(start, end + 1)
                ]
            )
    if not windows:
        raise ValueError("These particles need a rod rather than a branched footprint.")
    tracks = {}
    for p in trunk + [p for w in windows for p in w]:
        tracks.setdefault(tuple(p["cell"]), []).append(p["interval"])
    # Reject a filled slab masquerading as branches.
    occupied = sum(b - a + 1 for ivs in tracks.values() for a, b in ivs)
    rectangle = len(tracks) * length
    if occupied > 0.88 * rectangle:
        raise ValueError("The attachment bands merge into a platform at this spacing.")
    # Approximate weak-axis rectangular-section bending. Used only to order a
    # finite search; CanDo evaluates the actual crosslinked duplex core later.
    thickness = float(np.ptp(xy[:, 1]) + 2)
    spine_width = trunk_cols * pitch
    axial = float(np.ptp(local[:, 2]))
    arm_lengths = np.abs(x - (first + last) * pitch / 2)
    proxy = axial**3 / (spine_width * thickness**3) + float(np.sum(arm_lengths**3)) / (
        band_periods * period * RISE * thickness**3
    )
    return dict(
        cells=[list(c) for c in sorted(tracks)],
        nominal_length_bp=length,
        branch_tracks=[
            dict(cell=list(c), intervals=ivs) for c, ivs in sorted(tracks.items())
        ],
        branch_trunk=trunk,
        branch_windows=windows,
        center_local=center.tolist(),
        rows=rows,
        trunk_helix_count=rows * trunk_cols,
        branch_count=len(windows),
        nominal_scaffold_nt=occupied,
        bending_proxy=proxy,
        empty_footprint_fraction=1 - occupied / rectangle,
        length_nm=length * RISE,
        helix_count=len(tracks),
        section=f"{rows * trunk_cols}-helix trunk + {len(windows)} lattice branches",
    )


def plan_branches(source, settings):
    if settings.branch_geometry == "curved":
        from backend.core.curved_branches import plan_curved_branches
        return plan_curved_branches(source, settings)
    particles, centers, distance = gold_particles(source, (3, 4))
    if (
        settings.mechanics != "legacy"
        or settings.pathing != "colocalized"
        or settings.particle_order
    ):
        raise ValueError(
            "Branched designs choose their own trunk and branches; curved-rod path and mechanical sizing settings do not apply."
        )
    lattice = source.lattice_type
    if lattice not in (LatticeType.HONEYCOMB, LatticeType.SQUARE):
        raise ValueError("Branched designs require a honeycomb or square lattice.")
    frames = _perimeter_frames(centers)
    if np.max(np.abs((centers - centers.mean(0)) @ frames[0][:, 1])) > 2.0:
        raise ValueError(
            "Branched generation currently requires particle centers within 2 nm of one plane. A spatial junction router is needed for this arrangement."
        )
    trials = []
    seen = set()
    rejected = dict(geometry=0, budget=0, routing=0)
    for base in frames[:8]:
        frame = rotate_platform_frame(base, settings.roll_deg)
        local = (centers - centers.mean(0)) @ frame
        local[:, [0, 2]] -= (local[:, [0, 2]].min(0) + local[:, [0, 2]].max(0)) / 2
        for rows in (2, 4):
            for trunk_cols in (4, 6):
                for band in (2, 3):
                    for fraction in (0.5,):
                        try:
                            summary = _layout(
                                local, lattice, rows, trunk_cols, band, fraction
                            )
                        except ValueError:
                            rejected["geometry"] += 1
                            continue
                        if summary["nominal_scaffold_nt"] > 8064:
                            rejected["budget"] += 1
                            continue
                        key = (
                            tuple(np.round(frame.ravel(), 6)),
                            str(summary["branch_tracks"]),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        summary.update(shape="branched", base_frame=base.tolist())
                        trials.append(summary)
    trials.sort(key=lambda s: (s["bending_proxy"], s["nominal_scaffold_nt"]))
    best = {}
    attempted = 0
    for summary in trials:
        attempted += 1
        try:
            routed, _ = route_branches(branch_seed(lattice, summary), summary)
        except ValueError:
            rejected["routing"] += 1
            continue
        used = scaffold_nt(routed)
        if used > 8064:
            rejected["budget"] += 1
            continue
        for size, name in ((7249, "M13mp18"), (8064, "p8064")):
            if used <= size and size not in best:
                s = deepcopy(summary)
                s.update(
                    scaffold_size=size,
                    scaffold_name=name,
                    scaffold_used_nt=used,
                    unused_scaffold_nt=size - used,
                )
                best[size] = RodCandidate(routed, s)
        if len(best) == 2:
            break
    if not best:
        raise ValueError(
            "No routable branched design fits 7249/8064 scaffold bases in this search. "
            "Compact layouts may merge into a platform; wide or irregular layouts may exceed the budget or lack a routable junction. "
            f"Compared {len(trials)} budget candidates; {rejected['routing']} routing failures."
        )
    chosen = min(
        best.values(),
        key=lambda c: (c.summary["bending_proxy"], c.summary["scaffold_size"]),
    )

    def public(c):
        return {
            k: v
            for k, v in c.summary.items()
            if k
            not in (
                "branch_tracks",
                "branch_trunk",
                "branch_windows",
                "cells",
                "base_frame",
                "center_local",
            )
        }

    return RodCandidate(
        chosen.design.model_copy(deep=True), deepcopy(chosen.summary)
    ), dict(
        shape="branched",
        lattice_type=lattice.value,
        particle_ids=[p.id for p in particles],
        centers_nm=centers.tolist(),
        center_distance_nm=distance,
        selected=public(chosen),
        alternatives=[
            public(best[n]) if n in best else dict(scaffold_size=n, feasible=False)
            for n in (7249, 8064)
        ],
        search=dict(
            candidates=len(trials), routing_attempts=attempted, rejected=rejected
        ),
        reason="Lowest geometric bending proxy among the routed trunk-and-branch candidates searched.",
        qualification=QUALIFICATION,
        settings=settings.model_dump(),
    )

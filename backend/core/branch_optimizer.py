"""Route-checked discrete section sizing for planar curved fork networks.

Minimize a weak-axis beam compliance proxy, with actual insertion/deletion-aware
scaffold cost. This is a finite sizing search, not a global topology or CanDo
optimization. Unroutable cells, excessive bending and unused bases stay explicit.
"""

from copy import deepcopy
from functools import lru_cache
import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import LatticeType
from backend.core.lattice import honeycomb_position, square_position
from backend.core.two_np_generator import RodCandidate, cross_sections, gold_particles
from backend.core.platform_generator import _perimeter_frames, rotate_platform_frame


def section_moment(cells, lattice):
    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    xy = np.array([position(*c) for c in cells])
    xy -= xy.mean(0)
    return float(np.linalg.eigvalsh(xy.T @ xy)[0] + len(cells) / 4)


def section_library(lattice, custom=None):
    if custom is not None:
        if not 1 <= len(custom) <= 12:
            raise ValueError("Supply one to twelve branch cross-sections.")
        sections = [list(map(tuple, cells)) for cells in custom]
        if any(abs(r) > 128 or abs(c) > 128 for cells in sections for r, c in cells):
            raise ValueError(
                "Define branch cross-sections within 128 lattice cells of the origin."
            )
        if any(
            max(r for r, c in cells) - min(r for r, c in cells) > 24
            or max(c for r, c in cells) - min(c for r, c in cells) > 24
            for cells in sections
            if cells
        ):
            raise ValueError(
                "Branch cross-sections must span at most 24 lattice rows and columns."
            )
        if any(not 4 <= len(c) <= 96 or len(set(c)) != len(c) for c in sections):
            raise ValueError(
                "Each branch cross-section needs 4–96 distinct lattice cells."
            )
    else:
        sections = [
            list(map(tuple, s["cells"]))
            for s in cross_sections(lattice)
            if s["helix_count"] <= 24
        ]
        if lattice == LatticeType.HONEYCOMB:
            sections += [
                [(r, c) for r in range(rows) for c in range(1, cols + 1)]
                for rows in (4, 6)
                for cols in (3, 5)
                if rows * cols <= 24
            ]
    return list({tuple(sorted(c)): c for c in sections}.values())


def adjoining_sections(a, b, lattice):
    """Pack disjoint faces with real lattice neighbors, preserving lattice parity."""
    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    aa = np.array([position(*c) for c in a])
    best = None
    # Put the second face to the right; vertical overlap keeps the junction compact.
    for dc in range(
        max(c for r, c in a) - min(c for r, c in b),
        max(c for r, c in a) - min(c for r, c in b) + 3,
    ):
        for dr in range(
            min(r for r, c in a) - max(r for r, c in b) - 1,
            max(r for r, c in a) - min(r for r, c in b) + 2,
        ):
            if (dr + dc) % 2:
                continue
            moved = [(r + dr, c + dc) for r, c in b]
            if set(a).intersection(moved):
                continue
            bb = np.array([position(*c) for c in moved])
            distances = np.linalg.norm(aa[:, None] - bb[None, :], axis=-1)
            if distances.min() < 2.24 or not np.any(np.isclose(distances, 2.25)):
                continue
            score = (
                abs(aa[:, 1].mean() - bb[:, 1].mean()),
                bb[:, 0].mean() - aa[:, 0].mean(),
            )
            if best is None or score < best[0]:
                best = score, moved
    if best is None:
        raise ValueError("Cross-sections have no compatible side-by-side junction.")
    return a, best[1]


def compliance(summary, lattice):
    """Unit-load weak-axis L³/I proxy; dimensions nm, common modulus omitted."""
    a, b = summary["fork_faces"]
    ia, ib = section_moment(a, lattice), section_moment(b, lattice)
    ij = section_moment(a + b, lattice)
    count = len(summary["fork_crossover_intervals"])
    stem = (summary["stem_end_bp"] - summary["stem_start_bp"]) * RISE
    hub = summary["junction_length_bp"] * RISE
    arm = summary["radius_nm"] * np.pi / 2
    # Compliance contributions for a cantilever, integrating squared moment over
    # reinforced intervals. Both fork ends load the common stem conservatively.
    return float(
        count * arm**3 * (1 / ia + 1 / ib)
        + stem**2 * (max(0, stem - count * hub) / ia + count * hub / ij)
    )


@lru_cache(maxsize=256)
def _collar_cells(a, b, cells, lattice):
    a, b = list(a), list(b)
    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    occupied = set(map(tuple, a + b))
    aa = np.array([position(*c) for c in a])
    all_xy = np.array([position(*c) for c in occupied])
    choices = []
    for dr in range(-12, 13):
        for dc in range(-6, 7):
            if (dr + dc) % 2:
                continue
            moved = [(r + dr, c + dc) for r, c in cells]
            if occupied.intersection(moved):
                continue
            xy = np.array([position(*c) for c in moved])
            if np.linalg.norm(all_xy[:, None] - xy[None, :], axis=-1).min() < 2.24:
                continue
            if not np.any(
                np.isclose(np.linalg.norm(aa[:, None] - xy[None, :], axis=-1), 2.25)
            ):
                continue
            # Prefer reinforcement behind the cargo-facing surface.
            choices.append(
                (float(xy[:, 1].max()), -section_moment(a + moved, lattice), moved)
            )
    if not choices:
        raise ValueError("No adjacent stem reinforcement section fits.")
    return tuple(min(choices)[2])


def reinforce_stem(summary, cells, lattice):
    """Attach an independently sized, straight collar between the curved arms."""
    a, b = summary["fork_faces"]
    moved = list(
        _collar_cells(
            tuple(map(tuple, a)),
            tuple(map(tuple, b)),
            tuple(map(tuple, cells)),
            lattice,
        )
    )
    s = deepcopy(summary)
    lo, hi = s["stem_start_bp"] + 7, s["stem_end_bp"] - 7
    if hi - lo < 42:
        raise ValueError("Stem reinforcement needs two crossover periods.")
    interval = [lo, hi]
    s["cells"] += [list(c) for c in moved]
    s["fork_faces"].append([list(c) for c in moved])
    s["fork_paths"].append(deepcopy(s["fork_paths"][0]))
    s["branch_tracks"] += [dict(cell=list(c), intervals=[interval]) for c in moved]
    s["branch_windows"].append([dict(cell=list(c), interval=interval) for c in moved])
    s["branch_junction_intervals"].append([lo + 7, hi - 7])
    s["fork_rule_specs"] = [
        (0, 1, s["fork_crossover_intervals"]),
        (0, 2, [interval]),
        (1, 2, []),
    ]
    s["stem_reinforcement_cells"] = [list(c) for c in moved]
    s["stem_reinforcement_interval"] = interval
    s["trunk_helix_count"] += len(moved)
    s["helix_count"] += len(moved)
    s["nominal_scaffold_nt"] += len(moved) * (hi - lo + 1)
    base_junction = s["junction_helix_count"]
    s["junction_helix_count"] += len(moved)
    s["junction_helix_count_range"] = [base_junction, s["junction_helix_count"]]
    s["section"] = (
        f"{s['trunk_helix_count']}HB reinforced stem · "
        f"{base_junction}–{s['junction_helix_count']}HB junctions · "
        f"{len(a)}/{len(b)}HB curved arms"
    )
    # Replace the straight-stem term with its reinforced weak-axis moment.
    ia = section_moment(a, lattice)
    reinforced = section_moment(a + moved, lattice)
    span = (hi - lo) * RISE
    s["bending_proxy"] = compliance(summary, lattice) - span**2 * span * (
        1 / ia - 1 / reinforced
    )
    # Use a positive conservative sum of independently loaded arms and stem.
    arm = s["radius_nm"] * np.pi / 2
    s["bending_proxy"] = float(
        len(s["fork_crossover_intervals"])
        * arm**3
        * (1 / ia + 1 / section_moment(b, lattice))
        + ((s["stem_end_bp"] - s["stem_start_bp"]) * RISE) ** 3 / reinforced
    )
    return s


def plan_optimized_branches(source, settings):
    if settings.branch_scaffold_size == "auto":
        return combine_budget_plans(
            source, settings, plan_optimized_branches, screened=False
        )
    from backend.core.curved_branches import _candidate
    from backend.core.branched_generator import branch_seed, route_branches
    from backend.core.generated_sweep import encode_sweep
    from backend.core.curved_rod_generator import physical_scaffold_nt

    particles, centers, distance = gold_particles(source, (3, 4))
    if (
        settings.mechanics != "legacy"
        or settings.pathing != "colocalized"
        or settings.particle_order
    ):
        raise ValueError(
            "Branched sizing chooses its own fork stations; rod path settings do not apply."
        )
    frames = _perimeter_frames(centers)
    if max(abs((centers - centers.mean(0)) @ frames[0][:, 1])) > 2:
        raise ValueError(
            "Curved branches currently require particle centers within 2 nm of one plane."
        )
    lattice = source.lattice_type
    budget = settings.branch_scaffold_size
    sections = section_library(lattice, settings.branch_sections)
    pairs = []
    for a in sections:
        for b in sections:
            try:
                pairs.append(adjoining_sections(a, b, lattice))
            except ValueError:
                pass
    trials, seen = [], set()
    rejected = dict(geometry=0, budget=0, routing=0)
    geometry_failure = "No compatible planar fork layout."
    for base in frames[:8]:
        for sign in (1, -1):
            frame = rotate_platform_frame(base, settings.roll_deg)
            frame[:, [0, 2]] *= sign
            local = (centers - centers.mean(0)) @ frame
            local[:, [0, 2]] -= (local[:, [0, 2]].min(0) + local[:, [0, 2]].max(0)) / 2
            for faces in pairs:
                for periods, tail in (
                    (p, t)
                    for p in range(2, 9)
                    for t in sorted({21, 28, 35, 42, *range(21, 43, 3)})
                ):
                    try:
                        s = _candidate(
                            local,
                            frame,
                            len(particles) == 4,
                            faces,
                            lattice,
                            periods,
                            tail,
                        )
                    except ValueError as exc:
                        geometry_failure = str(exc)
                        rejected["geometry"] += 1
                        continue
                    if s["nominal_scaffold_nt"] > budget + 64:
                        rejected["budget"] += 1
                        continue
                    key = (tuple(np.round(frame.ravel(), 5)), str(s["branch_tracks"]))
                    if key in seen:
                        continue
                    seen.add(key)
                    s["base_frame"] = rotate_platform_frame(
                        frame, -settings.roll_deg
                    ).tolist()
                    s["bending_proxy"] = compliance(s, lattice)
                    trials.append(s)
    # The stem can carry a separate collar; its section need not match either arm.
    collars = []
    for s in trials:
        if s["nominal_scaffold_nt"] + 6 * 42 > budget + 64:
            continue
        for cells in sorted(sections, key=len)[:3]:
            try:
                reinforced = reinforce_stem(s, cells, lattice)
                if reinforced["nominal_scaffold_nt"] <= budget + 64:
                    collars.append(reinforced)
            except ValueError:
                pass
    trials += collars
    trials.sort(key=lambda s: (s["bending_proxy"], -s["nominal_scaffold_nt"]))
    choices, attempted = [], 0
    route_seen, family_counts = set(), {}
    for s in trials:
        route_key = str(s["branch_tracks"])
        family = str(s["fork_faces"]), s["junction_length_bp"]
        if route_key in route_seen or family_counts.get(family, 0) >= 3:
            continue
        if attempted >= 64:
            break
        route_seen.add(route_key)
        attempted += 1
        try:
            routed, _ = route_branches(branch_seed(lattice, s), s)
            encoded = encode_sweep(routed)
            used = physical_scaffold_nt(encoded)
            if used > budget + 21:
                rejected["budget"] += 1
                continue
            if used > budget:
                encoded = trim_to_budget(encoded, budget)
                s["budget_trim_nt"] = used - budget
                used = physical_scaffold_nt(encoded)
            s.update(
                scaffold_used_nt=used,
                scaffold_size=budget,
                scaffold_name="M13mp18" if budget == 7249 else "p8064",
                unused_scaffold_nt=budget - used,
                scaffold_utilization=used / budget,
                sizing="optimized",
            )
            choices.append(RodCandidate(encoded, s))
            family_counts[family] = family_counts.get(family, 0) + 1
            # Preserve a few alternatives for buildability/attachment diagnostics.
            if len(choices) >= 24:
                break
        except ValueError:
            rejected["routing"] += 1
        if attempted >= 64:
            break
    if not choices and not trials:
        raise ValueError(
            "No curved branch layout fits this arrangement. " + geometry_failure
        )
    if not choices:
        raise ValueError(
            f"No routable curved branch sections fit the {budget}-base scaffold and bend limits. Tried {attempted} routes; increase particle spacing or change cross-sections."
        )
    # Prefer full-budget solutions, then minimize compliance; no ssDNA padding.
    choices.sort(
        key=lambda c: (
            c.summary["unused_scaffold_nt"] != 0,
            c.summary["bending_proxy"],
            c.summary["unused_scaffold_nt"],
        )
    )
    chosen = choices[0]
    hidden = {
        "branch_tracks",
        "branch_trunk",
        "branch_windows",
        "fork_paths",
        "fork_faces",
        "fork_stations",
        "cells",
        "base_frame",
        "center_local",
        "sizing_candidates",
    }

    def public(c):
        return {k: deepcopy(v) for k, v in c.summary.items() if k not in hidden}

    chosen.summary["sizing_candidates"] = [
        deepcopy(c.summary) for c in choices if c is not chosen
    ]
    return chosen, dict(
        shape="branched",
        branch_geometry="curved",
        lattice_type=lattice.value,
        particle_ids=[p.id for p in particles],
        centers_nm=centers.tolist(),
        center_distance_nm=distance,
        selected=public(chosen),
        alternatives=[public(c) for c in choices],
        settings=settings.model_dump(),
        search=dict(
            candidates=len(trials), routing_attempts=attempted, rejected=rejected
        ),
        reason="Lowest weak-axis beam compliance proxy among route-checked section and junction sizes in a bounded search.",
        qualification="Experimental planar forks. Cross-sections are independently sized; curvature and actual scaffold cost are checked. Discrete routing can leave unused bases; no unpaired filler is counted as reinforcement. CanDo validates the generated structure, not a global rigidity optimum.",
    )


def trim_to_budget(design, budget):
    """Fit a short scaffold nick gap, never change a crossover or add filler DNA.

    Run before autostapling. Trim at most one honeycomb period from a free
    scaffold end, keep a full period of anchoring domain, and remove matching
    staple precursor coverage so all remaining DNA can be paired/sequenceable.
    """
    from backend.core.curved_rod_generator import physical_scaffold_nt
    from backend.core.sequences import domain_bp_range
    from backend.core.models import StrandType

    excess = physical_scaffold_nt(design) - budget
    if excess == 0:
        return design
    if not 0 < excess <= 21:
        raise ValueError(
            "Exact scaffold fitting needs a terminal adjustment of at most 21 bases."
        )
    scaffolds = [s for s in design.scaffolds() if not s.is_reference]
    if len(scaffolds) != 1:
        raise ValueError("Budget fitting requires one scaffold.")
    scaffold = scaffolds[0]
    for end in (0, -1):
        d = scaffold.domains[end]
        indices = list(domain_bp_range(d))
        if end == -1:
            indices.reverse()
        marks = {m.bp_index: m.delta for m in design.find_helix(d.helix_id).loop_skips}
        removed, nt = [], 0
        for bp in indices[:-21]:
            removed.append(bp)
            nt += max(0, 1 + marks.get(bp, 0))
            if nt >= excess:
                break
        if nt != excess or any(
            half.helix_id == d.helix_id
            and min(abs(half.index - x) for x in removed) < 2
            for xo in design.crossovers
            for half in (xo.half_a, xo.half_b)
        ):
            continue
        remaining = [bp for bp in domain_bp_range(d) if bp not in removed]
        domains = list(scaffold.domains)
        domains[end] = d.model_copy(
            update=dict(start_bp=remaining[0], end_bp=remaining[-1])
        )
        strands = [scaffold.model_copy(update=dict(domains=domains, sequence=None))]
        for s in design.strands:
            if s.id == scaffold.id:
                continue
            if s.strand_type != StrandType.STAPLE or all(
                dom.helix_id != d.helix_id for dom in s.domains
            ):
                strands.append(s)
                continue
            if len(s.domains) != 1:
                raise ValueError("Budget fitting must precede staple routing.")
            dom = s.domains[0]
            pieces, current = [], []
            for bp in domain_bp_range(dom):
                if bp in removed:
                    if current:
                        pieces.append(current)
                        current = []
                else:
                    current.append(bp)
            if current:
                pieces.append(current)
            for i, piece in enumerate(pieces):
                new = dom.model_copy(update=dict(start_bp=piece[0], end_bp=piece[-1]))
                strands.append(
                    s.model_copy(
                        update=dict(
                            id=f"{s.id}_budget_{i}",
                            domains=[new],
                            routing_seed=[new],
                            sequence=None,
                        )
                    )
                )
        result = design.copy_with(strands=strands)
        if physical_scaffold_nt(result) != budget:
            raise ValueError(
                "Scaffold budget fitting did not preserve the measured nucleotide count."
            )
        return result
    raise ValueError(
        "No safe free scaffold end can absorb the small budget adjustment."
    )


def combine_budget_plans(source, settings, planner, *, screened):
    """Keep feasible budgets, prefer complete routes, then compare rigidity."""
    feasible, unavailable = [], []
    for size in (7249, 8064):
        try:
            feasible.append(
                planner(
                    source, settings.model_copy(update={"branch_scaffold_size": size})
                )
            )
        except ValueError as exc:
            unavailable.append(
                dict(scaffold_size=size, feasible=False, reason=str(exc))
            )
    if not feasible:
        raise ValueError(
            "Neither scaffold budget supports a validated branched design. "
            + "; ".join(x["reason"] for x in unavailable)
        )

    def score(item):
        s = item[0].summary
        rigidity = (
            s["sizing_validation"]["max_rmsf_nm"] if screened else s["bending_proxy"]
        )
        return s["unused_scaffold_nt"] != 0, rigidity, s["scaffold_size"]

    candidate, chosen = min(feasible, key=score)
    report = deepcopy(chosen)
    report["settings"] = settings.model_dump()
    report["alternatives"] = [
        deepcopy(r["selected"]) for c, r in feasible
    ] + unavailable
    report["search"] = dict(
        candidates=sum(r["search"]["candidates"] for c, r in feasible),
        structural_candidates=sum(
            r["search"].get("structural_candidates", 0) for c, r in feasible
        ),
        budgets={
            str(c.summary["scaffold_size"]): deepcopy(r["search"]) for c, r in feasible
        },
    )
    report["reason"] = (
        "Compared both scaffold lengths; prefer full utilization, then lower "
        + ("CanDo maximum core RMSF." if screened else "weak-axis compliance proxy.")
    )
    return candidate, report

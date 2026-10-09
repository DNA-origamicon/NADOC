"""Discrete, route-checked beam sizing for generated sweeps.

The path is held fixed. Search symmetric lattice layers and contiguous, period-
aligned reinforcement intervals; this is a bounded sizing search, not a global
shape/topology optimum. Every accepted candidate has one routed scaffold.
"""

from copy import deepcopy
import numpy as np

from backend.core.models import Design, LatticeType
from backend.core.sweep import SweepRequest, build_sweep
from backend.core.generated_sweep import encode_sweep, sweep_request
from backend.core.two_np_generator import RodCandidate, gold_particles, scaffold_nt
from backend.core.curved_rod_generator import physical_scaffold_nt, check_path_geometry
from backend.core.generator_mechanics import prepare_beam, robust_score


def resize_profile(design, profile):
    from backend.core.lattice import resize_strand_ends

    by_cell = {tuple(p["cell"]): p for p in profile}
    helices = {h.id: h for h in design.helices}
    entries = []
    for strand in design.strands:
        if len(strand.domains) != 1:
            raise ValueError("Section sizing must precede scaffold routing.")
        d = strand.domains[0]
        h = helices[d.helix_id]
        p = by_cell[h.grid_pos]
        lo, hi = p["start_bp"], p["end_bp"]
        forward = d.start_bp < d.end_bp
        for end, old, new in [
            ("5p", d.start_bp, lo if forward else hi),
            ("3p", d.end_bp, hi if forward else lo),
        ]:
            if new != old:
                entries.append(
                    dict(
                        strand_id=strand.id, helix_id=h.id, end=end, delta_bp=new - old
                    )
                )
    return resize_strand_ends(design, entries), entries


def routed_profile(lattice, request, profile):
    from backend.core.seamed_router import auto_scaffold_seamed

    design = build_sweep(Design(lattice_type=lattice), request)
    design, _ = resize_profile(design, profile)
    design, result = auto_scaffold_seamed(design)
    if (
        not result.valid
        or len([s for s in design.scaffolds() if not s.is_reference]) != 1
    ):
        raise ValueError("Reinforcement cannot be routed as one scaffold.")
    return encode_sweep(design)


def _optimize_budget(source, settings, candidate, report, budget):
    lattice = source.lattice_type
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    summary = deepcopy(candidate.summary)
    if not summary.get("sweep_request"):
        summary["sweep_request"] = sweep_request(
            lattice,
            summary["cells"],
            summary["nominal_length_bp"],
            summary["path"],
            summary["path_start_bp"],
            source=source,
        ).model_dump(mode="json")
    summary["path_feature"] = "sweep"
    cells = [tuple(c) for c in summary["sweep_request"]["cells"]]
    length = summary["nominal_length_bp"]
    profile = [dict(cell=c, start_bp=0, end_bp=length - 1) for c in cells]
    particles, centers, _ = gold_particles(source)
    from backend.core.two_np_generator import compatible_particle_handle

    handles = [compatible_particle_handle(source, p.id) for p in particles]
    lengths = [len(h[2].sequence) if h else settings.duplex_bp for h in handles]
    beam = prepare_beam(summary, centers, lattice, lengths)
    robust = settings.mechanics not in ("beam", "variable")
    baseline = robust_score(beam, profile, robust)
    current = baseline
    request = SweepRequest.model_validate(summary["sweep_request"])
    design = routed_profile(lattice, request, profile)
    used = max(physical_scaffold_nt(design), scaffold_nt(design))
    if used > budget:
        raise ValueError("The core exceeds this scaffold budget.")
    evaluated, routed, rejected = 1, 1, 0
    from backend.core.lattice import honeycomb_position, square_position

    position = (
        honeycomb_position if lattice == LatticeType.HONEYCOMB else square_position
    )
    minrow, maxrow = min(r for r, c in cells), max(r for r, c in cells)
    cols = sorted({c for r, c in cells})
    rectangular = len(cells) == (maxrow - minrow + 1) * len(cols)
    accepted = []
    if rectangular:
        # Honeycomb adds two rows on each side to close complete faces.
        # Symmetry avoids an unmodelled shear-center shift.
        width = 2 if lattice == LatticeType.HONEYCOMB else 1
        allowed_start, allowed_end = 0, length - 1
        for layer in range(1, 5):
            rows = list(
                range(minrow - width * layer, minrow - width * (layer - 1))
            ) + list(
                range(maxrow + 1 + width * (layer - 1), maxrow + 1 + width * layer)
            )
            added = [(r, c) for r in rows for c in cols]
            intervals = [(0, length - 1)]
            if settings.mechanics != "beam":
                # Sample a coarse lattice-aligned interval grid. Endpoints are discrete,
                # not hand-picked around the middle of any particular example.
                knots = sorted(
                    set(
                        [0, length]
                        + [int(x // period) * period for x in np.linspace(0, length, 9)]
                    )
                )
                intervals += [
                    (a, b - 1) for a in knots for b in knots if b - a >= 2 * period
                ]
            trials = []
            for a, b in sorted(set(intervals)):
                if a < allowed_start or b > allowed_end:
                    continue
                trial = profile + [dict(cell=c, start_bp=a, end_bp=b) for c in added]
                nominal = sum(p["end_bp"] - p["start_bp"] + 1 for p in trial)
                if nominal > budget:
                    continue
                score = robust_score(beam, trial, robust)
                evaluated += 1
                if score["score_nm2"] >= current["score_nm2"] * (1 - 1e-6):
                    continue
                trials.append((score["score_nm2"], nominal, a, b, trial, score))
            found = False
            for _, _, a, b, trial, score in sorted(trials, key=lambda t: (t[0], t[1])):
                req = request.model_copy(
                    update={"cells": [tuple(p["cell"]) for p in trial]}
                )
                try:
                    routed += 1
                    built = routed_profile(lattice, req, trial)
                    cost = max(physical_scaffold_nt(built), scaffold_nt(built))
                    if cost > budget:
                        raise ValueError("Physical scaffold budget exceeded.")
                    xy = np.asarray([position(*p["cell"]) for p in trial])
                    xy -= xy.mean(0)
                    radius = float(np.linalg.norm(xy, axis=1).max() + 1)
                    check_path_geometry(built, {h.id for h in built.helices}, radius)
                except ValueError:
                    rejected += 1
                    continue
                profile, current, design, request, used = trial, score, built, req, cost
                allowed_start, allowed_end = a, b
                accepted.append(dict(start_bp=a, end_bp=b, added_helices=len(added)))
                found = True
                break
            if not found:
                break
    # The final footprint, including reinforcement, must remain editable beside
    # all existing lattice cells. A parity-preserving shift changes no mechanics.
    from backend.core.lattice_occupancy import occupied_lattice_cells

    occupied = occupied_lattice_cells(source, "XY")
    if occupied.intersection(tuple(p["cell"]) for p in profile):
        shift = 2 * (
            (max(c for _, c in occupied) - min(p["cell"][1] for p in profile)) // 2 + 1
        )
        profile = [{**p, "cell": (p["cell"][0], p["cell"][1] + shift)} for p in profile]
        request = request.model_copy(update={"cells": [p["cell"] for p in profile]})
        design = routed_profile(lattice, request, profile)
    size = budget
    summary.update(
        cells=[p["cell"] for p in profile],
        section_profile=profile,
        helix_count=len(profile),
        scaffold_size=size,
        scaffold_name="M13mp18" if size == 7249 else "p8064",
        scaffold_used_nt=used,
        unused_scaffold_nt=size - used,
        sweep_request=request.model_dump(mode="json"),
        section=f"{len(cells)}-helix core + {len(profile) - len(cells)} reinforcement helices",
    )
    xy = np.asarray([position(*p["cell"]) for p in profile])
    xy -= xy.mean(0)
    summary["radius_nm"] = float(np.linalg.norm(xy, axis=1).max() + 1)
    mechanics = dict(
        level=settings.mechanics,
        attachment_duplex_bp=lengths,
        baseline=baseline,
        predicted=current,
        improvement_fraction=1 - current["score_nm2"] / baseline["score_nm2"],
        candidates_evaluated=evaluated,
        routing_attempts=routed,
        routing_rejections=rejected,
        layers=accepted,
        scope="Fixed planar path; greedy sizing of symmetric lattice layers with nested contiguous spans.",
        objective="Mean pair-distance variance + 0.5 × worst pair variance + 0.25 × aligned 3D displacement variance.",
        qualification=current["qualification"],
        validation_status="not_run",
    )
    summary["mechanics"] = mechanics
    public = {k: v for k, v in summary.items() if k not in ("path", "sweep_request")}
    report.update(
        selected=public,
        alternatives=[public],
        mechanics=mechanics,
        settings=settings.model_dump(),
        reason="Minimize model-predicted particle motion within a routed scaffold budget.",
        qualification=current["qualification"],
    )
    return RodCandidate(design, summary), report


def optimize_reinforcement(source, settings, candidate, report):
    """Compare both scaffold budgets, preferring 7249 for equal compliance."""
    results = []
    alternatives = []
    for budget in (7249, 8064):
        try:
            result = _optimize_budget(
                source, settings, candidate, deepcopy(report), budget
            )
        except ValueError as exc:
            alternatives.append(
                dict(scaffold_size=budget, feasible=False, reason=str(exc))
            )
            continue
        results.append(result)
        alternatives.append(result[1]["selected"])
    if not results:
        raise ValueError("No reinforced design fits either scaffold budget.")
    chosen, selected_report = min(
        results,
        key=lambda r: (
            round(r[1]["mechanics"]["predicted"]["score_nm2"], 8),
            r[0].summary["scaffold_size"],
        ),
    )
    selected_report["alternatives"] = alternatives
    return chosen, selected_report

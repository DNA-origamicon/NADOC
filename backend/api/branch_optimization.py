"""Isolated staple/CanDo screening for the curved branch sizing shortlist."""

from copy import deepcopy
from functools import lru_cache
import json

from backend.core.models import Design
from backend.core.two_np_generator import RodCandidate
from backend.core.platform_generator import plan_generated


@lru_cache(maxsize=32)
def _screen(lattice_value, serialized_summary):
    from backend.api import state
    from backend.api.headless_build import scratch_session, full_autostaple
    from backend.core.models import LatticeType
    from backend.core.branched_generator import branch_seed, route_branches
    from backend.core.branch_optimizer import trim_to_budget
    from backend.core.curved_branches import validate_fork_junctions
    from backend.core.generated_sweep import encode_sweep
    from backend.core.curved_rod_generator import physical_scaffold_nt
    from backend.core.generator_validation import check_generated_structure

    summary = json.loads(serialized_summary)
    lattice = LatticeType(lattice_value)
    budget = summary["scaffold_size"]
    routed, _ = route_branches(branch_seed(lattice, summary), summary)
    encoded = encode_sweep(routed)
    raw_used = physical_scaffold_nt(encoded)
    target = min(budget, raw_used)
    for _ in range(3):
        prepared = trim_to_budget(encoded, target) if raw_used > target else encoded
        with scratch_session(lattice):
            state.set_design(prepared)
            stapled = full_autostaple(summary["scaffold_name"]).model_copy(deep=True)
        stapled = encode_sweep(stapled)
        used = physical_scaffold_nt(stapled)
        if used > budget or (summary.get("budget_trim_nt") and used != budget):
            target -= used - budget
            if not 0 <= raw_used - target <= 21:
                raise ValueError(
                    "Stapled curvature cannot fit this scaffold with a safe end adjustment."
                )
            continue
        validate_fork_junctions(stapled)
        screen = check_generated_structure(stapled, [h.id for h in stapled.helices])
        summary.update(
            budget_trim_nt=raw_used - target,
            budget_pre_staple_nt=target,
            scaffold_used_nt=used,
            unused_scaffold_nt=budget - used,
            scaffold_utilization=used / budget,
            sizing_validation=screen,
        )
        return summary, prepared.model_dump_json()
    raise ValueError("Scaffold count did not converge after staple routing.")


@lru_cache(maxsize=8)
def _attachment_fit(serialized_source, serialized_summary, serialized_settings):
    """Exercise the same isolated, recorded construction used by Generate."""
    from backend.api.generated_history import build_recorded
    from backend.core.two_np_generator import GeneratorSettings

    source = Design.model_validate_json(serialized_source)
    summary = json.loads(serialized_summary)
    settings = GeneratorSettings.model_validate_json(serialized_settings)
    try:
        _, placement = build_recorded(source, RodCandidate(Design(), summary), settings)
        return dict(
            passed=True,
            connections=len(placement["connections"]),
            maximum_residual_nm=max(placement["attachment_residuals_nm"], default=0),
        )
    except ValueError as exc:
        return dict(passed=False, reason=str(exc))


def plan_for_generation(source, settings, *, use_sweeps=True):
    if settings.connectivity_plan is not None:
        from backend.api.connectivity_build import plan_connectivity
        return plan_connectivity(source, settings)
    if (
        settings.shape == "branched"
        and settings.branch_geometry == "curved"
        and settings.branch_sizing == "optimized"
        and settings.branch_scaffold_size == "auto"
    ):
        from backend.core.branch_optimizer import combine_budget_plans

        return combine_budget_plans(
            source,
            settings,
            lambda d, s: plan_for_generation(d, s, use_sweeps=use_sweeps),
            screened=True,
        )
    candidate, report = plan_generated(source, settings, use_sweeps=use_sweeps)
    if (
        settings.shape != "branched"
        or settings.branch_geometry != "curved"
        or settings.branch_sizing != "optimized"
    ):
        return candidate, report
    from backend.api.generation_progress import report as progress

    pool = [deepcopy(candidate.summary)] + deepcopy(
        candidate.summary.get("sizing_candidates", [])
    )
    for s in pool:
        s.pop("sizing_candidates", None)
    # Compare independent cross-sections, rather than spend the entire screen
    # budget on rotations or cap-length variants of the same cross-section.
    groups = {}
    for s in pool:
        key = (str(s["fork_faces"]), s["junction_length_bp"])
        groups.setdefault(key, []).append(s)
    shortlist = []
    for group in groups.values():
        group.sort(key=lambda s: (s["unused_scaffold_nt"], s["bending_proxy"]))
        shortlist.append(group[0])
    shortlist.sort(key=lambda s: (s["unused_scaffold_nt"] != 0, s["bending_proxy"]))
    accepted, errors = [], []
    attempted = 0
    for i, s in enumerate(shortlist[:8]):
        attempted += 1
        progress(
            "Compare branched cores",
            f"Staples and CanDo: candidate {i + 1}/{min(8, len(shortlist))}",
            0.04,
        )
        try:
            summary, serialized = _screen(
                source.lattice_type.value, json.dumps(s, sort_keys=True)
            )
            accepted.append(
                RodCandidate(Design.model_validate_json(serialized), deepcopy(summary))
            )
        except ValueError as exc:
            errors.append(str(exc))
        if len(accepted) >= 3:
            break
    if not accepted:
        raise ValueError(
            "No sized branch candidate passed staple junction and CanDo checks. "
            + (errors[-1] if errors else "No compatible sections.")
        )
    accepted.sort(
        key=lambda c: (
            c.summary["unused_scaffold_nt"] != 0,
            c.summary["sizing_validation"]["max_rmsf_nm"],
            c.summary["unused_scaffold_nt"],
        )
    )
    fit_errors = []
    chosen = None
    for possible in accepted:
        progress(
            "Check sized attachments",
            "Verify all connections at the fixed nanoparticle centers",
            0.06,
        )
        fit = _attachment_fit(
            source.model_dump_json(),
            json.dumps(possible.summary, sort_keys=True),
            settings.model_dump_json(),
        )
        possible.summary["attachment_fit"] = fit
        possible.summary["feasible"] = fit["passed"]
        if fit["passed"]:
            chosen = possible
            break
        fit_errors.append(
            dict(section=possible.summary["section"], reason=fit["reason"])
        )
    if chosen is None:
        raise ValueError(
            "Sized branch cores route, but their attachments cannot reach all fixed centers. "
            + fit_errors[-1]["reason"]
        )
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
    }
    public = lambda s: {k: deepcopy(v) for k, v in s.items() if k not in hidden}
    report.update(
        selected=public(chosen.summary),
        alternatives=[public(c.summary) for c in accepted],
        reason="Prefer full scaffold utilization, then the lowest CanDo maximum core RMSF among the screened section candidates.",
    )
    report["search"].update(
        structural_candidates=attempted,
        structural_rejected=errors,
        attachment_rejected=fit_errors,
    )
    return chosen, report

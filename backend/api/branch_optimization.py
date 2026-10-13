"""First-pass routing and attachment checks for curved and joined branch sizing."""

from copy import deepcopy
from functools import lru_cache
import json

from backend.core.models import Design
from backend.core.two_np_generator import RodCandidate
from backend.core.platform_generator import plan_generated


@lru_cache(maxsize=32)
def _screen(lattice_value, serialized_summary):
    from backend.api import state
    from backend.api.headless_build import (
        scratch_session,
        full_autostaple,
        full_sequence,
    )
    from backend.core.models import LatticeType
    from backend.core.branched_generator import branch_seed, route_branches
    from backend.core.branch_optimizer import trim_to_budget
    from backend.core.curved_branches import validate_fork_junctions
    from backend.core.generated_sweep import encode_sweep
    from backend.core.curved_rod_generator import physical_scaffold_nt
    from backend.core.validator import validate_design

    summary = json.loads(serialized_summary)
    lattice = LatticeType(lattice_value)
    budget = summary["scaffold_size"]
    joined = summary.get("branch_geometry") == "join" and summary.get("join_curved")
    seed = branch_seed(lattice, summary)
    if joined:
        from backend.core.joined_branches import route_joined_branches

        routed, _ = route_joined_branches(seed, summary)
    else:
        routed, _ = route_branches(seed, summary)
    encoded = encode_sweep(routed)
    raw_used = physical_scaffold_nt(encoded)
    target = summary.get("budget_pre_staple_nt", min(budget, raw_used))
    for _ in range(3):
        prepared = trim_to_budget(encoded, target) if raw_used > target else encoded
        with scratch_session(lattice):
            state.set_design(prepared)
            stapled = full_autostaple(summary["scaffold_name"]).model_copy(deep=True)
        stapled = encode_sweep(stapled)
        used = physical_scaffold_nt(stapled)
        if used > budget or (
            (joined or summary.get("budget_trim_nt")) and used != budget
        ):
            target -= used - budget
            if not 0 <= raw_used - target <= 21:
                raise ValueError(
                    "Stapled curvature cannot fit this scaffold with a safe end adjustment."
                )
            continue
        if joined:
            with scratch_session(lattice):
                state.set_design(stapled)
                stapled = full_sequence(summary["scaffold_name"]).model_copy(deep=True)
            if physical_scaffold_nt(stapled) != budget:
                raise ValueError(
                    "The joined core must use the entire selected scaffold."
                )
            if (
                sum(
                    len(s.sequence or "")
                    for s in stapled.scaffolds()
                    if not s.is_reference
                )
                != budget
            ):
                raise ValueError("The full joined scaffold sequence was not assigned.")
        else:
            validate_fork_junctions(stapled)
        validation = validate_design(stapled)
        scaffold_count = len([s for s in stapled.scaffolds() if not s.is_reference])
        if scaffold_count != 1 or not validation.passed:
            raise ValueError("The stapled core did not validate as one scaffold.")
        summary.update(
            budget_trim_nt=raw_used - target,
            budget_pre_staple_nt=target,
            scaffold_used_nt=used,
            unused_scaffold_nt=budget - used,
            scaffold_utilization=used / budget,
            sizing_validation=dict(
                status="passed", scaffold_count=scaffold_count, scaffold_used_nt=used
            ),
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
            screened=False,
        )
    candidate, report = plan_generated(source, settings, use_sweeps=use_sweeps)
    joined = (
        settings.shape == "branched"
        and settings.branch_geometry == "join"
        and candidate.summary.get("join_curved", False)
    )
    if not joined and (
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
    # Try geometric preferences in order, stopping at a feasible first pass.
    if joined:
        # Preserve both budgets in the bounded search. The core planner already
        # varies sections, safe end lengths, and multi-pair Join placements.
        groups = {}
        for s in pool:
            groups.setdefault(s["scaffold_size"], []).append(s)
        for group in groups.values():
            group.sort(key=lambda s: (s["bending_proxy"], s.get("connector_nt", 0)))
        shortlist = [
            group[index]
            for index in range(max(map(len, groups.values())))
            for group in groups.values()
            if index < len(group)
        ]
    else:
        groups = {}
        for s in pool:
            key = (str(s["fork_faces"]), s["junction_length_bp"])
            groups.setdefault(key, []).append(s)
        shortlist = []
        for group in groups.values():
            group.sort(key=lambda s: (s["unused_scaffold_nt"], s["bending_proxy"]))
            shortlist.append(group[0])
        shortlist.sort(key=lambda s: (s["unused_scaffold_nt"] != 0, s["bending_proxy"]))
    accepted, errors, fit_errors = [], [], []
    fitted_budgets = {}
    attempted = 0
    for i, s in enumerate(shortlist[:8]):
        if joined and s["scaffold_size"] in fitted_budgets:
            continue
        attempted += 1
        progress(
            "Compare branched cores",
            f"Check scaffold and staples: candidate {i + 1}/{min(8, len(shortlist))}",
            0.04,
        )
        try:
            summary, serialized = _screen(
                source.lattice_type.value, json.dumps(s, sort_keys=True)
            )
            possible = RodCandidate(
                Design.model_validate_json(serialized), deepcopy(summary)
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
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
            accepted.append(possible)
            if not joined:
                break
            fitted_budgets[possible.summary["scaffold_size"]] = possible
            continue
        fit_errors.append(
            dict(section=possible.summary["section"], reason=fit["reason"])
        )
    if not accepted:
        raise ValueError(
            "No sized branch candidate passed routing and fixed-center attachment checks. "
            + (
                fit_errors[-1]["reason"]
                if fit_errors
                else errors[-1] if errors else "No compatible sections."
            )
        )
    accepted.sort(
        key=lambda c: (
            c.summary["unused_scaffold_nt"] != 0,
            c.summary["bending_proxy"],
            c.summary.get("connector_nt", 0),
        )
    )
    chosen = accepted[0]
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
        "join_sections",
        "join_arms",
        "join_crossbars",
        "join_attachments",
        "sizing_candidates",
    }
    public = lambda s: {k: deepcopy(v) for k, v in s.items() if k not in hidden}
    report.update(
        selected=public(chosen.summary),
        alternatives=[public(c.summary) for c in accepted],
        reason="Prefer full scaffold utilization and the geometric bending estimate; stop at a routable design with reachable attachments for each scaffold length.",
    )
    report["search"].update(
        routing_candidates=attempted,
        routing_rejected=errors,
        attachment_rejected=fit_errors,
    )
    if joined:
        report["reason"] = (
            "Use every scaffold base and compare the first feasible design for each "
            "scaffold length by the geometric bending estimate; shorter Join connectors break ties."
        )
        requested_budgets = (
            (7249, 8064)
            if settings.branch_scaffold_size == "auto"
            else (int(settings.branch_scaffold_size),)
        )
        report["alternatives"] = [
            public(fitted_budgets[budget].summary)
            if budget in fitted_budgets
            else dict(
                scaffold_size=budget,
                feasible=False,
                reason="No candidate for this scaffold passed routing and fixed-center attachment checks.",
            )
            for budget in requested_budgets
        ]
    return chosen, report

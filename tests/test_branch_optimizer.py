"""Budget and mechanical sizing invariants for independently sized branches."""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.core.two_np_generator import GeneratorSettings
from backend.core.platform_generator import plan_generated
from backend.core.curved_rod_generator import physical_scaffold_nt
from backend.core.branch_optimizer import (
    section_library,
    trim_to_budget,
    reinforce_stem,
)
from backend.core.models import LatticeType
from backend.core.validator import validate_design
from tests.test_branched_generator import source


@pytest.mark.slow
@pytest.mark.parametrize("budget", [7249, 8064])
def test_sizing_respects_selected_physical_budget_and_preserves_source(budget):
    original = source()
    before = original.model_dump_json()
    candidate, report = plan_generated(
        original, GeneratorSettings(shape="branched", branch_scaffold_size=budget)
    )
    assert original.model_dump_json() == before
    assert candidate.summary["scaffold_size"] == budget
    assert (
        physical_scaffold_nt(candidate.design)
        == candidate.summary["scaffold_used_nt"]
        <= budget
    )
    assert report["selected"]["unused_scaffold_nt"] == budget - physical_scaffold_nt(
        candidate.design
    )
    assert candidate.summary["junction_helix_count"] > 12
    assert len(candidate.design.scaffolds()) == 1
    assert validate_design(candidate.design).passed
    assert report["search"]["candidates"] > 1


def test_independent_stem_reinforcement_has_its_own_constrained_route():
    from backend.core.branched_generator import branch_seed, route_branches

    c, _ = plan_generated(
        source(), GeneratorSettings(shape="branched", branch_sizing="fixed")
    )
    s = reinforce_stem(
        c.summary,
        [(r, c) for r in range(2) for c in range(1, 4)],
        LatticeType.HONEYCOMB,
    )
    seed = branch_seed(LatticeType.HONEYCOMB, s)
    routed, _ = route_branches(seed, s)
    assert s["trunk_helix_count"] == 12
    assert s["arm_helix_count"] == [6, 6]
    assert s["junction_helix_count_range"] == [12, 18]
    assert len(routed.scaffolds()) == 1
    assert len(routed.deformations) == 3
    assert len(routed.crossover_constraints) == 3
    assert routed.crossover_constraints[-1].allowed_bp_intervals == []
    assert validate_design(routed).passed


def test_safe_budget_trim_removes_precursor_bases_without_moving_crossovers():
    c, _ = plan_generated(
        source(), GeneratorSettings(shape="branched", branch_sizing="fixed")
    )
    design = c.design
    before = design.model_dump_json()
    used = physical_scaffold_nt(design)
    result = trim_to_budget(design, used - 1)
    assert design.model_dump_json() == before
    assert physical_scaffold_nt(result) == used - 1
    assert result.crossovers == design.crossovers
    assert result.deformations == design.deformations
    assert validate_design(result).passed
    with pytest.raises(ValueError, match="at most 21"):
        trim_to_budget(design, used - 22)


def test_custom_sections_are_bounded_and_not_silently_replaced():
    custom = [[(r, c) for r in range(4) for c in range(3)]]
    assert section_library(LatticeType.HONEYCOMB, custom) == custom
    for invalid in ([[]], [[(0, 0)] * 6], [[(0, 0), (0, 1), (1, 1), (1000000, 1)]]):
        with pytest.raises(ValueError):
            section_library(LatticeType.HONEYCOMB, invalid)
    with pytest.raises(ValidationError):
        GeneratorSettings(branch_scaffold_size=7500)


@pytest.mark.slow
def test_screened_i_uses_full_scaffold_and_closes_three_connections_per_particle():
    from backend.api.branch_optimization import plan_for_generation
    from backend.api.generated_history import build_recorded
    from backend.core.generator_validation import check_generated_structure

    original = source()
    settings = GeneratorSettings(
        shape="branched", branch_scaffold_size=7249, connections_per_particle=3
    )
    candidate, report = plan_for_generation(original, settings)
    generated, placement = build_recorded(original, candidate, settings)
    assert physical_scaffold_nt(generated) == 7249
    assert len(generated.scaffolds()[0].sequence) == 7249
    assert all(
        s.sequence and set(s.sequence) <= set("ACGT")
        for s in generated.strands
        if s.is_scaffold or s in generated.staples()
    )
    assert len(placement["connections"]) == 12
    assert max(placement["attachment_residuals_nm"]) < 0.02
    assert validate_design(generated).passed
    for p, q in zip(original.nanoparticles, generated.nanoparticles):
        np.testing.assert_array_equal(p.pose.to_array(), q.pose.to_array())
    assert report["search"]["structural_candidates"] > 1
    assert report["selected"]["sizing_validation"]["connected_components"] == 1
    screen = check_generated_structure(generated, placement["generated_helix_ids"])
    assert screen["status"] == "passed"
    assert screen["max_rmsf_nm"] < 3.66  # Original 6HB I fixture.


@pytest.mark.parametrize("better", [7249, 8064])
def test_auto_scaffold_compares_screened_rigidity_instead_of_preferring_size(better):
    from backend.core.branch_optimizer import combine_budget_plans
    from backend.core.two_np_generator import RodCandidate
    from backend.core.models import Design

    calls = []

    def planner(source, settings):
        size = settings.branch_scaffold_size
        calls.append(size)
        summary = dict(
            scaffold_size=size,
            unused_scaffold_nt=0,
            sizing_validation={"max_rmsf_nm": 2 if size == better else 4},
        )
        return RodCandidate(Design(), summary), dict(
            selected=summary, search={"candidates": 3, "structural_candidates": 2}
        )

    c, report = combine_budget_plans(
        source(), GeneratorSettings(shape="branched"), planner, screened=True
    )
    assert calls == [7249, 8064]
    assert c.summary["scaffold_size"] == better
    assert report["settings"]["branch_scaffold_size"] == "auto"
    assert len(report["alternatives"]) == 2
    assert report["search"]["structural_candidates"] == 4


def test_saved_branches_keep_their_original_geometry_and_sizing_mode():
    old = {"shape": "branched"}
    assert GeneratorSettings.from_history(old).branch_geometry == "lattice"
    assert old == {"shape": "branched"}
    assert (
        GeneratorSettings.from_history(
            {"shape": "branched", "branch_geometry": "curved"}
        ).branch_sizing
        == "fixed"
    )
    current = GeneratorSettings(shape="branched")
    assert GeneratorSettings.from_history(current.model_dump()) == current


def test_planning_adapter_preserves_the_history_replay_sweep_switch(monkeypatch):
    from backend.api import branch_optimization

    seen = []

    def planner(design, settings, *, use_sweeps):
        seen.append(use_sweeps)
        return None, {"shape": "auto"}

    monkeypatch.setattr(branch_optimization, "plan_generated", planner)
    branch_optimization.plan_for_generation(
        source(), GeneratorSettings(shape="auto"), use_sweeps=False
    )
    assert seen == [False]


def test_screened_sizing_rejects_unreachable_attachments_before_selection(monkeypatch):
    import json
    from copy import deepcopy
    from backend.api import branch_optimization as api
    from backend.core.models import Design
    from backend.core.two_np_generator import RodCandidate

    a = dict(
        section="stiff but unreachable",
        fork_faces=[[[0, 0]], [[0, 1]]],
        junction_length_bp=42,
        unused_scaffold_nt=0,
        bending_proxy=1,
        scaffold_size=7249,
    )
    b = {
        **a,
        "section": "reachable",
        "fork_faces": [[[1, 0]], [[1, 1]]],
        "bending_proxy": 2,
    }
    monkeypatch.setattr(
        api,
        "plan_generated",
        lambda *args, **kwargs: (
            RodCandidate(Design(), {**a, "sizing_candidates": [b]}),
            {"search": {"candidates": 2}},
        ),
    )

    def screen(lattice, serialized):
        s = json.loads(serialized)
        s["sizing_validation"] = {"max_rmsf_nm": s["bending_proxy"]}
        return s, Design().model_dump_json()

    monkeypatch.setattr(api, "_screen", screen)
    monkeypatch.setattr(
        api,
        "_attachment_fit",
        lambda src, summary, settings: {
            "passed": json.loads(summary)["section"] == "reachable",
            "reason": "fixed centers cannot be reached",
        },
    )
    original = source()
    before = deepcopy(original)
    c, report = api.plan_for_generation(
        original, GeneratorSettings(shape="branched", branch_scaffold_size=7249)
    )
    assert c.summary["section"] == "reachable"
    assert (
        report["search"]["attachment_rejected"][0]["section"] == "stiff but unreachable"
    )
    assert original == before

"""Fork compilation retains source recipes and matches native scientific output."""

from copy import deepcopy

import numpy as np
import pytest
from pydantic import ValidationError

from backend.api.generated_branch_steps import compile_fork_steps
from backend.api.part_branch_commands import (
    build as build_branch, compile_partition_params, compile_sparse_seed_params, route,
)
from backend.api.part_path_commands import build as build_path
from backend.core.branched_generator import route_branches
from backend.core.curved_branches import _candidate
from backend.core.models import Design, LatticeType
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_scope_references import remap_design
from backend.core.routing_identity import identity_scope
from tests.test_part_branch_commands import ROUTE, SEED, authored_native_seed, native_names


def fork_plan(reinforced=False):
    """Evaluate one retained construction choice, without planner search."""
    local = np.array([[-35, 0, -80], [35, 0, -80], [-35, 0, 80], [35, 0, 80]])
    summary = _candidate(local, np.eye(3), True)
    if reinforced:
        from backend.core.branch_optimizer import reinforce_stem
        summary = reinforce_stem(summary, [(r, c) for r in range(2) for c in range(1, 4)],
                                 LatticeType.HONEYCOMB)
    return summary


def construct(summary):
    seed = build_branch("branch-seed", Design(), compile_sparse_seed_params(summary, SEED))
    steps = compile_fork_steps(seed, summary)
    for kind, _, params, _ in steps:
        seed = build_path(kind, seed, params)
    return seed, steps


def normalize(actual, expected):
    normalized = native_names(actual, expected)
    return remap_design(normalized, {
        ("crossover_constraint", first.id): second.id
        for first, second in zip(normalized.crossover_constraints, expected.crossover_constraints)
    })


@pytest.mark.parametrize("reinforced", [False, True])
def test_compiled_fork_and_section_route_match_native_full_authoring(reinforced):
    summary = fork_plan(reinforced)
    expected_seed = authored_native_seed(LatticeType.HONEYCOMB, summary)
    original = deepcopy(summary)
    # Evaluated path outputs are not recipe inputs, even when present in a plan.
    summary["fork_paths"] = [{"poisoned": True}]
    actual, steps = construct(summary)
    assert len([step for step in steps if step[0] == "fork-path"]) == len(original["fork_faces"])
    assert all(step[2].get("constraint_id") for step in steps if step[0] == "crossover-constraint-create")
    normalized_seed = normalize(actual, expected_seed)
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized_seed, field) == getattr(expected_seed, field), field
    if reinforced:
        assert actual.crossover_constraints[-1].allowed_bp_intervals == []
    before = actual.model_dump_json()
    routed, report = route(actual, compile_partition_params(actual, summary, ROUTE))
    assert report.valid
    assert actual.model_dump_json() == before
    with identity_scope(ROUTE):
        expected, _ = route_branches(expected_seed, original)
    normalized = normalize(routed, expected)
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized, field) == getattr(expected, field), field


def test_compiler_requires_recipe_and_rejects_path_outputs_as_recipe_parameters():
    summary = fork_plan()
    seed = build_branch("branch-seed", Design(), compile_sparse_seed_params(summary, SEED))
    missing = deepcopy(summary)
    del missing["fork_path_recipes"]
    with pytest.raises(ValueError, match="numeric path recipe"):
        compile_fork_steps(seed, missing)
    summary["fork_path_recipes"][0]["point_frames"] = summary["fork_paths"][0]["point_frames"]
    with pytest.raises(ValidationError):
        compile_fork_steps(seed, summary)


@pytest.mark.parametrize("target", ["strand", "cluster", "preceding_path"])
def test_routing_rejects_deformation_ownership_it_cannot_preserve(target, monkeypatch):
    summary = fork_plan()
    design, _ = construct(summary)
    operation = design.deformations[0]
    if target == "strand":
        operation = operation.model_copy(update={"targets": [{"kind": "strand", "id": design.strands[0].id}]})
    elif target == "cluster":
        operation = operation.model_copy(update={"cluster_ids": ["selected-cluster"]})
    else:
        operation = operation.model_copy(update={"params": operation.params.model_copy(
            update={"preceding_op_ids": [design.deformations[1].id]})})
    design = design.copy_with(deformations=[operation, *design.deformations[1:]])
    monkeypatch.setattr("backend.core.branched_generator.route_branches", lambda *a: pytest.fail("not admitted"))
    with pytest.raises(ReferenceResolutionError, match="whole-helix deformations"):
        route(design, compile_partition_params(design, summary, ROUTE))

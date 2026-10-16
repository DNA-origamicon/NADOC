"""Joined path recipes regenerate exact native stations and indexed frames."""

from copy import deepcopy
from uuid import uuid5

import numpy as np
import pytest
from pydantic import ValidationError

from backend.api.part_joined_path_commands import JoinedPathRequest, build, compile_path_params
from backend.api.part_section_commands import build as build_section, compile_seed_params
from backend.core.join_crossbars import crossbar_summary
from backend.core.joined_branches import _extend_crossbar_tails, joined_seed
from backend.core.models import Design, LatticeType, Nanoparticle
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_scope_references import remap_design
from tests.test_join_crossbars import gentle_layout
from tests.test_joined_branches import _source
from tests.test_part_branch_commands import SEED


def selected_plan(lattice=LatticeType.HONEYCOMB, extras=0):
    source = _source(True).copy_with(lattice_type=lattice)
    centers = np.array([particle.pose.to_array()[:3, 3] for particle in source.nanoparticles])
    summary = crossbar_summary(source, centers, gentle_layout(centers), 12, 6)
    if extras:
        summary = _extend_crossbar_tails(summary, (extras, extras))
    return summary


def seeded(summary, lattice=LatticeType.HONEYCOMB):
    design = Design(lattice_type=lattice, nanoparticles=[Nanoparticle(id="unrelated", diameter_nm=10)])
    groups = []
    for index, spec in enumerate(summary["join_sections"]):
        prior = {helix.id for helix in design.helices}
        design = build_section("independent-section-seed", design,
                               compile_seed_params(spec, index, uuid5(SEED, str(index))))
        groups.append([helix.id for helix in design.helices if helix.id not in prior])
    return design, groups


@pytest.mark.parametrize("lattice", list(LatticeType))
@pytest.mark.parametrize("extras", [0, 13])
def test_numeric_recipes_match_native_indexed_paths_including_asymmetric_tails(lattice, extras):
    summary = selected_plan(lattice, extras)
    expected = joined_seed(lattice, summary)
    design, groups = seeded(summary, lattice)
    source = design.model_dump_json()
    for index, spec in enumerate(summary["join_sections"]):
        if "path_recipe" not in spec:
            continue
        assert spec["path_recipe"]["extra_left_bp"] == extras // 2
        assert spec["path_recipe"]["extra_right_bp"] == extras - extras // 2
        # A planner's evaluated output must not become an input to replay.
        spec["path"] = {"positions": "poisoned", "frames": "poisoned"}
        params = compile_path_params(spec, index, groups[index])
        before = design
        design = build("joined-crossbar-path", design, params)
        for field in AUTHORING_FIELDS - {"deformations"}:
            assert getattr(design, field) == getattr(before, field), field
    assert source != design.model_dump_json()
    native_ids = {helix.grid_pos: helix.id for helix in expected.helices}
    normalized = remap_design(design, {("helix", helix.id): native_ids[helix.grid_pos]
                                      for helix in design.helices})
    assert normalized.deformations == expected.deformations
    repeated = deepcopy(summary)
    assert all("positions" not in spec["path_recipe"] and "frames" not in spec["path_recipe"]
               for spec in repeated["join_sections"] if "path_recipe" in spec)


def test_missing_recipe_and_sampled_geometry_inputs_are_rejected():
    summary = selected_plan()
    _, groups = seeded(summary)
    spec = summary["join_sections"][1]
    old = {key: value for key, value in spec.items() if key != "path_recipe"}
    with pytest.raises(ValueError, match="numeric path recipe"):
        compile_path_params(old, 1, groups[1])
    params = compile_path_params(spec, 1, groups[1])
    params["bp_positions_nm"] = spec["path"]["positions"]
    with pytest.raises(ValidationError):
        JoinedPathRequest.model_validate(params)


def test_missing_target_and_path_budget_fail_before_native_evaluation(monkeypatch):
    summary = selected_plan()
    design, groups = seeded(summary)
    params = compile_path_params(summary["join_sections"][1], 1, groups[1])
    before = design.model_dump_json()
    monkeypatch.setattr("backend.core.join_crossbars.crossbar_path", lambda *a: pytest.fail("not admitted"))
    missing = {**params, "helix_ids": ["missing"]}
    with pytest.raises(ReferenceResolutionError) as caught:
        build("joined-crossbar-path", design, missing)
    assert caught.value.as_issue()["references"] == [{
        "kind": "helix", "identity": "missing", "parameter_path": ["helix_ids", 0],
    }]
    excessive = {**params, "endpoint_a_nm": [-9999.0, 0.0, 0.0]}
    with pytest.raises(ProofBudgetExceeded):
        build("joined-crossbar-path", design, excessive)
    assert design.model_dump_json() == before

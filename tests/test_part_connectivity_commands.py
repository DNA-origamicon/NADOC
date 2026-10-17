"""Connectivity path recipes reproduce native station/frame geometry exactly."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.api.generated_connectivity_steps import (
    compile_connectivity_route_params, compile_connectivity_steps,
)
from backend.api.part_branch_commands import build as branch_build, compile_sparse_seed_params, route
from backend.api.part_connectivity_commands import build
from backend.api.part_path_commands import build as path_build
from backend.core.branched_generator import route_branches
from backend.core.connectivity_generator import ConnectivityInput, compile_connectivity
from backend.core.models import Design, LatticeType, Mat4x4, Nanoparticle
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_scope_references import remap_design
from backend.core.routing_identity import identity_scope
from tests.test_part_branch_commands import ROUTE, SEED, authored_native_seed, native_names


def connectivity_plan(branches=True, *, two_faces=False):
    """Small in-memory reviewed tree; no generator search, molecular solve or disk fixture."""
    positions = ({
        "root": (0, 0, -80), "split": (0, 0, -20), "leaf-a": (-40, 0, 55),
        "split-b": (30, 0, 40), "leaf-b": (15, 0, 110), "leaf-c": (65, 0, 100),
    } if branches else {"root": (0, 0, -40), "leaf-a": (0, 0, 40)})
    links = ([('root', 'split'), ('split', 'leaf-a'), ('split', 'split-b'),
              ('split-b', 'leaf-b'), ('split-b', 'leaf-c')]
             if branches else [('root', 'leaf-a')])
    if two_faces:
        positions = {"root": (0, 0, -80), "split": (0, 0, -20),
                     "leaf-a": (-40, 0, 55), "leaf-b": (40, 0, 55)}
        links = [('root', 'split'), ('split', 'leaf-a'), ('split', 'leaf-b')]
    nodes, particles = [], []
    for identity, position in positions.items():
        is_particle = not identity.startswith("split")
        nodes.append({"id": identity, "position": position,
                      "kind": "particle" if is_particle else "split",
                      "particleId": identity if is_particle else None})
        if is_particle:
            pose = np.eye(4)
            pose[:3, 3] = position
            particles.append(Nanoparticle(id=identity, diameter_nm=4,
                                          pose=Mat4x4(values=pose.reshape(-1).tolist())))
    edges = []
    for index, (source, target) in enumerate(links):
        a, b = np.asarray(positions[source]), np.asarray(positions[target])
        edges.append({"id": f"edge-{index}", "source": source, "target": target,
                      "controlPoints": [a.tolist(), (a + (b - a) / 3).tolist(),
                                        (b - (b - a) / 3).tolist(), b.tolist()]})
    source = Design(nanoparticles=particles)
    request = ConnectivityInput(nodes=nodes, edges=edges)
    return source, compile_connectivity(source, request, junction_bp=28)


def construct(summary):
    seed = branch_build("branch-seed", Design(), compile_sparse_seed_params(summary, SEED))
    steps = compile_connectivity_steps(seed, summary)
    for kind, _, params, _ in steps:
        seed = (build if kind == "connectivity-path" else path_build)(kind, seed, params)
    return seed, steps


def normalize(actual, expected):
    normalized = native_names(actual, expected)
    return remap_design(normalized, {
        ("crossover_constraint", a.id): b.id
        for a, b in zip(normalized.crossover_constraints, expected.crossover_constraints)
    })


@pytest.mark.parametrize("branches", [False, True])
def test_endpoint_recipes_exactly_match_native_paths_and_shared_frames(branches):
    _, summary = connectivity_plan(branches)
    expected = authored_native_seed(LatticeType.HONEYCOMB, summary)
    summary["connectivity_paths"] = [{"poisoned": True}]
    actual, steps = construct(summary)
    normalized = normalize(actual, expected)
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized, field) == getattr(expected, field), field
    params = [step[2] for step in steps if step[0] == "connectivity-path"]
    assert all("bp_positions_nm" not in str(value) and "bp_frames" not in str(value) for value in params)
    if branches:
        assert actual.crossover_constraints[-1].allowed_bp_intervals == [] or any(
            rule.allowed_bp_intervals == [] for rule in actual.crossover_constraints)
        for child in params[1:]:
            assert child["parent_deformation_id"]
            assert child["shared_interval"][0] == child["start_bp"]


def test_explicit_parent_routing_matches_native_section_choices():
    _, summary = connectivity_plan()
    actual, _ = construct(summary)
    expected_seed = authored_native_seed(LatticeType.HONEYCOMB, summary)
    params = compile_connectivity_route_params(actual, summary, ROUTE)
    groups = {h.grid_pos: h.id for h in actual.helices}
    for window, junction in zip(params["windows"], sorted(summary["connectivity_junctions"],
                                                         key=lambda item: item["child"])):
        assert window["parent_helix_ids"] == [groups[tuple(cell)]
            for cell in summary["connectivity_faces"][junction["parent"]]]
    before = actual.model_dump_json()
    routed, report = route(actual, params)
    with identity_scope(ROUTE):
        expected, native_report = route_branches(expected_seed, summary)
    assert report.valid and native_report.valid
    assert actual.model_dump_json() == before
    normalized = normalize(routed, expected)
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized, field) == getattr(expected, field), field


def test_single_section_keeps_native_routing_choices_after_identity_remap():
    from backend.core.seamed_router import auto_scaffold_seamed

    _, summary = connectivity_plan(False)
    actual, _ = construct(summary)
    expected_seed = authored_native_seed(LatticeType.HONEYCOMB, summary)
    params = {"_proof_version": 1, "history_seed": str(ROUTE),
              "cluster_id": actual.cluster_transforms[0].id, "lattice_column_offset": 0}
    routed = build("auto-scaffold-connectivity-section", actual, params)
    with identity_scope(ROUTE):
        expected, report = auto_scaffold_seamed(expected_seed)
    assert report.valid
    normalized = normalize(routed, expected)
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized, field) == getattr(expected, field), field


def test_missing_parent_has_structured_reference_and_does_not_mutate_input():
    _, summary = connectivity_plan()
    seed = branch_build("branch-seed", Design(), compile_sparse_seed_params(summary, SEED))
    child = compile_connectivity_steps(seed, summary)[1][2]
    before = seed.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        build("connectivity-path", seed, child)
    assert list(caught.value.references) == [{"kind": "deformation",
        "identity": child["parent_deformation_id"], "parameter_path": ["parent_deformation_id"]}]
    assert seed.model_dump_json() == before


def test_path_preserves_all_unrelated_state_and_uses_stable_identity():
    source, summary = connectivity_plan(False)
    seed = branch_build("branch-seed", source, compile_sparse_seed_params(summary, SEED))
    params = compile_connectivity_steps(seed, summary)[0][2]
    before = seed.model_dump_json()
    first = build("connectivity-path", seed, params)
    second = build("connectivity-path", seed, deepcopy(params))
    assert first.deformations == second.deformations
    for field in AUTHORING_FIELDS - {"deformations"}:
        assert getattr(first, field) == getattr(seed, field), field
    assert seed.model_dump_json() == before
    changed = deepcopy(params)
    changed["segments"][-1]["end_nm"][0] += 1
    edited = build("connectivity-path", seed, changed)
    assert edited.deformations[-1].id == first.deformations[-1].id
    assert edited.deformations[-1].params != first.deformations[-1].params


@pytest.mark.parametrize("invalid", ["sampled", "rotation", "huge", "helix", "frame", "parent_extent"])
def test_invalid_inputs_fail_before_native_segment(invalid, monkeypatch):
    _, summary = connectivity_plan()
    seed = branch_build("branch-seed", Design(), compile_sparse_seed_params(summary, SEED))
    steps = compile_connectivity_steps(seed, summary)
    params = deepcopy(steps[0][2])
    error = (ValueError, ReferenceResolutionError, ProofBudgetExceeded)
    if invalid == "sampled":
        params["segments"][0]["bp_positions_nm"] = [[0, 0, 0]]
    elif invalid == "rotation":
        params["segments"][0]["start_rotation"][0][0] = 4
    elif invalid == "huge":
        params["segments"][0]["end_nm"] = [9000, 9000, 9000]
    elif invalid == "helix":
        params["helix_ids"][0] = "missing-helix"
    elif invalid == "frame":
        seed.helices[0].lattice_frame_id = "unsupported-frame"
    else:
        seed = build("connectivity-path", seed, params)
        params = deepcopy(steps[1][2])
        params["start_bp"] = 2000
        params["shared_interval"] = [2000, 2001]
    monkeypatch.setattr("backend.core.connectivity_generator.segment",
                        lambda *a, **kw: pytest.fail("invalid input reached native segment"))
    with pytest.raises(error):
        build("connectivity-path", seed, params)


def test_compiler_rejects_missing_recipe_and_output_fields_in_recipe():
    _, summary = connectivity_plan(False)
    seed = branch_build("branch-seed", Design(), compile_sparse_seed_params(summary, SEED))
    missing = deepcopy(summary)
    del missing["connectivity_path_recipes"]
    with pytest.raises(ValueError, match="retained segment recipe"):
        compile_connectivity_steps(seed, missing)
    summary["connectivity_path_recipes"][0]["segments"][0]["frames"] = []
    with pytest.raises(ValidationError):
        compile_connectivity_steps(seed, summary)


def test_materialize_ignores_candidate_design(monkeypatch):
    from backend.api.connectivity_build import materialize_connectivity

    source, summary = connectivity_plan(False)
    expected, _ = construct(summary)

    class Candidate:
        @property
        def design(self):
            pytest.fail("native connectivity must not inspect candidate geometry")

    candidate = Candidate()
    candidate.summary = summary
    observed = []

    def build_steps(actual_source, actual_summary, history):
        observed.append((actual_source, actual_summary, history))
        return expected

    monkeypatch.setattr("backend.api.generated_connectivity_steps.build_connectivity_steps", build_steps)
    result, placement = materialize_connectivity(source, candidate,
        SimpleNamespace(duplex_bp=18, connections_per_particle=1))
    assert result is expected
    assert observed == [(source, summary, None)]
    assert len(placement["blunt_end_ports"]) == 2
    assert placement["connections"] == []

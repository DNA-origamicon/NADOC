"""Reviewed Ψ tree goes through the same compiler and history as the UI."""

import json
from pathlib import Path
import numpy as np
import pytest
from backend.core.models import Design, StrandType
from backend.core.two_np_generator import GeneratorSettings
from backend.core.connectivity_generator import compile_connectivity
from backend.core.validator import validate_design
from backend.api.branch_optimization import plan_for_generation
from backend.api.generated_history import build_recorded

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    source = Design.model_validate_json(
        (ROOT / "tests/fixtures/connectivity/NP_gen_tests.nadoc").read_text()
    )
    plan = json.loads(
        (ROOT / "tests/fixtures/connectivity/NP_gen_tests-plan.json").read_text()
    )
    return source, GeneratorSettings(shape="branched", connectivity_plan=plan)


@pytest.mark.slow
def test_reviewed_psi_routes_staples_and_preserves_source(inputs):
    source, settings = inputs
    before = source.model_dump_json()
    candidate, report = plan_for_generation(source, settings)
    assert report["selected"]["sizing_validation"]["connected_components"] == 1
    assert (
        0
        < report["selected"]["scaffold_used_nt"]
        <= report["selected"]["scaffold_size"]
    )
    generated, placement = build_recorded(source, candidate, settings)
    assert validate_design(generated).passed
    assert (
        len([s for s in generated.strands if s.strand_type == StrandType.SCAFFOLD]) == 1
    )
    assert generated.nanoparticles == source.nanoparticles
    assert source.model_dump_json() == before
    assert len(placement["blunt_end_ports"]) == 4
    assert (
        placement["connections"] == []
    )  # Assumed attachments must not masquerade as applied bindings.
    assert len(generated.feature_log) > len(source.feature_log)
    from backend.core.curved_branches import validate_fork_junctions

    validate_fork_junctions(generated)
    # Indexed frames survive native save/load, including coincident junction stations.
    restored = Design.model_validate_json(generated.model_dump_json())
    assert restored.deformations == generated.deformations
    for j in candidate.summary["connectivity_junctions"]:
        a, b = [
            candidate.summary["connectivity_paths"][j[k]] for k in ("parent", "child")
        ]
        lo, hi = j["interval"]
        assert np.allclose(
            np.array(a["frames"])[lo - a["start"] : hi + 2 - a["start"]],
            np.array(b["frames"])[: hi - lo + 2],
        )


def test_stale_particle_and_invalid_tree_rejected(inputs):
    source, settings = inputs
    plan = settings.connectivity_plan.model_copy(deep=True)
    leaf = next(n for n in plan.nodes if n.kind == "particle")
    leaf.position = tuple(np.array(leaf.position) + [1, 0, 0])
    with pytest.raises(ValueError, match="positions changed"):
        compile_connectivity(source, plan)
    plan = settings.connectivity_plan.model_copy(deep=True)
    plan.edges.pop()
    with pytest.raises(ValueError, match="one tree"):
        compile_connectivity(source, plan)


@pytest.mark.slow
@pytest.mark.parametrize("name", ["rod", "triangle", "rectangle"])
def test_simple_arrangements_route(name, inputs):
    source, _ = inputs
    plan = json.loads(
        (ROOT / f"tests/fixtures/connectivity/{name}-plan.json").read_text()
    )
    particles = []
    for node in plan["nodes"]:
        if node["kind"] != "particle":
            continue
        particle = source.nanoparticles[0].model_copy(deep=True)
        particle.id = node["particleId"]
        values = list(particle.pose.values)
        values[3], values[7], values[11] = node["position"]
        particle.pose = particle.pose.model_copy(update={"values": values})
        particles.append(particle)
    source = Design(lattice_type=source.lattice_type, nanoparticles=particles)
    candidate, report = plan_for_generation(
        source, GeneratorSettings(shape="branched", connectivity_plan=plan)
    )
    assert len(candidate.design.scaffolds()) == 1
    assert validate_design(candidate.design).passed
    assert report["selected"]["sizing_validation"]["connected_components"] == 1

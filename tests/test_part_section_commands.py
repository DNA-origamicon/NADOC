"""Independent section contracts preserve native axes and bounded end turns."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api.part_section_commands import (
    SectionSeedRequest, build, compile_seed_params, route,
)
from backend.core.joined_branches import joined_seed
from backend.core.models import Design, LatticeType, Nanoparticle, StrandExtension
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_scope_references import remap_design
from backend.core.routing_identity import identity_scope
from backend.core.seamed_router import auto_scaffold_seamed_bounded
from tests.test_part_branch_commands import ROUTE, SEED, native_names


def sections(lattice):
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    return [{"id": f"branch_cluster_{i}", "cells": [[r, c] for r in range(2) for c in range(1, 4)],
             "length_bp": 4 * period, "position": [i * 1000, 0, 0], "rotation": [0, 0, 0, 1]}
            for i in range(2)]


def prepared(lattice):
    specs = sections(lattice)
    expected = joined_seed(lattice, {"join_sections": specs})
    design = Design(lattice_type=lattice)
    for i, spec in enumerate(specs):
        design = build("independent-section-seed", design, compile_seed_params(spec, i, SEED if i == 0 else ROUTE))
    # Grouping is an independent, existing overlay feature. Fixture membership
    # follows the native groups while each section retains its own construction.
    by_cell = {helix.grid_pos: helix.id for helix in design.helices}
    mapped = remap_design(expected, {("helix", helix.id): by_cell[helix.grid_pos] for helix in expected.helices})
    return design.copy_with(cluster_transforms=mapped.cluster_transforms), expected


@pytest.mark.parametrize("lattice", list(LatticeType))
def test_independent_seed_matches_native_axes_phase_and_address_separation(lattice):
    actual, expected = prepared(lattice)
    normalized = native_names(actual, expected)
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized, field) == getattr(expected, field), field
    # Separate addresses never move the canonical physical seed axes.
    assert [h.axis_start for h in actual.helices[:6]] == [h.axis_start for h in actual.helices[6:]]
    assert not ({h.grid_pos for h in actual.helices[:6]} & {h.grid_pos for h in actual.helices[6:]})


@pytest.mark.parametrize("lattice", list(LatticeType))
def test_bounded_section_route_matches_native_and_preserves_other_work(lattice):
    actual, expected = prepared(lattice)
    for design in (actual, expected):
        strand = design.strands[0]
        design.extensions = [StrandExtension(id="independent-extension", strand_id=strand.id,
                                            end="five_prime", sequence="TT")]
        design.nanoparticles = [Nanoparticle(id="independent-particle", diameter_nm=10)]
    before = actual.model_dump_json()
    params = {"cluster_id": "branch_cluster_1", "history_seed": str(ROUTE),
              "lattice_column_offset": 1000}
    routed, report = route(actual, params)
    assert report.valid
    assert actual.model_dump_json() == before
    expected_ids = set(expected.cluster_transforms[1].helix_ids)
    local = Design(lattice_type=lattice,
                   helices=[h for h in expected.helices if h.id in expected_ids],
                   strands=[s for s in expected.strands if all(d.helix_id in expected_ids for d in s.domains)])
    with identity_scope(ROUTE):
        native, native_report = auto_scaffold_seamed_bounded(local)
    assert native_report.valid
    expected = expected.copy_with(
        helices=[h for h in expected.helices if h.id not in expected_ids] + native.helices,
        strands=[s for s in expected.strands if all(d.helix_id not in expected_ids for d in s.domains)] + native.strands,
        crossovers=native.crossovers,
    )
    normalized = native_names(routed, expected)

    def crossover_key(item):
        return tuple(sorted((half.helix_id, half.index, half.strand) for half in (item.half_a, item.half_b)))

    native_crossovers = {crossover_key(item): item.id for item in expected.crossovers}
    normalized = remap_design(normalized, {("crossover", item.id): native_crossovers[crossover_key(item)]
                                         for item in normalized.crossovers})
    for field in AUTHORING_FIELDS - {"metadata"}:
        if field == "strands":
            assert {s.id: s for s in normalized.strands} == {s.id: s for s in expected.strands}
        else:
            assert getattr(normalized, field) == getattr(expected, field), field
    repeated = build("auto-scaffold-bounded-section", actual, params)
    for field in AUTHORING_FIELDS:
        assert getattr(repeated, field) == getattr(routed, field), field


def test_seed_compiler_ignores_evaluated_paths_and_stable_seed_owns_initial_cluster():
    spec = sections(LatticeType.HONEYCOMB)[0]
    params = compile_seed_params({**spec, "path": {"positions": [[1, 2, 3]]}}, 0, SEED)
    assert "path" not in params
    first = build("independent-section-seed", Design(), params)
    second = build("independent-section-seed", Design(), deepcopy(params))
    assert len(first.cluster_transforms) == 1
    assert first.cluster_transforms[0].is_default
    assert first.cluster_transforms == second.cluster_transforms


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(lattice_column_offset=1),
    lambda p: p["tracks"][0]["intervals"][0].update(lo_bp=1),
    lambda p: p.update(bp_positions_nm=[[0, 0, 0]]),
])
def test_section_seed_rejects_odd_addresses_sparse_coverage_and_geometry_inputs(mutation):
    params = compile_seed_params(sections(LatticeType.HONEYCOMB)[0], 0, SEED)
    mutation(params)
    with pytest.raises(ValidationError):
        SectionSeedRequest.model_validate(params)


def test_missing_cluster_and_external_strand_owner_fail_before_routing(monkeypatch):
    design, _ = prepared(LatticeType.HONEYCOMB)
    params = {"cluster_id": "missing", "history_seed": str(ROUTE), "lattice_column_offset": 0}
    monkeypatch.setattr("backend.core.seamed_router.auto_scaffold_seamed_bounded", lambda *a: pytest.fail("not admitted"))
    with pytest.raises(ReferenceResolutionError) as missing:
        route(design, params)
    assert missing.value.as_issue()["references"] == [{
        "kind": "cluster", "identity": "missing", "parameter_path": ["cluster_id"],
    }]
    params["cluster_id"] = "branch_cluster_0"
    design.extensions = [StrandExtension(strand_id=design.strands[0].id, end="five_prime", sequence="TT")]
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError, match="extensions"):
        route(design, params)
    assert design.model_dump_json() == before

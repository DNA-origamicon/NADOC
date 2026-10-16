"""Sparse branch inputs reproduce native construction without saved geometry."""

from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.api.part_branch_commands import (
    BranchSeedRequest,
    build,
    compile_route_params,
    compile_seed_params,
    route,
)
from backend.core.branched_generator import branch_seed, route_branches
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    BiotinDNA,
    ClusterRigidTransform,
    Design,
    DomainRef,
    FlexibleSegmentMark,
    LatticeType,
    Nanoparticle,
    NucleotideTransform,
    StrandExtension,
)
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_scope_references import remap_design
from backend.core.routing_identity import identity_scope

SEED = UUID("57ac5de0-ac1e-48e2-b1f3-a7c653e79a6b")
ROUTE = UUID("ff8b602f-2937-427e-b091-222e1a787952")


def authored_native_seed(lattice, summary):
    """Existing scientific builder plus the seed command's zero-pose metadata."""
    from backend.core.cluster_autodetect import with_default_cluster
    from backend.core.feature_identity import identity_factory

    return with_default_cluster(branch_seed(lattice, summary),
                                identity_factory=lambda kind, _members: identity_factory(SEED)(kind, []))


def plan(lattice=LatticeType.HONEYCOMB):
    """The established teeth footprint, as small authored construction inputs."""
    period = 21 if lattice == LatticeType.HONEYCOMB else 32
    trunk = [(r, c) for r in range(2) for c in range(4)]
    teeth = [(r, c) for r in range(2, 4) for c in range(4)]
    windows = [(start * period, (start + 2) * period - 1) for start in (0, 4, 8)]
    return {
        "branch_geometry": "lattice",
        "cells": [list(cell) for cell in trunk + teeth],
        "nominal_length_bp": 12 * period,
        "branch_tracks": [
            {"cell": list(cell), "intervals": [[0, 12 * period - 1]] if cell in trunk else windows}
            for cell in trunk + teeth
        ],
        "branch_trunk": [{"cell": list(cell), "interval": [0, 12 * period - 1]} for cell in trunk],
        "branch_windows": [[{"cell": list(cell), "interval": list(interval)} for cell in teeth]
                           for interval in windows],
    }


@pytest.fixture
def seeded():
    summary = plan()
    params = compile_seed_params(summary, SEED)
    design = build("branch-seed", Design(), params)
    return design, summary, params


def native_names(actual, expected):
    """Normalize only identities using independently resolved topology roles."""
    expected_cells = {helix.grid_pos: helix.id for helix in expected.helices}
    mapping = {("helix", helix.id): expected_cells[helix.grid_pos] for helix in actual.helices}
    normalized = remap_design(actual, mapping)

    def strand_key(strand):
        return strand.strand_type, tuple(
            (domain.helix_id, domain.start_bp, domain.end_bp, domain.direction)
            for domain in strand.domains
        )

    by_topology = {strand_key(strand): strand.id for strand in expected.strands}
    mapping = {("strand", strand.id): by_topology[strand_key(strand)] for strand in normalized.strands}
    return remap_design(normalized, mapping)


def test_seed_matches_native_and_retains_identity_after_interval_edit(seeded):
    design, summary, params = seeded
    expected = branch_seed(design.lattice_type, summary)
    normalized = native_names(design, expected)
    assert normalized.helices == expected.helices
    assert normalized.strands == expected.strands
    again = build("branch-seed", Design(), deepcopy(params))
    assert again.helices == design.helices
    assert again.strands == design.strands
    changed = deepcopy(params)
    changed["tracks"][-1]["intervals"][-1]["hi_bp"] -= 1
    edited = build("branch-seed", Design(), changed)
    assert [h.id for h in edited.helices] == [h.id for h in design.helices]
    assert [s.id for s in edited.strands] == [s.id for s in design.strands]
    assert edited.strands != design.strands


def test_seed_authors_stable_default_placement_before_any_response(seeded):
    design, _, params = seeded
    assert len(design.cluster_transforms) == 1
    cluster = design.cluster_transforms[0]
    assert cluster.is_default and cluster.auto_created
    assert cluster.helix_ids == [helix.id for helix in design.helices]
    assert cluster.translation == [0.0, 0.0, 0.0]
    assert cluster.rotation == [0.0, 0.0, 0.0, 1.0]
    changed = deepcopy(params)
    changed["tracks"].append({"key": "added", "cell": [100, 100],
                              "intervals": [{"key": "full", "lo_bp": 0, "hi_bp": 20}]})
    edited = build("branch-seed", Design(), changed)
    assert edited.cluster_transforms[0].id == cluster.id
    assert edited.cluster_transforms[0].helix_ids == [helix.id for helix in edited.helices]


def test_registered_later_connected_seed_inherits_existing_default_placement():
    from backend.api.part_proof_commands import execute
    from backend.core.part_history_contract import create_empty_part

    def inputs(seed, cell):
        return {"_proof_version": 1, "history_seed": str(seed), "nominal_length_bp": 21,
                "tracks": [{"key": "track", "cell": cell,
                            "intervals": [{"key": "full", "lo_bp": 0, "hi_bp": 20}]}]}

    first = execute("branch-seed", create_empty_part("Branches", "HONEYCOMB"), inputs(SEED, [0, 0]))
    second = execute("branch-seed", first, inputs(ROUTE, [0, 1]))
    assert len(second.cluster_transforms) == 1
    assert second.cluster_transforms[0].id == first.cluster_transforms[0].id
    assert set(second.cluster_transforms[0].helix_ids) == {helix.id for helix in second.helices}


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
def test_route_matches_native_full_authoring_and_is_deterministic(lattice):
    summary = plan(lattice)
    design = build("branch-seed", Design(lattice_type=lattice), compile_seed_params(summary, SEED))
    params = compile_route_params(design, summary, ROUTE)
    original = design.model_dump_json()
    actual, report = route(design, params)
    assert report.valid
    assert design.model_dump_json() == original
    native_seed = authored_native_seed(design.lattice_type, summary)
    with identity_scope(ROUTE):
        expected, expected_report = route_branches(native_seed, summary)
    assert expected_report.valid
    normalized = native_names(actual, expected)
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized, field) == getattr(expected, field), field
    repeated = build("auto-scaffold-sections", design, deepcopy(params))
    for field in AUTHORING_FIELDS:
        assert getattr(repeated, field) == getattr(actual, field), field
    assert len(actual.scaffolds()) == 1


def test_preserves_independent_state_and_id_like_text(seeded):
    from backend.core.cluster_autodetect import with_default_cluster

    standalone, summary, params = seeded
    source = with_default_cluster(make_bundle_design([(0, 0)], 21))
    source.metadata.name = standalone.helices[0].id
    source.extensions = [StrandExtension(strand_id=source.strands[0].id, end="five_prime", sequence="ACGT")]
    source.nanoparticles = [Nanoparticle(diameter_nm=10)]
    before = source.model_dump_json()
    combined = build("branch-seed", source, params)
    branch_staple = next(s for s in combined.staples() if s.id not in {s.id for s in source.strands})
    branch_staple.name = standalone.helices[0].id
    branch_staple.notes = "h_XY_0_0"
    result, _ = route(combined, compile_route_params(standalone, summary, ROUTE))
    assert source.model_dump_json() == before
    assert result.find_strand(branch_staple.id).name == branch_staple.name
    assert result.find_strand(branch_staple.id).notes == branch_staple.notes
    assert result.find_helix(source.helices[0].id) == source.helices[0]
    assert all(result.find_strand(s.id) == s for s in source.strands)
    for field in AUTHORING_FIELDS - {"helices", "strands", "crossovers"}:
        assert getattr(result, field) == getattr(source, field), field


@pytest.mark.parametrize("change", [
    lambda p: p.update(tracks=[]),
    lambda p: p["tracks"][0].update(intervals=[]),
    lambda p: p["tracks"].append(deepcopy(p["tracks"][0])),
    lambda p: p["tracks"][0]["intervals"][0].update(lo_bp=3, hi_bp=2),
    lambda p: p["tracks"][0]["intervals"][0].update(hi_bp=252),
    lambda p: p["tracks"][0]["intervals"].append({"key": "overlap", "lo_bp": 10, "hi_bp": 15}),
    lambda p: p.update(nominal_length_bp="252"),
    lambda p: p.update(design={"helices": []}),
    lambda p: p.update(bp_positions_nm=[[0, 0, 0]]),
])
def test_seed_rejects_empty_ambiguous_or_output_inputs(change):
    params = compile_seed_params(plan(), SEED)
    change(params)
    with pytest.raises(ValidationError):
        BranchSeedRequest.model_validate(params)


def test_large_seed_rejected_before_native_builder(monkeypatch):
    params = compile_seed_params(plan(), SEED)
    params["nominal_length_bp"] = 2016
    params["tracks"] = [
        {"key": str(i), "cell": [0, i], "intervals": [{"key": "full", "lo_bp": 0, "hi_bp": 2015}]}
        for i in range(128)
    ]
    monkeypatch.setattr("backend.core.branched_generator.branch_seed", lambda *a: pytest.fail("not admitted"))
    with pytest.raises(ProofBudgetExceeded):
        build("branch-seed", Design(), params)


def test_missing_reference_reports_the_repairable_parameter(seeded, monkeypatch):
    design, summary, _ = seeded
    params = compile_route_params(design, summary, ROUTE)
    params["windows"][0]["tracks"][0]["helix_id"] = "deleted-helix"
    monkeypatch.setattr("backend.core.branched_generator.route_branches", lambda *a: pytest.fail("not admitted"))
    with pytest.raises(ReferenceResolutionError) as caught:
        route(design, params)
    assert caught.value.as_issue()["code"] == "missing_reference"
    assert caught.value.as_issue()["references"] == [{
        "kind": "helix", "identity": "deleted-helix",
        "parameter_path": ["windows", 0, "tracks", 0, "helix_id"],
    }]


def test_partition_cannot_fill_missing_coverage_or_hide_duplicate_identity(seeded, monkeypatch):
    design, summary, _ = seeded
    params = compile_route_params(design, summary, ROUTE)
    monkeypatch.setattr("backend.core.branched_generator.route_branches", lambda *a: pytest.fail("not admitted"))
    changed = deepcopy(params)
    changed["windows"][0]["tracks"][0]["interval"][1] += 1
    with pytest.raises(ReferenceResolutionError, match="occupied scaffold"):
        route(design, changed)
    duplicate = design.copy_with(helices=[*design.helices, design.helices[0]])
    with pytest.raises(ReferenceResolutionError, match="duplicate helix"):
        route(duplicate, params)


@pytest.mark.parametrize("change", [
    lambda p: p.update(trunk=[]),
    lambda p: p.update(windows=[]),
    lambda p: p["windows"][0].update(tracks=[]),
    lambda p: p["windows"][1].update(key=p["windows"][0]["key"]),
    lambda p: p["trunk"].append(deepcopy(p["trunk"][0])),
    lambda p: p["windows"][0]["tracks"].append(deepcopy(p["trunk"][0])),
    lambda p: p.update(fullDesign={"helices": []}),
])
def test_invalid_or_opaque_partitions_are_rejected_before_routing(seeded, monkeypatch, change):
    design, summary, _ = seeded
    params = compile_route_params(design, summary, ROUTE)
    change(params)
    monkeypatch.setattr("backend.core.branched_generator.route_branches", lambda *a: pytest.fail("not admitted"))
    with pytest.raises(ValidationError):
        route(design, params)


def test_explicit_splice_intervals_and_parents_keep_native_route(seeded):
    design, summary, _ = seeded
    summary["branch_junction_intervals"] = [window[0]["interval"] for window in summary["branch_windows"]]
    params = compile_route_params(design, summary, ROUTE)
    for window, interval in zip(params["windows"], summary["branch_junction_intervals"]):
        assert window["splice_interval"] == interval
        window["parent_helix_ids"] = [track["helix_id"] for track in params["trunk"]]
    actual, report = route(design, params)
    assert report.valid
    with identity_scope(ROUTE):
        expected, _ = route_branches(authored_native_seed(design.lattice_type, summary), summary)
    normalized = native_names(actual, expected)
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized, field) == getattr(expected, field), field


@pytest.mark.parametrize("dependency", ["extension", "flexible", "nucleotide", "domain_pose", "nanoparticle"])
def test_routing_rejects_selected_external_dependencies(seeded, monkeypatch, dependency):
    design, summary, _ = seeded
    params = compile_route_params(design, summary, ROUTE)
    strand = design.strands[0]
    domain = strand.domains[0]
    if dependency == "extension":
        design.extensions = [StrandExtension(strand_id=strand.id, end="five_prime", sequence="ACGT")]
    elif dependency == "flexible":
        design.flexible_segment_marks = [FlexibleSegmentMark(strand_id=strand.id, domain_index=0,
            bp_index=domain.start_bp, direction=domain.direction)]
    elif dependency == "nucleotide":
        design.nucleotide_transforms = [NucleotideTransform(kind="base", helix_id=domain.helix_id,
            bp_index=domain.start_bp, direction=domain.direction)]
    elif dependency == "domain_pose":
        design.cluster_transforms = [ClusterRigidTransform(domain_ids=[DomainRef(strand_id=strand.id, domain_index=0)])]
    else:
        design.nanoparticles = [Nanoparticle(diameter_nm=10, biotin_dna=[
            BiotinDNA(strand_id=strand.id, helix_id=domain.helix_id, chain="A")])]
    before = design.model_dump_json()
    monkeypatch.setattr("backend.core.branched_generator.route_branches", lambda *a: pytest.fail("not admitted"))
    with pytest.raises(ReferenceResolutionError) as caught:
        route(design, params)
    assert caught.value.code == "invalid_selection"
    assert design.model_dump_json() == before


def test_whole_helix_grouping_is_preserved(seeded):
    design, summary, _ = seeded
    design.cluster_transforms = [ClusterRigidTransform(helix_ids=[h.id for h in design.helices])]
    result, _ = route(design, compile_route_params(design, summary, ROUTE))
    assert result.cluster_transforms == design.cluster_transforms


@pytest.mark.parametrize("family", ["curved", "join", "connectivity"])
def test_other_branch_families_are_not_certified(family):
    summary = {**plan(), "branch_geometry": family}
    with pytest.raises(ValueError, match="Only planar"):
        compile_seed_params(summary, SEED)
    with pytest.raises(ValueError, match="Only planar"):
        compile_route_params(Design(), summary, ROUTE)

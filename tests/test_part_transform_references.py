"""Native transform replay diagnoses targets without changing native placement.

Reference fixtures exercise the existing address predicate; they do not build
atoms or invent different occupancy rules for loops, domains, or extra bases.
"""

from copy import deepcopy

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_nucleotide_transforms import _target_exists
from backend.core.models import (
    ClusterOpLogEntry, ClusterRigidTransform, Crossover, DomainRef,
    ForcedLigation, HalfCrossover, LoopSkip, NucleotideTransform, OverhangSpec,
    SnapshotLogEntry,
)
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from tests.conftest import make_minimal_design


SEED = "2cfcc963-e662-4ca9-9322-522f4e54b99a"
POSE = {"pivot": [0.0, 0.0, 0.0], "translation": [1.0, 2.0, 3.0],
        "rotation": [0.0, 0.0, 0.0, 1.0]}


@pytest.fixture
def validate():
    # Lazy so the native fixture controls run before the new boundary exists.
    from backend.api.part_transform_references import validate_transform_references
    return validate_transform_references


@pytest.fixture
def part():
    return make_minimal_design(helix_length_bp=10)


def base(**patch):
    return {"kind": "base", "helix_id": "h0", "bp_index": 4,
            "direction": "FORWARD", "copy_k": 0, **deepcopy(POSE), **patch}


def extra(**patch):
    return {"kind": "extra_base", "crossover_id": "connector", "extra_base_k": 1,
            **deepcopy(POSE), **patch}


def cluster_params(**patch):
    return {"_proof_version": 1, "cluster_id": "selected", **deepcopy(POSE), **patch}


def placement_part(part, **patch):
    owner = ClusterRigidTransform(id="selected", helix_ids=["h0"], **patch)
    return part.copy_with(cluster_transforms=[owner])


def connector(family="crossover", *, identity="connector", sequence="AT"):
    if family == "crossover":
        return Crossover(id=identity, extra_bases=sequence,
            half_a=HalfCrossover(helix_id="h0", index=4, strand="FORWARD"),
            half_b=HalfCrossover(helix_id="h0", index=4, strand="REVERSE"))
    return ForcedLigation(id=identity, extra_bases=sequence,
        three_prime_helix_id="h0", three_prime_bp=9, three_prime_direction="FORWARD",
        five_prime_helix_id="h0", five_prime_bp=9, five_prime_direction="REVERSE")


def reference(kind, identity, path):
    return {"kind": kind, "identity": identity, "parameter_path": path}


def refused(validate, kind, part, params, expected, *, code="missing_reference"):
    source, inputs = part.model_dump_json(), deepcopy(params)
    with pytest.raises(ReferenceResolutionError) as caught:
        validate(kind, part, params)
    assert caught.value.code == code
    assert caught.value.as_issue()["references"] == [expected]
    assert part.model_dump_json() == source
    assert params == inputs


def test_native_fixture_control_includes_real_direction_copy_and_extra_semantics(part):
    part.helices[0].loop_skips = [LoopSkip(bp_index=4, delta=2), LoopSkip(bp_index=5, delta=-1)]
    part.crossovers = [connector()]
    assert _target_exists(part, NucleotideTransform(**base()))
    assert _target_exists(part, NucleotideTransform(**base(copy_k=2)))
    assert not _target_exists(part, NucleotideTransform(**base(copy_k=3)))
    # Preserve native copy-zero acceptance at a skip; this is not a new rule.
    assert _target_exists(part, NucleotideTransform(**base(bp_index=5)))
    assert _target_exists(part, NucleotideTransform(**extra()))
    assert not _target_exists(part, NucleotideTransform(**extra(extra_base_k=2)))


def test_successful_recipe_batch_checks_native_occupancy_only_once_per_target(part, monkeypatch):
    from backend.api import routes_nucleotide_transforms as native

    original = native._target_exists
    calls = []

    def observed(design, target):
        calls.append(target.target_key())
        return original(design, target)

    monkeypatch.setattr(native, "_target_exists", observed)
    execute("nucleotide-transform-batch", part, {"_proof_version": 1, "history_seed": SEED,
        "transforms": [base(), base(bp_index=5)]})
    assert calls == [("base", "h0", 4, "FORWARD", 0), ("base", "h0", 5, "FORWARD", 0)]


def test_failed_native_batch_adds_indexed_diagnostics_before_applying_any_pose(part, monkeypatch):
    from backend.api import routes_nucleotide_transforms as native

    monkeypatch.setattr(native, "_apply_transform_body", lambda *_a, **_k: pytest.fail("applied partial batch"))
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("nucleotide-transform-batch", part, {"_proof_version": 1, "history_seed": SEED,
            "transforms": [base(), base(bp_index=99)]})
    assert caught.value.as_issue()["references"] == [
        reference("nucleotide", "h0:99:FORWARD", ["transforms", 1, "bp_index"])]


@pytest.mark.parametrize("status,detail", [(404, "unrelated native failure"),
    (422, "Move/rotate a converted CPD as one rigid unit."),
    (404, "Missing nucleotide transform target")])
def test_unexplained_native_failures_are_not_relabelled_as_authored_reference_errors(part, monkeypatch, status, detail):
    from fastapi import HTTPException
    from backend.api import part_annotation_commands as native

    expected = HTTPException(status, detail=detail)

    def fail(*_args):
        raise expected

    monkeypatch.setattr(native, "build", fail)
    with pytest.raises(HTTPException) as caught:
        execute("nucleotide-transform", part, {"_proof_version": 1, "history_seed": SEED, **base()})
    assert caught.value is expected


@pytest.mark.parametrize("kind", ["cluster_op", "nucleotide-transform", "nucleotide-transform-batch",
                                  "nucleotide-transform-delete"])
def test_valid_native_execution_matches_existing_builder_and_preserves_inputs(part, kind):
    if kind == "cluster_op":
        from backend.core.part_overlay_commands import build
        part = placement_part(part)
        params = cluster_params()
    else:
        from backend.api.part_annotation_commands import build
        params = {"_proof_version": 1, "history_seed": SEED}
        if kind.endswith("-delete"):
            stored = NucleotideTransform(id="stored", **base())
            part = part.copy_with(nucleotide_transforms=[stored])
            params.update(transform_id="stored", target=list(stored.target_key()))
        elif kind.endswith("-batch"):
            params["transforms"] = [base(), base(bp_index=5, direction="REVERSE")]
        else:
            params.update(base())
    source, inputs = part.model_dump_json(), deepcopy(params)
    expected = build(kind, part, deepcopy(params))
    result = execute(kind, part, params)
    assert result.model_dump(mode="json") == expected.model_dump(mode="json")
    assert part.model_dump_json() == source
    assert params == inputs


@pytest.mark.parametrize("duplicate", [False, True])
def test_selected_placement_requires_one_exact_owner(validate, part, duplicate):
    part = placement_part(part)
    part.cluster_transforms = part.cluster_transforms * 2 if duplicate else []
    refused(validate, "cluster_op", part, cluster_params(),
            reference("cluster", "selected", ["cluster_id"]),
            code="invalid_selection" if duplicate else "missing_reference")


@pytest.mark.parametrize("patch, expected", [
    ({"helix_ids": ["h0", "gone"]}, reference("helix", "gone", ["helix_ids", 1])),
    ({"domain_ids": [{"strand_id": "scaf", "domain_index": 0},
                     {"strand_id": "gone", "domain_index": 0}]},
     reference("strand", "gone", ["domain_ids", 1, "strand_id"])),
    ({"domain_ids": [{"strand_id": "scaf", "domain_index": 0},
                     {"strand_id": "scaf", "domain_index": 8}]},
     reference("domain", "scaf:8", ["domain_ids", 1, "domain_index"])),
])
def test_explicit_membership_paths_are_actual_command_inputs(validate, part, patch, expected):
    refused(validate, "cluster_op", placement_part(part), cluster_params(**patch), expected)


@pytest.mark.parametrize("broken, expected", [
    ({"helix_ids": ["gone"]}, reference("helix", "gone", ["cluster_id"])),
    ({"domain_ids": [DomainRef(strand_id="gone", domain_index=0)]},
     reference("strand", "gone", ["cluster_id"])),
    ({"domain_ids": [DomainRef(strand_id="scaf", domain_index=8)]},
     reference("domain", "scaf:8", ["cluster_id"])),
    ({"parent_cluster_id": "gone"}, reference("cluster", "gone", ["cluster_id"])),
    ({"overhang_duplex_driver_id": "gone"}, reference("overhang", "gone", ["cluster_id"])),
])
def test_inherited_consumers_point_back_to_selected_owner(validate, part, broken, expected):
    part = placement_part(part)
    part.cluster_transforms[0] = part.cluster_transforms[0].model_copy(update=broken)
    refused(validate, "cluster_op", part, cluster_params(), expected)


@pytest.mark.parametrize("family, resource, identity", [
    ("helices", "helix", "h0"), ("strands", "strand", "scaf"),
    ("parent", "cluster", "parent"), ("driver", "overhang", "driver"),
])
def test_ambiguous_consumed_owner_is_not_first_match(validate, part, family, resource, identity):
    part = placement_part(part, domain_ids=[DomainRef(strand_id="scaf", domain_index=0)])
    selected = part.cluster_transforms[0]
    if family in {"helices", "strands"}:
        values = getattr(part, family)
        setattr(part, family, [*values, values[0].model_copy(deep=True)])
    elif family == "parent":
        selected.parent_cluster_id = "parent"
        parent = ClusterRigidTransform(id="parent", helix_ids=["h0"])
        part.cluster_transforms.extend([parent, parent.model_copy(deep=True)])
    else:
        selected.overhang_duplex_driver_id = "driver"
        driver = OverhangSpec(id="driver", helix_id="h0", strand_id="scaf")
        part.overhangs = [driver, driver.model_copy(deep=True)]
    refused(validate, "cluster_op", part, cluster_params(),
            reference(resource, identity, ["cluster_id"]), code="invalid_selection")


@pytest.mark.parametrize("cycle", ["self", "parent"])
def test_selected_parent_cycle_refuses_without_recursive_fallback(validate, part, cycle):
    part = placement_part(part)
    selected = part.cluster_transforms[0]
    selected.parent_cluster_id = "selected" if cycle == "self" else "parent"
    if cycle == "parent":
        part.cluster_transforms.append(ClusterRigidTransform(
            id="parent", helix_ids=["h0"], parent_cluster_id="selected"))
    refused(validate, "cluster_op", part, cluster_params(),
            reference("cluster", "selected", ["cluster_id"]), code="invalid_selection")


def test_unrelated_broken_owner_does_not_expand_selected_reference_scope(validate, part):
    part = placement_part(part)
    part.cluster_transforms.append(ClusterRigidTransform(
        id="unrelated", helix_ids=["gone"], parent_cluster_id="unrelated"))
    before = part.model_dump_json()
    validate("cluster_op", part, cluster_params())
    assert part.model_dump_json() == before


def test_explicit_replacement_members_override_stale_inherited_members(validate, part):
    part = placement_part(part)
    part.cluster_transforms[0].helix_ids = ["gone"]
    part.cluster_transforms[0].domain_ids = [DomainRef(strand_id="gone", domain_index=0)]
    params = cluster_params(helix_ids=["h0"], domain_ids=[])
    before = part.model_dump_json()
    validate("cluster_op", part, params)
    assert part.model_dump_json() == before


@pytest.mark.parametrize("batch", [False, True])
def test_missing_base_helix_has_exact_authored_path(validate, part, batch):
    body = base(helix_id="gone")
    params = {"transforms": [base(), body]} if batch else body
    path = ["transforms", 1, "helix_id"] if batch else ["helix_id"]
    refused(validate, "nucleotide-transform-batch" if batch else "nucleotide-transform",
            part, params, reference("helix", "gone", path))


@pytest.mark.parametrize("change, accepted", [
    ({}, True), ({"direction": "REVERSE"}, True),
    ({"bp_index": -1}, False), ({"bp_index": 10}, False),
    ({"copy_k": 1}, True), ({"copy_k": 2}, True), ({"copy_k": 3}, False),
    ({"bp_index": 5, "copy_k": 0}, True), ({"bp_index": 5, "copy_k": 1}, False),
])
def test_base_slots_follow_native_predicate_exactly(validate, part, change, accepted):
    part.helices[0].loop_skips = [LoopSkip(bp_index=4, delta=2), LoopSkip(bp_index=5, delta=-1)]
    body = base(**change)
    assert _target_exists(part, NucleotideTransform(**body)) is accepted
    if accepted:
        before, inputs = part.model_dump_json(), deepcopy(body)
        validate("nucleotide-transform", part, body)
        assert part.model_dump_json() == before and body == inputs
    else:
        key = f"h0:{body['bp_index']}:{body['direction']}"
        if body["copy_k"]:
            key += f":{body['copy_k']}"
        refused(validate, "nucleotide-transform", part, body,
                reference("nucleotide", key, ["bp_index"]))


def test_direction_requires_domain_occupancy_not_only_helix_span(validate, part):
    part.strands = [part.strands[0]]
    body = base(direction="REVERSE")
    assert not _target_exists(part, NucleotideTransform(**body))
    refused(validate, "nucleotide-transform-batch", part, {"transforms": [base(), body]},
            reference("nucleotide", "h0:4:REVERSE", ["transforms", 1, "bp_index"]))


def test_duplicate_helix_id_refuses_before_native_first_match(validate, part):
    part.helices.append(part.helices[0].model_copy(deep=True))
    refused(validate, "nucleotide-transform", part, base(),
            reference("helix", "h0", ["helix_id"]), code="invalid_selection")


@pytest.mark.parametrize("family", ["crossover", "forced_ligation"])
@pytest.mark.parametrize("slot", [0, 1, 2])
def test_extra_slots_follow_native_owner_sequence(validate, part, family, slot):
    setattr(part, "crossovers" if family == "crossover" else "forced_ligations", [connector(family)])
    body = extra(extra_base_k=slot)
    assert _target_exists(part, NucleotideTransform(**body)) is (slot < 2)
    if slot < 2:
        validate("nucleotide-transform", part, body)
    else:
        refused(validate, "nucleotide-transform", part, body,
                reference("nucleotide", "__xb__:connector:2", ["extra_base_k"]))


@pytest.mark.parametrize("ambiguous", [False, True])
def test_extra_owner_namespace_covers_crossovers_and_forced_ligations(validate, part, ambiguous):
    if ambiguous:
        part.crossovers = [connector()]
        part.forced_ligations = [connector("forced_ligation")]
    refused(validate, "nucleotide-transform-batch", part, {"transforms": [base(), extra()]},
            reference("crossover", "connector", ["transforms", 1, "crossover_id"]),
            code="invalid_selection" if ambiguous else "missing_reference")


@pytest.mark.parametrize("body, resource, identity, field", [
    (base(), "nucleotide", "h0:4:FORWARD", "helix_id"),
    (extra(), "nucleotide", "__xb__:connector:1", "crossover_id"),
])
def test_duplicate_batch_target_is_not_silently_composed_twice(validate, part, body, resource, identity, field):
    part.crossovers = [connector()]
    refused(validate, "nucleotide-transform-batch", part,
            {"transforms": [body, {**deepcopy(body), "compose": True}]},
            reference(resource, identity, ["transforms", 1, field]), code="invalid_selection")


@pytest.mark.parametrize("duplicate", [False, True])
def test_reset_requires_one_exact_saved_transform(validate, part, duplicate):
    if duplicate:
        saved = NucleotideTransform(id="saved", **base())
        part.nucleotide_transforms = [saved, saved.model_copy(deep=True)]
    refused(validate, "nucleotide-transform-delete", part, {"transform_id": "saved"},
            reference("nucleotide_transform", "saved", ["transform_id"]),
            code="invalid_selection" if duplicate else "missing_reference")


@pytest.mark.parametrize("kind, params, builder_module", [
    ("cluster_op", cluster_params(cluster_id="gone"), "backend.core.part_overlay_commands"),
    ("nucleotide-transform", {"_proof_version": 1, "history_seed": SEED, **base(helix_id="gone")},
     "backend.api.part_annotation_commands"),
    ("nucleotide-transform-batch", {"_proof_version": 1, "history_seed": SEED,
                                   "transforms": [base(), base(helix_id="gone")]},
     "backend.api.part_annotation_commands"),
    ("nucleotide-transform-delete", {"_proof_version": 1, "transform_id": "gone"},
     "backend.api.part_annotation_commands"),
])
def test_recipe_boundary_refuses_before_native_builder(kind, params, builder_module, part, monkeypatch):
    from importlib import import_module
    before = part.model_dump_json()
    monkeypatch.setattr(import_module(builder_module), "build",
                        lambda *_: pytest.fail("native builder ran before target admission"))
    with pytest.raises(ReferenceResolutionError):
        execute(kind, part, params)
    assert part.model_dump_json() == before


@pytest.mark.parametrize("kind", ["cluster_op", "nucleotide-transform-delete"])
def test_missing_target_cannot_be_certified_as_matching_empty_noop(kind):
    part = create_empty_part("Missing transform", "SQUARE")
    if kind == "cluster_op":
        row = ClusterOpLogEntry(id="missing", proof_version=1, cluster_id="gone", **deepcopy(POSE))
    else:
        row = SnapshotLogEntry(id="missing", op_kind=kind, label="Reset missing",
            params={"_proof_version": 1, "transform_id": "gone"}, evicted=True)
    part.feature_log = [row]
    before = part.model_dump_json()
    result = assess_part_history(part, execute=execute, dependencies=dependencies)
    assert result["status"] == "failed"
    assert result["checked_commands"] == 0
    assert result["native_editable"] is False
    assert part.model_dump_json() == before

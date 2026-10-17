"""Tests first for explicit, bounded NP application and restoration inputs.

The existing native route helper is the geometry oracle. Its random identity
and wall-clock defaults are injected only in that oracle; command parameters
contain choices and selectors, never its resulting geometry or saved topology.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import routes_nanoparticles as routes
from backend.api.part_proof_commands import PART_TOPOLOGY, dependencies, execute
from backend.api.part_recipe_edit import regenerate
from backend.core.feature_identity import identity_factory
from backend.core.models import ClusterRigidTransform, Design, LoopSkip, StrandExtension
from backend.core import nanoparticle_connections as application_kernel
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_dependencies import Resource
from backend.core.part_edit_identity import preserve_proof_identity
from tests.test_part_pending_np_connections import (
    CREATE, DELETE, PATCH, append, authored, creation,
    native_prefix as native_prefix, owner_inputs, pending_model, seed,
)


@pytest.fixture
def source(native_prefix):
    return native_prefix.model_copy(deep=True)


def version(design, identity="candidate"):
    return next(item for item in design.nanoparticle_connection_versions if item.id == identity)


def application_params(design, kind=CREATE, *, version_id="candidate", applied=True,
                       duplex_id="application-duplex", history_seed=None, **changes):
    current = next((item for item in design.nanoparticle_connection_versions if item.id == version_id), None)
    values = owner_inputs(design, version_id=version_id)
    if current is not None:
        values.update(strand_id=current.strand_id, overhang_id=current.overhang_id)
    values.update(changes)
    owner = next(item for item in design.nanoparticle_conjugations if item.id == values["conjugation_id"])
    handle = next(item for item in owner.surface_strands if item.strand_id == values["strand_id"])
    values.update(nanoparticle_application_version=1,
        handle_overhang_id=handle.overhang_id, history_seed=history_seed or seed(9201),
        prior_duplex_id=current.duplex_id if current is not None else None,
        conflict_version_ids=[item.id for item in design.nanoparticle_connection_versions
            if item.id != version_id and (item.strand_id == values["strand_id"]
                                         or item.overhang_id == values["overhang_id"])])
    if kind == CREATE:
        values = {**creation(design), **values, "applied": applied}
    elif kind == PATCH:
        values["applied"] = applied
    if kind != DELETE and applied:
        values.update(duplex_id=duplex_id, duplex_created_at=15.0)
    return values


def command_module():
    # Keep the tests-first target collectable before the new adapter exists.
    from backend.api import part_np_application_commands
    return part_np_application_commands


def oracle(design, kind, values, monkeypatch):
    candidate = design
    if kind == CREATE:
        candidate = design.copy_with(nanoparticle_connection_versions=[
            *design.nanoparticle_connection_versions, pending_model(design, **{
                key: values[key] for key in ("version_id", "name", "created_at", "strand_id",
                                             "overhang_id", "direct_variant")})])
    original_duplex, original_relocate = application_kernel.Duplex, application_kernel.relocate_duplex
    with monkeypatch.context() as scoped:
        if kind != DELETE and values["applied"]:
            scoped.setattr(application_kernel, "Duplex", lambda **kw: original_duplex(
                id=values["duplex_id"], created_at=values["duplex_created_at"], **kw))
            scoped.setattr(application_kernel, "relocate_duplex", lambda source, duplex: original_relocate(
                source, duplex, identity_seed=values["history_seed"]))
        candidate = routes._set_np_version_applied(
            candidate, values["version_id"], kind != DELETE and values["applied"])
    if kind == DELETE:
        candidate = candidate.copy_with(nanoparticle_connection_versions=[
            item for item in candidate.nanoparticle_connection_versions if item.id != values["version_id"]])
    return candidate


@pytest.mark.parametrize("attach_end,variant", [("5p", "end-to-root"), ("3p", "root-to-root")])
def test_explicit_application_matches_native_math_and_stable_identity(source, monkeypatch, attach_end, variant):
    log = [*source.feature_log[:-1], source.feature_log[-1].model_copy(update={
        "params": {**source.feature_log[-1].params, "attach_end": attach_end}})]
    source = regenerate(source, log, lambda: None)
    values = application_params(source, direct_variant=variant)
    original = source.model_dump_json()
    expected = oracle(source, CREATE, values, monkeypatch)
    actual = command_module().build(CREATE, source, values)
    assert authored(actual) == authored(expected)
    assert authored(command_module().build(CREATE, source, deepcopy(values))) == authored(actual)
    assert source.model_dump_json() == original
    current = version(actual)
    assert current.applied and current.duplex_id == values["duplex_id"]
    duplex = next(item for item in actual.duplexes if item.id == current.duplex_id)
    assert duplex.created_at == values["duplex_created_at"] and duplex.prior_driven_topology
    expected_cluster = identity_factory(values["history_seed"])("duplex-cluster", [duplex.id])
    assert any(item.id == expected_cluster for item in actual.cluster_transforms)
    assert authored(Design.model_validate_json(actual.model_dump_json())) == authored(actual)


@pytest.mark.parametrize("operation", ["apply-pending", "unapply", "delete-applied"])
def test_each_native_lifecycle_transition_matches_existing_helper(source, monkeypatch, operation):
    commands = command_module()
    if operation == "apply-pending":
        source = append(source, CREATE, creation(source), "pending")
        kind, values = PATCH, application_params(source, PATCH)
    else:
        source = commands.build(CREATE, source, application_params(source))
        kind = DELETE if operation == "delete-applied" else PATCH
        values = application_params(source, kind, applied=False, history_seed=seed(9202))
    original = source.model_dump_json()
    actual = commands.build(kind, source, values)
    assert authored(actual) == authored(oracle(source, kind, values, monkeypatch))
    assert source.model_dump_json() == original
    if operation != "apply-pending":
        assert not actual.duplexes
        assert not any(item.overhang_duplex_driver_id for item in actual.cluster_transforms)
        assert all(item.bound_overhang_id is None for item in actual.nanoparticle_conjugations[0].surface_strands)
        assert all(item.constraint_root_nm is None and item.constraint_radius_nm is None
                   for item in actual.nanoparticle_connection_versions)


def test_exact_conflict_selector_switches_one_applied_owner_and_restores_old_handle(source, monkeypatch):
    commands = command_module()
    second_strand = source.nanoparticle_conjugations[0].surface_strands[1].strand_id
    source = append(source, CREATE, creation(source, version_id="alternate", strand_id=second_strand), "alternate")
    source = commands.build(CREATE, source, application_params(source))
    values = application_params(source, PATCH, version_id="alternate", duplex_id="alternate-duplex",
                                history_seed=seed(9203))
    assert values["conflict_version_ids"] == ["candidate"]
    actual = commands.build(PATCH, source, values)
    assert authored(actual) == authored(oracle(source, PATCH, values, monkeypatch))
    assert version(actual, "alternate").applied
    previous = version(actual)
    assert not previous.applied and previous.duplex_id is None
    assert previous.constraint_root_nm is None and previous.constraint_radius_nm is None


@pytest.mark.parametrize("kind", [CREATE, PATCH, DELETE])
def test_registered_application_dependencies_expose_typed_selectors_and_outputs(source, kind):
    values = application_params(source, kind, applied=kind != DELETE)
    values["conflict_version_ids"] = ["other-version"]
    if kind != CREATE:
        values["prior_duplex_id"] = "previous-duplex"
    contract = dependencies(kind, values)
    assert contract.known and contract.barrier and not contract.imported_sources
    assert {PART_TOPOLOGY, Resource("nanoparticle", "gold"), Resource("nanoparticle_conjugation", "gold-graft"),
            Resource("strand", values["strand_id"]), Resource("overhang", values["overhang_id"]),
            Resource("overhang", values["handle_overhang_id"]),
            Resource("nanoparticle_connection_version", "other-version")} <= contract.reads
    assert {PART_TOPOLOGY, Resource("nanoparticle_connection_version", "candidate")} <= contract.writes
    if kind != CREATE:
        assert Resource("nanoparticle_connection_version", "candidate") in contract.reads
        assert Resource("duplex", "previous-duplex") in contract.reads
    if kind != DELETE:
        assert Resource("duplex", values["duplex_id"]) in contract.writes


@pytest.mark.parametrize("field,value", [
    ("nanoparticle_application_version", True), ("nanoparticle_application_version", 2),
    ("nanoparticle_connection_version", True), ("history_seed", "not-a-UUID"),
    ("duplex_id", ""), ("duplex_created_at", float("inf")), ("applied", 1),
    ("conflict_version_ids", ["duplicate", "duplicate"]),
    ("conflict_version_ids", [str(index) for index in range(129)]),
    ("prior_driven_topology", {}), ("positions", [[0., 0., 0.]]),
])
def test_application_input_schema_does_not_accept_forged_or_sampled_inputs(source, field, value):
    values = {**application_params(source), field: value}
    with pytest.raises(ValidationError):
        command_module().parse_command(CREATE, values)
    assert not dependencies(CREATE, values).known


@pytest.mark.parametrize("field", ["nanoparticle_application_version", "handle_overhang_id", "history_seed",
                                    "prior_duplex_id", "conflict_version_ids", "duplex_id", "duplex_created_at"])
def test_application_identity_and_selection_slots_cannot_be_invented_when_absent(source, field):
    values = application_params(source)
    values.pop(field)
    assert not dependencies(CREATE, values).known
    with pytest.raises((ValidationError, NotImplementedError)):
        execute(CREATE, source, values)


@pytest.mark.parametrize("field,kind", [("nanoparticle_id", "nanoparticle"),
    ("conjugation_id", "nanoparticle_conjugation"), ("strand_id", "strand"),
    ("overhang_id", "overhang"), ("handle_overhang_id", "overhang")])
def test_missing_selected_resources_report_the_authored_parameter_before_geometry(source, monkeypatch, field, kind):
    from backend.core import design_geometry
    values = {**application_params(source), field: "missing"}
    monkeypatch.setattr(design_geometry, "fitting_geometry", lambda *_a, **_kw: pytest.fail("Missing resource reached geometry"))
    original = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        command_module().build(CREATE, source, values)
    assert error.value.code == "missing_reference"
    assert {"kind": kind, "identity": "missing", "parameter_path": [field]} in error.value.references
    assert source.model_dump_json() == original


@pytest.mark.parametrize("selected", [[], ["alternate", "missing"]])
def test_conflicts_are_an_exact_selector_not_a_hint(source, selected):
    source = append(source, CREATE, creation(source, version_id="alternate"), "alternate")
    values = {**application_params(source), "conflict_version_ids": selected}
    original = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        command_module().build(CREATE, source, values)
    assert any(ref["parameter_path"][0] == "conflict_version_ids" for ref in error.value.references)
    assert source.model_dump_json() == original


@pytest.mark.parametrize("damage", ["reference-count", "nucleotide-span", "loop-work", "extension"])
def test_source_and_emitted_work_are_bounded_before_any_geometry(source, monkeypatch, damage):
    from backend.core import design_geometry
    values = application_params(source)
    if damage == "reference-count":
        source.helices = [source.helices[0]] * 10_001
    elif damage == "nucleotide-span":
        source.helices[0] = source.helices[0].model_copy(update={"length_bp": 1_000_000})
    elif damage == "loop-work":
        source.helices[0] = source.helices[0].model_copy(update={
            "loop_skips": [LoopSkip(bp_index=0, delta=1_000_000)]})
    else:
        source.extensions = [StrandExtension(id="external", strand_id=values["strand_id"],
                                            end="five_prime", sequence="A")]
    monkeypatch.setattr(design_geometry, "fitting_geometry", lambda *_a, **_kw: pytest.fail("Oversize/unsupported source reached geometry"))
    with pytest.raises(CommandContractError):
        command_module().build(CREATE, source, values)


@pytest.mark.parametrize("damage", ["unknown-snapshot", "foreign-restored-helix", "dependent-child-cluster"])
def test_restoration_has_exact_saved_ownership_and_protects_live_consumers(source, damage):
    commands = command_module()
    applied = commands.build(CREATE, source, application_params(source))
    duplex = applied.duplexes[0]
    if damage == "unknown-snapshot":
        duplex.prior_driven_topology = {**duplex.prior_driven_topology, "opaque_geometry": []}
    elif damage == "foreign-restored-helix":
        saved = duplex.prior_driven_topology["driven_helix"]
        foreign = source.find_helix(saved["id"]).model_copy(deep=True)
        foreign.axis_start.x += 10.0
        applied.helices.append(foreign)
    else:
        child = next(item for item in applied.cluster_transforms if item.overhang_duplex_driver_id)
        applied.cluster_transforms.append(ClusterRigidTransform(id="outside-consumer", parent_cluster_id=child.id))
    original = applied.model_dump_json()
    with pytest.raises((CommandContractError, NotImplementedError)):
        commands.build(PATCH, applied, application_params(applied, PATCH, applied=False))
    assert applied.model_dump_json() == original


@pytest.mark.parametrize("kind", [CREATE, PATCH, DELETE])
def test_editing_preserves_only_existing_outputs_and_contract_identity(source, kind):
    previous = application_params(source, kind)
    updated = {**previous, "nanoparticle_application_version": 2, "history_seed": seed(9999),
        "handle_overhang_id": "other-handle", "overhang_id": "other-target", "version_id": "other-version"}
    if "duplex_id" in previous:
        updated.update(duplex_id="forged-output", duplex_created_at=99.0)
    result = preserve_proof_identity(previous, updated, kind=kind)
    for field in ("nanoparticle_application_version", "history_seed", "duplex_id", "duplex_created_at"):
        if field in previous:
            assert result[field] == previous[field]
    assert result["handle_overhang_id"] == "other-handle" and result["overhang_id"] == "other-target"
    assert result["version_id"] == ("candidate" if kind == CREATE else "other-version")
    assert preserve_proof_identity({}, {"name": "Edited"}, kind=kind) == {"name": "Edited"}


def test_application_marker_never_promotes_an_old_sparse_applied_receipt(source):
    sparse = {"nanoparticle_id": "gold", "version_id": "candidate", "applied": True}
    assert not dependencies(CREATE, sparse).known
    assert not dependencies(CREATE, {**sparse, "nanoparticle_application_version": 1}).known
    assert dependencies(CREATE, creation(source)).known


@pytest.mark.parametrize("handle_length", [8, 16])
def test_unequal_lengths_preserve_every_handle_base_or_refuse_before_fitting(source, monkeypatch, handle_length):
    from backend.core import design_geometry

    log = [*source.feature_log[:-1], source.feature_log[-1].model_copy(update={
        "params": {**source.feature_log[-1].params, "sequence": "ACGT" * (handle_length // 4)}})]
    source = regenerate(source, log, lambda: None)
    values = application_params(source)
    if handle_length > 12:
        monkeypatch.setattr(design_geometry, "fitting_geometry",
                            lambda *_a, **_kw: pytest.fail("Handle shortening reached geometry"))
        original = source.model_dump_json()
        with pytest.raises(ReferenceResolutionError) as error:
            command_module().build(CREATE, source, values)
        assert error.value.code == "invalid_selection"
        assert error.value.references == ({"kind": "overhang", "identity": values["overhang_id"],
                                           "parameter_path": ["overhang_id"]},)
        assert source.model_dump_json() == original
    else:
        actual = command_module().build(CREATE, source, values)
        assert authored(actual) == authored(oracle(source, CREATE, values, monkeypatch))
        strand = actual.find_strand(values["strand_id"])
        assert len(strand.sequence) == sum(abs(domain.end_bp - domain.start_bp) + 1 for domain in strand.domains) == 8
        restored = command_module().build(PATCH, actual, application_params(actual, PATCH, applied=False))
        assert restored.find_strand(strand.id).domains == source.find_strand(strand.id).domains

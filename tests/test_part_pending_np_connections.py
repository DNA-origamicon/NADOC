"""Pending NP connection metadata must be native, scoped and independently replayable.

Native contract for this P4 increment. No applied connection, placement,
relaxation or assembly behavior is admitted by this candidate lifecycle.
"""

from copy import deepcopy
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, routes_nanoparticles as routes, state
from backend.api.part_proof_commands import PART_TOPOLOGY, dependencies, execute
from backend.api.part_recipe_edit import prepare_change, regenerate
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, NanoparticleConnectionVersion, SnapshotLogEntry
from backend.core.overhang_ops import overhang_free_end_polarity
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_dependencies import Resource
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import capture
from tests.conftest import valid_overhang_sites


CREATE = "nanoparticle-connection-version-create"
PATCH = "nanoparticle-connection-version-patch"
DELETE = "nanoparticle-connection-version-delete"


def seed(value):
    return str(UUID(int=value))


def append(design, kind, values, identity):
    result = execute(kind, design, values)
    entry = SnapshotLogEntry(id=identity, op_kind=kind, label=identity,
        timestamp="2026-10-15T00:00:00Z", params=deepcopy(values),
        design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned recovery")
    return result.copy_with(feature_log=[*design.feature_log, entry])


def gold(identity):
    return {"_proof_version": 1, "nanoparticle_version": 1,
            "nanoparticle_id": identity, "diameter_nm": 10.0}


def graft(particle="gold", *, attach_end="5p", history_seed=None):
    return {"_proof_version": 1, "thiol_version": 1, "history_seed": history_seed or seed(704),
        "nanoparticle_id": particle, "conjugation_id": f"{particle}-graft", "replace_conjugation_ids": [],
        "scheme": "direct_thiol", "sequence": "ACGT" * 3, "count": 2,
        "attach_end": attach_end, "spacer_nm": None, "seed": 17}


@pytest.fixture(scope="module")
def native_prefix():
    # Reuse the existing native-overhang fixture's admitted six-cell bundle and
    # UI placement oracle. Every resulting owner/target comes from native rows.
    design = create_empty_part("Pending NP connections", "HONEYCOMB")
    design = append(design, "bundle-create", {"_proof_version": 1, "history_seed": seed(701),
        "cells": [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]],
        "length_bp": 42, "name": "Pending NP connections", "lattice_type": "HONEYCOMB"}, "bundle")
    site = next(site for site in valid_overhang_sites(design) if not site["is_five_prime"])
    site = {**site, "direction": site["direction"].value}
    design = append(design, "overhang-extrude", {"_proof_version": 1, "history_seed": seed(702),
        **site, "length_bp": 12}, "target")
    target = design.overhangs[0].id
    design = append(design, "overhang-sequence", {"_proof_version": 1, "overhang_id": target,
        "sequence": "ACGT" * 3, "defer_reassign": True}, "sequence")
    design = append(design, "nanoparticle-create", gold("gold"), "particle")
    return append(design, "nanoparticle-conjugate", graft(), "graft")


@pytest.fixture
def source(native_prefix):
    return native_prefix.model_copy(deep=True)


def owner_inputs(design, *, version_id="candidate"):
    owner = next(item for item in design.nanoparticle_conjugations if item.nanoparticle_id == "gold")
    target = next(item for item in design.overhangs if not item.auxiliary_endpoint)
    return {"_proof_version": 1, "nanoparticle_connection_version": 1,
        "nanoparticle_id": "gold", "conjugation_id": owner.id,
        "strand_id": owner.surface_strands[0].strand_id, "overhang_id": target.id,
        "version_id": version_id}


def creation(design, **changes):
    return {**owner_inputs(design), "name": "Candidate A", "created_at": 12.0,
        "connection_type": "direct", "direct_variant": "end-to-root", "applied": False, **changes}


def pending_model(design, **changes):
    values = creation(design, **changes)
    return NanoparticleConnectionVersion(id=values["version_id"], name=values["name"],
        created_at=values["created_at"], nanoparticle_id=values["nanoparticle_id"],
        strand_id=values["strand_id"], overhang_id=values["overhang_id"],
        direct_variant=values["direct_variant"], nanoparticle_attach="free_end", target_attach="root")


def authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def test_fixture_is_native_and_has_closed_unbound_owner_and_ordinary_target(source):
    result = proof(source)
    assert result["status"] == "verified", result
    assert result["checked_commands"] == 5 and source.recipe_root.kind == "empty"
    values = owner_inputs(source)
    assert overhang_free_end_polarity(source, values["overhang_id"]) == "3p"
    assert all(item.bound_overhang_id is None for item in source.nanoparticle_conjugations[0].surface_strands)


def test_pending_create_matches_existing_endpoint_mapping_without_geometry_execution(source, monkeypatch):
    from backend.core import design_geometry, duplex

    monkeypatch.setattr(design_geometry, "fitting_geometry", lambda *_a, **_kw: pytest.fail("Pending candidate computed geometry"))
    monkeypatch.setattr(duplex, "relocate_duplex", lambda *_a, **_kw: pytest.fail("Pending candidate relocated topology"))
    original = source.model_dump_json()
    values = creation(source)
    result = execute(CREATE, source, values)
    assert result.nanoparticle_connection_versions == [pending_model(source)]
    assert authored(result) == authored(source.copy_with(nanoparticle_connection_versions=[pending_model(source)]))
    assert source.model_dump_json() == original
    assert Design.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("attach_end,variant,np_attach,allowed", [
    ("5p", "end-to-root", "free_end", True), ("5p", "root-to-root", "root", False),
    ("3p", "end-to-root", "root", False), ("3p", "root-to-root", "free_end", True),
])
def test_pending_connection_preserves_existing_chemical_polarity_rules(source, attach_end, variant, np_attach, allowed):
    log = [*source.feature_log[:-1], source.feature_log[-1].model_copy(update={
        "params": {**source.feature_log[-1].params, "attach_end": attach_end}})]
    before = regenerate(source, log, lambda: None)
    values = creation(before, direct_variant=variant)
    if allowed:
        result = execute(CREATE, before, values)
        version = result.nanoparticle_connection_versions[0]
        assert (version.nanoparticle_attach, version.target_attach) == (np_attach, "root")
        assert result.strands == before.strands and result.helices == before.helices
    else:
        with pytest.raises(ReferenceResolutionError) as error:
            execute(CREATE, before, values)
        assert error.value.code == "invalid_selection"
        assert error.value.as_issue()["references"][0]["parameter_path"] == ["direct_variant"]


@pytest.mark.parametrize("kind", [CREATE, PATCH, DELETE])
def test_registered_dependencies_expose_exact_typed_owners_and_conservative_barrier(source, kind):
    values = creation(source) if kind == CREATE else owner_inputs(source)
    if kind == PATCH:
        values["name"] = "Renamed"
    contract = dependencies(kind, values)
    assert contract.known and contract.barrier and not contract.imported_sources
    expected = {PART_TOPOLOGY, Resource("nanoparticle", values["nanoparticle_id"]),
        Resource("nanoparticle_conjugation", values["conjugation_id"]),
        Resource("strand", values["strand_id"]), Resource("overhang", values["overhang_id"])}
    assert expected <= contract.reads
    version = Resource("nanoparticle_connection_version", values["version_id"])
    assert {PART_TOPOLOGY, version} <= contract.writes
    if kind != CREATE:
        assert version in contract.reads


def test_pending_lifecycle_has_exact_portable_inputs_and_independent_cold_proof(source):
    original = source.model_dump_json()
    created = append(source, CREATE, creation(source), "candidate-create")
    renamed = append(created, PATCH, {**owner_inputs(created), "name": "Chosen candidate"}, "candidate-rename")
    assert renamed.nanoparticle_connection_versions[0].name == "Chosen candidate"
    assert renamed.nanoparticle_connection_versions[0].created_at == 12.0
    transported = Design.model_validate_json(renamed.model_dump_json())
    worker = VerificationWorker(capture(transported))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["checked_commands"] == 7 and result["native_editable"]
    finally:
        worker.close()
    deleted = append(renamed, DELETE, owner_inputs(renamed), "candidate-delete")
    assert authored(deleted) == authored(source)
    result = proof(deleted)
    assert result["status"] == "verified", result
    assert source.model_dump_json() == original


def test_upstream_geometry_edit_rebuilds_owner_while_preserving_pending_output_identity(source):
    created = append(source, CREATE, creation(source), "candidate-create")
    candidate, _ = prepare_change(created, capture(created, preserve_entry_types=True), 3, lambda: None,
                                  params={"diameter_nm": 14.0})
    assert candidate.nanoparticles[0].diameter_nm == 14.0
    assert candidate.nanoparticle_conjugations[0].surface_strands[0].strand_id == owner_inputs(source)["strand_id"]
    assert candidate.nanoparticle_connection_versions == created.nanoparticle_connection_versions
    before = {item.id: item.axis_start for item in created.helices if item.id.startswith("__np__")}
    assert any(item.axis_start != before[item.id] for item in candidate.helices if item.id in before)
    assert proof(candidate)["status"] == "verified"
    protected, _ = prepare_change(created, capture(created, preserve_entry_types=True), 5, lambda: None,
        params={"name": "Edited", "version_id": "forged", "created_at": 99.0,
                "nanoparticle_connection_version": 99})
    version = protected.nanoparticle_connection_versions[0]
    assert (version.id, version.created_at, version.name) == ("candidate", 12.0, "Edited")
    assert protected.feature_log[-1].params["nanoparticle_connection_version"] == 1


@pytest.mark.parametrize("field,resource", [("nanoparticle_id", "nanoparticle"),
    ("conjugation_id", "nanoparticle_conjugation"), ("strand_id", "strand"), ("overhang_id", "overhang")])
def test_missing_selected_owner_reports_typed_parameter_path_without_mutation(source, field, resource):
    original = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        execute(CREATE, source, creation(source, **{field: "missing"}))
    assert error.value.code == "missing_reference"
    assert error.value.as_issue()["references"][0] == {
        "kind": resource, "identity": "missing", "parameter_path": [field]}
    assert source.model_dump_json() == original


@pytest.mark.parametrize("kind", [PATCH, DELETE])
def test_missing_version_and_changed_owner_are_not_silently_retargeted(source, kind):
    values = {**owner_inputs(source), **({"name": "Rename"} if kind == PATCH else {})}
    with pytest.raises(ReferenceResolutionError) as error:
        execute(kind, source, values)
    assert error.value.code == "missing_reference"
    assert error.value.as_issue()["references"][0] == {
        "kind": "nanoparticle_connection_version", "identity": "candidate", "parameter_path": ["version_id"]}
    source.nanoparticle_connection_versions = [pending_model(source)]
    values["strand_id"] = source.nanoparticle_conjugations[0].surface_strands[1].strand_id
    original = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        execute(kind, source, values)
    assert error.value.code == "invalid_selection"
    assert error.value.as_issue()["references"][0]["parameter_path"] == ["strand_id"]
    assert source.model_dump_json() == original


@pytest.mark.parametrize("state_change", [{"applied": True}, {"duplex_id": "retained-duplex"},
    {"relaxed": True}, {"residual_nm": 0.1}, {"constraint_root_nm": (1.0, 2.0, 3.0)},
    {"constraint_radius_nm": 5.0}])
@pytest.mark.parametrize("kind", [PATCH, DELETE])
def test_pending_contract_refuses_materialized_or_retained_application_state(source, kind, state_change):
    source.nanoparticle_connection_versions = [pending_model(source).model_copy(update=state_change)]
    values = {**owner_inputs(source), **({"name": "Rename"} if kind == PATCH else {})}
    original = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        execute(kind, source, values)
    assert error.value.code == "invalid_selection"
    assert source.model_dump_json() == original


@pytest.mark.parametrize("change", [{"_proof_version": True}, {"nanoparticle_connection_version": 2},
    {"nanoparticle_connection_version": True}, {"applied": True}, {"applied": 0},
    {"connection_type": "indirect"}, {"direct_variant": "end-to-end"}, {"created_at": True},
    {"created_at": -1.0}, {"created_at": float("inf")}, {"name": "x" * 257},
    {"version_id": ""}, {"conjugation_id": ""}, {"saved_particle": {}},
    {"prior_driven_topology": {}}, {"duplex_id": "output"}])
def test_pending_schema_cannot_admit_application_or_opaque_output(source, change):
    assert not dependencies(CREATE, creation(source, **change)).known


def test_deleted_target_producer_reports_actual_pending_consumer(source):
    created = append(source, CREATE, creation(source), "candidate-create")
    preview = prepare_change(created, capture(created, preserve_entry_types=True), 1, lambda: None)
    assert preview["needs_cascade_decision"]
    issue = next(item["issues"]["candidate-create"] for item in preview["dependents"]
                 if "candidate-create" in item["issues"])
    assert issue["code"] == "missing_reference"
    assert issue["references"][0] == {"kind": "overhang", "identity": owner_inputs(source)["overhang_id"],
                                       "parameter_path": ["overhang_id"]}


@pytest.fixture
def document(source):
    identity = f"__pending_np_{uuid4()}"
    token = doc_context.set_current_doc(identity)
    revision, entry = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    try:
        state.load_design(source)
        yield source
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(revision)
        doc_context.set_request_feature_log_entry_id(entry)


def test_visible_pending_routes_record_all_inputs_once_and_preserve_undo(document):
    original = state.get_or_404()
    original_json = original.model_dump_json()
    values = owner_inputs(original)
    revision, depth = state.revision(), state.undo_depth()
    result = routes.create_np_connection_version("gold", routes.NanoparticleConnectionVersionCreate(
        strand_id=values["strand_id"], overhang_id=values["overhang_id"], name="Pending"))
    created = state.get_or_404()
    row = created.feature_log[-1]
    assert row.params["nanoparticle_connection_version"] == 1
    assert row.params["conjugation_id"] == values["conjugation_id"]
    assert row.params["strand_id"] == values["strand_id"] and row.params["overhang_id"] == values["overhang_id"]
    assert row.params["version_id"] == result["version_id"]
    assert row.params["created_at"] == created.nanoparticle_connection_versions[0].created_at
    assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
    assert len(created.feature_log) == len(original.feature_log) + 1
    assert original.model_dump_json() == original_json
    routes.patch_np_connection_version("gold", result["version_id"], routes.NanoparticleConnectionVersionPatch(name="Renamed"))
    renamed = state.get_or_404()
    assert renamed.feature_log[-1].params["name"] == "Renamed"
    routes.delete_np_connection_version("gold", result["version_id"])
    assert state.get_or_404().nanoparticle_connection_versions == []
    assert state.revision() == revision + 3 and state.undo_depth() == depth + 3
    state.undo()
    assert state.get_or_404().nanoparticle_connection_versions[0].name == "Renamed"
    state.redo()
    assert not state.get_or_404().nanoparticle_connection_versions
    assert proof(state.get_or_404())["status"] == "verified"


def test_pending_delete_preserves_unrelated_legacy_direct_binding_metadata(document):
    before = append(document, "nanoparticle-create", gold("other"), "other-particle")
    before = append(before, "nanoparticle-conjugate", graft("other", history_seed=seed(706)), "other-graft")
    # Compatibility state is deliberately not claimed as a native complete
    # recipe. Deleting one pending version must not normalize unrelated owners.
    unrelated = next(item for item in before.nanoparticle_conjugations if item.nanoparticle_id == "other")
    unrelated.surface_strands[0].bound_overhang_id = owner_inputs(before)["overhang_id"]
    before.nanoparticle_connection_versions = [pending_model(before), pending_model(before, version_id="keep", name="Keep")]
    state.load_design(before)
    expected = deepcopy(unrelated)
    revision, depth = state.revision(), state.undo_depth()
    routes.delete_np_connection_version("gold", "candidate")
    after = state.get_or_404()
    assert next(item for item in after.nanoparticle_conjugations if item.id == unrelated.id) == expected
    assert [item.id for item in after.nanoparticle_connection_versions] == ["keep"]
    assert authored(after) == authored(before.copy_with(nanoparticle_connection_versions=before.nanoparticle_connection_versions[1:]))
    assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
    assert after.feature_log[-1].params["nanoparticle_connection_version"] == 1


def test_pending_route_reference_failure_is_atomic(document):
    before, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    with pytest.raises(HTTPException):
        routes.create_np_connection_version("gold", routes.NanoparticleConnectionVersionCreate(
            strand_id=owner_inputs(before)["strand_id"], overhang_id="missing"))
    assert state.get_design_with_revision() == (before, revision) and state.undo_depth() == depth


def request(design, **updates):
    values = owner_inputs(design)
    return routes.NanoparticleConnectionVersionCreate(
        **{"strand_id": values["strand_id"], "overhang_id": values["overhang_id"], **updates})


def signature():
    session = state._session()
    return (session.design.model_dump_json(), session.revision,
            [item.model_dump_json() for item in session.history],
            [item.model_dump_json() for item in session.redo],
            doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id())


def test_stale_revision_refuses_before_identity_time_or_builder(document, monkeypatch):
    from backend.api import part_nanoparticle_connection_commands as native

    before = signature()
    def unexpected(*_args, **_kwargs):
        pytest.fail("Stale request reached native preparation")
    for name in ("uuid4", "time", "_prepare_source", "_build_prepared"):
        monkeypatch.setattr(native, name, unexpected)
    with pytest.raises(HTTPException) as error:
        routes.create_np_connection_version("gold", request(document, expected_revision=state.revision() - 1))
    assert error.value.status_code == 409
    assert signature() == before


def test_locked_adapter_is_not_reentrant_and_freezes_defaults_once(document, monkeypatch):
    from backend.api import part_nanoparticle_connection_commands as native

    class GuardedLock:
        held = False
        def __enter__(self):
            assert not self.held, "Nested acquisition of state lock"
            self.held = True
            return self
        def __exit__(self, *_args):
            self.held = False

    lock = GuardedLock()
    monkeypatch.setattr(state, "_lock", lock)
    calls = {"id": 0, "time": 0, "build": 0}
    original_build = native._build_prepared
    def make_id():
        assert lock.held
        calls["id"] += 1
        return UUID(int=730)
    def now():
        assert lock.held
        calls["time"] += 1
        return 37.0
    def build(*args):
        assert lock.held
        calls["build"] += 1
        return original_build(*args)
    monkeypatch.setattr(native, "uuid4", make_id)
    monkeypatch.setattr(native, "time", now)
    monkeypatch.setattr(native, "_build_prepared", build)
    result = routes.create_np_connection_version("gold", request(document, expected_revision=state.revision()))
    assert calls == {"id": 1, "time": 1, "build": 1}
    assert result["version_id"] == str(UUID(int=730))
    version = state.get_or_404().nanoparticle_connection_versions[0]
    assert (version.name, version.created_at) == ("V1", 37.0)


def test_native_pending_recording_uses_only_current_document(document):
    original = signature()
    other = f"__pending_np_other_{uuid4()}"
    token = doc_context.set_current_doc(other)
    try:
        state.load_design(document.model_copy(deep=True).copy_with(id=str(uuid4())))
        first = routes.create_np_connection_version("gold", request(document))
        assert state.get_or_404().nanoparticle_connection_versions[0].id == first["version_id"]
    finally:
        state.drop_doc(other)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(original[-2])
        doc_context.set_request_feature_log_entry_id(original[-1])
    assert signature() == original
    with pytest.raises(HTTPException) as error:
        routes.delete_np_connection_version("gold", first["version_id"])
    assert error.value.status_code == 404
    assert signature() == original


@pytest.mark.parametrize("stage", ["post-encode", "publish", "cancel"])
def test_pending_record_failure_restores_design_history_revision_and_markers(document, monkeypatch, stage):
    original = signature()
    encode = state.encode_design_snapshot
    calls = 0
    def encode_or_fail(design):
        nonlocal calls
        calls += 1
        if calls == 2:
            if stage == "cancel":
                raise KeyboardInterrupt()
            raise RuntimeError("Injected pending post-encode failure")
        return encode(design)
    if stage == "publish":
        bump = state._bump_revision
        def bump_or_fail(session):
            bump(session)
            raise RuntimeError("Injected pending publication failure")
        monkeypatch.setattr(state, "_bump_revision", bump_or_fail)
    else:
        monkeypatch.setattr(state, "encode_design_snapshot", encode_or_fail)
    with pytest.raises(KeyboardInterrupt if stage == "cancel" else RuntimeError):
        routes.create_np_connection_version("gold", request(document))
    assert signature() == original


def test_multiple_legacy_owners_keep_legacy_path_before_native_execution(document, monkeypatch):
    from backend.api import part_nanoparticle_connection_commands as native

    # Legacy files can retain several otherwise-unbound ownership records; the
    # first native contract deliberately requires one exact radial owner.
    owner = document.nanoparticle_conjugations[0]
    document.nanoparticle_conjugations.append(owner.model_copy(update={"id": "legacy-second-owner"}))
    for name in ("_prepare_source", "_build_prepared"):
        monkeypatch.setattr(native, name, lambda *_args: pytest.fail("Unsupported owner reached native preparation"))
    routes.create_np_connection_version("gold", request(document))
    row = state.get_or_404().feature_log[-1]
    assert "nanoparticle_connection_version" not in row.params
    assert not dependencies(row.op_kind, row.params).known


def test_pending_delete_with_legacy_endpoint_metadata_stays_unverified_and_local(document):
    document.nanoparticle_connection_versions = [pending_model(document).model_copy(update={
        "nanoparticle_attach": None})]
    owner = document.nanoparticle_conjugations[0]
    owner.surface_strands[1].bound_overhang_id = owner_inputs(document)["overhang_id"]
    expected = deepcopy(owner)
    routes.delete_np_connection_version("gold", "candidate")
    after = state.get_or_404()
    assert not after.nanoparticle_connection_versions
    assert after.nanoparticle_conjugations[0] == expected
    assert not dependencies(DELETE, after.feature_log[-1].params).known


def test_generated_scope_does_not_promote_unqualified_compound_owner_contract(source):
    values = creation(source, _generated_scope={"version": 1, "input_ids": []})
    assert not dependencies(CREATE, values).known
    with pytest.raises(NotImplementedError, match="versioned proof contract"):
        execute(CREATE, source, values)


@pytest.mark.parametrize("nested", ["surface_strands", "cluster_membership", "saved_topology"])
def test_oversized_nested_reference_work_refuses_before_reference_or_identity_walk(source, monkeypatch, nested):
    from backend.api import part_nanoparticle_connection_commands as native
    from backend.core.part_command_errors import CommandContractError

    if nested == "surface_strands":
        original = source.nanoparticle_conjugations[0]
        unrelated = original.model_copy(update={"id": "large-unrelated", "nanoparticle_id": "other",
            "surface_strands": [original.surface_strands[0]] * (native.MAX_OPERATION_NODES + 1)})
        source.nanoparticle_conjugations.append(unrelated)
    elif nested == "cluster_membership":
        source.cluster_transforms[0].helix_ids = [source.helices[0].id] * (native.MAX_OPERATION_NODES + 1)
    else:
        from backend.core.models import Duplex, DuplexEnd
        target = owner_inputs(source)["overhang_id"]
        other = source.nanoparticle_conjugations[0].surface_strands[0].overhang_id
        source.duplexes.append(Duplex(left=DuplexEnd(overhang_id=target, start_bp=0, end_bp=1),
            right=DuplexEnd(overhang_id=other, start_bp=0, end_bp=1),
            prior_driven_topology={"oversized": [None] * (native.MAX_OPERATION_NODES + 1)}))
    assert not native._route_eligible(source, "gold", None, {})
    def unexpected(*_args, **_kwargs):
        pytest.fail("Oversized nested ownership reached reference construction")
    monkeypatch.setattr(native, "typed_ownership_supported", unexpected)
    monkeypatch.setattr(native, "identity_index", unexpected)
    with pytest.raises(CommandContractError) as error:
        native.build(CREATE, source, creation(source))
    assert error.value.code == "unsupported_np_connection_source"


def test_reference_node_budget_accepts_exact_boundary_and_refuses_next_before_parsing(source, monkeypatch):
    from backend.api import part_nanoparticle_connection_commands as native

    # Use actual reference-list work. Aliases must count on every occurrence;
    # they are traversed on every occurrence by the shared reference resolver.
    original = list(source.cluster_transforms[0].helix_ids)
    monkeypatch.setattr(native, "MAX_OPERATION_BYTES", 10**9)  # Isolate the existing node ceiling in this test only.
    low, high = 0, native.MAX_OPERATION_NODES
    while low < high:
        middle = (low + high + 1) // 2
        source.cluster_transforms[0].helix_ids = original + [source.helices[0].id] * middle
        if native._bounded(source):
            low = middle
        else:
            high = middle - 1
    assert low > 0
    source.cluster_transforms[0].helix_ids = original + [source.helices[0].id] * low
    assert native._bounded(source)
    source.cluster_transforms[0].helix_ids.append(source.helices[0].id)
    assert not native._bounded(source)


def test_reference_byte_budget_does_not_traverse_unrelated_atom_or_user_text_payloads(source):
    from backend.api import part_nanoparticle_connection_commands as native

    source.strands[0].notes = "Unrelated authored prose " * native.MAX_OPERATION_BYTES
    assert native._bounded(source)
    source.cluster_transforms[0].helix_ids.append("x" * native.MAX_OPERATION_BYTES)
    assert not native._bounded(source)


@pytest.mark.parametrize("field", ["nanoparticles", "nanoparticle_conjugations", "nanoparticle_connection_versions"])
def test_top_level_refusal_precedes_particle_owner_and_version_search(document, monkeypatch, field):
    from backend.api import part_nanoparticle_connection_commands as native

    class NoScan(list):
        def __iter__(self):
            pytest.fail("Oversized top-level collection was scanned")
    item = pending_model(document) if field == "nanoparticle_connection_versions" else getattr(document, field)[0]
    setattr(document, field, NoScan([item] * (native.MAX_OPERATION_NODES + 1)))
    monkeypatch.setattr(native, "_bounded", lambda *_args: pytest.fail("Oversized list reached nested traversal"))
    assert native._route_eligible(document, "gold", None, {}) is False
    assert native.try_record(CREATE, "gold", {}) is None

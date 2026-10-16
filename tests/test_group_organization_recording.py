"""Owned group edits record inputs, preserve placement and publish once."""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.core.models import Design
from backend.core.part_overlay_commands import command_input
from tests.test_group_organization_history import history, _verified


@pytest.fixture
def document(monkeypatch):
    _, states = history()
    source = states[2]
    doc = f"__organization_recording__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    previous = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True, raising=False)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    try:
        state.load_design(source)
        yield state._sessions[doc]
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(previous[0])
        doc_context.set_request_feature_log_entry_id(previous[1])


def apply(session, kind="group-organize", inputs=None, **kwargs):
    from backend.api import part_group_organization_recording as recorder
    if inputs is None:
        inputs = {"expected_placement_ids": [c.id for c in session.design.cluster_transforms]}
    return recorder.apply(kind, inputs, expected_revision=kwargs.get("revision", session.revision))


def before(session):
    return (session.design, session.design.model_dump_json(), session.revision,
        tuple(session.history), tuple(session.redo), doc_context.current_request_revision(),
        doc_context.current_request_feature_log_entry_id())


def unchanged(session, saved):
    current = before(session)
    assert current[0] is saved[0] and current[1:3] == saved[1:3]
    for old, new in zip(saved[3:5], current[3:5]):
        assert len(old) == len(new) and all(a is b for a, b in zip(old, new))
    assert current[5:] == saved[5:]


def test_actual_commands_cold_replay_save_reload_undo_redo(document):
    session = document
    source = session.design
    source_json = source.model_dump_json()
    initial_revision = session.revision
    original_placements = deepcopy(source.cluster_transforms)
    converted, _, first = apply(session)
    created, _, creation = apply(session, "group-create", {"name": "Selected",
        "helix_ids": [source.helices[0].id], "color": "#abcdef"})
    group_id = creation.params["group"]["id"]
    updated, _, edit = apply(session, "group-update", {"group_id": group_id,
        "fields": {"name": "Renamed", "opacity": 0.5}})
    dissolved, _, last = apply(session, "group-dissolve", {"group_ids": [group_id]})
    assert [entry.op_kind for entry in (first, creation, edit, last)] == [
        "group-organize", "group-create", "group-update", "group-dissolve"]
    assert session.revision == initial_revision + 4 and len(session.history) == 4
    assert source.model_dump_json() == source_json and dissolved.cluster_transforms == original_placements
    for design in (converted, created, updated, dissolved):
        _verified(design)
    for expected in (updated, created, converted, source):
        restored, _ = state.undo()
        assert restored.group_organization == expected.group_organization
        assert restored.cluster_transforms == expected.cluster_transforms
    for expected in (converted, created, updated, dissolved):
        restored, _ = state.redo()
        assert restored.group_organization == expected.group_organization
    saved, _, _ = state.copy_for_workspace_save()
    loaded = Design.model_validate_json(saved.model_dump_json())
    crud._install_loaded_design(loaded)
    assert session.design.group_organization == dissolved.group_organization
    assert session.design.cluster_transforms == original_placements
    _verified(session.design)


def test_explicit_placement_edit_never_uses_same_named_group_membership(document):
    apply(document)
    apply(document, "group-update", {"group_id": "placement", "fields": {
        "helix_ids": [document.design.helices[1].id]}})
    organization = deepcopy(document.design.group_organization)
    candidate, _, entry = apply(document, "placement-update", {"placement_id": "placement",
        "fields": {"translation": [8, 9, 10]}})
    kind, params = command_input(entry)
    assert kind == "cluster_op" and set(params) == {
        "cluster_id", "translation", "rotation", "pivot", "_proof_version"}
    assert candidate.group_organization == organization and not entry.authored_fields
    assert next(c for c in candidate.cluster_transforms if c.id == "placement").translation == [8, 9, 10]
    _verified(candidate)


@pytest.mark.parametrize("kind,inputs", [
    ("group-update", {"group_id": "placement", "fields": {"name": "Arm"}}),
    ("placement-update", {"placement_id": "placement", "fields": {"translation": [2, -1, 3]}}),
])
def test_noop_keeps_exact_source_history_revision_and_redo(document, monkeypatch, kind, inputs):
    apply(document)
    document.redo.append(Design())
    saved = before(document)
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("No-op encoded recovery"))
    result, _, entry = apply(document, kind, inputs)
    assert result is saved[0] and entry is None
    unchanged(document, saved)


@pytest.mark.parametrize("kind,inputs", [
    ("group-create", {"id": "request-owned"}),
    ("group-create", {"translation": [1, 2, 3]}),
    ("group-create", {"is_default": True}),
    ("group-organize", {"expected_placement_ids": ["placement"], "log": False}),
    ("group-update", {"group_id": "placement", "fields": {"translation": [1, 2, 3]}}),
    ("group-dissolve", {"group_ids": ["missing"]}),
    ("placement-update", {"placement_id": "placement", "fields": {"helix_ids": []}}),
    ("placement-update", {"placement_id": "placement", "fields": {"rotation": [0, 0, 0, 0]}}),
    ("placement-update", {"placement_id": "placement", "fields": {"translation": [True, 0, 0]}}),
    ("placement-update", {"placement_id": "missing", "fields": {"pivot": [0, 0, 0]}}),
])
def test_bad_requests_never_publish_or_encode(document, monkeypatch, kind, inputs):
    apply(document)
    saved = before(document)
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("Invalid input encoded recovery"))
    with pytest.raises(HTTPException):
        apply(document, kind, inputs)
    unchanged(document, saved)


@pytest.mark.parametrize("revision", [-1, True, "1", None])
def test_revision_is_required_and_exact(document, revision):
    saved = before(document)
    with pytest.raises(HTTPException):
        apply(document, revision=revision)
    unchanged(document, saved)


@pytest.mark.parametrize("refusal", ["disabled", "strict", "cursor", "stale"])
def test_admission_refuses_before_capture(document, monkeypatch, refusal):
    from backend.core import part_verification_capture
    if refusal == "disabled":
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    elif refusal == "strict":
        policy._install_configuration(policy.HostPolicyConfiguration(default_mode="registered_only"))
    elif refusal == "cursor":
        document.design.feature_log_cursor = 1
    saved = before(document)
    monkeypatch.setattr(part_verification_capture, "capture", lambda *_args, **_kw: pytest.fail("Refusal captured source"))
    with pytest.raises(HTTPException):
        apply(document, revision=document.revision - (refusal == "stale"))
    unchanged(document, saved)


def test_builder_runs_outside_lock_and_changed_source_refuses(document, monkeypatch):
    from backend.api import part_group_organization_recording as recorder
    from backend.core.part_group_organization import build
    saved_source = document.design
    concurrent = saved_source.model_copy(deep=True)

    def racing(kind, source, inputs):
        assert state._lock.acquire(blocking=False), "Native preparation held global state lock"
        state._lock.release()
        result = build(kind, source, inputs)
        with state._lock:
            document.design = concurrent
            document.revision += 1
        return result

    monkeypatch.setattr(recorder, "build_organization", racing)
    with pytest.raises(HTTPException) as error:
        apply(document)
    assert error.value.detail["code"] == "source_changed"
    assert document.design is concurrent and not document.history
    assert saved_source.group_organization is None


@pytest.mark.parametrize("failure", ["encode", "publication"])
def test_preparation_and_publication_failures_are_atomic(document, monkeypatch, failure):
    document.redo.append(Design())
    saved = before(document)

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(state, "encode_design_snapshot" if failure == "encode" else "_bump_revision", fail)
    with pytest.raises(RuntimeError, match="injected"):
        apply(document)
    unchanged(document, saved)


def test_publication_preserves_non_authoring_fields_and_old_recovery(document):
    from backend.core.part_history_contract import FIELD_ROLES
    from backend.core.models import AtomisticReference, CameraPose, DesignLoadout
    source = document.design
    source.camera_poses = [CameraPose(name="Retained viewpoint", position=[10, 20, 30])]
    source.atomistic_reference = AtomisticReference(source="existing physical reference", notes="retain")
    source.visibility_state.hidden_cluster_ids = ["placement"]
    source.loadouts = [DesignLoadout(id="editable", name="Working branch", head_revision_id="saved-head")]
    source.active_loadout_id = "editable"
    old_log = list(source.feature_log)
    candidate, _, entry = apply(document)
    for field, role in FIELD_ROLES.items():
        if role in {"presentation", "physical", "repair_draft"}:
            assert getattr(candidate, field) is getattr(source, field)
    assert all(a is b for a, b in zip(old_log, candidate.feature_log))
    assert entry.design_snapshot_gz_b64 and entry.post_state_gz_b64
    assert state.decode_design_snapshot(entry.design_snapshot_gz_b64).group_organization is None
    assert state.decode_design_snapshot(entry.post_state_gz_b64).group_organization == candidate.group_organization
    recovered = crud._seek_feature_log(candidate, len(candidate.feature_log) - 1)
    assert recovered.camera_poses == source.camera_poses
    assert recovered.atomistic_reference == source.atomistic_reference
    assert recovered.visibility_state == source.visibility_state
    assert recovered.loadouts == source.loadouts


def test_new_row_must_fit_the_complete_authoring_budget(document, monkeypatch):
    from backend.core import part_verification_capture as projection
    from backend.core.part_group_organization import build

    source = projection.capture(document.design, preserve_entry_types=True)
    prepared = build("group-organize", source, {"_proof_version": 1,
        "expected_placement_ids": [c.id for c in source.cluster_transforms]})
    # Set a small real node allowance that admits the new authoring fields but
    # has no room for the additional feature definition. No large fixture.
    real_admit = projection.admit
    low, high = 1, 30_000
    while low < high:
        middle = (low + high) // 2
        try:
            real_admit(prepared, max_nodes=middle, preserve_entry_types=True)
            high = middle
        except projection.CaptureLimit:
            low = middle + 1

    def limited(candidate, **options):
        return real_admit(candidate, max_nodes=low, **options)

    monkeypatch.setattr(projection, "admit", limited)
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("Over-budget candidate encoded recovery"))
    saved = before(document)
    with pytest.raises(HTTPException) as error:
        apply(document)
    assert error.value.detail["code"] == "group_capture_limit"
    unchanged(document, saved)


def test_existing_scientific_dependency_gate_still_precedes_recovery(document, monkeypatch):
    from backend.core import photoproducts

    monkeypatch.setattr(photoproducts, "stale_photoproduct_ids", lambda *_: ["formed-cpd"])
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("Stale product encoded recovery"))
    saved = before(document)
    with pytest.raises(HTTPException) as error:
        apply(document)
    assert error.value.detail["code"] == "photoproduct_dependency"
    unchanged(document, saved)


def test_noop_binds_request_revision_to_accepted_source(document):
    apply(document)
    accepted = document.revision
    doc_context.set_request_revision(None)
    source, _, entry = apply(document, "group-update", {
        "group_id": "placement", "fields": {"name": "Arm"}})
    assert source is document.design and entry is None
    assert document.revision == accepted
    assert doc_context.current_request_revision() == accepted


def test_shared_authoring_graph_cannot_trigger_unbounded_recovery_encoding(document, monkeypatch):
    from backend.core.models import ProteinAsset

    shared = ["small"]
    for _ in range(20):
        shared = [shared, shared]
    source = document.design
    source.protein_assets = [ProteinAsset(id="metadata", metadata={"nested": shared})]
    revision = document.revision
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("Shared graph reached encoding"))
    with pytest.raises(HTTPException) as error:
        apply(document)
    assert error.value.detail["code"] == "group_capture_limit"
    assert document.design is source and source.group_organization is None
    assert document.revision == revision and not document.history
    assert source.protein_assets[0].metadata["nested"] is shared

"""Draft metadata survives editing without entering proof or recovery inputs."""

import base64
from collections import deque
import gzip
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import crud, doc_context, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design, DesignLoadout, MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_history_contract import FIELD_ROLES, create_empty_part
from backend.core.part_history_proof import assess, import_root, root_design
from backend.core.part_input_sources import EmbeddedInput, MAX_SOURCES, describe, embed
from backend.core.part_recipe_publication import preserve_document_state
from backend.core.part_repair_document import preserve_repair_draft, restore_recovery_draft
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_verification_capture import capture
from backend.core.validator import validate_design


def proposal(*, identity="part", generation=0):
    return RepairDraft.model_validate({"version": 1, "draft_id": "draft", "generation": generation,
        "base_design_id": identity, "repair_version": 1,
        "base": {"version": 1, "root_sha256": "a" * 64, "commands_sha256": "b" * 64, "sources_sha256": "c" * 64},
        "actions": [{"action": "set_input", "feature_id": "feature", "parameter_path": ["length_bp"],
                     "expected_old": 21, "value": 32}]})


def source():
    return create_empty_part("Draft boundary", "HONEYCOMB").copy_with(id="part", repair_draft=proposal())


@pytest.fixture
def document(monkeypatch):
    identity = f"__draft_boundary_test__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    revision, entry = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    state.load_design(source())

    def response(design, report, **options):
        return crud._design_response(design, report, **{key: value for key, value in options.items()
            if key in {"preserve_feature_log_id", "full_feature_log"}})

    monkeypatch.setattr(crud, "_design_response_with_geometry", response)
    monkeypatch.setattr(crud, "_design_replace_response", lambda _before, after, report: crud._design_response(after, report))
    try:
        yield
    finally:
        with state._lock:
            state._sessions.pop(identity, None)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(revision)
        doc_context.set_request_feature_log_entry_id(entry)


def test_role_and_proof_ignore_proposed_actions_and_capture_does_not_visit_them():
    design = source()
    assert FIELD_ROLES["repair_draft"] == "repair_draft"
    reference = assess(design, max_entries=10, execute=execute, dependencies=dependencies, checkpoint=None)
    # Nonserializable/large private values would fail if proof capture,
    # comparison or input fingerprints traversed this excluded field.
    poisoned = proposal().model_copy(update={"actions": [object(), "x" * 3_000_000]})
    design.repair_draft = poisoned
    captured = capture(design, seconds=1)
    assert captured.repair_draft is None
    result = assess(design, max_entries=10, execute=execute, dependencies=dependencies, checkpoint=None)
    assert result["status"] == "verified"
    assert result["recipe_fingerprint"] == reference["recipe_fingerprint"]
    assert result["authoring_fingerprint"] == reference["authoring_fingerprint"]
    assert "repair_draft" in result["excluded_roles"]


def test_import_root_excludes_proposal_and_rejects_nested_draft_in_supplied_source():
    design = Design(id="part", repair_draft=proposal())
    root = import_root(design)
    assert "repair_draft" not in json.loads(root.source_json)
    assert root_design(root).repair_draft is None
    raw = design.model_dump_json()
    poisoned = root.model_copy(update={"source_json": raw, "source_sha256": hashlib.sha256(raw.encode()).hexdigest()})
    with pytest.raises(ValueError, match="repair draft"):
        root_design(poisoned)


def test_recovery_snapshot_excludes_proposal_before_serialization():
    design = source()
    design.repair_draft = proposal().model_copy(update={"actions": [object()]})
    encoded, size = state.encode_design_snapshot(design)
    raw = gzip.decompress(base64.b64decode(encoded))
    assert len(raw) == size and "repair_draft" not in json.loads(raw)
    assert state.decode_design_snapshot(encoded).repair_draft is None
    assert design.repair_draft is not None


def test_numerical_authoring_source_projections_exclude_draft_without_visiting_actions():
    from backend.core.part_cpd_contract import native_source as cpd_source
    from backend.core.part_duplex_relax_contract import native_source as duplex_source
    design = source()
    design.repair_draft = proposal().model_copy(update={"actions": [object()]})
    assert cpd_source(design).repair_draft is None
    assert duplex_source(design).repair_draft is None


def test_native_publication_preserves_draft_but_keeps_deliberate_candidate_source_replacement():
    design = source()
    digest = "a" * 64
    design.input_sources = {digest: EmbeddedInput(data_b64="old")}
    replacement = EmbeddedInput(data_b64="new")
    candidate = design.copy_with(repair_draft=None, input_sources={digest: replacement})
    published = preserve_document_state(design, candidate)
    assert published.repair_draft is design.repair_draft
    assert published.input_sources[digest] is replacement
    assert candidate.repair_draft is None
    assert preserve_repair_draft(design.copy_with(repair_draft=None), published).repair_draft is None


def test_legacy_recovery_retains_new_source_and_live_repaired_bytes_without_decoding(monkeypatch):
    import backend.core.part_input_sources as sources
    design = source()
    selected = describe(b"new input", format="blob", media_type="application/octet-stream")
    repaired = describe(b"repaired", format="blob", media_type="application/octet-stream")
    design.input_sources = {selected.sha256: embed(selected, b"new input"), repaired.sha256: embed(repaired, b"repaired")}
    historical = design.copy_with(repair_draft=None, input_sources={repaired.sha256: EmbeddedInput(data_b64="corrupt")})
    monkeypatch.setattr(sources, "decode", lambda *_: pytest.fail("Recovery decoded sources"))
    restored = restore_recovery_draft(design, historical)
    assert restored.repair_draft is design.repair_draft
    assert restored.input_sources == design.input_sources
    assert restored.input_sources[repaired.sha256] is design.input_sources[repaired.sha256]
    assert historical.input_sources[repaired.sha256].data_b64 == "corrupt"
    discarded = restore_recovery_draft(design.copy_with(repair_draft=None), historical)
    assert discarded.input_sources is historical.input_sources and discarded.repair_draft is None


@pytest.mark.parametrize("minor", [False, True])
def test_replacement_recording_callback_keeps_draft_and_omits_it_from_feature_payloads(document, minor):
    before = state.get_or_404().repair_draft
    callback = lambda design: design.copy_with(repair_draft=None)
    if minor:
        design, _, _ = state.mutate_with_minor_log(op_subtype="nick", label="Replacement", params={}, fn=callback)
        payloads = (design.feature_log[-1].pre_state_gz_b64, design.feature_log[-1].post_state_gz_b64)
    else:
        design, _, _ = state.mutate_with_feature_log(op_kind="auto-break", label="Replacement", params={}, fn=callback)
        payloads = (design.feature_log[-1].design_snapshot_gz_b64, design.feature_log[-1].post_state_gz_b64)
    assert design.repair_draft == before
    assert all(state.decode_design_snapshot(payload).repair_draft is None for payload in payloads)


@pytest.mark.parametrize("discard", [False, True])
def test_same_branch_geometry_undo_redo_retains_current_proposal_or_explicit_discard(document, discard):
    state.mutate_and_validate(lambda design: setattr(design.metadata, "description", "geometry edit"))
    current = None if discard else proposal(generation=4)
    state.set_design_silent(state.get_or_404().copy_with(repair_draft=current))
    state.undo()
    assert state.get_or_404().repair_draft == current
    state.redo()
    assert state.get_or_404().repair_draft == current


@pytest.mark.parametrize("other_part", [False, True])
def test_undo_across_branch_or_part_restores_destination_proposal(document, other_part):
    before = state.get_or_404().copy_with(active_loadout_id="first")
    state.load_design(before)
    after = before.copy_with(id="different" if other_part else before.id,
        active_loadout_id="first" if other_part else "second", repair_draft=proposal(generation=5))
    state.set_design(after)
    state.undo()
    assert state.get_or_404().repair_draft == before.repair_draft
    state.redo()
    assert state.get_or_404().repair_draft == after.repair_draft


@pytest.mark.parametrize("operation", ["undo", "redo"])
def test_new_source_retention_refusal_does_not_change_undo_redo_or_revision(document, operation):
    current = state.get_or_404()
    current.input_sources = {f"{index:064x}": EmbeddedInput(data_b64="") for index in range(MAX_SOURCES)}
    old = current.copy_with(input_sources={f"{MAX_SOURCES:064x}": EmbeddedInput(data_b64="")})
    with state._lock:
        session = state._session()
        session.history = deque([old], maxlen=50)
        session.redo = deque([old], maxlen=50)
    revision, request_revision = state.revision(), doc_context.current_request_revision()
    with pytest.raises(HTTPException) as error:
        getattr(state, operation)()
    assert error.value.status_code == 409 and error.value.detail["code"] == "repair_draft_source_limit"
    assert state.get_or_404() is current and state.revision() == revision
    assert doc_context.current_request_revision() == request_revision
    assert list(session.history) == [old] and list(session.redo) == [old]


def legacy_document(*, child=False):
    historical = Design(id="part")
    payload, size = state.encode_design_snapshot(historical)
    if child:
        entry = RoutingClusterLogEntry(id="feature", pre_state_gz_b64=payload, pre_state_size_bytes=size,
            post_state_gz_b64=payload, post_state_size_bytes=size,
            children=[MinorMutationLogEntry(id="child", op_subtype="nick", label="Child", params={})])
    else:
        entry = SnapshotLogEntry(id="feature", op_kind="auto-break", label="Legacy", params={},
            design_snapshot_gz_b64=payload, snapshot_size_bytes=size, post_state_gz_b64=payload, post_state_size_bytes=size)
    descriptor = describe(b"staged input", format="blob", media_type="application/octet-stream")
    live = historical.copy_with(repair_draft=proposal(), feature_log=[entry],
        input_sources={descriptor.sha256: embed(descriptor, b"staged input")},
        loadouts=[DesignLoadout(id="branch", name="Branch")], active_loadout_id="branch", last_editable_loadout_id="branch")
    return live


@pytest.mark.parametrize("operation", ["snapshot-revert", "child-revert", "snapshot-edit", "delete-replay"])
def test_legacy_whole_recovery_keeps_branch_proposal_and_staged_sources(document, monkeypatch, operation):
    live = legacy_document(child=operation == "child-revert")
    state.load_design(live)
    if operation == "snapshot-revert":
        crud.revert_to_before_feature(0)
    elif operation == "child-revert":
        crud.revert_to_before_feature(0, sub_index=0)
    elif operation == "snapshot-edit":
        monkeypatch.setattr(crud, "_edit_dispatch_run", lambda _kind, design, _params: design)
        crud.edit_feature(0, crud.EditFeatureBody(params={}))
    else:
        crud._delete_snapshot_feature_by_replay(live, live.feature_log, 0, live.feature_log[0], [])
    restored = state.get_or_404()
    assert restored.repair_draft == live.repair_draft and restored.input_sources == live.input_sources
    assert restored.active_loadout_id == restored.last_editable_loadout_id == "branch"
    assert restored.loadouts == live.loadouts


def test_slider_seek_retains_live_proposal(document):
    live = legacy_document()
    assert crud._seek_feature_log(live, -2).repair_draft is live.repair_draft
    assert crud._seek_feature_log(live, -1).repair_draft is live.repair_draft


@pytest.mark.parametrize("full_feature_log", [False, True])
def test_response_excludes_actions_during_dump_and_only_returns_noncertifying_summary(document, full_feature_log):
    design = state.get_or_404()
    design.repair_draft = proposal().model_copy(update={"actions": [object()]})
    response = crud._design_response(design, validate_design(design), full_feature_log=full_feature_log)
    assert "repair_draft" not in response["design"]
    assert response["repair_draft"] == {"version": 1, "draft_id": "draft", "generation": 0,
        "action_count": 1, "status": "pending", "base_status": "unchecked"}


def test_fresh_empty_cadnano_host_rejects_pending_proposal(document):
    from backend.api.routes_part_cadnano_import import ReplacementQuery, _current
    query = ReplacementQuery(expected_design_id="part", expected_revision=state.revision())
    with pytest.raises(HTTPException) as error:
        _current(query)
    assert error.value.status_code == 422 and error.value.detail["code"] == "fresh_empty_part_required"


def test_native_edit_and_delete_keep_proposal(document):
    state.load_design(None)
    crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=21))
    design = state.get_or_404()
    saved = proposal(identity=design.id)
    design.repair_draft = saved
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 32}))
    assert state.get_or_404().helices[0].length_bp == 32
    assert state.get_or_404().repair_draft == saved
    crud.delete_feature(0)
    assert not state.get_or_404().helices and state.get_or_404().repair_draft == saved

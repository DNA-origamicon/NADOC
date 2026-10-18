"""Reference-only refusals must precede full-model recording work.

These tests intentionally retain the authentic native prefix used by the cold
proof suite. They measure no elapsed-time threshold: a known bad selection has
no reason to allocate an undo image, encode recovery, or create output identity.
"""

from fastapi import HTTPException
import pytest

from backend.api import doc_context, routes_connection_versions as routes, state
from backend.api import part_connection_version_commands as commands
from tests.test_part_pending_connection_versions import (
    document as document,
    native_prefix as native_prefix,
    pending_model,
    source as source,
)


def _signature(session):
    return (
        session.design.model_dump_json(), session.revision,
        [item.model_dump_json() for item in session.history],
        [item.model_dump_json() for item in session.redo],
        doc_context.current_request_revision(),
        doc_context.current_request_feature_log_entry_id(),
    )


def _trap_recording_work(monkeypatch):
    identity_calls = []
    for name in ("uuid4", "time"):
        original = getattr(commands, name)

        def observed(*args, _name=name, _original=original, **kwargs):
            identity_calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(commands, name, observed)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Known pending selection refusal reached whole-design recording work")

    for name in ("_snapshot_copy", "encode_design_snapshot", "validate_design",
                 "reconcile_cluster_membership", "_retry_pending_ligations"):
        monkeypatch.setattr(state, name, unexpected)
    monkeypatch.setattr(routes, "_design_response", unexpected)
    return identity_calls


@pytest.mark.parametrize("invalid", ["overhang_a_id", "overhang_b_id", "same_endpoint"])
def test_create_invalid_selection_refuses_before_snapshot_and_identity(document, monkeypatch, invalid):
    session = state._session()
    original, before = session.design, _signature(session)
    selected = {"overhang_a_id": original.overhangs[0].id,
                "overhang_b_id": original.overhangs[1].id}
    if invalid == "same_endpoint":
        selected["overhang_b_id"] = selected["overhang_a_id"]
        status, code, parameter = 422, "invalid_selection", "overhang_b_id"
    else:
        selected[invalid] = "missing"
        status, code, parameter = 404, "missing_reference", invalid
    identity_calls = _trap_recording_work(monkeypatch)

    with pytest.raises(HTTPException) as caught:
        routes.create_connection_version(routes.ConnectionVersionCreateRequest(
            **selected, connection_type="root-to-root"))

    assert caught.value.status_code == status
    assert caught.value.detail["code"] == code
    assert caught.value.detail["references"] == [{
        "kind": "overhang", "identity": selected[parameter], "parameter_path": [parameter],
    }]
    assert identity_calls == []
    assert session.design is original
    assert _signature(session) == before


@pytest.mark.parametrize("action", ["patch", "delete"])
@pytest.mark.parametrize("missing", ["version_id", "overhang_a_id", "overhang_b_id"])
def test_existing_selection_refuses_before_snapshot(document, monkeypatch, action, missing):
    version = pending_model(document)
    prepared = document.copy_with(connection_versions=[version])
    if missing != "version_id":
        identity = getattr(version, missing)
        prepared = prepared.copy_with(overhangs=[item for item in prepared.overhangs if item.id != identity])
    else:
        identity = "missing-version"
    # A broken loaded recipe remains editable; this fixture does not pretend
    # that removing an endpoint is a newly recorded native operation.
    state.load_design(prepared)
    session = state._session()
    original, before = session.design, _signature(session)
    identity_calls = _trap_recording_work(monkeypatch)
    selected_version = identity if missing == "version_id" else version.id

    with pytest.raises(HTTPException) as caught:
        if action == "patch":
            routes.patch_connection_version(selected_version, routes.ConnectionVersionPatchRequest(name="Chosen"))
        else:
            routes.delete_connection_version(selected_version)

    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == "missing_reference"
    assert caught.value.detail["references"] == [{
        "kind": "connection_version" if missing == "version_id" else "overhang",
        "identity": identity, "parameter_path": [missing],
    }]
    assert identity_calls == []
    assert session.design is original
    assert _signature(session) == before


def test_generated_identity_collision_refuses_before_snapshot(document, monkeypatch):
    version = pending_model(document)
    state.load_design(document.copy_with(connection_versions=[version]))
    session = state._session()
    original, before = session.design, _signature(session)
    monkeypatch.setattr(commands, "uuid4", lambda: version.id)
    identity_calls = _trap_recording_work(monkeypatch)

    with pytest.raises(HTTPException) as caught:
        routes.create_connection_version(routes.ConnectionVersionCreateRequest(
            overhang_a_id=version.overhang_a_id, overhang_b_id=version.overhang_b_id,
            connection_type="root-to-root"))

    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_selection"
    assert caught.value.detail["references"] == [{
        "kind": "connection_version", "identity": version.id, "parameter_path": ["version_id"],
    }]
    assert identity_calls == ["uuid4", "time"]
    assert session.design is original
    assert _signature(session) == before


def test_preallocation_placeholder_is_not_an_authored_output_identity(document, monkeypatch):
    version = pending_model(document, version_id="pending")
    state.load_design(document.copy_with(connection_versions=[version]))
    inventory, snapshot, encode = commands._inventory, state._snapshot_copy, state.encode_design_snapshot
    calls = {"inventory": 0, "snapshot": 0, "encode": 0}

    def observed(name, original):
        def wrapped(*args, **kwargs):
            calls[name] += 1
            return original(*args, **kwargs)
        return wrapped

    monkeypatch.setattr(commands, "_inventory", observed("inventory", inventory))
    monkeypatch.setattr(state, "_snapshot_copy", observed("snapshot", snapshot))
    monkeypatch.setattr(state, "encode_design_snapshot", observed("encode", encode))
    routes.create_connection_version(routes.ConnectionVersionCreateRequest(
        overhang_a_id=version.overhang_a_id, overhang_b_id=version.overhang_b_id,
        connection_type="root-to-root"))

    assert state.get_or_404().connection_versions[0] == version
    assert state.get_or_404().connection_versions[1].id != "pending"
    assert calls == {"inventory": 1, "snapshot": 1, "encode": 2}

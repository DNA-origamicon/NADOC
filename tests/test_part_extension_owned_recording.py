"""Organized terminal edits own extensions/history, never placement or topology."""

from threading import Event

import pytest
from fastapi import HTTPException

from backend.api import state, part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.api.part_extension_recording import record
from tests import test_group_organization_recording as groups
from tests.test_group_organization_history import _verified


document = groups.document


@pytest.fixture
def organized(document):
    groups.apply(document)
    return document


def values(session, **fields):
    return [{"strand_id": session.design.strands[0].id, "end": "three_prime",
             "sequence": "AT", "modification": None, "label": None, **fields}]


def apply(session, action="create", items=None, **options):
    return record(action, values(session) if items is None else items,
                  expected_revision=options.pop("expected_revision", session.revision), **options)


def test_owned_crud_preserves_all_other_fields_and_records_one_undo(organized):
    session = organized
    saved = groups.before(session)
    source = session.design
    made, _, ids = apply(session)
    entry = made.feature_log[-1]
    assert entry.params["_proof_version"] == 2 and entry.op_kind == "extension-upsert"
    assert len(session.history) == len(saved[3]) + 1
    for field in type(source).model_fields:
        if field not in {"extensions", "feature_log"}:
            assert getattr(made, field) is getattr(source, field), field
    assert all(a is b for a, b in zip(source.feature_log, made.feature_log))
    assert entry.design_snapshot_gz_b64 and entry.post_state_gz_b64
    assert state.decode_design_snapshot(entry.post_state_gz_b64).extensions == made.extensions
    updated, _, _ = apply(session, "update", [{"sequence": "TT", "modification": "cy3"}], extension_id=ids[0])
    assert updated.extensions[0].id == ids[0] and updated.extensions[0].modification == "cy3"
    cleared, _, _ = apply(session, "update", [{"sequence": "", "label": ""}], extension_id=ids[0])
    assert cleared.extensions[0].sequence is None and cleared.extensions[0].modification == "cy3"
    removed, _, _ = apply(session, "delete", ids)
    assert not removed.extensions and removed.feature_log[-1].params["_proof_version"] == 1
    _verified(removed)
    restored = type(removed).from_json(removed.to_json())
    _verified(restored)
    for _ in range(4):
        state.undo()
    assert session.design.model_dump_json() == saved[1]
    for _ in range(4):
        state.redo()
    assert session.design.model_dump_json() == removed.model_dump_json()


@pytest.mark.parametrize("action", ["batch", "delete"])
def test_empty_action_keeps_source_stacks_and_binds_revision(organized, action, monkeypatch):
    before = groups.before(organized)
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("Empty edit encoded recovery"))
    result, _, ids = apply(organized, action, [])
    assert result is before[0] and ids == []
    groups.unchanged(organized, before)


@pytest.mark.parametrize("refusal", ["missing-revision", "stale", "boolean", "disabled", "strict", "cursor", "cancel"])
def test_refused_admission_never_captures_or_mutates(organized, monkeypatch, refusal):
    from backend.core import part_verification_capture
    kwargs = {}
    if refusal == "missing-revision": kwargs["expected_revision"] = None
    if refusal == "stale": kwargs["expected_revision"] = organized.revision - 1
    if refusal == "boolean": kwargs["expected_revision"] = True
    if refusal == "disabled": monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    if refusal == "strict": policy._install_configuration(policy.HostPolicyConfiguration(default_mode="registered_only"))
    if refusal == "cursor": organized.design.feature_log_cursor = 0
    if refusal == "cancel":
        cancelled = Event(); cancelled.set(); kwargs["cancelled"] = cancelled
    saved = groups.before(organized)
    monkeypatch.setattr(part_verification_capture, "capture", lambda *_a, **_k: pytest.fail("Refusal captured source"))
    with pytest.raises(HTTPException): apply(organized, **kwargs)
    groups.unchanged(organized, saved)


@pytest.mark.parametrize("race", ["source", "revision", "session", "policy", "disable", "cancel"])
def test_outside_lock_preparation_cannot_commit_after_context_change(organized, monkeypatch, race):
    from backend.api import part_extension_owned_recording as owned
    original = owned.build
    cancelled = Event()
    snapshot = {}

    def racing(*args):
        assert state._lock.acquire(blocking=False)
        state._lock.release()
        result = original(*args)
        with state._lock:
            if race == "source": organized.design = organized.design.model_copy(deep=True)
            if race == "revision": organized.revision += 1
            if race == "session": organized.identity = "replacement-incarnation"
            if race == "policy": policy._install_configuration(policy.HostPolicyConfiguration())
            if race == "disable": monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
            if race == "cancel": cancelled.set()
            snapshot["value"] = groups.before(organized)
        return result

    monkeypatch.setattr(owned, "build", racing)
    with pytest.raises(HTTPException): apply(organized, cancelled=cancelled)
    groups.unchanged(organized, snapshot["value"])


@pytest.mark.parametrize("failure", ["validation", "encode", "publish"])
def test_failed_preparation_and_publication_preserve_exact_source(organized, monkeypatch, failure):
    saved = groups.before(organized)
    field = {"validation": "validate_design", "encode": "encode_design_snapshot", "publish": "_bump_revision"}[failure]
    monkeypatch.setattr(state, field, lambda *_: (_ for _ in ()).throw(RuntimeError("injected failure")))
    with pytest.raises(RuntimeError, match="injected"): apply(organized)
    groups.unchanged(organized, saved)


def test_rootless_organization_is_not_given_a_recipe_certificate(organized):
    organized.design = organized.design.copy_with(recipe_root=None)
    made, _, _ = apply(organized)
    assert made.recipe_root is None


def test_extension_growth_is_admitted_before_snapshots_or_native_response(organized, monkeypatch):
    from backend.api import part_group_geometry_budget as geometry_budget
    monkeypatch.setattr(geometry_budget, "MAX_NATIVE_WORK", 100)
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("Over-budget extensions encoded recovery"))
    saved = groups.before(organized)
    with pytest.raises(HTTPException) as caught: apply(organized, items=values(organized, sequence="A" * 1000))
    assert caught.value.detail["code"] == "group_geometry_limit"
    groups.unchanged(organized, saved)


@pytest.mark.parametrize("action,items,identity", [
    ([], [], None), ("delete", [[]], None), ("create", [{}], None),
    ("batch", [None], None), ("batch", [{"strand_id": [], "end": "five_prime"}], None),
    ("update", [{"strand_id": "replacement"}], "extension"),
    ("update", [{"sequence": "AT"}], []),
])
def test_closed_host_input_refuses_malformed_fields_atomically(organized, action, items, identity):
    from backend.api import part_extension_owned_recording as owned
    saved = groups.before(organized)
    with pytest.raises(HTTPException) as caught:
        owned.apply(action, items, extension_id=identity, expected_revision=organized.revision)
    assert caught.value.status_code == 422
    groups.unchanged(organized, saved)

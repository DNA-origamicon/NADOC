"""Ordinary grouping must remain reconstructible from authored inputs.

These are route-level, memory-only regressions. The desktop omits ``log``;
explicit legacy false must not make construction disappear from new history.
Recovery payloads are poisoned before the independent proof oracle runs.
"""

import pytest
from fastapi import HTTPException
from backend.api import crud, doc_context, routes_clusters as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS, command_rows


@pytest.fixture
def document():
    request_revision = doc_context.current_request_revision()
    request_entry = doc_context.current_request_feature_log_entry_id()
    token = set_current_doc("geometry-group-history-test")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=42))
        yield state.get_or_404()
    finally:
        try:
            state.close_session()
        finally:
            reset_current_doc(token)
            doc_context.set_request_revision(request_revision)
            doc_context.set_request_feature_log_entry_id(request_entry)


def _stored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS | {"feature_log", "recipe_root"})


def _proof(design):
    # ClusterCreateLogEntry.cluster_snapshot is the authored grouping input,
    # not recovery geometry. Only cached whole-model/diff outputs are poisoned.
    isolated = Design.model_validate_json(design.model_dump_json())
    for entry in isolated.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "not recovery data"
        elif entry.feature_type == "routing-cluster":
            entry.pre_state_gz_b64 = entry.post_state_gz_b64 = "not recovery data"
            for child in entry.children:
                child.diff_added_b64 = child.diff_removed_b64 = child.diff_modified_b64 = "not a diff"
    return assess_part_history(isolated, execute=execute, dependencies=dependencies)


def _verified(design):
    result = _proof(design)
    assert result["status"] == "verified", result
    assert result["native_editable"] is True
    assert result["checked_commands"] == len(list(command_rows(design, 2000)))


def _create(design, *, name="Arm", **extra):
    body = routes.AddClusterBody(name=name, helix_ids=[design.helices[0].id], **extra)
    response = routes.add_cluster(body)
    current = state.get_or_404()
    cluster = next(c for c in current.cluster_transforms if c.name == name)
    return current, cluster, response


@pytest.mark.parametrize("log_value", ["omitted", False, True])
def test_default_desktop_and_legacy_log_values_record_exact_group_input(document, log_value):
    before = _stored(document)
    depth, revision = state.undo_depth(), state.revision()
    kwargs = {} if log_value == "omitted" else {"log": log_value}
    updated, group, response = _create(document, **kwargs)

    assert len(updated.feature_log) == len(document.feature_log) + 1
    row = updated.feature_log[-1]
    assert row.feature_type == "cluster_create"
    assert row.proof_version == 1
    assert row.cluster_id == group.id
    assert row.cluster_snapshot == group
    assert row.helix_ids == [document.helices[0].id]
    assert row.domain_ids == []
    assert updated.recipe_root == document.recipe_root
    assert state.undo_depth() == depth + 1
    assert state.revision() == revision + 1 == response["revision"]
    assert _stored(document) == before
    _verified(updated)


def test_default_group_then_direct_move_commit_replays_without_cached_outputs(document):
    grouped, group, _ = _create(document)
    depth, revision = state.undo_depth(), state.revision()
    response = routes.update_cluster(group.id, routes.PatchClusterBody(
        translation=[2, -3, 4], rotation=[0, 0, 0, 1], pivot=[1, 2, 3], commit=True,
    ))
    moved = state.get_or_404()

    assert len(moved.feature_log) == 3
    assert [row.feature_type for row in moved.feature_log] == ["snapshot", "cluster_create", "cluster_op"]
    assert moved.feature_log[-1].cluster_id == group.id
    assert next(c for c in moved.cluster_transforms if c.id == group.id).translation == [2, -3, 4]
    assert moved.helices == grouped.helices and moved.strands == grouped.strands
    assert state.undo_depth() == depth + 1
    assert state.revision() == revision + 1 == response["revision"]
    _verified(moved)


def test_grouping_between_nicks_preserves_chronological_routing_boundaries(document):
    domain = document.strands[0].domains[0]
    for index in (10, 20):
        crud.add_nick(crud.NickRequest(
            helix_id=domain.helix_id, bp_index=index, direction=domain.direction,
        ))
        if index == 10:
            _create(state.get_or_404())
    final = state.get_or_404()
    assert [row.feature_type for row in final.feature_log] == [
        "snapshot", "routing-cluster", "cluster_create", "routing-cluster",
    ]
    assert len(final.feature_log[1].children) == len(final.feature_log[3].children) == 1
    _verified(final)


def test_pose_confirm_records_previewed_fields_without_logging_each_preview(document):
    grouped, group, _ = _create(document, log=True)
    depth = state.undo_depth()
    routes.update_cluster(group.id, routes.PatchClusterBody(
        translation=[3, 4, 5], name="Moved arm", color="#123456", opacity=0.5,
    ))
    assert state.undo_depth() == depth
    assert len(state.get_or_404().feature_log) == len(grouped.feature_log)
    routes.update_cluster(group.id, routes.PatchClusterBody(commit=True))
    committed = state.get_or_404()
    assert state.undo_depth() == depth + 1
    assert committed.feature_log[-1].translation == [3, 4, 5]
    assert committed.feature_log[-1].authored_fields["name"] == "Moved arm"
    _verified(committed)


def test_group_and_direct_move_each_have_exact_undo_redo_history(document):
    states = [_stored(document)]
    grouped, group, _ = _create(document)
    states.append(_stored(grouped))
    routes.update_cluster(group.id, routes.PatchClusterBody(translation=[1, -2, 3], commit=True))
    states.append(_stored(state.get_or_404()))
    _verified(state.get_or_404())

    for expected in reversed(states[:-1]):
        restored, _ = state.undo()
        assert _stored(restored) == expected
        _verified(restored)
    for expected in states[1:]:
        restored, _ = state.redo()
        assert _stored(restored) == expected
        _verified(restored)


def test_grouping_preserves_overlapping_intentional_groups_and_domain_membership(document):
    first, group, _ = _create(document, name="First", log=True)
    original_group = group.model_dump(mode="json")
    domain = {"strand_id": document.strands[0].id, "domain_index": 0}
    routes.add_cluster(routes.AddClusterBody(name="Domain selection", helix_ids=[], domain_ids=[domain]))
    domain_grouped = state.get_or_404()
    domain_group = next(c for c in domain_grouped.cluster_transforms if c.name == "Domain selection")
    assert domain_group.helix_ids == []
    assert [ref.model_dump(mode="json") for ref in domain_group.domain_ids] == [domain]
    assert domain_grouped.cluster_transforms[:-1] == first.cluster_transforms
    final, second_group, _ = _create(domain_grouped, name="Overlapping selection")
    assert next(c for c in final.cluster_transforms if c.id == group.id).model_dump(mode="json") == original_group
    assert second_group.helix_ids == group.helix_ids
    _verified(final)


@pytest.mark.parametrize("failure", ["validation", "publication", "cancellation"])
def test_group_creation_failure_keeps_source_stacks_and_revision(document, monkeypatch, failure):
    from backend.core import validator

    # A real redo entry makes premature clear/append visible, not only a depth
    # check against an empty stack. Its grouping uses explicit logging so the
    # setup is valid even before the default-creation bug is repaired.
    _create(document, name="Redo group", log=True)
    state.undo()
    source = state.get_or_404()
    session = state._session()
    stored = _stored(source)
    history, redo = list(session.history), list(session.redo)
    revision = state.revision()
    request_revision = doc_context.current_request_revision()
    request_entry = doc_context.current_request_feature_log_entry_id()

    class Cancelled(BaseException):
        pass

    error_type = Cancelled if failure == "cancellation" else RuntimeError
    # Restore injected faults before any assertions or document teardown, even
    # when the route fails the expected rollback contract or raises BaseException.
    with monkeypatch.context() as faults:
        if failure == "validation":
            def reject_validation(_candidate):
                raise error_type("group validation failed")
            faults.setattr(validator, "validate_design", reject_validation)
            faults.setattr(state, "validate_design", reject_validation)
        else:
            original_bump = state._bump_revision

            def reject_publication(target):
                original_bump(target)
                raise error_type("group publication failed")
            faults.setattr(state, "_bump_revision", reject_publication)

        with pytest.raises(error_type, match="group .* failed"):
            _create(source)
    assert state.get_or_404() is source
    assert _stored(source) == stored
    assert list(session.history) == history
    assert list(session.redo) == redo
    assert state.revision() == revision
    assert doc_context.current_request_revision() == request_revision
    assert doc_context.current_request_feature_log_entry_id() == request_entry


def test_new_group_does_not_bless_or_reconstruct_unlogged_legacy_input(document):
    legacy = document.copy_with(recipe_root=None, feature_log=[])
    state.load_design(legacy)
    updated, group, _ = _create(legacy)
    assert group.id in {c.id for c in updated.cluster_transforms}
    assert updated.recipe_root is None
    result = _proof(updated)
    assert result["status"] == "unverified"
    assert result["native_editable"] is False
    assert any(issue["code"] == "missing_recipe_root" for issue in result["issues"])


@pytest.mark.parametrize("cursor,sub_cursor", [(-2, None), (0, None), (0, 0)])
def test_historical_group_creation_refuses_before_building_or_allocating(document, monkeypatch, cursor, sub_cursor):
    from backend.api import part_group_recording

    historical = document.copy_with(feature_log_cursor=cursor, feature_log_sub_cursor=sub_cursor)
    state.load_design(historical)
    before = historical.model_dump(mode="json")
    depth, revision = state.undo_depth(), state.revision()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Historical grouping must refuse before allocating or building")

    monkeypatch.setattr(part_group_recording, "ClusterRigidTransform", unexpected)
    monkeypatch.setattr(part_group_recording, "build", unexpected)
    with pytest.raises(HTTPException) as caught:
        _create(historical)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "historical_cursor"
    assert "latest" in caught.value.detail["message"]
    assert state.get_or_404() is historical
    assert historical.model_dump(mode="json") == before
    assert state.undo_depth() == depth and state.revision() == revision


def test_group_creation_holds_one_nonreentrant_lock_without_proof_or_reconciliation(document, monkeypatch):
    from backend.api import part_group_recording as recording
    from backend.api import part_proof_commands
    from backend.core import part_history_contract

    class GuardedLock:
        held = False

        def __enter__(self):
            assert not self.held, "Group creation reacquired the non-reentrant state lock"
            self.held = True
            return self

        def __exit__(self, *_args):
            self.held = False

    lock = GuardedLock()
    events = []
    build = recording.build
    validate = state.validate_design
    snapshot = state._snapshot_copy
    publish = recording.publish_replacement

    def grouped(kind, source, params):
        assert lock.held and source is document
        events.append("build")
        return build(kind, source, params)

    def validated(candidate):
        assert lock.held and candidate is not document
        events.append("validate")
        return validate(candidate)

    def copied(source):
        assert lock.held and source is document
        events.append("undo")
        return snapshot(source)

    def published(session, candidate):
        assert lock.held and session.design is document
        events.append("publish")
        return publish(session, candidate)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Group creation must not run full proof or topology reconciliation")

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", lock)
        hooks.setattr(recording, "build", grouped)
        hooks.setattr(state, "validate_design", validated)
        hooks.setattr(state, "_snapshot_copy", copied)
        hooks.setattr(recording, "publish_replacement", published)
        hooks.setattr(state, "reconcile_cluster_membership", unexpected)
        hooks.setattr(state, "_retry_pending_ligations", unexpected)
        hooks.setattr(part_history_contract, "assess_part_history", unexpected)
        hooks.setattr(part_proof_commands, "execute", unexpected)
        routes.add_cluster(routes.AddClusterBody(name="Single-lock group", helix_ids=[document.helices[0].id]))
    assert not lock.held
    assert events == ["build", "validate", "publish", "undo"]
    _verified(state.get_or_404())

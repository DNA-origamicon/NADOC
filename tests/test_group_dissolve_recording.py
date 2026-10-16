"""A group dissolve is one native, undoable, failure-atomic history command."""

from dataclasses import replace

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, routes_clusters as routes, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design
from backend.core.part_dependencies import Resource
from tests.test_geometry_group_history import document as document, _create, _proof, _stored, _verified
from tests.test_group_edit_recording import _snapshot, _unchanged


@pytest.mark.parametrize("batch", [False, True])
def test_dissolve_records_only_inputs_and_one_undo_with_exact_geometry(document, batch, monkeypatch):
    source, group, _ = _create(document)
    source, other, _ = _create(source, name="Other")
    selected = [group.id, other.id] if batch else [group.id]
    before, depth, revision = _stored(source), state.undo_depth(), state.revision()
    response_helper = crud._design_response_with_geometry

    def response(candidate, report, **kwargs):
        assert state._lock.acquire(blocking=False), "Response geometry must run outside publication lock"
        state._lock.release()
        assert candidate is state.get_or_404()
        assert kwargs == {"normalize_legacy": False, "preserve_feature_log_id": candidate.feature_log[-1].id}
        return response_helper(candidate, report, **kwargs)

    monkeypatch.setattr(crud, "_design_response_with_geometry", response)
    result = (routes.dissolve_clusters(routes.DissolveClustersBody(cluster_ids=selected))
              if batch else routes.delete_cluster(group.id))
    current = state.get_or_404()
    entry = current.feature_log[-1]
    assert entry.op_kind == "cluster-dissolve"
    assert entry.params == {"_proof_version": 1, "cluster_ids": selected}
    assert entry.timestamp
    assert [c.id for c in current.cluster_transforms] == [c.id for c in source.cluster_transforms if c.id not in selected]
    assert current.helices == source.helices and current.strands == source.strands
    assert state.undo_depth() == depth + 1
    assert state.revision() == revision + 1 == result["revision"]
    assert result["nucleotides"] and result["helix_axes"]
    assert result["design"]["feature_log"][-1] == entry.model_dump(mode="json")
    assert _stored(source) == before
    assert state.decode_design_snapshot(entry.design_snapshot_gz_b64).cluster_transforms == source.cluster_transforms
    assert state.decode_design_snapshot(entry.post_state_gz_b64).cluster_transforms == current.cluster_transforms
    assert Design.model_validate_json(current.model_dump_json()) == current
    _verified(current)
    restored, _ = state.undo()
    assert _stored(restored) == before
    restored, _ = state.redo()
    assert _stored(restored) == _stored(current)
    _verified(restored)


def test_delete_dissolve_feature_restores_group_and_upstream_edit_replays_it(document):
    grouped, group, _ = _create(document)
    routes.delete_cluster(group.id)
    dissolved = state.get_or_404()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 52}))
    changed = state.get_or_404()
    assert changed.helices[0].length_bp == 52
    assert group.id not in {c.id for c in changed.cluster_transforms}
    _verified(changed)
    crud.delete_feature(len(changed.feature_log) - 1)
    assert group.id in {c.id for c in state.get_or_404().cluster_transforms}
    _verified(state.get_or_404())
    assert len(dissolved.feature_log) == len(grouped.feature_log) + 1


def test_group_producer_delete_reports_dissolve_consumer(document):
    grouped, group, _ = _create(document)
    routes.delete_cluster(group.id)
    before = _snapshot()
    result = crud.delete_feature(len(grouped.feature_log) - 1)
    assert result["needs_cascade_decision"]
    assert any(row["index"] == len(grouped.feature_log) for row in result["dependents"])
    _unchanged(before)
    crud.delete_feature(len(grouped.feature_log) - 1, cascade=True)
    _verified(state.get_or_404())


def test_missing_dissolve_input_can_be_repaired_without_reading_recovery(document, monkeypatch):
    from backend.api.part_recipe_repair import prepare_repair

    _, group, _ = _create(document)
    routes.delete_cluster(group.id)
    source = Design.model_validate_json(state.get_or_404().model_dump_json())
    row = source.feature_log[-1]
    row.params = {"_proof_version": 1, "cluster_ids": ["missing-group"]}
    for entry in source.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "not an input"
    before = source.model_dump_json()
    diagnostic = _proof(source)
    assert diagnostic["status"] == "failed"
    assert any(issue["code"] == "missing_reference" for issue in diagnostic["issues"])

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Group repair must use inputs, not recovery")

    monkeypatch.setattr(state, "decode_design_snapshot", unexpected)
    result = prepare_repair(source, {"repair_version": 1, "expected_design_id": source.id,
        "expected_revision": 7, "actions": [{"action": "set_input", "feature_id": row.id,
            "parameter_path": ["cluster_ids", 0], "expected_old": "missing-group", "value": group.id}]},
        source_revision=7, executor=execute, dependency_resolver=dependencies)
    assert result["status"] == "ready", result
    candidate = result["candidate"]
    assert group.id not in {c.id for c in candidate.cluster_transforms}
    _verified(candidate)
    assert source.model_dump_json() == before


def test_dissolve_dependencies_are_bounded_typed_and_conservative():
    params = {"_proof_version": 1, "cluster_ids": ["a", "b"]}
    contract = dependencies("cluster-dissolve", params)
    assert contract.known and contract.barrier
    assert {Resource("cluster", "a"), Resource("cluster", "b"), Resource("part", "topology")} <= contract.reads
    assert contract.reads <= contract.writes
    for invalid in ({**params, "cluster_ids": ["a", "a"]}, {**params, "unexpected": True},
                    {**params, "_proof_version": True}, {**params, "_generated_scope": {}}):
        assert not dependencies("cluster-dissolve", invalid).known


def test_dissolve_executor_has_no_reconciliation_or_retry(document, monkeypatch):
    from backend.core import cluster_reconcile, lattice
    grouped, group, _ = _create(document)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Dissolve must not recreate groups or ligate topology")

    monkeypatch.setattr(cluster_reconcile, "reconcile_cluster_membership", unexpected)
    monkeypatch.setattr(lattice, "retry_pending_ligations", unexpected)
    result = execute("cluster-dissolve", grouped, {"_proof_version": 1, "cluster_ids": [group.id]})
    assert group.id not in {c.id for c in result.cluster_transforms}


@pytest.mark.parametrize("failure", ["snapshot", "validation", "publication", "cancellation"])
def test_dissolve_failure_preserves_source_and_both_stacks(document, monkeypatch, failure):
    source, group, _ = _create(document)
    _create(source, name="Redo-only")
    state.undo()
    before = _snapshot()

    class Cancelled(BaseException):
        pass

    error = Cancelled if failure == "cancellation" else RuntimeError
    with monkeypatch.context() as fault:
        if failure in {"snapshot", "validation"}:
            def fail(*_args, **_kwargs):
                raise error("dissolve failed")
            fault.setattr(state, "encode_design_snapshot" if failure == "snapshot" else "validate_design", fail)
        else:
            bump = state._bump_revision

            def fail(session):
                bump(session)
                raise error("dissolve failed")
            fault.setattr(state, "_bump_revision", fail)
        with pytest.raises(error, match="dissolve failed"):
            routes.delete_cluster(group.id)
    _unchanged(before)


@pytest.mark.parametrize("replacement", ["source", "session", "revision"])
def test_dissolve_cannot_overwrite_replaced_source_or_session(document, monkeypatch, replacement):
    source, group, _ = _create(document)
    validate = state.validate_design
    observed = []

    def validated(candidate):
        report = validate(candidate)
        session = state._session()
        if replacement == "source":
            session.design = source.model_copy(deep=True)
        elif replacement == "session":
            state._sessions[doc_context.get_current_doc()] = replace(session, identity="replacement")
        else:
            session.revision += 1
        observed.append(_snapshot())
        return report

    monkeypatch.setattr(state, "validate_design", validated)
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster(group.id)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "source_changed"
    _unchanged(observed[0])


@pytest.mark.parametrize("cursor,sub_cursor", [(-2, None), (0, None), (-1, 0)])
def test_historical_dissolve_refuses_before_encoding(document, monkeypatch, cursor, sub_cursor):
    source, group, _ = _create(document)
    state.load_design(source.copy_with(feature_log_cursor=cursor, feature_log_sub_cursor=sub_cursor))
    before = _snapshot()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Historical dissolve must refuse before serialization")

    monkeypatch.setattr(state, "encode_design_snapshot", unexpected)
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster(group.id)
    assert caught.value.detail["code"] == "historical_cursor"
    _unchanged(before)


def test_atomic_batch_missing_target_preserves_every_group(document):
    _, group, _ = _create(document)
    before = _snapshot()
    with pytest.raises(HTTPException) as caught:
        routes.dissolve_clusters(routes.DissolveClustersBody(cluster_ids=[group.id, "absent"]))
    assert caught.value.detail["code"] == "missing_reference"
    _unchanged(before)


def test_rootless_dissolve_never_infers_recipe_or_default_membership(document):
    source, group, _ = _create(document)
    legacy = source.copy_with(recipe_root=None, feature_log=[])
    state.load_design(legacy)
    routes.delete_cluster(group.id)
    result = state.get_or_404()
    assert result.recipe_root is None
    assert result.cluster_transforms == [c for c in legacy.cluster_transforms if c.id != group.id]
    assert len(result.feature_log) == 1
    assert _proof(result)["status"] == "unverified"


def test_rootless_dissolve_all_survives_subsequent_normalized_reads(document):
    from tests.test_group_dissolve_command import source

    legacy = source()
    state.load_design(legacy)
    routes.dissolve_clusters(routes.DissolveClustersBody(cluster_ids=[c.id for c in legacy.cluster_transforms]))
    accepted = state.get_or_404()
    before = _snapshot()
    assert accepted.cluster_transforms == [] and accepted.recipe_root is None
    for _ in range(2):
        response = crud._design_response(accepted, state.validate_design(accepted))
        assert response["design"]["cluster_transforms"] == []
        _unchanged(before)
    restored = Design.model_validate_json(accepted.model_dump_json())
    assert crud._ensure_default_cluster(restored, persist=False) is restored
    assert restored.cluster_transforms == [] and restored.recipe_root is None


def test_dissolve_never_runs_full_proof_during_recording(document, monkeypatch):
    from backend.core import part_history_contract
    _, group, _ = _create(document)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Ordinary dissolve must not run history proof or reconciliation")

    monkeypatch.setattr(part_history_contract, "assess_part_history", unexpected)
    monkeypatch.setattr(state, "reconcile_cluster_membership", unexpected)
    monkeypatch.setattr(state, "_retry_pending_ligations", unexpected)
    routes.delete_cluster(group.id)


def test_protected_loadout_refuses_before_encoding(document, monkeypatch):
    _, group, _ = _create(document)
    before = _snapshot()

    def protected(*_args):
        raise HTTPException(409, detail={"code": "protected_loadout"})

    monkeypatch.setattr(state, "_assert_active_loadout_editable", protected)
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster(group.id)
    assert caught.value.detail["code"] == "protected_loadout"
    _unchanged(before)


@pytest.mark.parametrize("failure", ["retained", "encoding"])
def test_recovery_limit_failure_never_publishes_or_changes_old_payloads(document, monkeypatch, failure):
    from backend.core import part_recovery_storage
    from backend.core.part_capture_graph import CaptureLimit
    from backend.api import part_recovery_budget

    _, group, _ = _create(document)
    before = _snapshot()
    if failure == "retained":
        def refuse(*_args, **_kwargs):
            raise CaptureLimit("Retained recovery exceeds its publication byte allowance")
        monkeypatch.setattr(part_recovery_storage, "retained_recovery_bytes", refuse)

        def unexpected(*_args, **_kwargs):
            raise AssertionError("Existing recovery must be admitted before encoding")
        monkeypatch.setattr(state, "encode_design_snapshot", unexpected)
    else:
        # Exercise the real charge path with a tiny allowance, no bulk payload.
        original = part_recovery_budget.RecoveryBudget
        monkeypatch.setattr(part_recovery_budget, "RecoveryBudget", lambda _limit: original(1))
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster(group.id)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "group_recovery_limit"
    _unchanged(before)

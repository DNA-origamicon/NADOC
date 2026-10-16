"""Automatic crossover work uses an owned source outside the publication lock."""

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, part_auto_commands, state
from backend.api.part_proof_commands import execute
from backend.core.models import Design, DesignLoadout
from tests.test_geometry_routing_recording import _GuardedLock, _authoring, _signature, _verified


@pytest.fixture
def document(request):
    revision = doc_context.current_request_revision()
    entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc("geometry-auto-crossover-recording-test")
    try:
        crud.create_bundle(crud.BundleRequest(
            cells=[[0, 0], [0, 1], [0, 2]], length_bp=48,
            lattice_type=getattr(request, "param", "HONEYCOMB"),
        ))
        yield state.get_or_404()
    finally:
        try:
            state.close_session()
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(revision)
            doc_context.set_request_feature_log_entry_id(entry)


def test_native_auto_crossover_uses_detached_input_outside_lock(document, monkeypatch):
    lock, stages = _GuardedLock(), []
    original = part_auto_commands.crossovers

    def native(source, *, history_seed):
        assert not lock.held, "Fixed-point crossover work must not hold the global state lock"
        assert source is not document, "Native routing received the live mutable source"
        assert source.helices[0] is not document.helices[0]
        assert source.feature_log[0] is not document.feature_log[0]
        stages.append("native")
        return original(source, history_seed=history_seed)

    def counted(name, callback):
        def call(*args, **kwargs):
            assert lock.held, f"{name} ran without source/publication ownership"
            stages.append(name)
            return callback(*args, **kwargs)
        return call

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", lock)
        hooks.setattr(part_auto_commands, "crossovers", native)
        for name in ("_snapshot_copy", "reconcile_cluster_membership", "_retry_pending_ligations"):
            hooks.setattr(state, name, counted(name, getattr(state, name)))
        crud.auto_crossover()
    assert not lock.held
    # The extra owned-source copy is explicit; the existing recorder still owns
    # its undo copy and single reconciliation/retry. This is not a latency claim.
    assert stages == [
        "_snapshot_copy", "native", "_snapshot_copy",
        "reconcile_cluster_membership", "_retry_pending_ligations",
    ]


def test_interleaved_nick_survives_stale_auto_crossover_refusal(document, monkeypatch):
    domain = document.strands[0].domains[0]
    interleaved = []

    def another_edit():
        crud.add_nick(crud.NickRequest(
            helix_id=domain.helix_id, bp_index=12, direction=domain.direction,
        ))
        interleaved.append(_signature())

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", _GuardedLock(another_edit))
        with pytest.raises(HTTPException) as caught:
            crud.auto_crossover()
    assert caught.value.status_code == 409
    assert len(interleaved) == 1 and _signature() == interleaved[0]
    assert not any(getattr(row, "op_kind", None) == "auto-crossover"
                   for row in state.get_or_404().feature_log)
    _verified(state.get_or_404())


def test_protected_loadout_refuses_before_source_copy_or_native_work(document, monkeypatch):
    loadout = DesignLoadout(name="Protected", protected=True)
    source = document.copy_with(loadouts=[loadout], active_loadout_id=loadout.id)
    state.load_design(source)
    before = _signature()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Protected loadout reached automatic crossover preparation")

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_snapshot_copy", unexpected)
        hooks.setattr(part_auto_commands, "crossovers", unexpected)
        with pytest.raises(HTTPException) as caught:
            crud.auto_crossover()
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "protected_simulation_loadout"
    assert _signature() == before and state.get_or_404() is source


def test_policy_roundtrip_cannot_publish_an_old_automatic_routing_capture(document, monkeypatch):
    from backend.api import part_publication_policy as policy

    original_policy = policy.current_configuration()
    original = part_auto_commands.crossovers
    before = _signature()

    def native(source, *, history_seed):
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(
            document_modes={doc_context.get_current_doc(): "registered_only"},
        ))
        state.configure_part_publication_policy(original_policy)
        return original(source, history_seed=history_seed)

    try:
        with monkeypatch.context() as hooks:
            hooks.setattr(part_auto_commands, "crossovers", native)
            with pytest.raises(HTTPException) as caught:
                crud.auto_crossover()
        assert caught.value.status_code == 409
        assert _signature() == before and state.get_or_404() is document
    finally:
        state.configure_part_publication_policy(original_policy)


def test_strict_policy_refuses_before_source_copy_or_native_work(document, monkeypatch):
    from backend.api import part_publication_policy as policy

    original_policy = policy.current_configuration()
    before = _signature()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Strict policy reached automatic crossover preparation")

    try:
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(
            document_modes={doc_context.get_current_doc(): "registered_only"},
        ))
        with monkeypatch.context() as hooks:
            hooks.setattr(state, "_snapshot_copy", unexpected)
            hooks.setattr(part_auto_commands, "crossovers", unexpected)
            with pytest.raises(HTTPException) as caught:
                crud.auto_crossover()
        assert caught.value.status_code == 403
        assert caught.value.detail["code"] == "construction_policy"
    finally:
        state.configure_part_publication_policy(original_policy)
    assert _signature() == before and state.get_or_404() is document


@pytest.mark.parametrize("document", ["HONEYCOMB", "SQUARE"], indirect=True)
def test_native_fixed_point_seed_stats_record_and_replay_are_preserved(document, monkeypatch, capsys):
    source = Design.model_validate_json(document.model_dump_json())
    depth, revision = state.undo_depth(), state.revision()
    original, observed = part_auto_commands.crossovers, []

    def native(design, *, history_seed):
        updated, stats = original(design, history_seed=history_seed)
        observed.append((history_seed, dict(stats)))
        return updated, stats

    with monkeypatch.context() as hooks:
        hooks.setattr(part_auto_commands, "crossovers", native)
        response = crud.auto_crossover()
    assert len(observed) == 1
    seed, stats = observed[0]
    assert stats["placed"] > 0
    updated = state.get_or_404()
    row = updated.feature_log[-1]
    assert row.op_kind == "auto-crossover" and row.label == "Auto-crossover"
    assert row.params == {"history_seed": seed, **stats, "_proof_version": 1}
    assert f"[AUTO XOVER] placed {stats['placed']} crossovers" in capsys.readouterr().out
    expected = execute("auto-crossover", source, row.params)
    assert _authoring(updated) == _authoring(expected)
    assert _authoring(document) == _authoring(source)
    assert len(updated.feature_log) == len(source.feature_log) + 1
    assert state.undo_depth() == depth + 1
    assert state.revision() == revision + 1 == response["revision"]
    assert response.get("partial_geometry", False) is False
    _verified(updated)
    restored, _ = state.undo()
    assert _authoring(restored) == _authoring(source)
    restored, _ = state.redo()
    assert _authoring(restored) == _authoring(expected)


@pytest.mark.parametrize("stage", ["native", "reconcile", "validate", "publish", "cancel"])
def test_auto_crossover_failure_preserves_document_stacks_and_markers(document, monkeypatch, stage):
    state._session().redo.append(Design())
    before = _signature()
    error = KeyboardInterrupt if stage == "cancel" else RuntimeError

    def fail(*_args, **_kwargs):
        raise error("automatic routing failure")

    def fail_native(source, **_kwargs):
        # Isolation must hold even if the native call fails after a local write.
        source.metadata.name = "private unfinished routing"
        fail()

    bump = state._bump_revision

    def fail_publication(session):
        bump(session)
        fail()

    with monkeypatch.context() as hooks:
        if stage == "native":
            hooks.setattr(part_auto_commands, "crossovers", fail_native)
        elif stage in {"reconcile", "validate"}:
            hooks.setattr(state, "reconcile_cluster_membership" if stage == "reconcile"
                          else "validate_design", fail)
        else:
            hooks.setattr(state, "_bump_revision", fail_publication)
        with pytest.raises(error, match="automatic routing failure"):
            crud.auto_crossover()
    assert _signature() == before

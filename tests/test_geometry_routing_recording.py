"""Routing records its owned source and never conceals failed selections.

Small route-level fixtures retain the real recorder, reconciliation and response.
The interleave is deterministic: another authored edit runs at the first released
state lock, rather than relying on scheduling or wall-clock sleeps.
"""

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core import lattice
from backend.core.models import Design, DesignLoadout, StrandExtension
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS, command_rows
from backend.core.positional_refs import resolve


@pytest.fixture
def document():
    revision = doc_context.current_request_revision()
    entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc("geometry-routing-recording-test")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0], [0, 1], [0, 2]], length_bp=42))
        yield state.get_or_404()
    finally:
        try:
            state.close_session()
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(revision)
            doc_context.set_request_feature_log_entry_id(entry)


def _request(design, *, seam=False):
    strands = [s for s in design.strands if s.strand_type == "staple"]
    return crud.ForcedLigationRequest(
        three_prime_strand_id=strands[0].id, five_prime_strand_id=strands[1].id,
        is_periodic_seam=seam,
    )


def _authoring(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


def _verified(design):
    isolated = Design.model_validate_json(design.model_dump_json())
    for row in isolated.feature_log:
        if row.feature_type == "snapshot":
            row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
        elif row.feature_type == "routing-cluster":
            row.pre_state_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
            for child in row.children:
                child.diff_added_b64 = child.diff_removed_b64 = child.diff_modified_b64 = "poisoned diff"
    result = assess_part_history(isolated, execute=execute, dependencies=dependencies)
    assert result["status"] == "verified", result
    assert result["native_editable"] is True
    assert result["checked_commands"] == len(list(command_rows(isolated, 100)))


class _GuardedLock:
    def __init__(self, released=None):
        self.held = False
        self.released = released

    def __enter__(self):
        assert not self.held, "Routing reacquired the non-reentrant state lock"
        self.held = True
        return self

    def __exit__(self, *_args):
        self.held = False
        callback, self.released = self.released, None
        if callback is not None:
            callback()


def test_native_ligation_runs_only_inside_the_recording_lock(document, monkeypatch):
    lock = _GuardedLock()
    original = lattice._ligate
    observed = []
    stages = []

    def counted(name, callback):
        def call(*args, **kwargs):
            assert lock.held, f"{name} ran outside the recording lock"
            stages.append(name)
            return callback(*args, **kwargs)
        return call

    def guarded(source, first, second):
        assert lock.held, "Forced ligation built before acquiring its recording lock"
        observed.append((source, first.id, second.id))
        return original(source, first, second)

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", lock)
        hooks.setattr(lattice, "_ligate", guarded)
        for name in ("_snapshot_copy", "reconcile_cluster_membership", "_retry_pending_ligations"):
            hooks.setattr(state, name, counted(name, getattr(state, name)))
        crud.forced_ligation(_request(document))
    assert len(observed) == 1 and observed[0][0] is document
    assert stages == ["_snapshot_copy", "reconcile_cluster_membership", "_retry_pending_ligations"]
    assert not lock.held


def test_edit_between_source_read_and_recording_cannot_be_overwritten(document, monkeypatch):
    third = [s for s in document.strands if s.strand_type == "staple"][2]
    domain = third.domains[0]
    depth, revision = state.undo_depth(), state.revision()
    interleaved = []

    def another_edit():
        crud.add_nick(crud.NickRequest(
            helix_id=domain.helix_id, bp_index=12, direction=domain.direction,
        ))
        interleaved.append(True)

    lock = _GuardedLock(another_edit)
    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", lock)
        crud.forced_ligation(_request(document))
    final = state.get_or_404()
    assert interleaved == [True]
    fragments = [s for s in final.strands if s.strand_type == "staple"
                 and any(d.helix_id == domain.helix_id for d in s.domains)]
    assert len(fragments) == 2, "The ligation discarded the interleaved nick"
    assert state.undo_depth() == depth + 2 and state.revision() == revision + 2
    assert [kind for _identity, kind, _params in command_rows(final, 100)].count("nick") == 1
    _verified(final)


@pytest.mark.parametrize("seam", [False, True])
def test_one_record_undo_revision_and_input_only_replay_match_native_builder(document, seam):
    source = Design.model_validate_json(document.model_dump_json())
    before = _authoring(document)
    body = _request(document, seam=seam)
    depth, revision = state.undo_depth(), state.revision()
    response = crud.forced_ligation(body)
    updated = state.get_or_404()
    cluster = updated.feature_log[-1]
    assert cluster.feature_type == "routing-cluster" and len(cluster.children) == 1
    row = cluster.children[0]
    assert row.op_subtype == "forced-ligation-create"
    # Recorded by position (v2); resolving against the source gives the native request.
    assert row.params["_proof_version"] == 2
    assert resolve("forced-ligation-create", row.params, source) == {
        **body.model_dump(mode="json"), "_fl_id": updated.forced_ligations[-1].id, "_proof_version": 1}
    expected = execute("forced-ligation-create", source, row.params)
    assert _authoring(updated) == _authoring(expected)
    assert _authoring(document) == before
    assert state.undo_depth() == depth + 1
    assert state.revision() == revision + 1 == response["revision"]
    assert response["partial_geometry"] is True
    assert set(response["changed_helix_ids"]) == {
        source.find_strand(body.three_prime_strand_id).domains[-1].helix_id,
        source.find_strand(body.five_prime_strand_id).domains[0].helix_id,
    }
    _verified(updated)
    restored, _ = state.undo()
    assert _authoring(restored) == before
    restored, _ = state.redo()
    assert _authoring(restored) == _authoring(expected)
    _verified(restored)


@pytest.mark.parametrize("owner", ["three_prime_strand_id", "five_prime_strand_id"])
def test_selected_extension_keeps_full_response_fallback(document, monkeypatch, owner):
    body = _request(document)
    source = document.copy_with(extensions=[StrandExtension(
        strand_id=getattr(body, owner), end="three_prime", sequence="TT",
    )])
    state.load_design(source)
    scopes = []
    original = crud._design_response_with_geometry

    def response(*args, **kwargs):
        scopes.append(kwargs.get("changed_helix_ids"))
        return original(*args, **kwargs)

    with monkeypatch.context() as hooks:
        hooks.setattr(crud, "_design_response_with_geometry", response)
        result = crud.forced_ligation(body)
    assert scopes == [None]
    assert result.get("partial_geometry", False) is False


def test_protected_loadout_refuses_before_native_work(document, monkeypatch):
    loadout = DesignLoadout(name="Protected", protected=True)
    source = document.copy_with(loadouts=[loadout], active_loadout_id=loadout.id)
    state.load_design(source)
    before = source.model_dump(mode="json")
    depth, revision = state.undo_depth(), state.revision()

    def unexpected(*_args):
        raise AssertionError("Protected loadout reached native ligation")

    with monkeypatch.context() as hooks:
        hooks.setattr(lattice, "_ligate", unexpected)
        with pytest.raises(HTTPException) as caught:
            crud.forced_ligation(_request(source))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "protected_simulation_loadout"
    assert state.get_or_404() is source and source.model_dump(mode="json") == before
    assert state.undo_depth() == depth and state.revision() == revision


@pytest.mark.parametrize("side", ["three_prime_strand_id", "five_prime_strand_id", "self"])
def test_existing_missing_and_self_target_errors_remain_exact(document, side):
    params = _request(document).model_dump()
    if side == "self":
        params["five_prime_strand_id"] = params["three_prime_strand_id"]
        status, detail = 409, "Cannot ligate a strand to itself (would create circular strand)."
    else:
        params[side] = "missing"
        status = 404
        detail = f"{'3' if side.startswith('three') else '5'}' strand 'missing' not found."
    before = document.model_dump(mode="json")
    depth, revision = state.undo_depth(), state.revision()
    with pytest.raises(HTTPException) as caught:
        crud.forced_ligation(crud.ForcedLigationRequest(**params))
    assert caught.value.status_code == status and caught.value.detail == detail
    assert state.get_or_404() is document and document.model_dump(mode="json") == before
    assert state.undo_depth() == depth and state.revision() == revision


@pytest.mark.parametrize("stage", ["build", "validate", "publish", "cancel"])
def test_failure_restores_persisted_source_stacks_and_request_markers(document, monkeypatch, stage):
    session = state._session()
    session.redo.append(Design())
    before = (session.design.model_dump(mode="json"), [d.model_dump(mode="json") for d in session.history],
              [d.model_dump(mode="json") for d in session.redo], session.revision,
              doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id())
    error = KeyboardInterrupt if stage == "cancel" else RuntimeError

    def fail(*_args, **_kwargs):
        raise error("routing failure")

    bump = state._bump_revision

    def publish(target):
        bump(target)
        fail()

    with monkeypatch.context() as hooks:
        if stage == "build":
            hooks.setattr(lattice, "_ligate", fail)
        elif stage == "validate":
            hooks.setattr(state, "validate_design", fail)
        else:
            hooks.setattr(state, "_bump_revision", publish)
        with pytest.raises(error, match="routing failure"):
            crud.forced_ligation(_request(document))
    after = (session.design.model_dump(mode="json"), [d.model_dump(mode="json") for d in session.history],
             [d.model_dump(mode="json") for d in session.redo], session.revision,
             doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id())
    assert after == before


def _signature():
    session = state._session()
    return (
        session.design.model_dump(mode="json"),
        [item.model_dump(mode="json") for item in session.history],
        [item.model_dump(mode="json") for item in session.redo], session.revision,
        doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id(),
    )


def _nick(design, bp=10):
    domain = design.strands[0].domains[0]
    return {"helix_id": domain.helix_id, "bp_index": bp, "direction": domain.direction}


def _resize(design, **overrides):
    strand = design.strands[0]
    return {"strand_id": strand.id, "helix_id": strand.domains[-1].helix_id,
            "end": "3p", "delta_bp": 2, **overrides}


@pytest.mark.parametrize("failure", ["missing", "terminal", "duplicate", "outside"])
def test_live_nick_batch_rejects_failed_later_selection_without_partial_recording(document, failure):
    first = _nick(document)
    second = dict(first)
    if failure == "missing":
        second["helix_id"] = "missing"
    elif failure == "terminal":
        second["bp_index"] = document.strands[0].domains[0].end_bp
    elif failure == "outside":
        second["bp_index"] = 1000
    state._session().redo.append(Design())
    before = _signature()
    with pytest.raises(HTTPException) as caught:
        crud.add_nick_batch(crud.NickBatchRequest(nicks=[first, second]))
    assert caught.value.status_code == (404 if failure == "missing" else 422)
    assert caught.value.detail["code"] == ("missing_reference" if failure == "missing" else "invalid_selection")
    assert caught.value.detail["references"] == [{
        "kind": "helix", "identity": second["helix_id"],
        "parameter_path": ["nicks", 1, "helix_id"],
    }]
    assert _signature() == before


def test_live_nick_batch_rejects_missing_backbone(document):
    request = _nick(document)
    source = document.copy_with(strands=document.strands[1:])
    state.load_design(source)
    state._session().redo.append(Design())
    before = _signature()
    with pytest.raises(HTTPException) as caught:
        crud.add_nick_batch(crud.NickBatchRequest(nicks=[request]))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_selection"
    assert caught.value.detail["references"][0]["parameter_path"] == ["nicks", 0, "helix_id"]
    assert _signature() == before


@pytest.mark.parametrize("failure", ["strand", "helix", "wrong-terminal", "empty-domains"])
def test_live_resize_rejects_failed_later_reference_without_partial_recording(document, failure):
    first = _resize(document)
    second = _resize(document)
    source = document
    if failure in {"strand", "helix"}:
        second[f"{failure}_id"] = "missing"
    elif failure == "wrong-terminal":
        second["helix_id"] = document.helices[1].id
    else:
        empty = document.strands[1].model_copy(update={"domains": []})
        source = document.copy_with(strands=[document.strands[0], empty, *document.strands[2:]])
        second["strand_id"] = empty.id
        state.load_design(source)
    state._session().redo.append(Design())
    before = _signature()
    with pytest.raises(HTTPException) as caught:
        crud.strand_end_resize(crud.StrandEndResizeRequest(entries=[first, second]))
    assert caught.value.status_code == (404 if failure in {"strand", "helix"} else 422)
    issue = caught.value.detail
    assert issue["code"] == ("missing_reference" if failure in {"strand", "helix"} else "invalid_selection")
    assert issue["references"][0]["parameter_path"] == [
        "entries", 1, f"{failure}_id" if failure in {"strand", "helix"} else "strand_id",
    ]
    assert _signature() == before


@pytest.mark.parametrize("operation", ["nick-batch", "strand-end-resize"])
@pytest.mark.parametrize("empty", [False, True])
def test_valid_and_empty_routing_batches_preserve_native_recording_and_replay(document, operation, empty):
    source = Design.model_validate_json(document.model_dump_json())
    depth, revision = state.undo_depth(), state.revision()
    if operation == "nick-batch":
        body = crud.NickBatchRequest(nicks=[] if empty else [_nick(source, 10), _nick(source, 20)])
        response = crud.add_nick_batch(body)
    else:
        body = crud.StrandEndResizeRequest(entries=[] if empty else [_resize(source)])
        response = crud.strand_end_resize(body)
    updated = state.get_or_404()
    row = updated.feature_log[-1].children[-1]
    assert row.op_subtype == operation
    native = {**body.model_dump(mode="json"), "_proof_version": 1}
    assert resolve(operation, row.params, source) == native
    assert row.params["_proof_version"] == (2 if operation == "strand-end-resize" else 1)
    expected = execute(operation, source, row.params)
    assert _authoring(updated) == _authoring(expected)
    assert state.undo_depth() == depth + 1
    assert state.revision() == revision + 1 == response["revision"]
    if not empty:
        assert response["partial_geometry"] is True
        assert response["changed_helix_ids"] == [source.helices[0].id]
        assert {nuc["helix_id"] for nuc in response["nucleotides"]} == {source.helices[0].id}
        if operation == "strand-end-resize":
            assert [axis["helix_id"] for axis in response["helix_axes"]] == [source.helices[0].id]
    _verified(updated)
    restored, _ = state.undo()
    assert _authoring(restored) == _authoring(source)
    restored, _ = state.redo()
    assert _authoring(restored) == _authoring(expected)


def test_batch_nick_partial_response_covers_all_helices_of_the_actual_owned_strand(document, monkeypatch):
    first = document.find_strand(_request(document).three_prime_strand_id)
    request = crud.NickBatchRequest(nicks=[{
        "helix_id": first.domains[0].helix_id, "bp_index": 10,
        "direction": first.domains[0].direction,
    }])
    sources, interleaved = [], []
    make_nick = lattice.make_nick

    def native(source, *args, **kwargs):
        sources.append(source)
        return make_nick(source, *args, **kwargs)

    def another_edit():
        crud.forced_ligation(_request(document))
        interleaved.append(True)

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", _GuardedLock(another_edit))
        hooks.setattr(lattice, "make_nick", native)
        response = crud.add_nick_batch(request)
    assert interleaved == [True] and len(sources) == 1
    selected, _ = lattice._find_strand_at(
        sources[0], request.nicks[0].helix_id, 10, request.nicks[0].direction,
    )
    assert set(response["changed_helix_ids"]) == {domain.helix_id for domain in selected.domains}
    _verified(state.get_or_404())


def test_valid_batch_nick_on_multihelix_strand_refreshes_both_sides(document):
    body = _request(document)
    crud.forced_ligation(body)
    source = state.get_or_404()
    selected = source.find_strand(body.three_prime_strand_id)
    response = crud.add_nick_batch(crud.NickBatchRequest(nicks=[{
        "helix_id": selected.domains[0].helix_id, "bp_index": 10,
        "direction": selected.domains[0].direction,
    }]))
    assert set(response["changed_helix_ids"]) == {domain.helix_id for domain in selected.domains}
    _verified(state.get_or_404())


@pytest.mark.parametrize("operation", ["nick-batch", "strand-end-resize"])
def test_checked_batches_use_one_lock_snapshot_reconcile_and_retry(document, monkeypatch, operation):
    from backend.api import part_routing_recording
    from backend.core import part_history_contract

    lock, stages = _GuardedLock(), []

    def counted(name, callback):
        def call(*args, **kwargs):
            assert lock.held, f"{name} ran outside the recording lock"
            stages.append(name)
            return callback(*args, **kwargs)
        return call

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Interactive routing must not run full recipe proof")

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", lock)
        hooks.setattr(part_routing_recording, "validate_command_references", counted(
            "references", part_routing_recording.validate_command_references,
        ))
        for name in ("_snapshot_copy", "reconcile_cluster_membership", "_retry_pending_ligations"):
            hooks.setattr(state, name, counted(name, getattr(state, name)))
        hooks.setattr(part_history_contract, "assess_part_history", unexpected)
        native = "make_nick" if operation == "nick-batch" else "resize_strand_ends"
        hooks.setattr(lattice, native, counted("native", getattr(lattice, native)))
        if operation == "nick-batch":
            crud.add_nick_batch(crud.NickBatchRequest(nicks=[_nick(document)]))
        else:
            crud.strand_end_resize(crud.StrandEndResizeRequest(entries=[_resize(document)]))
    assert not lock.held
    assert stages == [
        "references", "_snapshot_copy", "native", "reconcile_cluster_membership", "_retry_pending_ligations",
    ]

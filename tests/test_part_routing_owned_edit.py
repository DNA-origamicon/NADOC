"""Actual Fine Routing children cross the shared owned history boundary."""

from threading import Event
from uuid import UUID

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, part_proof_commands as commands, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.core import models as m
from backend.core.part_history_contract import assess_part_history, create_empty_part
from tests.test_part_pattern_recording import saved, unchanged, worker
from tests.test_part_transform_preview import snapshot

__all__ = ["worker"]


def host():
    from backend.api import part_ordinary_recipe_recording
    return part_ordinary_recipe_recording


def _verified(source):
    report = assess_part_history(source, execute=commands.execute, dependencies=commands.dependencies)
    assert report["status"] == "verified" and report["native_editable"], report
    assert report["checked_commands"] == sum(len(row.children)
        if row.feature_type == "routing-cluster" else 1 for row in source.feature_log)


def recipe(organized=False):
    source = snapshot(create_empty_part("Routing edit", "HONEYCOMB"), "bundle-create",
        crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=21,
            ligate_adjacent=False, history_seed=UUID(int=27001)).model_dump(mode="json"), "bundle")
    if organized:
        source = snapshot(source, "group-organize", {"expected_placement_ids": [
            owner.id for owner in source.cluster_transforms]}, "organize")
    index = len(source.feature_log)
    old_log = list(source.feature_log)
    helix = source.helices[0].id
    children = []
    for number, (kind, values) in enumerate((
        ("nick", {"helix_id": helix, "bp_index": 5, "direction": "FORWARD"}),
        ("nick", {"helix_id": helix, "bp_index": 9, "direction": "FORWARD"}),
        ("loop-skip-insert", {"helix_id": helix, "bp_index": 12, "delta": 1}),
    )):
        params = {"_proof_version": 1, **values}
        child = m.MinorMutationLogEntry(id=f"child-{number}", op_subtype=kind,
            label=kind, params=params, diff_added_b64="unusable-diff")
        children.append(child)
        source = commands.execute(kind, source, params)
    parent = m.RoutingClusterLogEntry(id="routing", children=children,
        pre_state_gz_b64="unusable-pre", post_state_gz_b64="unusable-post", diffs_evicted=True)
    source = source.copy_with(feature_log=[*old_log, parent])
    source = snapshot(source, "extrude-segment", {"cells": [[7, 7]], "length_bp": 4,
        "plane": "XY", "history_seed": str(UUID(int=27002))}, "suffix")
    return source, index


@pytest.fixture(params=[False, True], ids=["legacy", "organized"])
def document(request, monkeypatch):
    token = doc_context.set_current_doc("__routing_editor__")
    markers = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    source, index = recipe(request.param)
    state.load_design(source)
    session = state._sessions[doc_context.get_current_doc()]
    try:
        yield session, index
    finally:
        state.drop_doc(doc_context.get_current_doc())
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(markers[0])
        doc_context.set_request_feature_log_entry_id(markers[1])


def guards(document, **changes):
    session, index = document
    parent = session.design.feature_log[index]
    return {"expected_design_id": session.design.id, "expected_revision": session.revision,
            "expected_feature_id": parent.id, "expected_child_id": parent.children[1].id, **changes}


def edit(document, params=None, **changes):
    return host().edit_routing(document[1], 1, {"bp_index": 10} if params is None else params,
                               **guards(document, **changes))


def test_native_child_edit_rebuilds_siblings_suffix_and_cold_history_once(document, worker):
    session, index = document
    before = saved(session)
    source = session.design
    _verified(source)
    candidate, report, parent = edit(document)
    assert candidate is session.design and report.passed
    assert parent is candidate.feature_log[index] and parent.id == "routing"
    assert parent.children[1].id == "child-1" and parent.children[1].params["bp_index"] == 10
    assert parent.children[0].params == source.feature_log[index].children[0].params
    assert parent.children[2].params == source.feature_log[index].children[2].params
    assert candidate.feature_log[-1].params == source.feature_log[-1].params
    assert session.revision == before[2] + 1 and len(session.history) == len(before[3]) + 1
    assert source.model_dump_json() == before[1]
    _verified(m.Design.model_validate_json(candidate.model_dump_json()))
    state.undo()
    assert session.design.model_dump_json() == before[1]
    state.redo()
    _verified(session.design)


def test_reference_inventory_is_before_selected_child_after_previous_sibling(document, worker):
    session, index = document
    before = saved(session)
    packet = host().routing_inputs(index, 1, **guards(document))
    assert packet["kind"] == "nick" and packet["params"]["bp_index"] == 9
    assert packet["source_revision"] == session.revision
    assert packet["feature_id"] == "routing" and packet["child_id"] == "child-1"
    # The selected nick and later extrusion must not appear in historical choices.
    assert len(packet["prefix"]["helices"]) == 2
    assert len(packet["prefix"]["strands"]) == 5
    assert len(session.design.strands) == 8
    assert "nucleotides" not in packet and "candidate" not in packet
    unchanged(session, before)


@pytest.mark.parametrize("field", ["expected_design_id", "expected_revision", "expected_feature_id", "expected_child_id"])
def test_stale_parent_or_child_refuses_before_capture(document, worker, monkeypatch, field):
    session, _ = document
    before = saved(session)
    monkeypatch.setattr(host(), "capture", lambda *_a, **_k: pytest.fail("Stale editor captured"))
    with pytest.raises(HTTPException) as caught:
        edit(document, **{field: session.revision + 1 if field == "expected_revision" else "wrong"})
    assert caught.value.status_code == 409
    unchanged(session, before)
    assert not worker.instances


@pytest.mark.parametrize("change", ["source", "session", "incarnation", "policy", "cancel"])
def test_interleaved_source_or_host_change_cannot_publish(document, worker, change):
    session, _ = document
    cancelled = Event()
    observed = []

    def interleave(_):
        with state._lock:
            if change == "source":
                session.design = session.design.copy_with(name="New work")
            elif change == "session":
                replacement = type(session)()
                replacement.design, replacement.revision = session.design, session.revision
                state._sessions[doc_context.get_current_doc()] = replacement
            elif change == "incarnation":
                session.identity = "new-incarnation"
            elif change == "policy":
                config, generation = policy._configuration
                policy._configuration = config, generation + 1
            else:
                cancelled.set()
            observed.append(saved(state._sessions[doc_context.get_current_doc()]))

    worker.on_result = interleave
    with pytest.raises(HTTPException):
        edit(document, cancelled=cancelled)
    unchanged(state._sessions[doc_context.get_current_doc()], observed[0])
    assert worker.instances[-1].closed


def test_missing_child_reference_and_later_failure_keep_redo_and_source(document, worker):
    session, _ = document
    session.redo.append(m.Design())
    before = saved(session)
    for params in ({"helix_id": "missing"}, {"bp_index": 5}):
        with pytest.raises(HTTPException) as caught:
            edit(document, params)
        assert caught.value.status_code == 409
        assert "child-1" in str(caught.value.detail)
        unchanged(session, before)

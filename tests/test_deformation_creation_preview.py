"""Ordinary creation uses one isolated prefix and one atomic native append.

Tiny memory-only native fixtures; no scientific runtime, files or browser state.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api import part_deformation_preview as preview
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.api.part_proof_commands import dependencies, execute
from backend.core import models as m
from backend.core.part_history_contract import assess_part_history
from backend.core.part_overlay_commands import command_input
from tests.test_named_deformation_preview import _snapshot, named_source
from tests.test_part_deformation_preview import authoring, native_source
from tests.test_part_deformation_preview_sessions import Timer, cancellation, checkpoint, unchanged, update


@pytest.fixture
def document(monkeypatch, request):
    source = named_source("twist") if getattr(request, "param", True) else native_source("twist")
    identity = f"__deformation_creation__{uuid4()}"
    previous_revision = doc_context.current_request_revision()
    previous_entry = doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(host, "Timer", Timer)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 41))
    token = doc_context.set_current_doc(identity)
    try:
        state.load_design(source)
        yield identity
    finally:
        try:
            host.clear_for_testing()
            state.drop_doc(identity)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(previous_revision)
            doc_context.set_request_feature_log_entry_id(previous_entry)


def opening(kind="bend", **changes):
    source, revision = state.get_design_with_revision()
    target = ({"kind": "part_group", "id": source.group_organization.groups[0].id}
              if source.group_organization is not None else
              {"kind": "strand", "id": source.strands[0].id})
    return {"mode": "create", "preview_id": str(uuid4()), "feature_id": str(uuid4()),
            "expected_design_id": source.id, "expected_revision": revision,
            "type": kind, "targets": [target], "cluster_ids": [], **changes}


def draft(kind="bend"):
    return {"plane_a_bp": 4, "plane_b_bp": 32,
            "params": {"kind": kind, **({"curvature_deg_per_bp": .25, "direction_deg": 20}
                                       if kind == "bend" else {"total_degrees": 8})}}


@pytest.mark.parametrize("document", [False, True], indirect=True)
@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_create_preview_apply_reload_cold_replay_and_undo_are_one_native_append(document, kind):
    before = checkpoint()
    request = opening(kind)
    opened = host.prepare_create(request)
    assert opened["mode"] == "create" and opened["awaiting_parameters"] is True
    assert opened["candidate"] is None and opened["feasibility"] is None
    assert opened["control_context"]["selected_operation"] is None
    assert opened["control_context"]["creation"] == {
        "type": kind, "targets": request["targets"], "cluster_ids": []}
    assert opened["selected_scope"]["id"] == opened["deformation_id"]
    assert opened["selected_scope"]["target_ranges"]
    assert opened["before"]["nucleotides"]
    assert opened["source_equivalence_checked"] is False
    assert opened["physical_validity"] is False
    unchanged(before)
    evaluated = host.evaluate(update(opened, params=draft(kind)))
    assert evaluated["mode"] == "create" and evaluated["awaiting_parameters"] is False
    assert evaluated["selected_scope"]["id"] == opened["deformation_id"]
    assert evaluated["candidate"]["display_topology"]["deformations"][-1]["id"] == opened["deformation_id"]
    unchanged(before)
    receipt = host.apply(update(opened, sequence=2, params=draft(kind)))
    result = state.get_or_404()
    assert receipt["revision"] == before["revision"] + 1
    assert state.undo_depth() == len(before["history"]) + 1
    assert len(result.feature_log) == len(before["source"].feature_log) + 1
    assert [entry.id for entry in result.feature_log[:-1]] == [entry.id for entry in before["source"].feature_log]
    entry = result.feature_log[-1]
    assert type(entry) is m.DeformationLogEntry and entry.proof_version == 1
    assert entry.id == request["feature_id"] == receipt["feature_id"]
    assert entry.deformation_id == opened["deformation_id"] == receipt["deformation_id"]
    assert entry.op_snapshot == result.deformations[-1]
    assert entry.op_snapshot.targets == request["targets"]
    assert entry.op_snapshot.cluster_ids == []
    assert result.cluster_transforms == before["source"].cluster_transforms
    assert result.group_organization == before["source"].group_organization
    expected = execute("deformation", before["source"], command_input(entry)[1])
    assert authoring(result) == authoring(expected)
    assert before["source"].model_dump(mode="json") == before["json"]
    loaded = m.Design.from_json(result.to_json())
    proof = assess_part_history(loaded, execute=execute, dependencies=dependencies)
    assert proof["status"] == "verified", proof
    assert host.status(cancellation(opened))["status"] == "applied"
    assert host.cancel(cancellation(opened))["status"] == "applied"
    with pytest.raises(HTTPException):
        host.apply(update(opened, sequence=3, params=draft(kind)))
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]
    state.redo()
    assert state.get_or_404().feature_log[-1].id == entry.id


def test_sliders_reuse_fixed_prefix_and_never_replay_or_prove_source(document, monkeypatch):
    before = checkpoint()
    request = opening()
    opened = host.prepare_create(request)
    execute_native = preview.execute

    def only_selected(kind, source, params):
        assert kind == "deformation" and params["id"] == opened["deformation_id"]
        return execute_native(kind, source, params)

    monkeypatch.setattr(preview, "execute", only_selected)
    monkeypatch.setattr("backend.core.part_history_contract.assess_part_history",
                        lambda *_a, **_k: pytest.fail("Slider attempted full proof"))
    first = host.evaluate({**update(opened, params=draft()), "include_geometry": False})
    assert first["candidate"] is None and first["feasibility"]
    # Returned request/controls/results cannot mutate the retained input graph.
    request["targets"].clear()
    opened["control_context"]["group_organization"]["groups"].clear()
    first["selected_scope"]["affected_helix_ids"].clear()
    second = host.evaluate({**update(opened, sequence=2, params=draft()), "include_geometry": False})
    assert second["selected_scope"]["affected_helix_ids"]
    assert host.cancel(cancellation(opened))["status"] == "cancelled"
    unchanged(before)


@pytest.mark.parametrize("partial", [{}, {"plane_a_bp": 4}, {"plane_a_bp": 4, "plane_b_bp": 32},
    {"plane_a_bp": True, "plane_b_bp": 32, "params": {"kind": "bend"}},
    {"plane_a_bp": 4, "plane_b_bp": 32, "params": {"kind": "bend", "direction_deg": float("inf")}}])
@pytest.mark.parametrize("operation", ["evaluate", "apply"])
def test_creation_requires_explicit_complete_finite_draft_without_publishing(document, partial, operation):
    opened = host.prepare_create(opening())
    before = checkpoint()
    with pytest.raises(HTTPException) as caught:
        getattr(host, operation)(update(opened, params=partial))
    assert caught.value.status_code == 422
    unchanged(before)


@pytest.mark.parametrize("fields", [
    {"targets": []}, {"targets": [{"kind": "part_group", "id": "missing"}]},
    {"targets": [{"kind": "part_group", "id": "other"}, {"kind": "atom", "id": "x"}]},
    {"targets": [{"kind": "strand", "id": "missing"}]},
    {"targets": [{"kind": "domain", "strand_id": "missing", "domain_index": 0}]},
    {"targets": [{"kind": "cluster", "id": "missing"}]},
    {"targets": [{"kind": "part_group", "id": "other", "scope": "all"}]},
    {"cluster_ids": ["missing"]}, {"mode": "edit"}, {"feature_id": "not-a-uuid"},
    {"affected_helix_ids": []}, {"target_ranges": []}, {"deformation_id": "client-owned"},
])
def test_closed_creation_origin_refuses_missing_or_malformed_selection(document, fields):
    before = checkpoint()
    with pytest.raises(HTTPException) as caught:
        host.prepare_create(opening(**fields))
    assert caught.value.status_code == 422
    unchanged(before)
    assert document not in host._entries


@pytest.mark.parametrize("field,value", [("id", "new-id"), ("target_ranges", []),
    ("affected_helix_ids", []), ("targets", []), ("cluster_ids", ["missing"]),
    ("type", "twist"), ("source_operation_id", "preview-operation")])
def test_creation_patch_cannot_replace_bound_identity_or_selection(document, field, value):
    opened = host.prepare_create(opening())
    before = checkpoint()
    with pytest.raises(HTTPException):
        host.evaluate(update(opened, params={**draft(), field: value}))
    unchanged(before)


def test_empty_named_group_and_nonintersecting_window_never_expand_to_all(document):
    source = state.get_or_404()
    empty = _snapshot(source, "group-create", group={"id": "empty", "name": "Empty"})
    with state._lock:
        state._session().design = empty
    with pytest.raises(HTTPException):
        host.prepare_create(opening(targets=[{"kind": "part_group", "id": "empty"}]))
    with state._lock:
        state._session().design = source
    opened = host.prepare_create(opening())
    before = checkpoint()
    with pytest.raises(HTTPException):
        host.evaluate(update(opened, params={**draft(), "plane_a_bp": 80, "plane_b_bp": 90}))
    unchanged(before)


@pytest.mark.parametrize("which", ["historical", "subcursor", "feature_collision"])
def test_creation_admission_precedes_prefix_replay(document, monkeypatch, which):
    request = opening()
    source = state.get_or_404()
    if which == "feature_collision":
        source.feature_log[0].id = request["feature_id"]
    elif which == "historical":
        source.feature_log_cursor = 0
    else:
        source.feature_log_sub_cursor = 0
    before = checkpoint()
    monkeypatch.setattr(preview, "execute", lambda *_a, **_k: pytest.fail("Rejected opening replayed source"))
    with pytest.raises(HTTPException):
        host.prepare_create(request)
    unchanged(before)


def test_changed_materialization_cannot_be_certified_by_create_preview(document):
    # Preview is recipe-stage output, not proof that saved authoring matches it.
    source = state.get_or_404()
    source.helices[0].length_bp += 1
    opened = host.prepare_create(opening())
    before = checkpoint()
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened, params=draft()))
    assert caught.value.status_code == 409
    unchanged(before)


@pytest.mark.parametrize("change", ["cancel", "same_revision_source", "session_aba", "gate", "expiry"])
def test_creation_current_source_and_lease_guards_precede_evaluation(document, monkeypatch, change):
    opened = host.prepare_create(opening())
    source, revision = state.get_design_with_revision()
    if change == "cancel":
        host.cancel(cancellation(opened))
    elif change == "same_revision_source":
        with state._lock:
            state._session().design = source.copy_with()
    elif change == "session_aba":
        state.drop_doc(document)
        state.load_design(source)
        with state._lock:
            state._session().revision = revision
    elif change == "gate":
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    else:
        host._entries[document].expires = 0
    before = checkpoint()
    monkeypatch.setattr(host, "local_evaluate", lambda *_a, **_k: pytest.fail("Retired create reached native work"))
    with pytest.raises(HTTPException):
        host.apply(update(opened, params=draft()))
    unchanged(before)


def test_creation_cancel_before_prepare_and_publication_failure_preserve_source(document, monkeypatch):
    request = opening()
    before = checkpoint()
    assert host.cancel(cancellation(request))["status"] == "cancelled"
    with pytest.raises(HTTPException):
        host.prepare_create(request)
    unchanged(before)
    opened = host.prepare_create(opening())
    bump = state._bump_revision

    def fail(session):
        bump(session)
        raise RuntimeError("after publication")

    with monkeypatch.context() as fault:
        fault.setattr(state, "_bump_revision", fail)
        with pytest.raises(RuntimeError, match="after publication"):
            host.apply(update(opened, params=draft()))
    unchanged(before)
    assert host.status(cancellation(opened))["status"] == "ready"
    assert host.apply(update(opened, sequence=2, params=draft()))["revision"] == before["revision"] + 1


@pytest.mark.parametrize("scoped", [False, True])
def test_explicit_null_targets_preserve_legacy_whole_or_placement_scope(document, scoped):
    source = state.get_or_404()
    placements = [source.cluster_transforms[0].id] if scoped else []
    request = opening(targets=None, cluster_ids=placements)
    opened = host.prepare_create(request)
    assert opened["selected_scope"]["target_ranges"] is None
    assert opened["selected_scope"]["affected_helix_ids"]
    host.apply(update(opened, params=draft()))
    op = state.get_or_404().deformations[-1]
    assert op.targets is None and op.target_ranges is None
    assert op.cluster_ids == placements
    from backend.core.deformation import helices_crossing_planes, resolve_cluster_scope
    expected = resolve_cluster_scope(source, placements, helices_crossing_planes(source, 4, 32))
    assert op.affected_helix_ids == expected["helix_ids"]


def test_null_target_placement_picker_changes_only_the_owned_draft(document):
    source = state.get_or_404()
    before = checkpoint()
    placement = source.cluster_transforms[0].id
    opened = host.prepare_create(opening(targets=None, cluster_ids=[placement]))
    assert opened["control_context"]["capabilities"]["change_clusters"] is True
    host.evaluate({**update(opened, params={**draft(), "cluster_ids": []}), "include_geometry": False})
    unchanged(before)
    host.apply(update(opened, sequence=2, params={**draft(), "cluster_ids": []}))
    assert state.get_or_404().deformations[-1].cluster_ids == []

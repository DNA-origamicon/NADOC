"""Explicit unassigned grouping is one owned, replayable authoring operation."""

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, routes_clusters as routes, state
from backend.core import cluster_components, feature_history_clusters
from backend.core.lattice import make_bundle_design
from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry, ClusterRigidTransform, Design
from backend.core.part_history_proof import import_root
from tests.test_geometry_group_history import _proof, _verified
from tests.test_geometry_group_history import document as document
from tests.test_group_edit_recording import _snapshot, _unchanged


def _unassigned(*, imported=False):
    source = make_bundle_design([(0, 0), (0, 1), (6, 0)], length_bp=6)
    source = source.copy_with(cluster_transforms=[], feature_log=[], recipe_root=None)
    if imported:
        source = source.copy_with(recipe_root=import_root(source))
    state.load_design(source)
    return source


def test_native_unassigned_grouping_records_complete_v2_rows_and_one_publication(document):
    default = document.cluster_transforms[0]
    routes.update_cluster(default.id, routes.PatchClusterBody(helix_ids=[]))
    source = state.get_or_404()
    original = source.model_dump(mode="json")
    depth, revision = state.undo_depth(), state.revision()
    result = routes.repair_unassigned_clusters()
    current = state.get_or_404()
    rows = current.feature_log[len(source.feature_log):]
    assert rows
    assert len(rows) == len(current.cluster_transforms) - len(source.cluster_transforms)
    for row, group in zip(rows, current.cluster_transforms[len(source.cluster_transforms):], strict=True):
        assert row.proof_version == 2 and row.cluster_snapshot == group
        assert row.cluster_id == group.id and row.helix_ids == group.helix_ids
    assert current.cluster_transforms[:len(source.cluster_transforms)] == source.cluster_transforms
    assert current.helices == source.helices and current.strands == source.strands
    assert source.model_dump(mode="json") == original
    assert state.undo_depth() == depth + 1
    assert state.revision() == revision + 1 == result["revision"]
    _verified(Design.from_json(current.model_dump_json()))
    undone, _ = state.undo()
    assert undone.model_dump(mode="json") == original
    redone, _ = state.redo()
    assert redone.model_dump(mode="json") == current.model_dump(mode="json")


@pytest.mark.parametrize("imported", [False, True], ids=["rootless", "explicit-import"])
def test_empty_group_source_uses_native_default_owner_semantics(document, imported):
    source = _unassigned(imported=imported)
    planned = cluster_components.cluster_unassigned_components(source).cluster_transforms
    routes.repair_unassigned_clusters()
    current = state.get_or_404()
    assert len(current.cluster_transforms) == len(planned) + 1
    default, *created = current.cluster_transforms
    assert default.is_default and default.auto_created
    assert default.helix_ids == [] and default.domain_ids == []
    assert created == planned
    assert [row.cluster_snapshot for row in current.feature_log] == created
    assert all(row.proof_version == 2 for row in current.feature_log)
    report = _proof(current)
    assert report["status"] == ("reproduced_import" if imported else "unverified"), report
    assert current.recipe_root == source.recipe_root


def test_component_graph_runs_on_detached_input_outside_publication_lock(document, monkeypatch):
    source = _unassigned()
    original = source.model_dump(mode="json")
    planner = cluster_components.cluster_unassigned_components
    seen = []

    def owned_graph(captured, *args, **kwargs):
        assert not state._lock.locked(), "Component graph work must not hold the state lock"
        assert captured is not source and captured.helices[0] is not source.helices[0]
        captured.metadata.name = "Private graph input"
        seen.append(captured)
        return planner(captured, *args, **kwargs)

    monkeypatch.setattr(cluster_components, "cluster_unassigned_components", owned_graph)
    routes.repair_unassigned_clusters()
    assert len(seen) == 1
    assert source.model_dump(mode="json") == original
    assert state.get_or_404().metadata == source.metadata


def test_noop_unassigned_grouping_keeps_exact_source_revision_and_undo(document, monkeypatch):
    before = _snapshot()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("No-op grouping cannot publish, snapshot, or infer membership")

    monkeypatch.setattr(state, "_snapshot_copy", unexpected)
    monkeypatch.setattr(crud, "_ensure_default_cluster", unexpected)
    routes.repair_unassigned_clusters()
    _unchanged(before)


@pytest.mark.parametrize("cursor,sub", [(-2, None), (0, None), (-1, 0)])
def test_historical_unassigned_grouping_refuses_before_graph_work(document, monkeypatch, cursor, sub):
    source = _unassigned().copy_with(feature_log_cursor=cursor, feature_log_sub_cursor=sub)
    state.load_design(source)
    before = _snapshot()
    monkeypatch.setattr(cluster_components, "cluster_unassigned_components", lambda *_a, **_kw: pytest.fail("Historical grouping reached graph work"))
    with pytest.raises(HTTPException) as caught:
        routes.repair_unassigned_clusters()
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "historical_cursor"
    _unchanged(before)


@pytest.mark.parametrize("race", ["source", "session-aba"])
def test_graph_result_refuses_changed_source_or_session_before_publication(document, monkeypatch, race):
    source = _unassigned()
    planner = cluster_components.cluster_unassigned_components
    replacements = []

    def racing_graph(captured, *args, **kwargs):
        result = planner(captured, *args, **kwargs)
        session = state._session()
        if race == "source":
            state.set_design(source.copy_with(metadata=source.metadata.model_copy(update={"name": "Concurrent edit"})))
        else:
            state._sessions[doc_context.get_current_doc()] = state._DesignSession(design=source, revision=session.revision)
        replacements.append(_snapshot())
        return result

    monkeypatch.setattr(cluster_components, "cluster_unassigned_components", racing_graph)
    with pytest.raises(HTTPException) as caught:
        routes.repair_unassigned_clusters()
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "source_changed"
    _unchanged(replacements[0])


@pytest.mark.parametrize("failure", ["validation", "publication", "cancellation"])
def test_unassigned_group_publication_failures_keep_source_stacks_and_revision(document, monkeypatch, failure):
    _unassigned()
    before = _snapshot()

    class Cancelled(BaseException):
        pass

    expected = Cancelled if failure == "cancellation" else RuntimeError

    def fail(*_args, **_kwargs):
        raise expected("Injected group transaction failure")

    with monkeypatch.context() as patch:
        patch.setattr(state, "validate_design" if failure == "validation" else "_bump_revision", fail)
        with pytest.raises(expected):
            routes.repair_unassigned_clusters()
        _unchanged(before)


def test_authored_group_history_suppresses_later_legacy_membership_inference(document):
    source = _unassigned()
    group = ClusterRigidTransform(id="intentional", auto_created=True, is_default=True,
                                  helix_ids=[h.id for h in source.helices])
    state.load_design(source.copy_with(cluster_transforms=[group]))
    routes.update_cluster(group.id, routes.PatchClusterBody(helix_ids=[]))
    before = _snapshot()
    current = before["source"]
    response = crud._design_response(current, state.validate_design(current))
    assert response["design"]["cluster_transforms"][0]["helix_ids"] == []
    _unchanged(before)


@pytest.mark.parametrize("kind,version,recognized", [
    ("create", None, False), ("create", 1, True), ("create", 2, True),
    ("pose", None, False), ("pose", 1, True), ("pose", True, False),
])
def test_authored_group_intent_guard_does_not_promote_unversioned_rows(kind, version, recognized):
    group = ClusterRigidTransform(id="group")
    row = (ClusterCreateLogEntry(cluster_id=group.id, name=group.name, helix_ids=[], cluster_snapshot=group)
           if kind == "create" else ClusterOpLogEntry(cluster_id=group.id, translation=[0, 0, 0],
               rotation=[0, 0, 0, 1], pivot=[0, 0, 0], authored_fields={"helix_ids": []}))
    row = row.model_copy(update={"proof_version": version})
    assert feature_history_clusters.has_authored_group_history([row]) is recognized


def test_unassigned_preserves_excluded_document_state_and_original_recovery(document, monkeypatch):
    from backend.api import part_proof_commands
    from backend.core.models import AtomisticReference
    from backend.core.part_repair_draft import RepairDraft
    from tests.test_part_repair_draft import draft

    default = document.cluster_transforms[0]
    routes.update_cluster(default.id, routes.PatchClusterBody(helix_ids=[]))
    source = state.get_or_404().copy_with(
        repair_draft=RepairDraft.model_validate(draft()), annotations_enabled=False,
        atomistic_reference=AtomisticReference(source="Retained physical result"),
    )
    state.load_design(source)
    before = source.model_dump(mode="json")

    def unexpected(*_args, **_kwargs):
        pytest.fail("Ordinary grouping cannot execute proof or derive molecular geometry")

    monkeypatch.setattr(part_proof_commands, "execute", unexpected)
    monkeypatch.setattr(crud, "_geometry_for_design", unexpected)
    routes.repair_unassigned_clusters()
    current = state.get_or_404()
    assert current.repair_draft == source.repair_draft
    assert current.atomistic_reference == source.atomistic_reference
    assert current.annotations_enabled is False
    assert current.feature_log[:len(source.feature_log)] == source.feature_log
    assert source.feature_log[0].design_snapshot_gz_b64
    assert source.model_dump(mode="json") == before


def test_unassigned_protected_loadout_refuses_before_capture_or_graph(document, monkeypatch):
    from backend.core import part_verification_capture

    before = _snapshot()

    def protected(*_args, **_kwargs):
        raise HTTPException(409, detail={"code": "protected_simulation_loadout"})

    monkeypatch.setattr(state, "_assert_active_loadout_editable", protected)
    monkeypatch.setattr(part_verification_capture, "capture", lambda *_a, **_kw: pytest.fail("Protected branch captured"))
    with pytest.raises(HTTPException) as caught:
        routes.repair_unassigned_clusters()
    assert caught.value.detail["code"] == "protected_simulation_loadout"
    _unchanged(before)


@pytest.mark.parametrize("boundary", ["capture", "items", "identity", "graph", "groups"])
def test_unassigned_bounds_refuse_before_native_creation(document, monkeypatch, boundary):
    from backend.api import part_group_recording as recording
    from backend.core import part_verification_capture

    _unassigned()
    before = _snapshot()
    if boundary == "capture":
        def fail_capture(*_args, **_kwargs):
            raise part_verification_capture.CaptureLimit("Injected bounded capture refusal")
        monkeypatch.setattr(part_verification_capture, "capture", fail_capture)
    elif boundary == "items":
        monkeypatch.setattr(recording, "MAX_ITEMS", 1)
    elif boundary == "identity":
        monkeypatch.setattr(recording, "MAX_ID_CHARS", 1)
    elif boundary == "graph":
        monkeypatch.setattr(recording, "MAX_COMPONENT_GRAPH_WORK", 1)
    else:
        monkeypatch.setattr(recording, "MAX_COMPONENT_GROUPS", 1)
    monkeypatch.setattr(recording, "build", lambda *_a, **_kw: pytest.fail("Refused grouping reached native creation"))
    with pytest.raises(HTTPException) as caught:
        routes.repair_unassigned_clusters()
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] in {"group_capture_limit", "group_input_limit", "group_graph_limit"}
    _unchanged(before)


@pytest.mark.parametrize("malformed", ["duplicate-helix", "duplicate-group", "missing-member", "missing-domain"])
def test_unassigned_bad_typed_references_refuse_before_graph(document, monkeypatch, malformed):
    from backend.core.models import DomainRef

    source = _unassigned()
    if malformed == "duplicate-helix":
        source = source.copy_with(helices=[*source.helices, source.helices[0]])
    else:
        group = ClusterRigidTransform(id="retained")
        if malformed == "duplicate-group":
            source = source.copy_with(cluster_transforms=[group, group])
        elif malformed == "missing-member":
            source = source.copy_with(cluster_transforms=[group.model_copy(update={"helix_ids": ["absent"]})])
        else:
            source = source.copy_with(cluster_transforms=[group.model_copy(update={
                "domain_ids": [DomainRef(strand_id="absent", domain_index=0)]})])
    state.load_design(source)
    before = _snapshot()
    monkeypatch.setattr(cluster_components, "cluster_unassigned_components", lambda *_a, **_kw: pytest.fail("Invalid reference reached graph"))
    with pytest.raises(HTTPException) as caught:
        routes.repair_unassigned_clusters()
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] in {"missing_reference", "invalid_selection"}
    _unchanged(before)


def test_policy_configuration_replacement_invalidates_prepared_grouping(document, monkeypatch):
    from backend.api import part_publication_policy as policy

    _unassigned()
    before = _snapshot()
    config = policy.current_configuration()
    planner = cluster_components.cluster_unassigned_components

    def replace_policy(captured, *args, **kwargs):
        planned = planner(captured, *args, **kwargs)
        state.configure_part_publication_policy(config)
        return planned

    monkeypatch.setattr(cluster_components, "cluster_unassigned_components", replace_policy)
    try:
        with pytest.raises(HTTPException) as caught:
            routes.repair_unassigned_clusters()
        assert caught.value.status_code == 409 and caught.value.detail["code"] == "policy_changed"
        _unchanged(before)
    finally:
        state.configure_part_publication_policy(config)


def test_dense_component_work_counts_neighbor_bucket_before_edge_allocation(document, monkeypatch):
    # Four co-located continuations in each neighboring cell expose fanout.
    # No molecular placement/solver is invoked by component classification.
    source = _unassigned()
    left, right = source.helices[:2]
    helices = [helix.model_copy(update={"id": f"{side}-{index}"})
               for side, helix in (("left", left), ("right", right)) for index in range(4)]
    source = source.copy_with(helices=helices, strands=[], crossovers=[], forced_ligations=[])
    monkeypatch.setattr(cluster_components, "crossover_neighbor", lambda *_a, **_kw: right.grid_pos)
    # First neighbor probe costs one, matched bucket costs four; refuse before
    # producing even a partial adjacency graph. Default legacy call is intact.
    with pytest.raises(cluster_components.ClusterComponentLimit):
        cluster_components.lattice_cluster_graph(source, max_work=4)
    graph = cluster_components.lattice_cluster_graph(source)
    assert set(graph["left-0"]) == {f"right-{index}" for index in range(4)}

"""The ordinary pivot choice records one complete editable absolute pose.

Native molecular helpers supply both the candidate and parity oracle. Fixtures
are tiny input-built parts in memory; no sampled geometry is authored or saved.
"""

from dataclasses import replace

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, routes_clusters as routes, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core import duplex_cluster
from backend.core.models import Design
from backend.core.part_dependencies import Resource
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_overlay_commands import command_input
from tests.test_geometry_group_history import _stored, _verified
from tests.test_geometry_group_history import document as document
from tests.test_group_edit_recording import _snapshot, _unchanged
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import append, native_prefix as native_prefix


@pytest.fixture
def duplex_part(document, application_prefix):
    first, second = application_prefix.overhangs[:2]
    source = append(application_prefix, "duplex-connect", {
        "_proof_version": 1, "history_seed": "212cb729-37fa-49e4-bb35-c6a0cbd2cd2e",
        "duplex_id": "pivot-duplex", "created_at": 4.0,
        "overhang_a_id": first.id, "overhang_b_id": second.id, "binding_ids": [],
    }, "pivot-duplex-connect")
    row = source.feature_log[-1]
    row.design_snapshot_gz_b64, row.snapshot_size_bytes = state.encode_design_snapshot(application_prefix)
    row.post_state_gz_b64, row.post_state_size_bytes = state.encode_design_snapshot(source)
    state.load_design(source)
    child = next(c for c in source.cluster_transforms if c.overhang_duplex_driver_id)
    routes.update_cluster(child.id, routes.PatchClusterBody(
        translation=[2.0, -3.0, 4.0], rotation=[0.0, 0.0, 0.6, 0.8], commit=True))
    source = state.get_or_404()
    child = next(c for c in source.cluster_transforms if c.id == child.id)
    _verified(source)
    return source, child


def _point(source, child, index=0):
    points = duplex_cluster.duplex_cluster_rotation_points(source, child)
    assert len(points) == 3
    point = points[index]
    return routes.RotationPointBody(kind=point["kind"], overhang_id=point.get("overhang_id")), point["point"]


@pytest.mark.parametrize("point_index", [0, 1, 2], ids=["driver-root", "driven-root", "centroid"])
def test_pivot_records_absolute_pose_with_native_parity_replay_seek_and_undo(duplex_part, point_index, monkeypatch):
    source, child = duplex_part
    body, point = _point(source, child, point_index)
    expected = duplex_cluster.set_duplex_cluster_pivot(source, child.id, point)
    before = _snapshot()
    response = routes.set_cluster_rotation_point(child.id, body)
    current = state.get_or_404()
    assert current.cluster_transforms == expected.cluster_transforms
    assert current.model_dump(include=AUTHORING_FIELDS) == expected.model_dump(include=AUTHORING_FIELDS)
    assert len(current.feature_log) == len(source.feature_log) + 1
    row = current.feature_log[-1]
    assert row.feature_type == "cluster_op" and row.proof_version == 1
    assert row.source == "rotation-point" and row.cluster_id == child.id
    assert state.revision() == before["revision"] + 1 == response["revision"]
    assert state.undo_depth() == len(before["history"]) + 1
    assert response["design"]["feature_log"][-1]["id"] == row.id
    kind, params = command_input(row)
    assert Resource("cluster", child.id) in dependencies(kind, params).reads
    assert execute(kind, source, params).cluster_transforms == expected.cluster_transforms
    assert source.model_dump(mode="json") == before["stored"]
    # The selected point is captured once, as the existing absolute-pose input;
    # replay never reruns a geometric point picker or needs recovery outputs.
    monkeypatch.setattr(duplex_cluster, "duplex_cluster_rotation_points",
                        lambda *_: pytest.fail("Absolute pose replay must not pick a point"))
    loaded = Design.from_json(current.model_dump_json())
    _verified(loaded)
    previous = crud._seek_feature_log(loaded, len(source.feature_log) - 1)
    assert previous.cluster_transforms == source.cluster_transforms
    assert crud._seek_feature_log(previous, -1).cluster_transforms == expected.cluster_transforms
    undone, _ = state.undo()
    assert _stored(undone) == _stored(source)
    redone, _ = state.redo()
    assert _stored(redone) == _stored(current)


def test_point_geometry_uses_detached_input_outside_state_lock(duplex_part, monkeypatch):
    source, child = duplex_part
    original = duplex_cluster.duplex_cluster_rotation_points
    seen = []

    def points(private, selected):
        assert not state._lock.locked()
        assert private is not source and selected is not child
        assert private.helices[0] is not source.helices[0]
        seen.append(private)
        return original(private, selected)

    monkeypatch.setattr(duplex_cluster, "duplex_cluster_rotation_points", points)
    routes.set_cluster_rotation_point(child.id, routes.RotationPointBody(kind="centroid"))
    assert len(seen) == 1


@pytest.mark.parametrize("cursor,subcursor", [(-2, None), (0, None), (-1, 0)])
def test_historical_pivot_refuses_before_geometry(duplex_part, monkeypatch, cursor, subcursor):
    source, child = duplex_part
    state.load_design(source.copy_with(feature_log_cursor=cursor, feature_log_sub_cursor=subcursor))
    before = _snapshot()
    monkeypatch.setattr(duplex_cluster, "duplex_cluster_rotation_points", lambda *_: pytest.fail("No point work"))
    with pytest.raises(HTTPException) as caught:
        routes.set_cluster_rotation_point(child.id, routes.RotationPointBody(kind="centroid"))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "historical_cursor"
    _unchanged(before)


@pytest.mark.parametrize("race", ["source", "session-aba"])
def test_pivot_rejects_stale_computation_without_overwriting_newer_state(duplex_part, monkeypatch, race):
    source, child = duplex_part
    original = duplex_cluster.duplex_cluster_rotation_points
    changed = []

    def points(private, selected):
        result = original(private, selected)
        with state._lock:
            session = state._session()
            if race == "source":
                session.design = source.copy_with(metadata=source.metadata.model_copy(update={"description": "newer"}))
                session.revision += 1
            else:
                state._sessions[doc_context.get_current_doc()] = replace(session, identity="replacement-session")
        changed.append(_snapshot())
        return result

    monkeypatch.setattr(duplex_cluster, "duplex_cluster_rotation_points", points)
    with pytest.raises(HTTPException) as caught:
        routes.set_cluster_rotation_point(child.id, routes.RotationPointBody(kind="centroid"))
    assert caught.value.status_code == 409
    _unchanged(changed[0])


@pytest.mark.parametrize("stage", ["compute", "validation", "publication", "cancel"])
def test_pivot_failure_is_atomic(duplex_part, monkeypatch, stage):
    source, child = duplex_part
    before = _snapshot()
    error = KeyboardInterrupt if stage == "cancel" else RuntimeError

    def fail(*_args, **_kwargs):
        raise error("injected pivot failure")

    if stage in {"compute", "cancel"}:
        monkeypatch.setattr(duplex_cluster, "duplex_cluster_rotation_points", fail)
    elif stage == "validation":
        monkeypatch.setattr(state, "validate_design", fail)
    else:
        monkeypatch.setattr(state, "_snapshot_copy", fail)
    with pytest.raises(error, match="injected pivot failure"):
        routes.set_cluster_rotation_point(child.id, routes.RotationPointBody(kind="centroid"))
    _unchanged(before)


def test_invalid_pivot_choice_and_missing_group_preserve_state(duplex_part):
    _, child = duplex_part
    before = _snapshot()
    for identity, body, status in [
        ("missing", routes.RotationPointBody(kind="centroid"), 404),
        (child.id, routes.RotationPointBody(kind="overhang_root", overhang_id="missing"), 422),
    ]:
        with pytest.raises(HTTPException) as caught:
            routes.set_cluster_rotation_point(identity, body)
        assert caught.value.status_code == status
        _unchanged(before)


def test_pivot_keeps_excluded_document_fields_and_original_recovery(duplex_part):
    from backend.core.models import AtomisticReference
    from backend.core.part_repair_draft import RepairDraft
    from tests.test_part_repair_draft import draft

    source, child = duplex_part
    source = source.copy_with(repair_draft=RepairDraft.model_validate(draft()), annotations_enabled=False,
                              atomistic_reference=AtomisticReference(source="Retained physical result"))
    state.load_design(source)
    before = source.model_dump(mode="json")
    routes.set_cluster_rotation_point(child.id, routes.RotationPointBody(kind="centroid"))
    current = state.get_or_404()
    assert current.repair_draft == source.repair_draft
    assert current.atomistic_reference == source.atomistic_reference
    assert current.annotations_enabled is False
    assert current.feature_log[:len(source.feature_log)] == source.feature_log
    assert source.model_dump(mode="json") == before


def test_policy_replacement_invalidates_prepared_pivot(duplex_part, monkeypatch):
    from backend.api import part_publication_policy as policy

    _, child = duplex_part
    config = policy.current_configuration()
    before = _snapshot()
    original = duplex_cluster.duplex_cluster_rotation_points

    def points(private, selected):
        result = original(private, selected)
        state.configure_part_publication_policy(config)
        return result

    monkeypatch.setattr(duplex_cluster, "duplex_cluster_rotation_points", points)
    try:
        with pytest.raises(HTTPException) as caught:
            routes.set_cluster_rotation_point(child.id, routes.RotationPointBody(kind="centroid"))
        assert caught.value.status_code == 409 and caught.value.detail["code"] == "policy_changed"
        _unchanged(before)
    finally:
        state.configure_part_publication_policy(config)


def test_large_scalar_geometry_refuses_before_point_work(duplex_part, monkeypatch):
    source, child = duplex_part
    helices = [source.helices[0].model_copy(update={"length_bp": 1_000_000}), *source.helices[1:]]
    state.load_design(source.copy_with(helices=helices))
    before = _snapshot()
    monkeypatch.setattr(duplex_cluster, "duplex_cluster_rotation_points",
                        lambda *_: pytest.fail("Over-budget source reached native geometry"))
    with pytest.raises(HTTPException) as caught:
        routes.set_cluster_rotation_point(child.id, routes.RotationPointBody(kind="centroid"))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "group_geometry_limit"
    _unchanged(before)

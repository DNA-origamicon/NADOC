"""Organization seek requires complete bounded recovery, never inferred output.

All fixtures and encoded snapshots stay in memory. Public activation of the
organization model is still gated: route refusals start at a legacy position
with future organization history, while successful chronology stays private.
"""

import pytest
from fastapi import HTTPException

from backend.api import crud, part_group_recovery as recovery, routes_feature_log as routes, state
from backend.core import models as m
from tests.test_geometry_group_history import document as document
from tests.test_group_edit_recording import _snapshot, _unchanged
from tests.test_group_organization_commands import group
from tests.test_group_organization_history import _append, history


@pytest.fixture(scope="module")
def histories():
    # Real native rows, including 33 rows for the optimized snapshot scan.
    return {False: history(), True: history(padding=26)}


def _design(histories, optimized=False):
    design, _ = histories[optimized]
    return design.model_copy(deep=True)


def _unavailable(design, missing, index=4):
    row = design.feature_log[index]
    if missing in {"pre", "both"}:
        row.design_snapshot_gz_b64 = ""
    if missing in {"post", "both"}:
        row.post_state_gz_b64 = ""
    if missing == "evicted":
        row.evicted = True
    return row


def _tripwire(*_args, **_kwargs):
    pytest.fail("Recovery admission must refuse before decoding, geometry, or publication")


def _no_materialization(monkeypatch):
    monkeypatch.setattr(state, "decode_design_snapshot", _tripwire)
    monkeypatch.setattr(state, "set_design", _tripwire)
    monkeypatch.setattr(routes, "deformed_helix_axes", _tripwire)


def _refused(call, *, status=409):
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == status
    expected = "group_recovery_unavailable" if status == 410 else "group_recovery_invalid"
    assert caught.value.detail["code"] == expected
    return caught.value.detail


@pytest.mark.parametrize("optimized", [False, True], ids=["ordinary", "optimized-33"])
@pytest.mark.parametrize("position", [-2, 3, -1], ids=["F0", "before-dissolve", "end"])
@pytest.mark.parametrize("missing", ["pre", "post", "both", "evicted"])
def test_missing_organization_transition_never_uses_another_snapshot(
        histories, monkeypatch, optimized, position, missing):
    design = _design(histories, optimized)
    row = _unavailable(design, missing)
    # Later complete bodies really exist and could otherwise hide the gap.
    assert design.feature_log[-1].post_state_gz_b64
    original = design.model_dump(mode="json")
    _no_materialization(monkeypatch)
    issue = _refused(lambda: crud._seek_feature_log(design, position, optimized=optimized), status=410)
    assert issue["feature_id"] == row.id
    assert design.model_dump(mode="json") == original


@pytest.mark.parametrize("index", [3, 4, 5, 6], ids=["organize", "dissolve", "create", "update"])
def test_each_organization_command_requires_both_full_bodies(histories, monkeypatch, index):
    design = _design(histories)
    row = _unavailable(design, "post", index)
    _no_materialization(monkeypatch)
    issue = _refused(lambda: recovery.prepare_group_seek(design, -1), status=410)
    assert issue["feature_id"] == row.id


@pytest.mark.parametrize("reader", ["seek", "preview", "geometry-batch"])
def test_route_refusal_preserves_exact_session_and_nonempty_redo(
        document, histories, monkeypatch, reader):
    design = _design(histories)
    _unavailable(design, "pre")
    # A legal earlier cursor may retain later organization history while the
    # active materialized design is still in the legacy representation.
    legacy = histories[False][1][2].copy_with(
        feature_log=design.feature_log, feature_log_cursor=2)
    assert legacy.group_organization is None
    state.load_design(legacy)
    state.set_design(legacy.model_copy(deep=True))
    state.undo()
    before = _snapshot()
    assert before["redo"]
    _no_materialization(monkeypatch)
    if reader == "geometry-batch":
        invoke = lambda: routes.geometry_batch(routes.GeometryBatchBody(positions=[-2, -1]))
    elif reader == "preview":
        invoke = lambda: routes.preview_features(routes.SeekFeaturesBody(position=-2))
    else:
        invoke = lambda: routes.seek_features(routes.SeekFeaturesBody(position=-2))
    _refused(invoke, status=410)
    _unchanged(before)


@pytest.mark.parametrize("change", [
    {"params": {"_proof_version": True, "group_ids": ["placement"]}},
    {"params": {"_proof_version": 2, "group_ids": ["placement"]}},
    {"params": {"_proof_version": 1, "group_ids": ["placement"], "candidate": {}}},
    {"params": {"_proof_version": 1, "group_ids": ["placement"], "_generated_scope": {}}},
    {"params": {"_proof_version": 1, "group_ids": ["placement", "placement"]}},
    {"params": {"_proof_version": 1, "group_ids": []}},
    {"params": []},
    {"evicted": "false"},
    {"design_snapshot_gz_b64": b"encoded"},
    {"post_state_size_bytes": -1},
    {"snapshot_size_bytes": True},
    {"id": ""},
    {"id": "row-3"},
], ids=["bool-version", "future-version", "extra-input", "generated-scope", "duplicate-selection",
        "empty-selection", "nonmapping-input", "nonbool-eviction", "nonstring-body", "negative-size",
        "bool-size", "empty-id", "duplicate-feature-id"])
def test_malformed_organization_metadata_refuses_before_any_decode(histories, monkeypatch, change):
    design = _design(histories)
    # Deliberately corrupted in-memory models; the normal JSON loader is not
    # bypassed or weakened by recovery admission.
    design.feature_log[4] = design.feature_log[4].model_copy(update=change)
    _no_materialization(monkeypatch)
    _refused(lambda: crud._seek_feature_log(design, -2))


def test_group_command_cannot_hide_as_a_routing_child(histories, monkeypatch):
    design = _design(histories)
    child = m.MinorMutationLogEntry.model_construct(id="nested", op_subtype="group-dissolve",
        label="Invalid nested organization", params={"_proof_version": 1, "group_ids": ["placement"]})
    design.feature_log = [m.RoutingClusterLogEntry.model_construct(
        id="routing", label="Routing", children=[child])]
    _no_materialization(monkeypatch)
    _refused(lambda: crud._seek_feature_log(design, -2))


@pytest.mark.parametrize("constant,value", [
    ("MAX_ORGANIZATION_HISTORY_ENTRIES", 3),
    ("MAX_ORGANIZATION_ITEMS", 8),
    ("MAX_ORGANIZATION_METADATA_BYTES", 8),
    ("MAX_ORGANIZATION_RECOVERY_BYTES", 8),
    ("MAX_ORGANIZATION_ID_CHARS", 2),
], ids=["history-rows", "metadata-nodes", "metadata-bytes", "encoded-bodies", "identity-length"])
def test_limits_refuse_before_decode_without_large_test_fixtures(histories, monkeypatch, constant, value):
    design = _design(histories)
    monkeypatch.setattr(recovery, constant, value, raising=False)
    _no_materialization(monkeypatch)
    _refused(lambda: crud._seek_feature_log(design, -1))


def test_schema_admission_is_not_a_decode_replay_or_geometry_operation(histories, monkeypatch):
    from backend.core import part_group_organization

    design = _design(histories)
    design.feature_log[4].params["_generator"] = {"label": "Bounded provenance"}
    # Body contents are deliberately opaque to this metadata-only guard.
    # A later decoder still owns their validity; this is not input proof.
    design.feature_log[4].design_snapshot_gz_b64 = "not decoded by admission"
    original = design.model_dump(mode="json")
    with monkeypatch.context() as patch:
        _no_materialization(patch)
        patch.setattr(part_group_organization, "build", _tripwire)
        patch.setattr(m.SnapshotLogEntry, "model_dump", _tripwire)
        assert recovery.prepare_group_seek(design, -1) == {}
    assert design.model_dump(mode="json") == original


@pytest.mark.parametrize("optimized", [False, True], ids=["ordinary", "optimized-33"])
def test_complete_same_id_recreation_roundtrips_each_incarnation(histories, optimized):
    _, states = histories[False]
    design = states[4]
    recreated = _append(design, m.SnapshotLogEntry(id="recreated-placement",
        op_kind="group-create", label="Recreated organization", params={"_proof_version": 1,
            "group": group("placement", name="New organizational identity",
                           helix_ids=[design.helices[1].id])}))
    expected = {2: states[2], 3: states[3], 4: states[4], 5: recreated}
    design = recreated
    for index in range(27 if optimized else 0):
        design = _append(design, m.SnapshotLogEntry(id=f"rename-{index}",
            op_kind="group-update", label="Rename recreated group", params={"_proof_version": 1,
                "group_id": "placement", "fields": {"name": f"Later name {index}"}}))
    assert len(design.feature_log) == (33 if optimized else 6)
    original = design.model_dump(mode="json")
    current = design
    for position in (-1, 3, 4, 5, 2, -2, 5, 3, -1):
        current = crud._seek_feature_log(current, position, optimized=optimized)
        if position == -2:
            assert current.group_organization is None
        else:
            target = design if position == -1 else expected[position]
            assert current.group_organization == target.group_organization
            assert current.cluster_transforms == target.cluster_transforms
        current = m.Design.model_validate_json(current.model_dump_json())
    assert design.model_dump(mode="json") == original


def test_unrelated_legacy_history_has_no_new_limits_or_metadata_validation(monkeypatch):
    design = m.Design(feature_log=[m.SnapshotLogEntry(id=f"legacy-{index}", op_kind="extrude-frame",
        label="Old evicted entry", params={}, evicted=True) for index in range(2_001)])
    monkeypatch.setattr(recovery, "MAX_ORGANIZATION_ITEMS", 0, raising=False)
    _no_materialization(monkeypatch)
    assert recovery.prepare_group_seek(design, -2) == {}
    result = crud._seek_feature_log(design, -2, optimized=True)
    assert result.feature_log_cursor == -2
    assert result.group_organization is None

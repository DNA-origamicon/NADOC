"""Grouping upgrades are explicit definition receipts, never generic editors."""

from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, part_repair_input_metadata as metadata, state
from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry, RoutingClusterLogEntry
from tests.test_group_creation_v2 import arguments, grouping, row, source
from backend.core.part_overlay_commands import build


def old_group_source():
    original = source()
    group = grouping(original)
    entry = row(group, 1).model_copy(update={"id": "old-group"})
    # Keep the actual broken v1 live output. This metadata read must not try to
    # validate/reload the full model or depend on its missing placement owner.
    return build("cluster_create", original, arguments(group, 1)).copy_with(
        feature_log=[*original.feature_log, entry])


@pytest.fixture
def document():
    design = old_group_source()  # All fallible construction precedes context mutation.
    doc = f"__group_upgrade_metadata__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    revision = doc_context.current_request_revision()
    entry = doc_context.current_request_feature_log_entry_id()
    try:
        state.load_design(design)
        yield design
    finally:
        try:
            state.drop_doc(doc)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(revision)
            doc_context.set_request_feature_log_entry_id(entry)


def selection(**changes):
    design, revision = state.get_design_with_revision()
    return {"expected_design_id": design.id, "expected_revision": revision,
            "feature_id": "old-group", **changes}


def helper():
    from backend.core import part_group_repair
    return part_group_repair


def test_broken_live_group_exposes_only_exact_upgrade_without_full_source_reads(document, monkeypatch):
    import backend.api.part_proof_commands as commands

    expected = helper().upgrade_action(document.feature_log[-1])
    monkeypatch.setattr(commands, "execute", lambda *_a, **_k: pytest.fail("Metadata executed history"))
    document.helices = object()
    document.input_sources = object()
    document.feature_log[0].post_state_gz_b64 = object()
    revision, depth = state.revision(), state.undo_depth()
    result = metadata.inspect_inputs(selection())
    assert result["kind"] == "cluster_create" and result["definition_supported"] is True
    assert result["assessment"] == "inputs_only" and result["references_checked"] is False
    assert result["fields"] == []
    assert len(result["upgrades"]) == 1 and result["upgrades"][0]["label"]
    assert result["upgrades"][0]["action"] == expected
    assert result["upgrades"][0]["action"]["expected_version"] == 1
    assert (state.revision(), state.undo_depth()) == (revision, depth)


def test_metadata_hashes_and_serializes_only_detached_definition_outside_lock(document, monkeypatch):
    group_repair = helper()
    original_digest = group_repair.digest
    original_dump = ClusterCreateLogEntry.model_dump
    original_lock = state._lock
    held = False
    seen = []
    digested = []

    class TrackingLock:
        def __enter__(self):
            nonlocal held
            original_lock.acquire()
            held = True

        def __exit__(self, *_):
            nonlocal held
            held = False
            original_lock.release()

    def checked_digest(value):
        assert not held
        digested.append(value)
        return original_digest(value)

    def checked_dump(entry, *args, **kwargs):
        assert not held
        assert entry is not document.feature_log[-1]
        seen.append(entry)
        return original_dump(entry, *args, **kwargs)

    request = selection()
    monkeypatch.setattr(state, "_lock", TrackingLock())
    monkeypatch.setattr(group_repair, "digest", checked_digest)
    monkeypatch.setattr(ClusterCreateLogEntry, "model_dump", checked_dump)
    result = metadata.inspect_inputs(request)
    assert seen and digested and result["upgrades"]
    seen[0].cluster_snapshot.helix_ids.clear()
    assert document.feature_log[-1].cluster_snapshot.helix_ids


@pytest.mark.parametrize("version", [None, 2, 3, True])
def test_current_unversioned_and_unknown_rows_do_not_get_upgrade_actions(document, version):
    document.feature_log[-1] = document.feature_log[-1].model_copy(update={"proof_version": version})
    result = metadata.inspect_inputs(selection())
    assert result["upgrades"] == [] and result["fields"] == []
    assert result["definition_supported"] is False and result["reason"]


@pytest.mark.parametrize("change", ["identity", "members", "missing_snapshot"])
def test_incoherent_typed_rows_do_not_get_upgrade_receipts(document, change):
    selected = document.feature_log[-1]
    if change == "identity":
        selected.cluster_id = "different-owner"
    elif change == "members":
        selected.helix_ids = []
    else:
        selected.cluster_snapshot = None
    result = metadata.inspect_inputs(selection())
    assert not result["definition_supported"] and result["upgrades"] == [] and result["fields"] == []


@pytest.mark.parametrize("shape", ["nodes", "bytes"])
def test_overlay_definition_capture_refuses_before_hash_when_over_budget(document, monkeypatch, shape):
    monkeypatch.setattr(helper(), "digest", lambda *_: pytest.fail("Unbounded row was hashed"))
    if shape == "nodes":
        document.feature_log[-1].helix_ids = ["h"] * 10_001
    else:
        document.feature_log[-1].name = "x" * 256_001
    with pytest.raises(HTTPException) as error:
        metadata.inspect_inputs(selection())
    assert error.value.status_code == 413
    assert error.value.detail["code"] == "repair_input_capture_limit"


def test_other_overlay_kinds_still_require_reviewed_input_editor(document):
    document.feature_log[-1] = ClusterOpLogEntry(id="old-group", cluster_id="owner", proof_version=1,
        translation=[0, 0, 0], rotation=[0, 0, 0, 1], pivot=[0, 0, 0])
    with pytest.raises(HTTPException) as error:
        metadata.inspect_inputs(selection())
    assert error.value.status_code == 422


def test_group_upgrade_cannot_be_selected_as_a_routing_child(document):
    selected = document.feature_log[-1]
    document.feature_log[-1] = RoutingClusterLogEntry.model_construct(
        id="container", label="Invalid overlay container", children=[selected])
    with pytest.raises(HTTPException) as error:
        metadata.inspect_inputs(selection(feature_id="container", child_id=selected.id))
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "unsupported_repair_target"


def test_capabilities_separate_structural_upgrade_from_snapshot_scalar_edits():
    from backend.api.part_proof_commands import capabilities

    contract = capabilities()["repair_contract"]
    assert "upgrade_cluster_creation" in contract["actions"]
    assert contract["cluster_creation_upgrade"] == {
        "from_version": 1, "to_version": 2, "scope": "coherent typed cluster_create definitions",
        "expectations": ["expected_version", "expected_cluster_id", "expected_definition_sha256"],
        "publication": "Explicit repair evaluation and commit; existing definitions are not silently migrated",
    }

"""Long evaluation keeps proof inputs isolated and regenerates recovery in a child."""

import pytest
from pydantic import ValidationError

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design, OverhangRotationLogEntry
from backend.core.part_history_contract import assess_part_history
from backend.core.part_verification_capture import capture


@pytest.fixture
def native_part():
    token = set_current_doc("part-long-evaluation")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=21))
        yield state.get_or_404()
    finally:
        state.close_session()
        reset_current_doc(token)


def test_candidate_capture_keeps_definition_types_without_touching_recovery(native_part):
    source = native_part
    source.feature_log[0].design_snapshot_gz_b64 = "unreadable recovery" * 100_000
    source.feature_log[0].post_state_gz_b64 = "not a proof input" * 100_000
    source.feature_log.append(OverhangRotationLogEntry(
        overhang_ids=["missing-overhang"], rotations=[[0, 0, 0, 1]], proof_version=1,
    ))
    isolated = capture(source, preserve_entry_types=True)
    assert type(isolated.feature_log[0]) is type(source.feature_log[0])
    assert isolated.feature_log[0].params == source.feature_log[0].params
    assert not isolated.feature_log[0].design_snapshot_gz_b64
    assert not isolated.feature_log[0].post_state_gz_b64
    assert isolated.feature_log[1] == source.feature_log[1]
    isolated.feature_log[0].params["length_bp"] = 999
    assert source.feature_log[0].params["length_bp"] == 21
    isolated.feature_log[1].overhang_ids[0] = "changed"
    assert source.feature_log[1].overhang_ids == ["missing-overhang"]


@pytest.mark.parametrize("operation_input", [
    {"operation": "verify", "params": {}},
    {"operation": "append", "kind": "bundle-create", "params": {}},
    {"operation": "append", "kind": "photoproduct-create", "params": {}, "index": 0},
    {"operation": "edit", "index": 0},
    {"operation": "delete", "index": 0, "params": {}},
    {"operation": "edit", "index": True, "params": {}},
])
def test_operation_envelope_rejects_ambiguous_inputs(operation_input):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(operation_input)


@pytest.mark.parametrize("params", [
    {"huge": "x" * 256_000},
    {"wide": [0] * 10_001},
    {"nonfinite": float("nan")},
    {"opaque": object()},
])
def test_operation_budget_rejects_before_serialization_or_spawn(params, monkeypatch):
    import backend.api.part_evaluation_worker as module
    monkeypatch.setattr(module.json, "dumps", lambda *_a, **_k: pytest.fail("Unbounded serialization"))
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"operation": "edit", "index": 0, "params": params})
    with pytest.raises(ValueError):
        EvaluationWorker(Design(), {"request": {"params": params}})


def test_spawned_parameter_edit_returns_exact_replayable_candidate_without_publication(native_part):
    original, revision = state.get_design_with_revision()
    original.feature_log[0].design_snapshot_gz_b64 = "poisoned recovery"
    original.feature_log[0].post_state_gz_b64 = "poisoned saved output"
    worker = EvaluationWorker(capture(original, preserve_entry_types=True), {
        "request": {"operation": "edit", "index": 0, "params": {"length_bp": 28}},
        "header": {},
    })
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "ready", result.get("issues", result)
        candidate = Design.model_validate(result["candidate"])
    finally:
        worker.close()
    assert state.get_design_with_revision() == (original, revision)
    assert all(helix.length_bp == 28 for helix in candidate.helices)
    assert [h.id for h in candidate.helices] == [h.id for h in original.helices]
    assert candidate.feature_log[0].id == original.feature_log[0].id
    report = assess_part_history(candidate, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report
    recovered = state.decode_design_snapshot(candidate.feature_log[0].post_state_gz_b64)
    assert recovered.helices == candidate.helices
    assert recovered.cluster_transforms == candidate.cluster_transforms


def test_recovery_encoding_is_bounded_during_regeneration(native_part, monkeypatch):
    from backend.api import part_recovery_budget
    from backend.api.part_evaluation import evaluate

    source, revision = state.get_design_with_revision()
    monkeypatch.setattr(part_recovery_budget, "MAX_RECOVERY_BYTES", 1)
    result = evaluate(capture(source, preserve_entry_types=True), {
        "request": {"operation": "edit", "index": 0, "params": {"length_bp": 28}},
        "header": {},
    })
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "command_limit"
    assert state.get_design_with_revision() == (source, revision)


def test_append_reserves_its_row_before_expensive_execution():
    from backend.api.part_evaluation import evaluate
    from backend.core.models import SnapshotLogEntry
    from backend.core.part_history_contract import create_empty_part

    source = create_empty_part("Recipe at entry limit", "HONEYCOMB")
    source.feature_log = [SnapshotLogEntry(op_kind="assign-staple-sequences",
        label="Sequence", params={"_proof_version": 1}) for _ in range(2000)]
    result = evaluate(source, {
        "request": {"operation": "append", "kind": "photoproduct-create", "params": {}}, "header": {},
    }, executor=lambda *_a: pytest.fail("Execution before entry admission"))
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "command_limit"

"""Registered batch uses the shared worker without a second source proof."""

from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from backend.api.part_evaluation import EvaluationRequest, evaluate
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history
from backend.core.part_verification_capture import capture
from tests.test_part_registered_batch import GOLD, SEED, command, gold, helix, prepare, request, source


def operation(body=None, **changes):
    return {"request": {"operation": "batch", "batch": body or request()},
        "header": {"source_revision": 7, "source_design_id": "batch-part",
                   "identity": SEED, "timestamp": "2026-10-15T00:00:00Z"}, **changes}


@pytest.mark.parametrize("change", [{"batch": None}, {"params": {}}, {"kind": "duplex-relax"},
    {"index": 0}, {"sub_index": 0}, {"cascade": True}, {"expected_revision": 8},
    {"header": {}}, {"operation": "verify"}, {"operation": "edit", "index": 0, "params": {}}])
def test_batch_envelope_cannot_mix_operations_or_caller_headers(change):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"operation": "batch", "batch": request(), **change})


def test_matching_outer_revision_is_optional_and_commands_remain_typed():
    for outer in ({}, {"expected_revision": 7}):
        parsed = EvaluationRequest.model_validate({"operation": "batch", "batch": request(), **outer})
        assert parsed.batch.expected_revision == 7
        assert parsed.batch.commands[0].kind == "helix-add"
        assert "_proof_version" not in parsed.batch.commands[0].params


@pytest.mark.parametrize("header", [{}, {"source_revision": True, "source_design_id": "batch-part"},
    {"source_revision": 7, "source_design_id": "other-part", "identity": SEED, "timestamp": "now"},
    {"source_revision": 7, "source_design_id": "batch-part", "identity": SEED}])
def test_worker_requires_complete_host_capture_context_before_execution(header):
    result = evaluate(source(), operation(header=header), executor=lambda *_a: pytest.fail("Unbound batch executed"))
    assert result["issues"][0]["code"] == "invalid_capture_context" and "candidate" not in result


def test_nested_revision_is_checked_again_against_worker_header():
    payload = operation()
    payload["header"]["source_revision"] = 8
    result = evaluate(source(), payload, executor=lambda *_a: pytest.fail("Stale batch executed"))
    assert result["issues"][0]["code"] == "batch_conflict" and "candidate" not in result


def test_evaluation_reuses_one_source_proof_and_returns_distinct_composition_and_validation():
    design = prepare(body=request(gold()))["candidate"]
    design.feature_log[0].design_snapshot_gz_b64 = design.feature_log[0].post_state_gz_b64 = "poison"
    calls = []

    def run(kind, current, params):
        calls.append(kind)
        return execute(kind, current, params)

    payload = operation(request(command("nanoparticle-patch", {"nanoparticle_id": GOLD, "diameter_nm": 12.}), helix()))
    payload["header"]["identity"] = str(uuid5(UUID(SEED), "next batch"))
    result = evaluate(design, payload, executor=run)
    assert result["status"] == "ready", result
    assert calls == ["nanoparticle-create", "nanoparticle-patch", "helix-add"]
    assert result["source_assessment"]["status"] == "verified"
    assert result["batch"]["candidate_replay_verified"] is False
    assert result["batch"]["authoring_changes"]["visual_comparison"] is False
    assert {"passed", "results"} <= result["validation"].keys()
    assert design.feature_log[0].post_state_gz_b64 == "poison"


def test_batch_default_executor_keeps_long_job_refusal_for_its_prefix(monkeypatch):
    from backend.api import part_proof_commands

    design = prepare(body=request(gold()))["candidate"]

    def refusal(*_args):
        raise CommandContractError("Prefix requires an explicit long contract", code="long_job_required")

    monkeypatch.setattr(part_proof_commands, "execute", refusal)
    monkeypatch.setattr(part_proof_commands, "execute_long", lambda *_a: pytest.fail("Batch started a long native calculation"))
    payload = operation(request(helix()))
    payload["header"]["identity"] = str(uuid5(UUID(SEED), "next batch"))
    result = evaluate(design, payload)
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "long_job_required"
    assert "candidate" not in result and result["batch"]["completed"] == []


def test_spawned_mixed_batch_then_independent_cold_replay_survive_json_and_poisoned_recovery():
    design = source()
    before = design.model_dump_json()
    worker = EvaluationWorker(capture(design, preserve_entry_types=True), operation())
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "ready", result
        candidate = Design.from_json(Design.model_validate(result["candidate"]).to_json())
    finally:
        worker.close()
    assert design.model_dump_json() == before
    assert len(result["batch"]["completed"]) == 6
    assert candidate.feature_log[0].feature_type == "routing-cluster"
    for entry in candidate.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poison"
        elif entry.feature_type == "routing-cluster":
            entry.pre_state_gz_b64 = entry.post_state_gz_b64 = "poison"
            for child in entry.children:
                child.diff_added_b64 = child.diff_removed_b64 = child.diff_modified_b64 = "poison"
    verifier = VerificationWorker(capture(candidate))
    try:
        verifier.start()
        assert verifier.wait(5)
        replay = verifier.result()
        assert replay["status"] == "verified" and replay["checked_commands"] == 6, replay
    finally:
        verifier.close()


def test_direct_result_remains_replayable_and_whole_candidate_only_on_success():
    result = evaluate(source(), operation(request(gold(), command("nanoparticle-delete", {"nanoparticle_id": "missing"}), helix())))
    assert result["status"] == "failed" and "candidate" not in result
    assert result["issues"][0]["command_index"] == 1
    assert len(result["batch"]["completed"]) == len(result["batch"]["not_evaluated"]) == 1
    success = evaluate(source(), operation())
    candidate = Design.model_validate(success["candidate"])
    assert assess_part_history(candidate, execute=execute, dependencies=dependencies)["status"] == "verified"

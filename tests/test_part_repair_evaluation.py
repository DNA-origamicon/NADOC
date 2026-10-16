"""Repair uses the shared isolated worker without certifying old displayed state."""

from threading import Thread

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
from tests.test_part_recipe_repair import gold_build, request, set_input, source


def operation(**changes):
    return {"request": {"operation": "repair", "repair": request()},
            "header": {"source_revision": 7, "source_design_id": "repair-part"}, **changes}


@pytest.mark.parametrize("change", [
    {"repair": None}, {"params": {}}, {"kind": "duplex-relax"}, {"index": 0}, {"sub_index": 0},
    {"cascade": True}, {"expected_revision": 8}, {"header": {}},
    {"operation": "verify"}, {"operation": "edit", "index": 0, "params": {}},
])
def test_repair_envelope_rejects_ambiguous_operations_or_caller_capture_headers(change):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"operation": "repair", "repair": request(), **change})


def test_matching_outer_revision_is_optional_and_canonical_nested_request_is_preserved():
    for outer in ({}, {"expected_revision": 7}):
        parsed = EvaluationRequest.model_validate({"operation": "repair", "repair": request(), **outer})
        assert parsed.repair.expected_design_id == "repair-part" and parsed.repair.expected_revision == 7
        assert parsed.repair.model_dump(mode="json")["actions"] == [{**set_input(), "child_id": None}]


@pytest.mark.parametrize("header,code", [
    ({}, "invalid_capture_context"),
    ({"source_revision": True, "source_design_id": "repair-part"}, "invalid_capture_context"),
    ({"source_revision": 7, "source_design_id": "other-part"}, "invalid_capture_context"),
    ({"source_revision": 8, "source_design_id": "repair-part"}, "repair_conflict"),
])
def test_worker_requires_server_captured_context_and_never_trusts_nested_revision(header, code):
    result = evaluate(source(), operation(header=header), executor=lambda *_a: pytest.fail("Unbound repair executed"))
    assert result["issues"][0]["code"] == code and "candidate" not in result


def test_spawned_repair_rebuilds_broken_inputs_ignores_recovery_and_cold_verifies_after_reload():
    design = source()
    original = design.model_dump_json()
    assert assess_part_history(design, execute=execute, dependencies=dependencies)["status"] == "failed"
    isolated = capture(design, preserve_entry_types=True)
    worker = EvaluationWorker(isolated, operation())
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "ready", result
        candidate = Design.model_validate(result["candidate"])
    finally:
        worker.close()
    assert design.model_dump_json() == original
    assert {"passed", "results"} <= result["validation"].keys()
    assert result["repair"]["completed_prefix"] == ["create", "patch", "later"]
    assert result["repair"]["authoring_changes"] == {
        "basis": "captured_materialized_state", "changed_fields": ["nanoparticles"],
        "record_counts": {"nanoparticles": {"before": 1, "after": 2}},
        "visual_comparison": False, "scientific_qualification": False,
    }
    reloaded = Design.from_json(candidate.to_json())
    for entry in reloaded.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned again"
    verifier = VerificationWorker(capture(reloaded))
    try:
        verifier.start()
        assert verifier.wait(5)
        proof = verifier.result()
        assert proof["status"] == "verified", proof
        assert proof["checked_commands"] == 3
    finally:
        verifier.close()


def test_failed_repair_retains_first_failure_prefix_and_not_evaluated_suffix_in_canonical_result():
    design = source()
    result = evaluate(design, operation(request={"operation": "repair", "repair": request(set_input(value="future"))}))
    assert result["status"] == "failed" and "candidate" not in result
    assert result["issues"][0]["feature_id"] == "patch"
    assert result["issues"][0]["references"][0]["parameter_path"] == ["nanoparticle_id"]
    assert result["repair"]["completed_prefix"] == ["create"]
    assert result["repair"]["not_evaluated"] == ["later"]


def test_ordinary_edit_still_requires_source_proof_when_explicit_repair_would_succeed():
    design = source()
    result = evaluate(design, {"request": {"operation": "edit", "index": 1, "params": {"nanoparticle_id": "gold"}}, "header": {}})
    assert result["status"] == "failed" and "candidate" not in result
    assert result["issues"][0]["code"] == "missing_reference"
    assert evaluate(design, operation())["status"] == "ready"


@pytest.mark.parametrize("code", ["source_unavailable", "engine_mismatch"])
def test_unverified_runtime_or_source_failure_keeps_repair_diagnostics(code):
    def unavailable(kind, design, params):
        if kind == "nanoparticle-patch":
            raise CommandContractError("Required execution contract is unavailable", code=code)
        return gold_build(kind, design, params)

    result = evaluate(source(), operation(), executor=unavailable)
    assert result["status"] == "unverified" and "candidate" not in result
    assert result["issues"][0]["code"] == code
    assert result["repair"]["completed_prefix"] == ["create"]
    assert result["repair"]["not_evaluated"] == ["later"]


def test_changed_record_content_is_reported_even_when_collection_counts_are_equal():
    design = source()
    design.nanoparticles = [design.nanoparticles[0], design.nanoparticles[0].model_copy(update={"id": "future"})]
    changes = evaluate(design, operation())["repair"]["authoring_changes"]
    assert changes["changed_fields"] == ["nanoparticles"]
    assert changes["record_counts"]["nanoparticles"] == {"before": 2, "after": 2}


def test_spawned_explicit_duplex_engine_upgrade_preserves_old_revision_then_commits_and_cold_replays(monkeypatch):
    from backend.api import part_evaluation_jobs as jobs, state
    from backend.api.doc_context import reset_current_doc, set_current_doc
    from backend.core.part_history_proof import AUTHORING_FIELDS, import_root
    from tests.test_native_duplex_relax_proof import _run as run_duplex
    from tests.test_part_duplex_relax_contract import connected

    # Start from real native relaxation on the existing explicit imported basis.
    # A stale digest simulates a shared-model/code update; it is not evidence
    # that an unavailable historical engine produced the retained coordinates.
    initial = connected()
    initial.recipe_root = import_root(initial)
    appended = run_duplex(initial, {"operation": "append", "kind": "duplex-relax",
        "params": {"source": {"kind": "native"}, "duplex_id": "duplex"}})
    assert appended["status"] == "ready", appended.get("issues")
    old = Design.model_validate(appended["candidate"])
    old_entry = old.feature_log[0]
    old_entry.params["engine"]["implementation_sha256"] = "0" * 64
    old_entry.design_snapshot_gz_b64 = old_entry.post_state_gz_b64 = "poisoned old recovery"
    stale = run_duplex(old, {"operation": "verify"})
    assert stale["status"] == "unverified" and stale["issues"][0]["code"] == "engine_mismatch"

    threads = []

    def submit(*args):
        # Retain the supervisor handle for deterministic cleanup; the production
        # supervisor, spawned worker, numerical policy and commit are unchanged.
        thread = Thread(target=jobs._run, args=args, daemon=False)
        threads.append(thread)
        thread.start()

    monkeypatch.setattr(jobs, "_submit", submit)
    token = set_current_doc("native-duplex-explicit-repair")
    identity = None
    try:
        state.load_design(old)
        before, revision = old.model_dump_json(), state.revision()
        action = {"action": "upgrade_numerical_contract", "feature_id": old_entry.id,
                  "expected_engine": dict(old_entry.params["engine"])}
        started = jobs.start({"operation": "repair", "repair": {
            "repair_version": 1, "expected_design_id": old.id, "expected_revision": revision, "actions": [action]}})
        identity = started["job_id"]
        threads[0].join(30)
        assert not threads[0].is_alive(), "Tiny duplex upgrade exceeded its focused worker allowance"
        inspected = jobs.inspect(identity)
        result = inspected["result"]
        assert result["status"] == "ready", result
        assert "candidate" not in result
        assert state.get_or_404().model_dump_json() == before and state.revision() == revision
        assert state.undo_depth() == 0
        provenance = result["repair"]["numerical_upgrades"][0]
        assert provenance["changed"] and provenance["before"]["engine"] == old_entry.params["engine"]
        assert provenance["after"]["engine"]["implementation_sha256"] != "0" * 64
        assert provenance["after"]["engine"]["id"] == old_entry.params["engine"]["id"]

        committed = jobs.commit(identity)
        candidate = state.get_or_404()
        assert committed["revision"] == revision + 1 and state.undo_depth() == 1
        new_entry = candidate.feature_log[0]
        assert new_entry.id == old_entry.id
        assert {key: value for key, value in new_entry.params.items() if key != "engine"} == {
            key: value for key, value in old_entry.params.items() if key != "engine"}
        assert new_entry.params["engine"] == provenance["after"]["engine"]
        assert candidate.model_dump(include=AUTHORING_FIELDS) == old.model_dump(include=AUTHORING_FIELDS)
        assert new_entry.post_state_gz_b64 != "poisoned old recovery"
        reloaded = Design.from_json(candidate.to_json())
        reloaded.feature_log[0].design_snapshot_gz_b64 = reloaded.feature_log[0].post_state_gz_b64 = "poisoned upgraded recovery"
        proof = run_duplex(reloaded, {"operation": "verify"})
        assert proof["status"] == "reproduced_import" and proof["checked_commands"] == 1, proof
        state.undo()
        assert state.get_or_404().feature_log[0].params["engine"] == old_entry.params["engine"]
    finally:
        if identity is not None:
            with jobs._lock:
                job = jobs._jobs.get(identity)
                if job is not None:
                    job.cancelled.set()
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive(), "Repair supervisor failed to reap its worker"
        with jobs._lock:
            jobs._jobs.pop(identity, None)
        state.close_session()
        reset_current_doc(token)

"""Reference selection crosses the isolated worker boundary without candidates."""

import pytest
from pydantic import ValidationError

from backend.api.part_evaluation import EvaluationRequest, evaluate
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.core.part_verification_capture import capture
from tests.test_part_recipe_repair import gold_params, row, source
from tests.test_part_repair_selection import request


def operation(**changes):
    return {"request": {"operation": "selection", "selection": request()},
            "header": {"source_revision": 7, "source_design_id": "repair-part"}, **changes}


@pytest.mark.parametrize("change", [
    {"selection": None}, {"params": {}}, {"kind": "duplex-relax"}, {"index": 0}, {"sub_index": 0},
    {"cascade": True}, {"expected_revision": 8}, {"header": {}}, {"candidate": {}},
    {"operation": "verify"}, {"operation": "edit", "index": 0, "params": {}},
    {"operation": "repair"}, {"repair": {"repair_version": 1}},
])
def test_selection_envelope_rejects_mutations_and_caller_capture_context(change):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"operation": "selection", "selection": request(), **change})


def test_matching_outer_revision_is_optional_and_nested_selection_remains_exact():
    for outer in ({}, {"expected_revision": 7}):
        parsed = EvaluationRequest.model_validate({"operation": "selection", "selection": request(), **outer})
        assert parsed.selection.model_dump(mode="json") == {**request(), "child_id": None, "limit": 100}
        assert parsed.repair is None and parsed.params is None


@pytest.mark.parametrize("header,code", [
    ({}, "invalid_capture_context"),
    ({"source_revision": True, "source_design_id": "repair-part"}, "invalid_capture_context"),
    ({"source_revision": 7, "source_design_id": "other"}, "invalid_capture_context"),
    ({"source_revision": 8, "source_design_id": "repair-part"}, "selection_conflict"),
])
def test_worker_requires_host_capture_context_not_just_client_expectation(header, code):
    result = evaluate(source(), operation(header=header), executor=lambda *_a: pytest.fail("Unbound selector executed"))
    assert result["issues"][0]["code"] == code and "candidate" not in result


def test_spawned_selection_ignores_recovery_and_saved_geometry_without_running_broken_target():
    design = source()
    before = design.model_dump_json()
    worker = EvaluationWorker(capture(design, preserve_entry_types=True), operation())
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
    finally:
        worker.close()
    assert result["status"] == "preview", result
    assert result["selection"]["candidates"] == [{"kind": "nanoparticle", "identity": "gold", "label": "gold"}]
    assert result["selection"]["completed_prefix"] == ["create"]
    assert result["selection"]["not_evaluated"] == ["patch", "later"]
    assert not result["native_editable"] and not result["selection"]["whole_command_validated"]
    assert all(key not in result for key in ("candidate", "validation", "geometry", "authoring_changes"))
    assert design.model_dump_json() == before


def test_failed_prefix_retains_typed_failure_and_does_not_expose_a_partial_preview():
    design = source()
    design.feature_log.insert(1, row("broken-prefix", "nanoparticle-delete", gold_params("gone")))
    result = evaluate(design, operation())
    assert result["status"] == "failed" and result["issues"][0]["code"] == "missing_reference"
    assert result["issues"][0]["feature_id"] == "broken-prefix"
    assert result["selection"]["completed_prefix"] == ["create"]
    assert result["selection"]["not_evaluated"] == ["patch", "later"]
    assert result["selection"]["candidates"] == [] and "candidate" not in result


def test_no_per_candidate_executor_and_no_validation_or_comparison_phase(monkeypatch):
    from backend.api import part_evaluation
    from backend.api.part_nanoparticle_commands import build
    from backend.core import validator

    calls = []

    def execute(kind, current, params):
        calls.append((kind, params["nanoparticle_id"]))
        return build(kind, current, params)

    monkeypatch.setattr(validator, "validate_design", lambda *_a: pytest.fail("Selector performed final validation"))
    monkeypatch.setattr(part_evaluation, "_authoring_changes", lambda *_a: pytest.fail("Selector compared whole models"))
    design = source()
    design.feature_log.insert(1, row("second", "nanoparticle-create", gold_params("second", diameter_nm=8.0)))
    result = evaluate(design, operation(), executor=execute)
    assert result["status"] == "preview"
    assert [item["identity"] for item in result["selection"]["candidates"]] == ["gold", "second"]
    assert calls == [("nanoparticle-create", "gold"), ("nanoparticle-create", "second")]


@pytest.mark.parametrize("selection", [{"limit": 101}, {"expected_revision": True},
    {"parameter_path": [False]}, {"unexpected": [None] * 10001}])
def test_nested_request_bounds_apply_before_worker_transport(selection):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"operation": "selection", "selection": request(**selection)})

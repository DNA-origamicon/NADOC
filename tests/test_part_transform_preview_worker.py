"""Private transform worker boundaries; no host, session or rollout authority.

Small native recipes exercise the real Prepare/Apply pair. Numerical producer
fixtures and timing live in test_part_transform_numerical_history separately.
"""

from copy import deepcopy

from fastapi import HTTPException
import pytest

from backend.api import part_transform_preview_worker as worker
from backend.api.part_evaluation_candidate import CandidateDecodeError
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker, WorkerLimit
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history
from tests.test_part_deformation_preview import authoring, owned_capture
from tests.test_part_transform_preview import FEATURE, source_recipe
from tests.test_part_verification_worker import _assert_unlinked


PATCH = {"translation": [4.0, 2.0, 1.0]}


def operation(action, params=None):
    return {"action": action, "feature_id": FEATURE, "params": params}


@pytest.fixture(scope="module")
def native_results():
    source = source_recipe()
    captured = owned_capture(source)
    before = captured.model_dump(mode="json")
    prepared = worker.evaluate_operation(captured, operation("prepare"))
    applied = worker.evaluate_operation(captured, operation("apply", PATCH))
    assert prepared["status"] == "prepared", prepared
    assert applied["status"] == "ready", applied
    assert captured.model_dump(mode="json") == before
    return captured, prepared, applied


@pytest.fixture
def results(native_results):
    source, prepared, applied = native_results
    return source.model_copy(deep=True), deepcopy(prepared), deepcopy(applied)


def test_native_prepare_and_apply_are_owned_exact_and_cold_replayable(results):
    source, raw, applied = results
    source_before = source.model_dump(mode="json")
    prepared = worker.decode_prepared(source, FEATURE, raw)
    assert prepared.feature_id == FEATURE
    assert len(prepared.copy_prefix().helices) == 2
    assert prepared.copy_prefix().feature_log == []
    assert prepared._entry.source == "manual-test"
    assert prepared._entry.translation == [1, 2, 3]
    candidate = worker.decode_applied(source, FEATURE, applied, params=PATCH)
    assert candidate.id == source.id
    assert len(candidate.helices) == 3  # the unchanged downstream extrusion ran
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    assert candidate.feature_log[1].translation == PATCH["translation"]
    assert candidate.feature_log[1].authored_fields == source.feature_log[1].authored_fields
    proof = assess_part_history(candidate, execute=execute, dependencies=dependencies)
    assert proof["status"] == "verified", proof
    reloaded = Design.from_json(candidate.to_json())
    assert authoring(reloaded) == authoring(candidate)
    assert reloaded.feature_log[1].source == "manual-test"
    prepared.copy_prefix().helices.clear()
    raw["prefix"]["helices"].clear()
    assert len(prepared.copy_prefix().helices) == 2
    candidate.helices.clear()
    assert source.model_dump(mode="json") == source_before


def test_prepare_never_executes_selected_or_suffix_or_reads_recovery(monkeypatch):
    from backend.api import part_deformation_preview as preview, state

    source = owned_capture(source_recipe())
    native = preview.execute
    calls = []

    def record(kind, design, params):
        calls.append(kind)
        assert kind == "bundle-create"
        return native(kind, design, params)

    monkeypatch.setattr(preview, "execute", record)
    monkeypatch.setattr(state, "decode_design_snapshot", lambda *_: pytest.fail("decoded recovery"))
    result = worker.evaluate_operation(source, operation("prepare"))
    assert result["status"] == "prepared", result
    assert calls == ["bundle-create"]


@pytest.mark.parametrize("missing", [False, True], ids=["unknown-engine", "missing-endpoint"])
def test_native_numerical_prefix_refuses_before_placement(monkeypatch, missing):
    from backend.core import cpd_design
    from backend.core.models import SnapshotLogEntry
    from tests.test_native_cpd_proof import _incorrect_engine_params
    from tests.test_part_transform_numerical_history import native_cpd_prefix, selected_transform

    source, identities = native_cpd_prefix()
    params = {**_incorrect_engine_params(), "base_keys": list(identities["base_keys"])}
    if missing:
        params["base_keys"][1] = "__xb__:missing-crossover:1"
    # This intentionally broken input row has no materialized CPD output. Prepare
    # must diagnose its native input; neither the current model nor recovery can
    # replace the missing reference or unknown engine implementation.
    row = SnapshotLogEntry(id="unusable-numerical-producer", op_kind="photoproduct-create",
        label="Unusable producer", params=params, post_state_gz_b64="poisoned")
    source = source.copy_with(feature_log=[*source.feature_log, row])
    source = owned_capture(selected_transform(source))
    before = source.model_dump(mode="json")
    monkeypatch.setattr(cpd_design, "convert_extra_pair", lambda *_a, **_k: pytest.fail("placed invalid CPD"))
    result = worker.evaluate_operation(source, operation("prepare"))
    assert result["status"] in {"failed", "unverified"}
    assert result["issues"][0]["code"] == ("missing_reference" if missing else "engine_mismatch")
    assert result["issues"][0]["feature_id"] == "unusable-numerical-producer"
    if missing:
        assert result["issues"][0]["references"] == [{"kind": "base_key",
            "identity": "__xb__:missing-crossover:1", "parameter_path": ["base_keys", 1]}]
    assert "prefix" not in result and "candidate" not in result
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", ["nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete"])
def test_all_residue_roles_rebind_exact_original_inputs_on_owned_prefix(kind):
    captured = owned_capture(source_recipe(kind))
    result = worker.evaluate_operation(captured, operation("prepare"))
    assert result["status"] == "prepared", result
    prepared = worker.decode_prepared(captured, FEATURE, result)
    assert prepared.kind == kind and prepared.feature_id == FEATURE
    assert prepared._entry.params == result["entry"]["params"]
    if kind == "nucleotide-transform-delete":
        existing = prepared.copy_prefix().nucleotide_transforms[0]
        assert prepared._entry.params["transform_id"] == existing.id
        assert prepared._entry.params["target"] == list(existing.target_key())


@pytest.mark.parametrize("field,value", [("feature_id", "other"), ("design_id", "other"),
    ("kind", "nucleotide-transform"), ("definition_sha256", "0" * 64)])
def test_prepare_refuses_mismatched_original_selection_before_decode(results, monkeypatch, field, value):
    source, raw, _ = results
    raw["binding"][field] = value
    monkeypatch.setattr(worker, "decode_candidate", lambda *_: pytest.fail("decoded mismatched selection"))
    with pytest.raises(CommandContractError, match="captured selection"):
        worker.decode_prepared(source, FEATURE, raw)


@pytest.mark.parametrize("action", ["prepare", "apply"])
def test_changed_prefix_definition_with_same_source_and_selected_ids_refuses(results, action):
    source, prepared, applied = results
    source.feature_log[0].params["length_bp"] += 1
    with pytest.raises(CommandContractError):
        if action == "prepare":
            worker.decode_prepared(source, FEATURE, prepared)
        else:
            worker.decode_applied(source, FEATURE, applied, params=PATCH)


def test_apply_refuses_result_for_another_draft_of_the_same_selected_row(results):
    source, _, applied = results
    with pytest.raises(CommandContractError):
        worker.decode_applied(source, FEATURE, applied, params={"translation": [9.0, 2.0, 1.0]})


@pytest.mark.parametrize("field", ["design_id", "feature_id", "kind"])
def test_apply_refuses_mismatched_original_binding(results, field):
    source, _, result = results
    result["binding"][field] = "another-identity"
    with pytest.raises(CommandContractError):
        worker.decode_applied(source, FEATURE, result, params=PATCH)


@pytest.mark.parametrize("mutation", ["design-id", "root", "selected-id", "selected-role", "suffix-id"])
def test_apply_refuses_wrong_candidate_identity_or_recipe_even_when_it_decodes(results, mutation):
    source, _, result = results
    candidate = result["candidate"]
    if mutation == "design-id":
        candidate["id"] = "different-part"
    elif mutation == "root":
        candidate["recipe_root"]["initial_name"] = "different-root"
    elif mutation == "selected-id":
        candidate["feature_log"][1]["id"] = "different-feature"
    elif mutation == "selected-role":
        candidate["feature_log"][1] = {**deepcopy(candidate["feature_log"][0]), "id": FEATURE}
    else:
        candidate["feature_log"][-1]["id"] = "different-suffix"
    with pytest.raises(CommandContractError):
        worker.decode_applied(source, FEATURE, result, params=PATCH)


def test_prepare_rejects_normalized_prefix_before_exposing_owned_models(results):
    source, raw, _ = results
    raw["prefix"]["helices"][0]["length_bp"] = 12.0
    with pytest.raises((CandidateDecodeError, CommandContractError)) as caught:
        worker.decode_prepared(source, FEATURE, raw)
    assert caught.value.code in {"candidate_decode_changed_authoring", "invalid_transform_worker_result"}


@pytest.mark.parametrize("mutation", ["numeric-type", "unknown-field", "authored-fields"])
def test_prepare_keeps_exact_selected_metadata_not_python_numeric_equality(results, mutation):
    source, raw, _ = results
    if mutation == "numeric-type":
        raw["entry"]["translation"][0] = 1  # typed row serialized float 1.0
    elif mutation == "unknown-field":
        raw["entry"]["unreviewed"] = True
    else:
        raw["entry"]["authored_fields"]["name"] = "Different authored name"
    with pytest.raises(CommandContractError):
        worker.decode_prepared(source, FEATURE, raw)


@pytest.mark.parametrize("mutation", ["root", "history", "cursor"])
def test_prepare_refuses_retained_history_or_a_different_root(results, mutation):
    source, raw, _ = results
    if mutation == "root":
        raw["prefix"]["recipe_root"]["initial_name"] = "Other root"
    elif mutation == "history":
        raw["prefix"]["feature_log"] = [source.feature_log[0].model_dump(mode="json")]
    else:
        raw["prefix"]["feature_log_cursor"] = 0
    with pytest.raises(CommandContractError):
        worker.decode_prepared(source, FEATURE, raw)


@pytest.mark.parametrize("shape", ["aliased-tree", "cycle", "nonfinite"], ids=str)
def test_raw_prepare_budget_precedes_model_decode_for_expanded_json(results, monkeypatch, shape):
    source, raw, _ = results
    if shape == "aliased-tree":
        # Expanded ASCII content alone exceeds 2 MB; the shared serializer
        # correctly charges ASCII once per byte, not four bytes per character.
        shared = ["x" * 512 for _ in range(128)]
        raw["prefix"]["metadata"]["notes"] = [shared] * 64
    elif shape == "cycle":
        raw["prefix"]["metadata"]["notes"] = raw
    else:
        raw["prefix"]["metadata"]["notes"] = float("nan")
    monkeypatch.setattr(worker, "decode_candidate", lambda *_: pytest.fail("decoded inadmissible raw prefix"))
    with pytest.raises(CommandContractError) as caught:
        worker.decode_prepared(source, FEATURE, raw)
    assert caught.value.code in {"preview_limit", "invalid_transform_worker_result"}


def test_aliased_captured_source_is_bounded_before_whole_model_serialization(results, monkeypatch):
    from backend.core.part_verification_capture import admit

    source, _, _ = results
    suffix = source.feature_log[-1]
    leaf = {"text": "x" * 512}
    annotation = [leaf] * 50
    # Each inert suffix annotation fits the per-command input allowance. The
    # owned graph is small, but JSON expands its shared leaf at every position:
    # the strings alone exceed 2 MB before considering keys or other authoring.
    assert 96 * len(annotation) * len(leaf["text"]) > worker.MAX_PREFIX_BYTES
    source.feature_log.extend(suffix.model_copy(update={
        "id": f"aliased-suffix-{index}",
        "params": {**suffix.params, "_generator": annotation},
    }) for index in range(96))
    admit(source, preserve_entry_types=True)
    assert source.feature_log[-1].params["_generator"][0] is leaf
    assert source.feature_log[-1].params["_generator"][-1] is leaf

    monkeypatch.setattr(Design, "model_dump", lambda *_args, **_kwargs:
                        pytest.fail("serialized oversized aliased source"))
    result = worker.evaluate_operation(source, operation("prepare"))
    assert result["status"] == "unverified", result
    assert result["issues"][0]["code"] == "preview_limit"
    assert "prefix" not in result and "candidate" not in result


@pytest.mark.parametrize("bad", [
    {"action": [], "feature_id": FEATURE, "params": None},
    {"action": {}, "feature_id": FEATURE, "params": None},
    {"action": "other", "feature_id": FEATURE, "params": None},
    {"action": "prepare", "feature_id": FEATURE, "params": {}},
    {"action": "apply", "feature_id": FEATURE, "params": None},
    {"action": "prepare", "feature_id": FEATURE, "params": None, "executor": "other"},
], ids=["list-action", "object-action", "unknown-action", "prepare-params", "missing-apply-params", "unknown-field"])
def test_private_worker_operation_is_closed_before_selection(results, monkeypatch, bad):
    source, _, _ = results
    monkeypatch.setattr(worker, "select_from_capture", lambda *_: pytest.fail("selected malformed request"))
    result = worker.evaluate_operation(source, bad)
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "invalid_transform_worker_request"
    assert "prefix" not in result and "candidate" not in result


def test_apply_retains_exact_typed_reference_failure_and_feature_id(results):
    source, _, _ = results
    result = worker.evaluate_operation(source, operation("apply", {"cluster_id": "absent-owner"}))
    assert result["status"] == "failed"
    issue = result["issues"][0]
    assert issue["http_status"] == 409
    assert issue["detail"]["code"] == "missing_reference"
    assert issue["detail"]["feature_id"] == FEATURE
    assert issue["detail"]["references"] == [{"kind": "cluster", "identity": "absent-owner",
        "parameter_path": ["cluster_id"]}]
    assert "candidate" not in result


@pytest.mark.parametrize("status", [408, 413, 429])
def test_apply_preserves_resource_refusal_status_without_partial_candidate(results, monkeypatch, status):
    source, _, _ = results

    def refuse(*_args, **_kwargs):
        raise HTTPException(status, detail={"code": "native-resource-refusal", "feature_id": FEATURE})

    monkeypatch.setattr(worker, "prepare_change", refuse)
    result = worker.evaluate_operation(source, operation("apply", PATCH))
    assert result["issues"] == [{"code": "evaluation_rejected", "http_status": status,
        "detail": {"code": "native-resource-refusal", "feature_id": FEATURE}}]
    assert "candidate" not in result


def test_input_pickle_limit_refuses_before_shared_memory_allocation(results, monkeypatch):
    from backend.api import part_verification_worker as transport

    source, _, _ = results
    source.metadata.name = "x" * 2048
    monkeypatch.setattr(transport, "MAX_INPUT_BYTES", 1024)
    monkeypatch.setattr(VerificationWorker, "_initialize_input", lambda *_a, **_k: pytest.fail("allocated oversized transport"))
    with pytest.raises(WorkerLimit, match="input budget"):
        worker.TransformPreviewWorker(source, FEATURE)


@pytest.mark.parametrize("action", ["prepare", "apply"])
def test_real_small_worker_transport_is_isolated_and_releases_both_buffers(results, action):
    source, _, _ = results
    original = source.model_dump(mode="json")
    child = worker.TransformPreviewWorker(source, FEATURE, **({"params": PATCH} if action == "apply" else {}))
    names = [buffer.name for buffer in child._buffers]
    try:
        child.start()
        assert child.wait(15), "Tiny nonnumerical worker exceeded focused transport allowance"
        result = child.result()
        if action == "prepare":
            assert result["status"] == "prepared", result
            assert worker.decode_prepared(source, FEATURE, result).feature_id == FEATURE
        else:
            assert result["status"] == "ready", result
            assert worker.decode_applied(source, FEATURE, result, params=PATCH).feature_log[1].translation == PATCH["translation"]
    finally:
        child.close()
        _assert_unlinked(names)
    assert source.model_dump(mode="json") == original


@pytest.mark.parametrize("action,status", [("prepare", "ready"), ("apply", "prepared"), ("prepare", "unknown")])
def test_worker_result_cannot_change_operation_role(monkeypatch, action, status):
    child = object.__new__(worker.TransformPreviewWorker)
    child.action = action
    monkeypatch.setattr(child, "_read_result", lambda: {"status": status, "issues": []})
    with pytest.raises(CommandContractError):
        child.result()

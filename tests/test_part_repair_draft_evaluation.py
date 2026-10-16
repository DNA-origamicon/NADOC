"""Saved drafts compile to the existing repair request without replanning."""

from dataclasses import replace

import pytest

from backend.core.part_command_errors import CommandContractError
from backend.core.part_input_sources import EmbeddedInput, embed
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_draft_evaluation import compile_draft_evaluation, parse_evaluation_request
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from tests.test_part_recipe_repair import set_input, source as broken_source


def source():
    design = broken_source()
    design.repair_draft = RepairDraft.model_validate({"version": 1, "draft_id": "saved-proposal", "generation": 3,
        "base_design_id": design.id, "base": repair_base_fingerprint(design).model_dump(mode="json"),
        "repair_version": 1, "actions": [set_input()]})
    return design


def request(design=None, **changes):
    design = source() if design is None else design
    return {"draft_version": 1, "expected_design_id": design.id, "expected_revision": 7,
        "expected_draft_id": design.repair_draft.draft_id,
        "expected_generation": design.repair_draft.generation, **changes}


def captured(design):
    return capture_draft_inputs(design, source_revision=7, draft=design.repair_draft)


def test_compile_retains_exact_actions_and_owns_mutable_request_json(monkeypatch):
    design = source()
    capture = captured(design)
    before = design.model_dump_json()
    # Invalid old expectations are deliberately retained for the existing
    # repair worker's per-action diagnostics; no host silently substitutes them.
    capture.draft.actions[0].expected_old = "obsolete expectation"
    monkeypatch.setattr("backend.core.part_repair_planning.plan_actions",
                        lambda *_a, **_k: pytest.fail("Draft compiler duplicated action planning"))
    result = compile_draft_evaluation(capture, request(design))
    assert result.expected_design_id == design.id and result.expected_revision == 7
    assert result.actions[0].expected_old == "obsolete expectation"
    assert result.actions[0].value == "gold"
    result.actions[0].value = "mutated request"
    assert capture.draft.actions[0].value == "gold"
    assert design.model_dump_json() == before


@pytest.mark.parametrize("field,value", [("expected_design_id", "another-part"), ("expected_revision", 6),
    ("expected_draft_id", "another-draft"), ("expected_generation", 2)])
def test_mismatched_draft_and_runtime_identity_never_hashes_base(field, value, monkeypatch):
    import backend.core.part_repair_draft_evaluation as compiler
    design = source()
    monkeypatch.setattr(compiler, "repair_base_fingerprint", lambda *_a, **_k: pytest.fail("Stale request hashed"))
    with pytest.raises(CommandContractError) as error:
        compile_draft_evaluation(captured(design), request(design, **{field: value}))
    assert error.value.code == "draft_conflict"


@pytest.mark.parametrize("change", ["root", "inputs", "identity", "order", "base_part"])
def test_published_definition_changes_require_explicit_rebase(change):
    design = source()
    if change == "root":
        design.recipe_root = design.recipe_root.model_copy(update={"initial_name": "Other basis"})
    elif change == "inputs":
        design.feature_log[0].params["diameter_nm"] = 11.0
    elif change == "identity":
        design.feature_log[0].id = "new-owner"
    elif change == "order":
        design.feature_log.reverse()
    else:
        design.repair_draft = design.repair_draft.model_copy(update={"base_design_id": "former-part"})
    draft = design.repair_draft
    with pytest.raises(CommandContractError) as error:
        compile_draft_evaluation(captured(design), request(design))
    assert error.value.code == "draft_rebase_required"
    assert design.repair_draft is draft


@pytest.mark.parametrize("change", ["source_restore", "different_corruption"])
def test_published_source_evidence_changes_require_explicit_rebase(change):
    from tests.test_part_repair_sources import OLD, descriptor, source as source_draft
    design = source_draft(existing=EmbeddedInput(data_b64="old corruption"))
    design.input_sources[descriptor(OLD).sha256] = (
        embed(descriptor(OLD), OLD) if change == "source_restore" else EmbeddedInput(data_b64="other corruption"))
    with pytest.raises(CommandContractError) as error:
        compile_draft_evaluation(captured(design), request(design))
    assert error.value.code == "draft_rebase_required"


def test_geometry_presentation_recovery_and_unused_proposed_bytes_do_not_change_base():
    design = source()
    design.nanoparticles[0].diameter_nm = 77
    design.annotations_enabled = False
    design.feature_log[0].post_state_gz_b64 = "other recovery"
    design.input_sources["f" * 64] = EmbeddedInput(data_b64="corrupt unused proposed bytes")
    compiled = compile_draft_evaluation(captured(design), request(design))
    assert compiled.actions[0].value == "gold"


@pytest.mark.parametrize("change,code", [("root", "missing_or_unsupported_recipe_root"),
    ("cursor", "historical_cursor"), ("subcursor", "historical_cursor"), ("draft", "draft_conflict")])
def test_incomplete_basis_is_rejected_before_worker(change, code):
    design = source()
    body = request(design)
    if change == "root":
        design.recipe_root = None
    elif change == "cursor":
        design.feature_log_cursor = 0
    elif change == "subcursor":
        design.feature_log_sub_cursor = 0
    else:
        design.repair_draft = None
    with pytest.raises(CommandContractError) as error:
        compile_draft_evaluation(captured(design), body)
    assert error.value.code == code


def test_metadata_only_capture_cannot_compile():
    design = source()
    with pytest.raises(ValueError, match="captured published definitions"):
        compile_draft_evaluation(replace(captured(design), definitions_captured=False), request(design))


@pytest.mark.parametrize("field,value", [("draft_version", 2), ("expected_revision", True),
    ("expected_generation", False), ("actions", []), ("candidate", {}), ("ready", True),
    ("expected_session_identity", "client-token"), ("expected_source", {})])
def test_evaluation_schema_accepts_only_explicit_saved_draft_guards(field, value):
    with pytest.raises(ValueError):
        parse_evaluation_request(request(**{field: value}))

"""Explicit draft lifecycle prepares metadata without publishing geometry."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.api.part_proof_commands import dependencies
from backend.core.models import SnapshotLogEntry
from backend.core.part_dependencies import Dependencies
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import describe
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_draft_host import DiscardDraft, RebaseDraft, parse_draft_request, prepare_draft
from backend.core.part_repair_proposal import DraftInputError


def source():
    design = create_empty_part("Draft lifecycle", "HONEYCOMB")
    design.id = "part"
    design.feature_log = [SnapshotLogEntry(id="create", op_kind="nanoparticle-create", label="Gold",
        params={"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", "diameter_nm": 10.0}),
        SnapshotLogEntry(id="patch", op_kind="nanoparticle-patch", label="Resize",
        params={"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "missing", "diameter_nm": 12.0})]
    return design


def action(**extra):
    return {"action": "set_input", "feature_id": "patch", "parameter_path": ["nanoparticle_id"],
            "expected_old": "missing", "value": "gold", **extra}


def body(operation="create", draft=None, **extra):
    result = {"draft_version": 1, "operation": operation, "expected_design_id": "part", "expected_revision": 7,
              "expected_draft_id": draft.draft_id if draft else None,
              "expected_generation": draft.generation if draft else None}
    if operation in {"create", "update"}:
        result["actions"] = [action()]
    return {**result, **extra}


def prepare(design, value=None, draft=None, **options):
    request = parse_draft_request(body() if value is None else value)
    actions = [] if isinstance(request, DiscardDraft) else (
        draft.actions if isinstance(request, RebaseDraft) and request.actions is None else request.actions)
    captured = capture_draft_inputs(design, source_revision=7, draft=draft, proposed_actions=actions,
        include_definitions=not isinstance(request, DiscardDraft))
    return prepare_draft(captured, request, dependencies=options.pop("dependencies", dependencies),
                         new_draft_id=options.pop("new_draft_id", "draft-one"), **options)


def test_create_and_update_prepare_only_metadata_and_preserve_base_expectations():
    design = source()
    before = design.model_dump_json()
    proposal = prepare(design)
    updated = prepare(design, body("update", proposal, actions=[action(value="other-missing")]), proposal)
    assert proposal.generation == 0 and updated.generation == 1
    assert updated.draft_id == proposal.draft_id and updated.base == proposal.base
    assert updated.actions[0].value == "other-missing" and updated.actions[0].expected_old == "missing"
    assert proposal.actions[0].value == "gold"
    assert design.model_dump_json() == before


def test_definition_change_requires_explicit_rebase_and_retains_same_expected_old():
    design = source()
    proposal = prepare(design)
    design.feature_log[0].params["diameter_nm"] = 11.0
    with pytest.raises(DraftInputError) as error:
        prepare(design, body("update", proposal), proposal)
    assert error.value.code == "draft_rebase_required"
    rebased = prepare(design, body("rebase", proposal), proposal)
    assert rebased.base != proposal.base and rebased.generation == 1
    assert rebased.actions == proposal.actions


def test_rebase_never_replaces_changed_expected_old_without_explicit_new_actions():
    design = source()
    proposal = prepare(design)
    design.feature_log[1].params["nanoparticle_id"] = "different-missing"
    with pytest.raises(DraftInputError) as error:
        prepare(design, body("rebase", proposal), proposal)
    assert error.value.code == "repair_conflict"
    assert error.value.as_issue()["feature_id"] == "patch"
    assert error.value.as_issue()["parameter_path"] == ["nanoparticle_id"]
    rebased = prepare(design, body("rebase", proposal, actions=[action(expected_old="different-missing")]), proposal)
    assert rebased.actions[0].expected_old == "different-missing"
    assert proposal.actions[0].expected_old == "missing"


def test_discard_succeeds_with_only_metadata_and_never_fingerprints_or_executes(monkeypatch):
    proposal = prepare(source())
    captured = capture_draft_inputs(SimpleNamespace(id="part"), source_revision=7, draft=proposal,
                                    include_definitions=False)
    monkeypatch.setattr("backend.core.part_repair_draft_host.repair_base_fingerprint",
                        lambda *_a, **_k: pytest.fail("Discard inspected recipe"))
    assert prepare_draft(captured, body("discard", proposal), dependencies=None) is None
    assert captured.draft == proposal


@pytest.mark.parametrize("changes", [
    {"expected_design_id": "other"}, {"expected_revision": 6},
    {"expected_generation": 1}, {"expected_draft_id": "replacement-draft"},
])
def test_document_revision_and_draft_generation_guards_reject_stale_mutations(changes):
    design = source()
    proposal = prepare(design)
    with pytest.raises(DraftInputError) as error:
        prepare(design, body("update", proposal, **changes), proposal)
    assert error.value.code == "draft_conflict"


def test_create_cannot_overwrite_an_existing_draft_or_choose_its_own_identity():
    design = source()
    proposal = prepare(design)
    with pytest.raises(DraftInputError, match="already exists"):
        prepare(design, body(), proposal)
    with pytest.raises(ValueError, match="allocate"):
        prepare(design, new_draft_id=None)


@pytest.mark.parametrize("patch,code", [
    (action(expected_old="stale"), "repair_conflict"),
    (action(parameter_path=["does_not_exist"]), "invalid_parameter_path"),
    (action(parameter_path=["_proof_version"], expected_old=1, value=2), "protected_recipe_identity"),
    (action(parameter_path=["diameter_nm"], expected_old=12.0, value=-1.0), "invalid_repaired_contract"),
    (action(feature_id="gone"), "missing_feature"),
])
def test_preparation_preserves_native_target_and_input_guards(patch, code):
    design = source()
    before = design.model_dump_json()
    with pytest.raises(DraftInputError) as error:
        prepare(design, body(actions=[patch]))
    assert error.value.code == code
    assert design.model_dump_json() == before


def test_overlap_is_rejected_without_partial_input_rewrites():
    design = source()
    with pytest.raises(DraftInputError) as error:
        prepare(design, body(actions=[action(), action(value="other")]))
    assert error.value.code == "overlapping_repair_paths"
    assert design.feature_log[1].params["nanoparticle_id"] == "missing"


def test_missing_source_bytes_do_not_prevent_saving_a_valid_descriptor_change():
    design = source()
    old = describe(b"old", format="pdb", media_type="chemical/x-pdb")
    new = describe(b"new", format="pdb", media_type="chemical/x-pdb")
    design.feature_log = [SnapshotLogEntry(id="patch", op_kind="protein-import", label="Import",
        params={"_proof_version": 1, "source": old.model_dump(mode="json")})]
    request = body(actions=[action(parameter_path=["source"], expected_old=old.model_dump(mode="json"),
                                   value=new.model_dump(mode="json"))])
    proposal = prepare(design, request, dependencies=lambda *_: Dependencies())
    assert proposal.actions[0].value == new.model_dump(mode="json")
    assert not design.input_sources


def test_numerical_upgrade_saves_only_expected_pins_and_never_resolves_new_pins():
    design = source()
    pins = {"id": "old-engine", "implementation_sha256": "a" * 64}
    design.feature_log = [SnapshotLogEntry(id="relax", op_kind="duplex-relax", label="Relax",
        params={"_proof_version": 1, "engine": pins})]
    upgrade = {"action": "upgrade_numerical_contract", "feature_id": "relax", "expected_engine": pins}
    proposal = prepare(design, body(actions=[upgrade]), dependencies=lambda *_: Dependencies())
    assert proposal.actions[0].expected_engine == pins
    assert "engine" not in proposal.actions[0].model_dump()


@pytest.mark.parametrize("changes", [
    {"draft_version": True}, {"draft_version": 2}, {"expected_revision": True},
    {"expected_generation": 0}, {"expected_draft_id": "caller-chosen"},
    {"candidate": {}}, {"input_sources": {}}, {"source_bytes": "not accepted"},
    {"actions": [action()] * 65}, {"actions": [action(value="x" * 64_000)]},
])
def test_requests_are_strict_bounded_metadata_with_no_source_transport(changes):
    with pytest.raises((ValidationError, ValueError)):
        parse_draft_request(body(**changes))


def test_required_creation_absence_guards_cannot_be_omitted():
    request = body()
    request.pop("expected_generation")
    with pytest.raises(ValidationError):
        parse_draft_request(request)


def test_cancellation_leaves_previous_draft_and_source_unchanged():
    design = source()
    proposal = prepare(design)
    before = deepcopy(proposal.model_dump(mode="json"))

    def cancel():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        prepare(design, body("update", proposal), proposal, checkpoint=cancel)
    assert proposal.model_dump(mode="json") == before

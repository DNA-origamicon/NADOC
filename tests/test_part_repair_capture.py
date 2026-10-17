"""Draft capture retains private definitions and only named immutable evidence."""

from types import SimpleNamespace

import pytest

from backend.core.models import MinorMutationLogEntry, OverhangRotationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import describe, embed
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from backend.core.part_repair_inputs import SetInput
from backend.core.part_verification_capture import CaptureLimit


def source():
    design = create_empty_part("Draft capture", "HONEYCOMB")
    design.id = "part"
    design.feature_log = [SnapshotLogEntry(id="import", op_kind="protein-import", label="Import",
        params={"_proof_version": 1, "selection": ["old"]},
        design_snapshot_gz_b64="poison pre-state", post_state_gz_b64="poison output"),
        RoutingClusterLogEntry(id="group", pre_state_gz_b64="poison group", children=[
            MinorMutationLogEntry(id="child", op_subtype="nick", label="Nick", params={"bp": 2},
                                  diff_added_b64="poison diff")])]
    return design


def action(value="new"):
    return SetInput.model_validate({"action": "set_input", "feature_id": "import",
        "parameter_path": ["selection", 0], "expected_old": "old", "value": value})


def test_capture_preserves_exact_base_without_geometry_recovery_or_session_side_effects():
    design = source()
    design.feature_log.append(OverhangRotationLogEntry(id="rotate", overhang_ids=["oh"],
        rotations=[[0, 0, 0, 1]], proof_version=1))
    original = repair_base_fingerprint(design)
    before = design.model_dump_json()
    captured = capture_draft_inputs(design, source_revision=7, proposed_actions=[action()])
    assert captured.id == "part" and captured.source_revision == 7
    assert repair_base_fingerprint(captured) == original
    assert not hasattr(captured, "helices") and not hasattr(captured, "metadata")
    assert captured.feature_log[0].design_snapshot_gz_b64 == ""
    assert captured.feature_log[0].post_state_gz_b64 == ""
    assert captured.feature_log[1].id == "group"
    assert captured.feature_log[1].pre_state_gz_b64 == ""
    assert captured.feature_log[1].children[0].diff_added_b64 == ""
    assert design.model_dump_json() == before
    design.feature_log[0].params["selection"][0] = "live edit"
    design.feature_log[1].children[0].params["bp"] = 99
    design.feature_log[2].rotations[0][0] = 1
    assert repair_base_fingerprint(captured) == original


def test_capture_has_no_geometry_dependency_even_for_a_large_live_document():
    design = source()
    minimal = SimpleNamespace(id=design.id, recipe_root=design.recipe_root, feature_log=design.feature_log,
        input_sources={}, feature_log_cursor=-1, feature_log_sub_cursor=None)
    assert repair_base_fingerprint(capture_draft_inputs(minimal, source_revision=3)) == repair_base_fingerprint(design)


def test_only_published_and_typed_proposed_source_records_are_retained(monkeypatch):
    design = source()
    old = describe(b"old", format="pdb", media_type="chemical/x-pdb")
    new = describe(b"new", format="pdb", media_type="chemical/x-pdb")
    design.feature_log[0].params["source"] = old.model_dump(mode="json")
    design.input_sources = {old.sha256: embed(old, b"old"), new.sha256: embed(new, b"new"), "f" * 64: object()}
    patch = SetInput.model_validate({"action": "set_input", "feature_id": "import", "parameter_path": ["source"],
        "expected_old": old.model_dump(mode="json"), "value": new.model_dump(mode="json")})
    monkeypatch.setattr("backend.core.part_repair_planning.same_input", lambda *_: pytest.fail("Capture hashed inputs"))
    monkeypatch.setattr("backend.core.part_input_sources.decode", lambda *_: pytest.fail("Capture decoded sources"))
    captured = capture_draft_inputs(design, source_revision=1, proposed_actions=[patch])
    assert set(captured.input_sources) == {old.sha256, new.sha256}
    assert captured.input_sources[old.sha256] is design.input_sources[old.sha256]
    assert captured.input_sources[new.sha256] is design.input_sources[new.sha256]
    assert captured.feature_log[0].params["source"] == old.model_dump(mode="json")
    assert design.feature_log[0].params["source"] == old.model_dump(mode="json")


def test_missing_source_is_retained_as_descriptor_without_fetching_or_filling_bytes():
    design = source()
    old = describe(b"missing", format="pdb", media_type="chemical/x-pdb")
    design.feature_log[0].params["source"] = old.model_dump(mode="json")
    captured = capture_draft_inputs(design, source_revision=1)
    assert not captured.input_sources
    assert repair_base_fingerprint(captured) == repair_base_fingerprint(design)


def test_existing_draft_is_copied_and_metadata_only_discard_does_not_read_history():
    design = source()
    saved = RepairDraft.model_validate({"version": 1, "draft_id": "draft", "generation": 0,
        "base_design_id": "part", "base": repair_base_fingerprint(design).model_dump(mode="json"),
        "repair_version": 1, "actions": [action().model_dump(mode="json")]})
    captured = capture_draft_inputs(SimpleNamespace(id="part"), source_revision=5, draft=saved,
                                    include_definitions=False)
    assert not captured.definitions_captured and captured.draft == saved
    saved.actions[0].value = {"later": ["mutable change"]}
    assert captured.draft.actions[0].value == "new"


@pytest.mark.parametrize("limits", [
    {"max_entries": 2}, {"max_nodes": 1}, {"max_bytes": 1}, {"seconds": -1},
])
def test_definition_capture_fails_closed_at_its_own_budget(limits):
    design = source()
    before = design.model_dump_json()
    with pytest.raises(CaptureLimit):
        capture_draft_inputs(design, source_revision=1, **limits)
    assert design.model_dump_json() == before


def test_source_bytes_are_charged_before_reference_is_retained():
    design = source()
    raw = b"x" * 10_000
    descriptor = describe(raw, format="pdb", media_type="chemical/x-pdb")
    design.feature_log[0].params["source"] = descriptor.model_dump(mode="json")
    design.input_sources[descriptor.sha256] = embed(descriptor, raw)
    with pytest.raises(CaptureLimit):
        capture_draft_inputs(design, source_revision=1, max_bytes=10_000)


def test_capture_does_not_retain_untyped_source_shaped_input_values():
    design = source()
    descriptor = describe(b"unused", format="pdb", media_type="chemical/x-pdb")
    design.feature_log[0].params["opaque"] = descriptor.model_dump(mode="json")
    design.input_sources[descriptor.sha256] = object()
    assert capture_draft_inputs(design, source_revision=1).input_sources == {}

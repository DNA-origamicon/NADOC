"""Durable repair bases track definitions and evidence, not materialized output."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import EmbeddedInput, describe, embed
from backend.core.part_repair_fingerprint import RepairFingerprintLimit, repair_base_fingerprint


def source():
    design = create_empty_part("Repair base", "HONEYCOMB")
    design.id = "part-one"
    design.feature_log = [SnapshotLogEntry(id="create", op_kind="nanoparticle-create", label="Gold",
        params={"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", "diameter_nm": 10.0},
        design_snapshot_gz_b64="poisoned pre-state", post_state_gz_b64="poisoned post-state")]
    return design


def group(identity="group", child="child"):
    return RoutingClusterLogEntry(id=identity, label="Fine routing", pre_state_gz_b64="poisoned group",
        children=[MinorMutationLogEntry(id=child, op_subtype="nick", label="Nick",
            params={"_proof_version": 1, "helix_id": "helix", "bp": 2}, diff_added_b64="poisoned diff")])


def imported(data=b"Pinned source bytes"):
    design = source()
    descriptor = describe(data, format="pdb", media_type="chemical/x-pdb")
    design.feature_log = [SnapshotLogEntry(id="import", op_kind="protein-import", label="Protein",
        params={"_proof_version": 1, "source": descriptor.model_dump(mode="json")})]
    design.input_sources = {descriptor.sha256: embed(descriptor, data)}
    return design, descriptor


def test_definition_fingerprint_is_stable_across_json_reload_and_changed_session_identity():
    design = source()
    original = repair_base_fingerprint(design)
    reloaded = type(design).model_validate_json(design.model_dump_json())
    reloaded.id = "new-host-identity"  # draft.base_design_id owns this independent guard
    assert repair_base_fingerprint(reloaded) == original


def test_fingerprint_reads_only_definition_fields_not_geometry_or_a_future_draft_field():
    design = source()
    minimal = SimpleNamespace(recipe_root=design.recipe_root, feature_log=design.feature_log,
        input_sources=design.input_sources, feature_log_cursor=-1, feature_log_sub_cursor=None,
        repair_draft={"candidate": object()})
    assert repair_base_fingerprint(minimal) == repair_base_fingerprint(design)


def test_labels_timestamps_recovery_and_document_metadata_are_excluded():
    design = source()
    design.feature_log.append(group())
    original = repair_base_fingerprint(design)
    design.metadata.name = "A display name outside the initial recipe"
    design.feature_log[0].label = "Renamed"
    design.feature_log[0].timestamp = "different"
    design.feature_log[0].post_state_gz_b64 = "another poisoned saved output"
    design.feature_log[1].pre_state_gz_b64 = "different group recovery"
    design.feature_log[1].children[0].diff_added_b64 = "different poisoned diff"
    assert repair_base_fingerprint(design) == original


def test_parent_group_identity_and_child_container_boundary_are_part_of_the_base():
    design = source()
    design.feature_log.extend([group(), RoutingClusterLogEntry(id="empty-group", label="Empty", children=[])])
    original = repair_base_fingerprint(design)
    renamed = design.model_copy(deep=True)
    renamed.feature_log[1].id = "renamed-group"
    assert repair_base_fingerprint(renamed).commands_sha256 != original.commands_sha256
    moved = design.model_copy(deep=True)
    moved.feature_log[2].children = moved.feature_log[1].children
    moved.feature_log[1].children = []
    assert repair_base_fingerprint(moved).commands_sha256 != original.commands_sha256


@pytest.mark.parametrize("change", [
    lambda d: setattr(d.feature_log[0], "id", "renamed-feature"),
    lambda d: d.feature_log[0].params.update(diameter_nm=11.0),
    lambda d: d.feature_log[0].params.update(diameter_nm=10),
    lambda d: setattr(d, "feature_log_cursor", 0),
])
def test_definition_changes_and_numeric_json_types_change_the_base(change):
    design = source()
    original = repair_base_fingerprint(design)
    change(design)
    assert repair_base_fingerprint(design).commands_sha256 != original.commands_sha256


def test_root_changes_are_separate_from_command_changes():
    design = source()
    original = repair_base_fingerprint(design)
    design.recipe_root = design.recipe_root.model_copy(update={"initial_name": "Other initial name"})
    updated = repair_base_fingerprint(design)
    assert updated.root_sha256 != original.root_sha256
    assert updated.commands_sha256 == original.commands_sha256


def test_command_order_changes_but_dictionary_key_order_does_not():
    design = source()
    design.feature_log.append(group())
    original = repair_base_fingerprint(design)
    design.feature_log[0].params = dict(reversed(list(design.feature_log[0].params.items())))
    assert repair_base_fingerprint(design) == original
    design.feature_log.reverse()
    assert repair_base_fingerprint(design).commands_sha256 != original.commands_sha256


def test_overlay_inputs_are_included_without_requiring_a_snapshot_params_dict():
    from backend.core.models import OverhangRotationLogEntry

    design = source()
    design.feature_log.append(OverhangRotationLogEntry(id="rotate", overhang_ids=["oh"],
        rotations=[[0, 0, 0, 1]], proof_version=1))
    original = repair_base_fingerprint(design)
    design.feature_log[-1].rotations = [[0, 0, 1, 0]]
    assert repair_base_fingerprint(design).commands_sha256 != original.commands_sha256


def test_source_presence_corruption_and_restoration_change_only_source_evidence():
    design, descriptor = imported()
    original = repair_base_fingerprint(design)
    original_blob = design.input_sources.pop(descriptor.sha256)
    missing = repair_base_fingerprint(design)
    design.input_sources[descriptor.sha256] = EmbeddedInput(data_b64="invalid base64")
    corrupt = repair_base_fingerprint(design)
    design.input_sources[descriptor.sha256] = EmbeddedInput(data_b64="other invalid base64")
    differently_corrupt = repair_base_fingerprint(design)
    assert len({item.sources_sha256 for item in (original, missing, corrupt, differently_corrupt)}) == 4
    assert all(item.commands_sha256 == original.commands_sha256 for item in (missing, corrupt, differently_corrupt))
    design.input_sources[descriptor.sha256] = original_blob
    assert repair_base_fingerprint(design) == original


def test_validly_encoded_wrong_bytes_are_not_the_same_evidence_as_correct_source():
    design, descriptor = imported(b"aa")
    original = repair_base_fingerprint(design)
    other = describe(b"bb", format="pdb", media_type="chemical/x-pdb")
    design.input_sources[descriptor.sha256] = embed(other, b"bb")
    assert repair_base_fingerprint(design).sources_sha256 != original.sources_sha256


def test_changed_source_descriptor_is_part_of_definition_and_evidence_identity():
    design, _ = imported(b"aa")
    original = repair_base_fingerprint(design)
    design.feature_log[0].params["source"]["size_bytes"] = 3
    changed = repair_base_fingerprint(design)
    assert changed.commands_sha256 != original.commands_sha256
    assert changed.sources_sha256 != original.sources_sha256


def test_malformed_source_descriptor_fails_without_guessing_a_binding():
    design, _ = imported()
    design.feature_log[0].params["source"]["sha256"] = "not-a-source-digest"
    with pytest.raises(ValidationError):
        repair_base_fingerprint(design)


def test_unused_retained_sources_are_never_read_or_charged():
    design, _descriptor = imported()
    original = repair_base_fingerprint(design)
    # A future draft can stage additional bytes; they are outside the published
    # definition base. An intentionally invalid object proves no table-wide scan.
    design.input_sources["f" * 64] = object()
    assert repair_base_fingerprint(design) == original


def test_arbitrary_source_shaped_json_in_other_commands_is_not_interpreted_as_evidence():
    design = source()
    descriptor = describe(b"example", format="blob", media_type="application/octet-stream")
    design.feature_log[0].params["opaque"] = {"source": descriptor.model_dump(mode="json")}
    original = repair_base_fingerprint(design)
    design.input_sources[descriptor.sha256] = embed(descriptor, b"example")
    assert repair_base_fingerprint(design) == original


def test_multiple_declared_sources_and_shared_bytes_follow_binding_contract(monkeypatch):
    from backend.core import part_repair_fingerprint as fingerprint

    design, descriptor = imported()
    extra_data = b"coverage"
    extra = describe(extra_data, format="json", media_type="application/json")
    design.input_sources[extra.sha256] = embed(extra, extra_data)
    design.feature_log = [SnapshotLogEntry(id="coat", op_kind="nanoparticle-patch", label="Coat", params={
        "_proof_version": 1, "coating_version": 1, "action": "set",
        "pdb_source": descriptor.model_dump(mode="json"), "coverage_source": extra.model_dump(mode="json")}),
        SnapshotLogEntry(id="same-source", op_kind="protein-import", label="Import", params={
            "_proof_version": 1, "source": descriptor.model_dump(mode="json")})]
    calls = []
    decode = fingerprint.decode

    def counted(source, blob):
        calls.append(source.sha256)
        return decode(source, blob)

    monkeypatch.setattr(fingerprint, "decode", counted)
    original = repair_base_fingerprint(design)
    assert calls == [descriptor.sha256, extra.sha256]
    del design.input_sources[extra.sha256]
    assert repair_base_fingerprint(design).sources_sha256 != original.sources_sha256


@pytest.mark.parametrize("limits", [
    {"max_entries": 0}, {"max_input_nodes": 1}, {"max_input_bytes": 1},
    {"max_source_encoded_bytes": 1},
])
def test_fingerprint_refuses_budget_overruns_without_mutation(limits):
    design, _ = imported()
    before = design.model_dump_json()
    with pytest.raises(RepairFingerprintLimit):
        repair_base_fingerprint(design, **limits)
    assert design.model_dump_json() == before


def test_groups_count_toward_entry_budget():
    design = source()
    design.feature_log = [group()]
    with pytest.raises(RepairFingerprintLimit, match="entry"):
        repair_base_fingerprint(design, max_entries=1)
    repair_base_fingerprint(design, max_entries=2)


def test_source_budget_is_checked_before_decode(monkeypatch):
    design, _ = imported()
    monkeypatch.setattr("backend.core.part_repair_fingerprint.decode",
                        lambda *_: pytest.fail("Over-budget source was decoded"))
    with pytest.raises(RepairFingerprintLimit, match="source byte"):
        repair_base_fingerprint(design, max_source_encoded_bytes=0)


def test_duplicate_group_and_child_identity_is_rejected():
    design = source()
    design.feature_log.append(group(child="create"))
    with pytest.raises(CommandContractError, match="unique"):
        repair_base_fingerprint(design)


def test_cancellation_does_not_return_a_partial_fingerprint():
    design = source()
    before = deepcopy(design.model_dump(mode="json"))
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        if calls == 6:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        repair_base_fingerprint(design, checkpoint=cancelled)
    assert design.model_dump(mode="json") == before

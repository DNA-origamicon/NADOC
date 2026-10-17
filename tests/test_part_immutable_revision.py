"""A strict revision owns bytes, not a live Design or a proof certificate."""

from copy import copy
from dataclasses import FrozenInstanceError
import json
from weakref import ref

import pytest

from backend.api import part_immutable_revision as revisions
from backend.api.part_recovery_budget import MAX_RECOVERY_BYTES
from backend.core.models import Design, Helix, Nanoparticle, SnapshotLogEntry
from backend.core.nanoparticle import create_gold_nanosphere
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded, digest
from backend.core.part_verification_capture import CaptureLimit


def source():
    design = create_empty_part("Immutable source", "HONEYCOMB")
    design.id = "stable-part"
    return design


def retained_source():
    design = source()
    design.nanoparticles = [create_gold_nanosphere(10., nanoparticle_id="gold")]
    design.feature_log = [SnapshotLogEntry(id="feature", op_kind="nanoparticle-create", label="Gold",
        params={"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold",
                "diameter_nm": 10., "nested": {"values": [1, 2.0, True]}},
        design_snapshot_gz_b64="poisoned recovery is retained, never executed",
        post_state_gz_b64="also not executable evidence")]
    # Match the existing worker's ordinary typed JSON transport followed by
    # host candidate validation. Default Mat4x4 values become typed floats there.
    return Design.model_validate_json(design.model_dump_json())


def test_empty_revision_is_scope_qualified_and_has_no_proof_or_publication_label():
    design = source()
    handle = revisions.prepare_revision(design)
    metadata = revisions.revision_metadata(handle)
    assert type(handle.payload) is bytes
    assert json.loads(handle.payload) == design.model_dump(mode="json")
    assert metadata.design_id == design.id and metadata.name == design.metadata.name
    assert metadata.lattice_type == "HONEYCOMB"
    assert metadata.scope_tag == "registered_batch_v1" and metadata.storage_version == 1
    assert metadata.payload_bytes == len(handle.payload)
    assert metadata.history_rows == 0 and metadata.recovery_bytes == 0
    assert metadata.authoring_sha256 == digest(design.model_dump(mode="json", include=AUTHORING_FIELDS))
    assert metadata.recipe_sha256 == digest(design.model_dump(mode="json", include=revisions.RECIPE_FIELDS))
    assert not any(hasattr(metadata, name) for name in ("verified", "native_editable", "permit", "source_status"))


def test_payload_is_full_canonical_json_including_poisoned_recovery():
    design = retained_source()
    design.annotations_enabled = False
    handle = revisions.prepare_revision(design)
    expected = json.dumps(design.model_dump(mode="json"), sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode()
    assert handle.payload == expected
    assert revisions.materialize_revision(handle).model_dump(mode="json") == json.loads(expected)
    metadata = revisions.revision_metadata(handle)
    assert metadata.history_rows == 1
    assert metadata.recovery_bytes == sum(len(getattr(design.feature_log[0], field)) for field in (
        "design_snapshot_gz_b64", "post_state_gz_b64"))


def test_materializations_and_original_have_independent_nested_any_objects():
    design = retained_source()
    handle = revisions.prepare_revision(design)
    original_bytes = handle.payload
    first, second = revisions.materialize_revision(handle), revisions.materialize_revision(handle)
    first.feature_log[0].params["nested"]["values"].append("first")
    first.nanoparticles[0].diameter_nm = 99.
    design.feature_log[0].params["nested"]["values"].clear()
    design.metadata.tags.append("original alias")
    assert handle.payload is original_bytes
    assert second.feature_log[0].params["nested"]["values"] == [1, 2.0, True]
    assert second.nanoparticles[0].diameter_nm == 10.
    assert revisions.materialize_revision(handle).model_dump(mode="json") == json.loads(original_bytes)


def test_handles_are_weakrefable_and_identical_bytes_do_not_alias_identity():
    design = source()
    first, second = revisions.prepare_revision(design), revisions.prepare_revision(design)
    assert first.payload == second.payload and first is not second and first != second
    assert ref(first)() is first
    with pytest.raises((FrozenInstanceError, AttributeError)):
        first.payload = b"changed"
    with pytest.raises((FrozenInstanceError, AttributeError)):
        revisions.revision_metadata(first).name = "changed"


def test_constructor_and_copied_scope_seal_cannot_mint_another_handle():
    with pytest.raises(TypeError):
        revisions.StrictPartRevision()
    original = revisions.prepare_revision(source())
    duplicate = copy(original)
    assert not revisions.is_prepared_revision(duplicate)
    with pytest.raises(CommandContractError, match="prepared revision"):
        revisions.materialize_revision(duplicate)


@pytest.mark.parametrize("fake", [None, {}, {"storage_version": 1, "scope_tag": "registered_batch_v1"},
                                  b"{}", "{}", object()])
def test_serialized_labels_and_wrong_types_fail_before_decode(monkeypatch, fake):
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Unadmitted decode"))
    assert not revisions.is_prepared_revision(fake)
    with pytest.raises(CommandContractError, match="prepared revision"):
        revisions.materialize_revision(fake)


def test_uninitialized_exact_type_fails_before_decode(monkeypatch):
    fake = object.__new__(revisions.StrictPartRevision)
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Unadmitted decode"))
    assert not revisions.is_prepared_revision(fake)
    with pytest.raises(CommandContractError, match="prepared revision"):
        revisions.materialize_revision(fake)


@pytest.mark.parametrize("bad", [b"{}", {}, None])
def test_factory_accepts_only_a_private_design_not_restore_bytes(bad):
    with pytest.raises(CommandContractError, match="Design"):
        revisions.prepare_revision(bad)


@pytest.mark.parametrize("field,value", [("id", "x" * 1025), ("name", "x" * 1025),
    ("id", ""), ("name", ""), ("id", 12), ("name", None)])
def test_scalar_handle_metadata_is_bounded_before_serialization(monkeypatch, field, value):
    design = source()
    setattr(design if field == "id" else design.metadata, field, value)
    monkeypatch.setattr(Design, "model_dump", lambda *args, **kwargs: pytest.fail("Unadmitted serialization"))
    with pytest.raises(CommandContractError, match="bounded nonempty string"):
        revisions.prepare_revision(design)


def test_scalar_metadata_bound_is_inclusive():
    design = source()
    design.id = design.metadata.name = "x" * 1024
    metadata = revisions.revision_metadata(revisions.prepare_revision(design))
    assert metadata.design_id == metadata.name == "x" * 1024


@pytest.mark.parametrize("field,value", [("annotations_enabled", True), ("id", "changed-id")])
def test_full_roundtrip_detects_drift_outside_authoring_and_recipe(monkeypatch, field, value):
    design = retained_source()
    design.annotations_enabled = False
    original = Design.model_validate_json

    def drift(payload, *args, **kwargs):
        decoded = original(payload, *args, **kwargs)
        setattr(decoded, field, value)
        return decoded

    monkeypatch.setattr(Design, "model_validate_json", drift)
    with pytest.raises(CommandContractError) as error:
        revisions.prepare_revision(design)
    assert error.value.code == "revision_decode_changed_document"


def test_untransported_default_matrix_representation_drift_is_refused():
    design = source()
    design.nanoparticles = [Nanoparticle(id="gold", diameter_nm=10.)]
    with pytest.raises(CommandContractError) as error:
        revisions.prepare_revision(design)
    assert error.value.code == "revision_decode_changed_document"


def test_materialization_rechecks_exact_transport_after_model_behavior_changes(monkeypatch):
    handle = revisions.prepare_revision(source())
    original = Design.model_validate_json

    def drift(payload, *args, **kwargs):
        decoded = original(payload, *args, **kwargs)
        decoded.metadata.name = "new normalization"
        return decoded

    monkeypatch.setattr(Design, "model_validate_json", drift)
    with pytest.raises(CommandContractError) as error:
        revisions.materialize_revision(handle)
    assert error.value.code == "revision_decode_changed_document"


@pytest.mark.parametrize("field,value", [("input_sources", {"unqualified": object()}),
    ("repair_draft", object()), ("atomistic_reference", object()), ("annotations", [object()])])
def test_unsupported_state_never_gets_a_scope_seal(monkeypatch, field, value):
    design = source()
    setattr(design, field, value)
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Unadmitted decode"))
    with pytest.raises((CommandContractError, CaptureLimit)):
        revisions.prepare_revision(design)


def test_unknown_top_level_fields_are_not_silently_dropped(monkeypatch):
    design = source().model_copy(update={"unclassified_authority": {"verified": True}})
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Unadmitted decode"))
    with pytest.raises(CommandContractError, match="schema"):
        revisions.prepare_revision(design)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 2 ** 80, b"bytes", object(), {1: "non-string key"}])
def test_non_json_nested_inputs_fail_before_decode(monkeypatch, value):
    design = retained_source()
    design.feature_log[0].params["invalid"] = value
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Unadmitted decode"))
    with pytest.raises(CommandContractError):
        revisions.prepare_revision(design)


@pytest.mark.parametrize("cycle", [False, True])
def test_depth_and_cycles_are_refused_before_serialization(monkeypatch, cycle):
    design = retained_source()
    value = {}
    if cycle:
        value["next"] = value
    else:
        for _ in range(65):
            value = {"next": value}
    design.feature_log[0].params["invalid"] = value
    monkeypatch.setattr(Design, "model_dump", lambda *args, **kwargs: pytest.fail("Unbounded serialization"))
    with pytest.raises(CommandContractError):
        revisions.prepare_revision(design)


def test_existing_capture_authoring_budget_is_not_relaxed(monkeypatch):
    design = retained_source()
    design.feature_log[0].params["oversized"] = "a" * 500_001
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Unadmitted decode"))
    with pytest.raises(CaptureLimit):
        revisions.prepare_revision(design)


def test_existing_recovery_budget_is_not_relaxed(monkeypatch):
    design = retained_source()
    design.feature_log[0].post_state_gz_b64 = "a" * (MAX_RECOVERY_BYTES + 1)
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Unadmitted decode"))
    with pytest.raises(CaptureLimit):
        revisions.prepare_revision(design)


def test_encoded_payload_ceiling_is_checked_before_model_decode(monkeypatch):
    design = retained_source()
    monkeypatch.setattr(revisions, "MAX_CANDIDATE_BYTES", 512)
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Oversized decode"))
    with pytest.raises(CaptureLimit):
        revisions.prepare_revision(design)


def test_escaped_recovery_is_counted_by_encoded_transport_bytes(monkeypatch):
    design = retained_source()
    design.feature_log[0].post_state_gz_b64 = "\x00" * 30_000
    monkeypatch.setattr(revisions, "MAX_CANDIDATE_BYTES", 128_000)
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Oversized decode"))
    with pytest.raises(CaptureLimit, match="candidate byte ceiling"):
        revisions.prepare_revision(design)


def test_existing_aggregate_native_work_bound_is_preserved(monkeypatch):
    design = source()
    design.helices = [Helix(id="large", axis_start={"x": 0., "y": 0., "z": 0.},
                           axis_end={"x": 0., "y": 0., "z": 10.}, length_bp=50_001)]
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Oversized decode"))
    with pytest.raises(ProofBudgetExceeded, match="aggregate"):
        revisions.prepare_revision(design)


@pytest.mark.parametrize("change", ["no_root", "root_version", "legacy_row", "history_count"])
def test_existing_scope_contract_is_required_before_decode(monkeypatch, change):
    design = retained_source()
    if change == "no_root":
        design.recipe_root = None
    elif change == "root_version":
        design.recipe_root = design.recipe_root.model_copy(update={"version": 2})
    elif change == "legacy_row":
        design.feature_log[0].params.pop("_proof_version")
    else:
        design.feature_log *= 65
    monkeypatch.setattr(Design, "model_validate_json", lambda *args, **kwargs: pytest.fail("Unadmitted decode"))
    with pytest.raises((CommandContractError, CaptureLimit)):
        revisions.prepare_revision(design)


def test_preparation_cancellation_propagates_without_mutating_source():
    design = retained_source()
    before = design.model_dump_json()

    def cancelled():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        revisions.prepare_revision(design, checkpoint=cancelled)
    assert design.model_dump_json() == before

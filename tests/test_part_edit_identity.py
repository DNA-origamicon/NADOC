"""Editing-registry growth must preserve identity and existing numerical pins."""

import hashlib
from pathlib import Path

import pytest

from backend.core import feature_identity, part_edit_identity as editing
from backend.core.models import SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part
from backend.core.part_repair_inputs import SetInput
from backend.core.part_repair_planning import RepairInputError, plan_actions


CREATE = "nanoparticle-connection-version-create"
PATCH = "nanoparticle-connection-version-patch"
DELETE = "nanoparticle-connection-version-delete"


@pytest.mark.parametrize("kind", [CREATE, PATCH, DELETE])
def test_pending_edit_protects_outputs_but_keeps_consumer_references_editable(kind):
    previous = {"_proof_version": 1, "nanoparticle_connection_version": 1,
        "version_id": "authored-output", "created_at": 12.0,
        "strand_id": "old-strand", "overhang_id": "old-overhang", "name": "Before"}
    updated = {**previous, "_proof_version": 99, "nanoparticle_connection_version": 99,
        "version_id": "replacement", "created_at": 99.0, "strand_id": "new-strand",
        "overhang_id": "new-overhang", "name": "After"}
    result = editing.preserve_proof_identity(previous, updated, kind=kind)
    assert result == {**updated, "_proof_version": 1, "nanoparticle_connection_version": 1,
        "created_at": 12.0, "version_id": "authored-output" if kind == CREATE else "replacement"}
    assert previous["name"] == "Before" and updated["nanoparticle_connection_version"] == 99


def test_edit_wrapper_preserves_existing_identity_policy_and_never_creates_missing_slots():
    previous = {"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", "diameter_nm": 10.0}
    updated = {**previous, "nanoparticle_version": 99, "nanoparticle_id": "forged", "diameter_nm": 12.0}
    assert editing.preserve_proof_identity(previous, updated, kind="nanoparticle-create") == (
        feature_identity.preserve_proof_identity(previous, updated, kind="nanoparticle-create"))
    assert editing.preserve_proof_identity({}, {"name": "Edited"}, kind=CREATE) == {"name": "Edited"}


@pytest.mark.parametrize("field,value", [("version_id", "forged"), ("nanoparticle_connection_version", 99)])
def test_shared_repair_planner_rejects_new_protected_slots(field, value):
    params = {"_proof_version": 1, "nanoparticle_connection_version": 1, "version_id": "owned"}
    entry = SnapshotLogEntry(id="feature", op_kind=CREATE, label="Pending",
        timestamp="2026-10-15T00:00:00Z", params=params)
    source = create_empty_part("Planning only", "HONEYCOMB").copy_with(feature_log=[entry])
    action = SetInput.model_validate({"action": "set_input", "feature_id": entry.id,
        "parameter_path": [field], "expected_old": params[field], "value": value})
    with pytest.raises(RepairInputError) as error:
        plan_actions(source, [action])
    assert error.value.code == "protected_recipe_identity"
    assert entry.params == params


def test_new_edit_registry_does_not_change_published_duplex_identity_source_pin(monkeypatch):
    from backend.core import part_duplex_relax_contract as contract

    # This exact file was already part of duplex-v1 before pending NP features.
    # Preserve its bytes, rather than accepting another digest or auto-repinning.
    path = Path(feature_identity.__file__)
    expected = "063a5eb49c09c9335775bc6f66c83a24d667b28ad721be739796f29b3a7dc730"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    before = contract.implementation_manifest()
    monkeypatch.setitem(editing._PROTECTED, "future-edit-only-family", ("output_id",))
    assert editing.preserve_proof_identity({"output_id": "owned"}, {"output_id": "forged"},
        kind="future-edit-only-family") == {"output_id": "owned"}
    assert contract.implementation_manifest() == before
    assert before["files"]["backend/core/feature_identity.py"] == expected
    assert "backend/core/part_edit_identity.py" not in before["files"]

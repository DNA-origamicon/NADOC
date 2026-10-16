"""Tests first: applied-version rename preserves the complete legacy pipeline.

Rename is a closed input variant, not a metadata-only recorder exemption. All
new adapter imports stay inside tests while the independent broad suite runs.
"""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.api import doc_context, routes_nanoparticles as routes, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_edit import prepare_change, regenerate
from backend.api.part_verification_worker import VerificationWorker
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_dependencies import Resource
from backend.core.part_verification_capture import capture
from tests.test_part_np_application_commands import application_params, version
from tests.test_part_pending_np_connections import (
    CREATE, PATCH, append, authored, native_prefix as native_prefix, seed,
)


@pytest.fixture
def applied(native_prefix):
    source = native_prefix.model_copy(deep=True)
    return append(source, CREATE, application_params(source), "apply")


def rename_params(source, name="Renamed applied candidate"):
    # Absence of `applied` selects only the required-name variant. Existing
    # transition shapes remain separate and still require explicit outputs.
    values = application_params(source, PATCH, applied=False, history_seed=seed(9401))
    values.pop("applied")
    return {**values, "name": name}


def commands():
    from backend.api import part_np_application_commands
    return part_np_application_commands


def deny_application(monkeypatch):
    from backend.core import design_geometry, nanoparticle_connections

    def forbidden(*_args, **_kwargs):
        pytest.fail("Name-only patch attempted fitting, application or restoration")
    monkeypatch.setattr(commands(), "set_version_applied", forbidden)
    monkeypatch.setattr(nanoparticle_connections, "set_version_applied", forbidden)
    monkeypatch.setattr(routes, "_set_np_version_applied", forbidden)
    monkeypatch.setattr(design_geometry, "fitting_geometry", forbidden)


def test_pure_rename_changes_only_version_name_without_relocation_or_restoration(applied, monkeypatch):
    values = rename_params(applied)
    original = applied.model_dump_json()
    deny_application(monkeypatch)
    actual = commands().build(PATCH, applied, values)
    expected = applied.copy_with(nanoparticle_connection_versions=[
        item.model_copy(update={"name": values["name"]}) if item.id == "candidate" else item
        for item in applied.nanoparticle_connection_versions])
    assert authored(actual) == authored(expected)
    assert actual.duplexes == applied.duplexes
    assert actual.cluster_transforms == applied.cluster_transforms
    assert actual.nanoparticle_conjugations == applied.nanoparticle_conjugations
    assert actual.duplexes[0].prior_driven_topology == applied.duplexes[0].prior_driven_topology
    assert version(actual).constraint_root_nm == version(applied).constraint_root_nm
    assert version(actual).constraint_radius_nm == version(applied).constraint_radius_nm
    assert applied.model_dump_json() == original


def test_registered_rename_matches_full_legacy_route_and_keeps_postprocessing(applied, monkeypatch):
    from backend.api import part_nanoparticle_connection_commands as pending
    from backend.core import cluster_reconcile, lattice

    calls = {"reconcile": 0, "retry": 0}
    original_reconcile, original_retry = state.reconcile_cluster_membership, state._retry_pending_ligations

    def reconcile(*args, **kwargs):
        calls["reconcile"] += 1
        return original_reconcile(*args, **kwargs)

    def retry(*args, **kwargs):
        calls["retry"] += 1
        return original_retry(*args, **kwargs)

    monkeypatch.setattr(state, "reconcile_cluster_membership", reconcile)
    monkeypatch.setattr(cluster_reconcile, "reconcile_cluster_membership", reconcile)
    monkeypatch.setattr(state, "_retry_pending_ligations", retry)
    monkeypatch.setattr(lattice, "retry_pending_ligations", retry)
    monkeypatch.setattr(pending, "try_record", lambda *_args, **_kwargs: None)
    # This sentinel is limited to application. The real route response and
    # established reconciliation/retry still execute rather than being mocked.
    monkeypatch.setattr(routes, "_set_np_version_applied",
        lambda *_args, **_kwargs: pytest.fail("Legacy name-only route reapplied geometry"))
    doc = f"__np_rename_{uuid4()}"
    token = doc_context.set_current_doc(doc)
    prior_revision = doc_context.current_request_revision()
    prior_entry = doc_context.current_request_feature_log_entry_id()
    try:
        state.load_design(applied.model_copy(deep=True))
        revision, depth = state.revision(), state.undo_depth()
        routes.patch_np_connection_version("gold", "candidate", routes.NanoparticleConnectionVersionPatch(
            name="Renamed applied candidate", expected_revision=revision))
        expected = state.get_or_404().model_copy(deep=True)
        assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
        assert len(expected.feature_log) == len(applied.feature_log) + 1
        assert calls == {"reconcile": 1, "retry": 1}
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(prior_revision)
        doc_context.set_request_feature_log_entry_id(prior_entry)
    calls.update(reconcile=0, retry=0)
    actual = execute(PATCH, applied, rename_params(applied))
    assert authored(actual) == authored(expected)
    assert calls == {"reconcile": 1, "retry": 1}


def test_name_only_variant_retains_typed_dependencies_and_no_metadata_exemption(applied):
    from backend.api.part_connection_version_commands import is_metadata_command, metadata_policy

    values = rename_params(applied)
    contract = dependencies(PATCH, values)
    assert contract.known and contract.barrier
    assert Resource("duplex", version(applied).duplex_id) in contract.reads
    assert Resource("overhang", values["handle_overhang_id"]) in contract.reads
    assert Resource("nanoparticle_connection_version", "candidate") in contract.writes
    assert not any(item.kind == "duplex" for item in contract.writes)
    assert not is_metadata_command(PATCH, values)
    assert not metadata_policy(PATCH, values)


@pytest.mark.parametrize("field,kind", [
    ("version_id", "nanoparticle_connection_version"), ("nanoparticle_id", "nanoparticle"),
    ("conjugation_id", "nanoparticle_conjugation"), ("strand_id", "strand"),
    ("overhang_id", "overhang"), ("handle_overhang_id", "overhang"),
])
def test_rename_missing_selection_remains_typed_and_never_calls_application(applied, monkeypatch, field, kind):
    values = {**rename_params(applied), field: "missing"}
    original = applied.model_dump_json()
    deny_application(monkeypatch)
    with pytest.raises(ReferenceResolutionError) as error:
        commands().build(PATCH, applied, values)
    assert error.value.code == "missing_reference"
    assert {"kind": kind, "identity": "missing", "parameter_path": [field]} in error.value.references
    assert applied.model_dump_json() == original


def test_rename_requires_exact_current_duplex_and_preserves_source_on_refusal(applied, monkeypatch):
    original = applied.model_dump_json()
    deny_application(monkeypatch)
    with pytest.raises(ReferenceResolutionError) as error:
        commands().build(PATCH, applied, {**rename_params(applied), "prior_duplex_id": None})
    assert error.value.code == "invalid_selection"
    assert any(item["parameter_path"] == ["prior_duplex_id"] for item in error.value.references)
    assert applied.model_dump_json() == original


@pytest.mark.parametrize("change", [
    {"name": None}, {"name": ""}, {"name": "  "}, {"name": 42},
    {"applied": None}, {"applied": True}, {"duplex_id": "invented"},
    {"duplex_created_at": 99.0}, {"nanoparticle_application_version": 2},
    {"nanoparticle_application_version": True}, {"prior_driven_topology": {}},
])
def test_name_only_schema_never_supplies_outputs_or_weakens_transition_inputs(applied, change):
    values = {**rename_params(applied), **change}
    with pytest.raises(ValidationError):
        commands().parse_command(PATCH, values)
    assert not dependencies(PATCH, values).known


def test_existing_apply_and_unapply_schemas_remain_distinct(applied):
    apply = commands().parse_command(PATCH, application_params(applied, PATCH, duplex_id="next-duplex"))
    unapply = commands().parse_command(PATCH, application_params(applied, PATCH, applied=False))
    assert type(apply).__name__ == type(unapply).__name__ == "PatchRequest"
    assert apply.applied is True and apply.duplex_id == "next-duplex"
    assert unapply.applied is False and unapply.duplex_id is None


def test_renamed_applied_output_cold_rebuilds_without_recovery_geometry(applied):
    renamed = append(applied, PATCH, rename_params(applied), "rename")
    worker = VerificationWorker(capture(renamed))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "verified" and result["native_editable"], result
        assert result["checked_commands"] == 7
    finally:
        worker.close()
    poisoned = renamed.model_copy(deep=True)
    poisoned.duplexes[0].prior_driven_topology["driven_helix"]["axis_start"]["x"] += 1000.0
    assert authored(regenerate(poisoned, renamed.feature_log, lambda: None)) == authored(renamed)


def test_upstream_geometry_edit_regenerates_renamed_version_and_preserves_child_identity(applied):
    renamed = append(applied, PATCH, rename_params(applied), "rename")
    original = renamed.model_dump_json()
    before = deepcopy(renamed.nanoparticle_conjugations[0].surface_strands[0])
    index = next(index for index, row in enumerate(renamed.feature_log) if row.id == "particle")
    changed, _ = prepare_change(renamed, capture(renamed, preserve_entry_types=True), index,
                                lambda: None, params={"diameter_nm": 14.0})
    assert changed.nanoparticles[0].diameter_nm == 14.0
    assert changed.nanoparticle_conjugations[0].surface_strands[0].backbone_attachment_local_nm != before.backbone_attachment_local_nm
    assert version(changed).name == "Renamed applied candidate"
    assert version(changed).duplex_id == version(renamed).duplex_id
    assert changed.duplexes[0].id == renamed.duplexes[0].id
    assert {item.id for item in changed.cluster_transforms} == {item.id for item in renamed.cluster_transforms}
    assert changed.feature_log[-1].params == renamed.feature_log[-1].params
    assert renamed.model_dump_json() == original

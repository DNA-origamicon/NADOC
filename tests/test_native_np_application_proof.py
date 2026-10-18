"""Registered NP application must cold-rebuild geometry, not certify snapshots."""

from copy import deepcopy

import pytest

from backend.api.part_recipe_edit import prepare_change, regenerate
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_verification_capture import capture
from tests.test_part_pending_np_connections import (
    CREATE, DELETE, PATCH, append, authored, native_prefix as native_prefix, seed,
)
from tests.test_part_np_application_commands import application_params, version
from tests.test_part_thiol_patch_commands import move


def applied_recipe(source):
    return append(source, CREATE, application_params(source), "apply")


def test_complete_application_lifecycle_cold_rebuilds_from_native_inputs(native_prefix):
    source = native_prefix.model_copy(deep=True)
    source = applied_recipe(source)
    source = append(source, PATCH, application_params(source, PATCH, applied=False,
                    history_seed=seed(9302)), "unapply")
    source = append(source, "nanoparticle-patch", {
        "_proof_version": 1, "nanoparticle_version": 1, "thiol_version": 1,
        "nanoparticle_id": "gold", "conjugation_ids": ["gold-graft"],
        "pending_connection_version_ids": ["candidate"], "gizmo_move": move(),
    }, "move")
    source = append(source, PATCH, application_params(source, PATCH,
                    duplex_id="second-duplex", history_seed=seed(9303)), "reapply")
    # Keep application geometry in the captured expected output; deletion is
    # checked separately after the worker has rebuilt the relocated topology.
    transported = Design.model_validate_json(source.model_dump_json())
    worker = VerificationWorker(capture(transported))
    try:
        worker.start()
        assert worker.wait(5)
        proof = worker.result()
        assert proof["status"] == "verified", proof
        assert proof["native_editable"] and proof["checked_commands"] == 9
    finally:
        worker.close()
    deleted = append(source, DELETE, application_params(source, DELETE,
                     history_seed=seed(9304)), "delete")
    assert not deleted.nanoparticle_connection_versions and not deleted.duplexes
    assert all(item.bound_overhang_id is None for item in deleted.nanoparticle_conjugations[0].surface_strands)
    poisoned = deleted.model_copy(deep=True)
    poisoned.helices[0].axis_start.x += 1000.0
    assert authored(regenerate(poisoned, deleted.feature_log, lambda: None)) == authored(deleted)


def test_upstream_particle_edit_regenerates_real_applied_attachment_and_preserves_child_ids(native_prefix):
    source = applied_recipe(native_prefix.model_copy(deep=True))
    original = source.model_dump_json()
    before_handle = deepcopy(source.nanoparticle_conjugations[0].surface_strands[0])
    index = next(index for index, row in enumerate(source.feature_log) if row.id == "particle")
    candidate, _ = prepare_change(source, capture(source, preserve_entry_types=True), index,
                                  lambda: None, params={"diameter_nm": 14.0})
    assert candidate.nanoparticles[0].diameter_nm == 14.0
    after_handle = candidate.nanoparticle_conjugations[0].surface_strands[0]
    assert after_handle.backbone_attachment_local_nm != before_handle.backbone_attachment_local_nm
    assert version(candidate).duplex_id == version(source).duplex_id
    assert candidate.duplexes[0].id == source.duplexes[0].id
    assert {item.id for item in candidate.cluster_transforms} == {item.id for item in source.cluster_transforms}
    assert candidate.feature_log[-1].params == source.feature_log[-1].params
    assert source.model_dump_json() == original
    # The old materialization is not a source of saved restoration geometry.
    poisoned = source.model_copy(deep=True)
    poisoned.duplexes[0].prior_driven_topology["driven_helix"]["axis_start"]["x"] += 1000.0
    assert authored(regenerate(poisoned, candidate.feature_log, lambda: None)) == authored(candidate)


def test_deleting_the_graft_producer_reports_the_selected_owner_instead_of_restoring_output(native_prefix):
    source = applied_recipe(native_prefix.model_copy(deep=True))
    log = [row for row in source.feature_log if row.id != "graft"]
    with pytest.raises(ReferenceResolutionError) as error:
        regenerate(source, log, lambda: None)
    assert error.value.code == "missing_reference"
    assert any(ref["parameter_path"][0] in {"conjugation_id", "strand_id", "handle_overhang_id"}
               for ref in error.value.references)

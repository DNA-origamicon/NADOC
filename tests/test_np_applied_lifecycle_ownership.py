"""Existing NP application must leave coherent, locally owned lifecycle state.

ISSUE-92 tests first. These exercise the current native relocation/restoration
helpers and ordinary delete route; they do not introduce a replay contract.
"""

from copy import deepcopy
from uuid import uuid4

import pytest

from backend.api import doc_context, routes_nanoparticles as routes, state
from backend.api import part_thiol_patch_commands as motion
from backend.core.models import Design
from backend.core.two_np_generator import compatible_particle_handle
from tests.test_part_pending_np_connections import (
    CREATE, append, creation, gold, graft, native_prefix as native_prefix,
    owner_inputs, pending_model, seed,
)
from tests.test_part_thiol_patch_commands import move


@pytest.fixture
def pending(native_prefix):
    design = native_prefix.model_copy(deep=True)
    return append(design, CREATE, creation(design), "candidate-create")


def version(design, identity="candidate"):
    return next(item for item in design.nanoparticle_connection_versions if item.id == identity)


def handle(design):
    identity = version(design).strand_id
    return next(record for owner in design.nanoparticle_conjugations
                for record in owner.surface_strands if record.strand_id == identity)


def applied(design):
    result = routes._set_np_version_applied(design, "candidate", True)
    assert version(result).applied and version(result).duplex_id
    assert version(result).constraint_root_nm is not None
    assert version(result).constraint_radius_nm is not None
    return result


def test_unapply_clears_only_the_derived_active_constraint_state(pending):
    result = routes._set_np_version_applied(applied(pending), "candidate", False)
    current = version(result)
    assert not current.applied and not current.relaxed
    assert current.duplex_id is None and current.residual_nm is None
    assert current.constraint_root_nm is None
    assert current.constraint_radius_nm is None
    assert current.id == version(pending).id and current.created_at == version(pending).created_at


def test_apply_unapply_returns_to_supported_pending_thiol_motion(pending):
    result = routes._set_np_version_applied(applied(pending), "candidate", False)
    assert motion.native_route_eligible(result, "gold")
    moved = motion.build("nanoparticle-patch", result, {
        "_proof_version": 1, "nanoparticle_version": 1, "thiol_version": 1,
        "nanoparticle_id": "gold", "conjugation_ids": ["gold-graft"],
        "pending_connection_version_ids": ["candidate"], "gizmo_move": move(),
    })
    assert moved.nanoparticle_connection_versions == result.nanoparticle_connection_versions
    assert moved.nanoparticles[0].pose != result.nanoparticles[0].pose


def unrelated_binding(design):
    design = append(design, "nanoparticle-create", gold("other"), "other-particle")
    design = append(design, "nanoparticle-conjugate", graft("other", history_seed=seed(9192)), "other-graft")
    owner = next(item for item in design.nanoparticle_conjugations if item.nanoparticle_id == "other")
    # This is explicitly retained legacy direct-binding metadata, not a claimed
    # native applied receipt. Updating another particle must not normalize it.
    owner.surface_strands[0].bound_overhang_id = owner_inputs(design)["overhang_id"]
    return design, deepcopy(owner)


@pytest.mark.parametrize("operation", ["apply", "unapply", "delete"])
def test_applied_lifecycle_preserves_unrelated_direct_binding_metadata(pending, operation):
    before, expected = unrelated_binding(pending)
    if operation != "apply":
        before = applied(before)
        # Test this transition independently: the earlier apply has its own
        # case and may itself have erased the unrelated legacy metadata.
        before = before.model_copy(update={"nanoparticle_conjugations": [
            deepcopy(expected) if item.id == expected.id else item
            for item in before.nanoparticle_conjugations]})
    if operation == "delete":
        token = doc_context.set_current_doc(str(uuid4()))
        try:
            state.set_design(before)
            routes.delete_np_connection_version("gold", "candidate", expected_revision=state.revision())
            result = state.get_or_404()
            assert not result.nanoparticle_connection_versions
            actual = next(item for item in result.nanoparticle_conjugations if item.id == expected.id)
        finally:
            state.close_session()
            doc_context.reset_current_doc(token)
    else:
        result = routes._set_np_version_applied(before, "candidate", operation == "apply")
        actual = next(item for item in result.nanoparticle_conjugations if item.id == expected.id)
    assert actual == expected


def test_applied_surface_carrier_matches_live_domain_and_auxiliary_endpoint(pending):
    before_carrier = handle(pending).helix_id
    result = applied(pending)
    record = handle(result)
    strand = result.find_strand(record.strand_id)
    endpoint = next(item for item in result.overhangs if item.id == record.overhang_id)
    assert strand.domains[0].helix_id != before_carrier
    assert record.helix_id == strand.domains[0].helix_id == endpoint.helix_id
    assert record.bound_overhang_id == version(result).overhang_id
    restored = Design.model_validate_json(result.model_dump_json())
    assert handle(restored) == record
    unbound = routes._set_np_version_applied(restored, "candidate", False)
    assert handle(unbound).helix_id == before_carrier
    assert unbound.find_strand(record.strand_id).domains[0].helix_id == before_carrier


def test_planner_explicitly_skips_bound_handle_when_carrier_metadata_is_coherent(pending):
    result = applied(pending)
    record = handle(result)
    # Isolate the planner's required policy from the preexisting carrier bug:
    # fixing metadata must not turn a bound handle into a free candidate.
    record.helix_id = result.find_strand(record.strand_id).domains[0].helix_id
    assert record.bound_overhang_id is not None
    selected = compatible_particle_handle(result, "gold")
    assert selected is not None  # The second, unbound native handle remains usable.
    assert selected[2].id != record.strand_id
    assert selected[1].bound_overhang_id is None


def test_conflict_switch_clears_the_displaced_versions_active_constraints(pending):
    result = applied(pending)
    replacement = pending_model(pending, version_id="replacement", name="Replacement")
    result = result.model_copy(update={
        "nanoparticle_connection_versions": [*result.nanoparticle_connection_versions, replacement]})
    result = routes._set_np_version_applied(result, replacement.id, True)
    assert version(result, replacement.id).applied
    old = version(result)
    assert not old.applied and old.duplex_id is None
    assert old.constraint_root_nm is None and old.constraint_radius_nm is None

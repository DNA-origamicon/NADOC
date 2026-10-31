"""Native histories feeding the isolated, unapproved Direct linker candidate."""

from copy import deepcopy

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from experiments.direct_linker_candidate import candidate_model, root_endpoints
from experiments.direct_linker_native import (
    SEED, connect_inputs, connection_inputs, native_source, proposed_command,
    proposed_connect, proposed_connection_command,
)
from tests.test_direct_linker_candidate import assert_linker_internal_bonds


@pytest.fixture(scope="module")
def source():
    return native_source()


@pytest.fixture(scope="module")
def connected(source):
    return proposed_connect(source)


@pytest.fixture(scope="module")
def version_connected(source):
    return proposed_connection_command(source, connection_inputs(source), reference=source)


def assert_roots(reference, placed):
    duplex = placed.duplexes[0]
    driver = duplex.left.overhang_id if duplex.driver == "left" else duplex.right.overhang_id
    driven = next(o.id for o in placed.overhangs if o.id != driver)
    for fast in (True, False):
        before = build_atomistic_model(reference, fast_bridges=fast)
        after = candidate_model(placed, reference, [driven], fast_bridges=fast)
        for spec in reference.overhangs:
            old, new = root_endpoints(reference, before, spec.id), root_endpoints(placed, after, spec.id)
            assert new["length_nm"] == pytest.approx(old["length_nm"], abs=1e-8)
            np.testing.assert_allclose(new["fixed"], old["fixed"], atol=1e-10)
        assert_linker_internal_bonds(before, after, reference, placed, driven)


def test_input_is_a_genuine_empty_root_native_recipe(source):
    from tests.test_part_pending_connection_versions import proof

    before = source.model_dump_json()
    result = proof(source)
    assert result["status"] == "verified", result
    assert result["checked_commands"] == 3
    assert source.recipe_root.kind == "empty"
    assert [row.op_kind for row in source.feature_log] == ["bundle-create", "overhang-extrude", "overhang-extrude"]
    assert source.model_dump_json() == before


def test_real_connect_topology_and_child_preserve_both_native_roots(source, connected):
    from backend.core.duplex_cluster import duplex_cluster_for

    assert len(connected.duplexes) == 1
    assert connected.duplexes[0].bound
    assert len(connected.feature_log) == len(source.feature_log) == 3  # No fake approved F4.
    assert len(connected.helices) == len(source.helices) - 1
    assert duplex_cluster_for(connected, source.overhangs[0].id) is not None
    for parent in source.cluster_transforms:
        assert next(c for c in connected.cluster_transforms if c.id == parent.id).rotation == parent.rotation
        assert next(c for c in connected.cluster_transforms if c.id == parent.id).translation == parent.translation
    assert_roots(source, connected)


def test_production_connect_stays_refused_and_diagnostic_hook_is_restored(source):
    from fastapi import HTTPException
    from backend.api.part_duplex_commands import build
    from backend.core import direct_root_placement

    native = direct_root_placement.place_direct_roots
    original = source.model_dump_json()
    with pytest.raises(HTTPException, match="native viewer and export root linkers"):
        build("duplex-connect", source, connect_inputs(source))
    assert source.model_dump_json() == original
    assert direct_root_placement.place_direct_roots is native


def test_diagnostic_cold_reconstruction_uses_native_inputs_not_saved_outputs(source, connected):
    from backend.api.part_proof_commands import execute
    from backend.core.part_history_contract import create_empty_part
    from backend.core.part_history_proof import AUTHORING_FIELDS

    # This is comparison under the explicit experimental policy, not a native
    # production proof/receipt for the proposed Connect output.
    rebuilt = create_empty_part(source.metadata.name, "HONEYCOMB")
    for row in source.feature_log:
        rebuilt = execute(row.op_kind, rebuilt, deepcopy(row.params))
    actual = proposed_connect(rebuilt)
    assert actual.model_dump(mode="json", include=AUTHORING_FIELDS) == connected.model_dump(mode="json", include=AUTHORING_FIELDS)


def test_native_restoration_primitive_restores_atoms_without_candidate_policy(source, connected):
    from backend.core.duplex import revert_duplex_relocation

    # Duplex.bound is metadata; the native restoration primitive is a distinct action.
    reverted = revert_duplex_relocation(connected, connected.duplexes[0])
    for fast in (True, False):
        original = build_atomistic_model(source, fast_bridges=fast)
        restored = build_atomistic_model(reverted, fast_bridges=fast)
        assert original.atoms == restored.atoms
        assert original.bonds == restored.bonds


def test_opposite_driver_can_preserve_both_roots(source):
    reverse = proposed_connect(source, reverse=True)
    assert_roots(source, reverse)


def test_ordinary_version_connect_captures_root_dependencies(source, version_connected):
    from backend.api.part_proof_commands import dependencies
    from backend.core.part_dependencies import Resource
    from backend.core.part_scope_references import referenced_resources

    assert version_connected.connection_versions[0].applied
    assert_roots(source, version_connected)
    deps = dependencies("overhang-bulk", connection_inputs(source))
    assert deps.known
    assert all(Resource("overhang", o.id) in deps.reads for o in source.overhangs)
    binding = version_connected.overhang_bindings[0]
    assert all(("overhang", o.id) in referenced_resources(binding) for o in source.overhangs)


def test_native_candidate_namespace_keeps_root_ownership_and_geometry(source, version_connected):
    from backend.core.part_scope_references import namespace_design

    group = "00000000-0000-0000-0000-000000009214"
    mapped_source, mapped_connected = (namespace_design(d, group) for d in (source, version_connected))
    assert_roots(mapped_source, mapped_connected)
    assert set(mapped_connected.overhang_bindings[0].prior_driven_topology["root_bond_lengths_nm"]) == {
        o.id for o in mapped_source.overhangs}


def test_ordinary_version_unapply_restores_native_atoms(source, version_connected):
    from backend.api.part_connection_disconnect import capture_inputs

    values = capture_inputs(version_connected, version_connected.connection_versions[0], delete_version=False)
    restored = proposed_connection_command(version_connected, values, reference=source)
    assert not restored.connection_versions[0].applied
    assert not restored.duplexes and not restored.overhang_bindings
    for fast in (True, False):
        before = build_atomistic_model(source, fast_bridges=fast)
        after = build_atomistic_model(restored, fast_bridges=fast)
        assert before == after


def test_binding_driver_change_preserves_both_native_roots(source, version_connected):
    changed = proposed_command(version_connected, "duplex-patch", {
        "_proof_version": 1, "history_seed": SEED, "duplex_id": version_connected.duplexes[0].id,
        "driver": "right", "binding_ids": [version_connected.overhang_bindings[0].id],
    }, reference=source)
    assert changed.duplexes[0].driver == "right"
    assert_roots(source, changed)


def test_ordinary_version_cold_reconstruction_is_deterministic(source, version_connected):
    from backend.api.part_proof_commands import execute
    from backend.core.part_history_contract import create_empty_part
    from backend.core.part_history_proof import AUTHORING_FIELDS

    rebuilt = create_empty_part(source.metadata.name, "HONEYCOMB")
    for row in source.feature_log:
        rebuilt = execute(row.op_kind, rebuilt, deepcopy(row.params))
    actual = proposed_connection_command(rebuilt, connection_inputs(rebuilt), reference=rebuilt)
    assert actual.model_dump(mode="json", include=AUTHORING_FIELDS) == version_connected.model_dump(mode="json", include=AUTHORING_FIELDS)


def test_native_parent_move_before_connect_keeps_both_roots(source):
    from scipy.spatial.transform import Rotation
    from backend.api.part_proof_commands import execute
    from backend.core.models import ClusterOpLogEntry
    from backend.core.part_overlay_commands import command_input
    from tests.test_part_pending_connection_versions import proof

    parent = source.cluster_transforms[0]
    assert set(parent.helix_ids) == {h.id for h in source.helices}
    row = ClusterOpLogEntry(id="review-parent-pose", cluster_id=parent.id,
        translation=[3., -4., 2.], rotation=Rotation.from_euler("xyz", [25., -35., 15.], degrees=True).as_quat().tolist(),
        pivot=[1., 2., 3.], proof_version=1, source="manual-test")
    kind, params = command_input(row)
    moved = execute(kind, source, params).copy_with(feature_log=[*source.feature_log, row])
    prefix_proof = proof(moved)
    assert prefix_proof["status"] == "verified", prefix_proof
    assert prefix_proof["checked_commands"] == 4
    actual = proposed_connection_command(moved, connection_inputs(moved), reference=moved)
    assert_roots(moved, actual)

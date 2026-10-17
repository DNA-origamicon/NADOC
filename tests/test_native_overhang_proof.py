"""Native overhang inputs reproduce identities, sequences and editable children."""

import pytest
from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part
from tests.conftest import valid_overhang_sites


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("native-overhang-proof")
    try:
        crud.create_bundle(
            crud.BundleRequest(
                cells=[[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]], length_bp=42
            )
        )
        site = valid_overhang_sites(state.get_or_404())[0]
        crud.overhang_extrude(crud.OverhangExtrudeRequest(**site, length_bp=12))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def verified():
    result = verify_current_part()
    assert result["status"] == "verified", result


def test_overhang_extrusion_patch_rotation_and_producer_edit():
    oid = state.get_or_404().overhangs[0].id
    verified()
    crud.patch_overhang(
        oid,
        crud.OverhangPatchRequest(
            sequence="ACGT" * 3, label="Handle", defer_reassign=True
        ),
    )
    verified()
    crud.patch_overhang_rotations_batch(
        crud.PatchOverhangRotationsBatchBody(
            ops=[dict(overhang_id=oid, rotation=[0, 0, 1, 1])]
        )
    )
    verified()
    sid = state.get_or_404().overhangs[0].sub_domains[0].id
    crud.patch_sub_domain_rotation(
        oid, sid, crud.SubDomainRotationPatchBody(theta_deg=15, phi_deg=25, commit=True)
    )
    verified()
    crud.edit_feature(1, crud.EditFeatureBody(params={"length_bp": 14}))
    verified()
    assert state.get_or_404().overhangs[0].id == oid


def test_subdomain_split_patch_annotations_merge_and_binder():
    oid = state.get_or_404().overhangs[0].id
    sid = state.get_or_404().overhangs[0].sub_domains[0].id
    crud.split_sub_domain(
        oid, crud.SubDomainSplitRequest(sub_domain_id=sid, split_at_offset=6)
    )
    sids = [s.id for s in state.get_or_404().overhangs[0].sub_domains]
    verified()
    crud.patch_sub_domain(
        oid,
        sid,
        crud.SubDomainPatchRequest(sequence_override="ACGTAC", notes="binding domain"),
    )
    verified()
    crud.recompute_sub_domain_annotations(oid, sid)
    verified()
    crud.patch_tm_settings(crud.TmSettingsPatchRequest(na_mM=150))
    verified()
    crud.merge_sub_domains(
        oid,
        crud.SubDomainMergeRequest(sub_domain_a_id=sids[0], sub_domain_b_id=sids[1]),
    )
    verified()
    crud.generate_binder_for_overhang_endpoint(oid)
    verified()
    crud.edit_feature(2, crud.EditFeatureBody(params={"split_at_offset": 6}))
    verified()


@pytest.mark.parametrize("clear", [True, False])
def test_overhang_deletion_replays(clear):
    oid = state.get_or_404().overhangs[0].id
    if clear:
        crud.clear_all_overhangs()
    else:
        crud.delete_overhangs_batch(crud.OverhangBatchDeleteRequest(overhang_ids=[oid]))
    verified()


def second_overhang():
    first = state.get_or_404().overhangs[0]
    site = next(
        s
        for s in valid_overhang_sites(state.get_or_404())
        if s["is_five_prime"] != first.id.endswith("_5p")
    )
    crud.overhang_extrude(crud.OverhangExtrudeRequest(**site, length_bp=12))
    return state.get_or_404().overhangs[:2]


def test_binding_complete_history_and_identity_survive_producer_edit():
    from backend.api.routes_overhang_bindings import (
        create_overhang_binding,
        patch_overhang_binding,
        delete_overhang_binding,
        OverhangBindingCreateRequest,
        OverhangBindingPatchRequest,
    )

    a, b = second_overhang()
    for o in (a, b):
        crud.patch_overhang(
            o.id, crud.OverhangPatchRequest(sequence="ACGT" * 3, defer_reassign=True)
        )
    create_overhang_binding(
        OverhangBindingCreateRequest(
            sub_domain_a_id=a.sub_domains[0].id, sub_domain_b_id=b.sub_domains[0].id
        )
    )
    binding = state.get_or_404().overhang_bindings[0]
    verified()
    patch_overhang_binding(
        binding.id, OverhangBindingPatchRequest(name="Editable binding")
    )
    verified()
    crud.edit_feature(
        0,
        crud.EditFeatureBody(
            params={"cells": [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3], [8, 8]]}
        ),
    )
    assert state.get_or_404().overhang_bindings[0].id == binding.id
    verified()
    delete_overhang_binding(binding.id)
    verified()


def test_linker_length_edit_and_delete_replay_without_snapshots():
    from backend.api.routes_overhang_connections import (
        create_overhang_connection,
        patch_overhang_connection,
        delete_overhang_connection,
        OverhangConnectionCreateRequest,
        OverhangConnectionPatchRequest,
    )

    a, b = second_overhang()
    create_overhang_connection(
        OverhangConnectionCreateRequest(
            overhang_a_id=a.id,
            overhang_b_id=b.id,
            overhang_a_attach="free_end",
            overhang_b_attach="free_end",
            linker_type="ss",
            length_value=8,
            length_unit="bp",
        )
    )
    identity = state.get_or_404().overhang_connections[0].id
    verified()
    patch_overhang_connection(
        identity, OverhangConnectionPatchRequest(length_value=10, name="Bridge")
    )
    verified()
    # All saved recovery bodies are expendable to independent proof and editing.
    for entry in state.get_or_404().feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned"
    crud.edit_feature(3, crud.EditFeatureBody(params={"length_value": 12}))
    assert state.get_or_404().overhang_connections[0].id == identity
    verified()
    delete_overhang_connection(identity)
    verified()


@pytest.mark.parametrize("optimized", [False, True])
def test_later_extrusion_membership_survives_recovery_of_earlier_pose(optimized):
    from backend.api.routes_clusters import update_cluster, PatchClusterBody

    cid = state.get_or_404().cluster_transforms[0].id
    for i in range(33):
        update_cluster(cid, PatchClusterBody(name=f"Arm {i}", commit=True))
    before = state.get_or_404()
    second_overhang()
    after = state.get_or_404()
    # Earlier absolute membership edits may not erase a later extrusion's
    # inherited membership when scrubbing to its complete recorded state.
    for source in (after, crud._seek_feature_log(after, 1, optimized=optimized)):
        restored = crud._seek_feature_log(source, -1, optimized=optimized)
        assert restored.cluster_transforms == after.cluster_transforms
    restored = crud._seek_feature_log(
        after, len(before.feature_log) - 1, optimized=optimized
    )
    assert restored.cluster_transforms == before.cluster_transforms

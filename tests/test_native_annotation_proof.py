"""Full inputs, identities and producer edits for native annotations and cells."""

import pytest
from fastapi import Response
from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("native-annotation-proof")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=42))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def verified():
    result = verify_current_part()
    assert result["status"] == "verified", result


@pytest.mark.parametrize("batch", [False, True])
def test_nucleotide_pose_complete_inputs_and_identity(batch):
    from backend.api.routes_nucleotide_transforms import (
        NucleotideTransformBody,
        NucleotideTransformBatchBody,
        put_nucleotide_transform,
        put_nucleotide_transforms,
        delete_nucleotide_transform,
    )

    d = state.get_or_404()
    dom = d.strands[0].domains[0]
    body = NucleotideTransformBody(
        kind="base",
        helix_id=dom.helix_id,
        bp_index=5,
        direction=dom.direction,
        pivot=[0, 0, 0],
        translation=[1, 2, 3],
        rotation=[0, 0, 0, 1],
    )
    if batch:
        put_nucleotide_transforms(NucleotideTransformBatchBody(transforms=[body]))
    else:
        put_nucleotide_transform(body)
    identity = state.get_or_404().nucleotide_transforms[0].id
    verified()
    put_nucleotide_transform(body.model_copy(update={"compose": True}))
    verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert state.get_or_404().nucleotide_transforms[0].id == identity
    verified()
    delete_nucleotide_transform(identity)
    verified()


@pytest.mark.parametrize("batch", [False, True])
def test_flexible_mark_complete_inputs(batch):
    from backend.api.routes_flexible_segments import (
        FlexibleSegmentMarkBody,
        FlexibleSegmentBatchBody,
        add_flexible_segment,
        batch_flexible_segment,
        delete_flexible_segment,
    )

    d = state.get_or_404()
    crud.delete_strand(d.strands[1].id)
    strand = state.get_or_404().strands[0]
    body = FlexibleSegmentMarkBody(
        strand_id=strand.id,
        domain_index=0,
        bp_index=5,
        direction=strand.domains[0].direction.value,
    )
    if batch:
        batch_flexible_segment(FlexibleSegmentBatchBody(marks=[body]), Response())
    else:
        add_flexible_segment(body, Response())
    identity = state.get_or_404().flexible_segment_marks[0].id
    verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert state.get_or_404().flexible_segment_marks[0].id == identity
    verified()
    delete_flexible_segment(identity, Response())
    verified()
    batch_flexible_segment(FlexibleSegmentBatchBody(replace=True), Response())
    verified()


@pytest.mark.parametrize(
    "framed,populate", [(False, False), (False, True), (True, False), (True, True)]
)
def test_cell_creation_and_extent(framed, populate):
    d = state.get_or_404()
    frame = d.lattice_frames[0].id if framed else None
    crud.add_helix_at_cell(
        crud.HelixAtCellRequest(
            row=0, col=1, lattice_frame_id=frame, populate_strands=populate
        )
    )
    hid = state.get_or_404().helices[-1].id
    verified()
    crud.extend_helix_bounds(hid, crud.HelixExtendRequest(lo_bp=-4, hi_bp=50))
    verified()
    if not populate:
        crud.scaffold_domain_paint(
            crud.ScaffoldPaintRequest(helix_id=hid, lo_bp=0, hi_bp=30)
        )
        verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert state.get_or_404().helices[-1].id == hid
    verified()


def test_photoproduct_intent_replays_with_explicit_identity_and_method():
    from backend.api.routes_photoproducts import (
        post_photoproduct,
        PhotoproductCreateBody,
        delete_photoproduct,
    )

    strand = state.get_or_404().strands[0]
    dom = strand.domains[0]
    crud.patch_strand(strand.id, crud.StrandPatchRequest(sequence="T" * 42))
    keys = [f"{dom.helix_id}:{bp}:{dom.direction.value}" for bp in (2, 3)]
    post_photoproduct(PhotoproductCreateBody(base_keys=keys))
    identity = state.get_or_404().photoproduct_junctions[0].id
    verified()
    crud.edit_feature(2, crud.EditFeatureBody(params={"base_keys": keys}))
    assert state.get_or_404().photoproduct_junctions[0].id == identity
    verified()
    delete_photoproduct(identity)
    verified()


def test_expensive_cpd_conversion_is_rejected_before_native_placement(monkeypatch):
    from backend.api.part_proof_commands import dependencies
    from backend.core.models import SnapshotLogEntry
    from backend.core import cpd_design

    params = {
        "method": "convert",
        "history_seed": "84eef4b8-b3ce-48f8-b413-aaeaf41f9744",
        "_proof_version": 1,
    }
    assert not dependencies("photoproduct-create", params).known

    def forbidden(*args, **kwargs):
        raise AssertionError("Unbounded conversion ran on the proof path")

    monkeypatch.setattr(cpd_design, "convert_extra_pair", forbidden)
    d = state.get_or_404()
    state.set_design(
        d.copy_with(
            feature_log=[
                *d.feature_log,
                SnapshotLogEntry(
                    op_kind="photoproduct-create", label="Convert CPD", params=params
                ),
            ]
        )
    )
    result = verify_current_part()
    assert result["status"] == "unverified", result

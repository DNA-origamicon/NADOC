"""Lightweight save acknowledgement must not falsely acknowledge intervening edits."""
import pytest
from backend.api import state
from backend.api.doc_context import _current_doc, _request_revision
from backend.core.models import Design


@pytest.fixture(autouse=True)
def isolated_document():
    doc = '__test_save_revision__'
    token = _current_doc.set(doc)
    revision_token = _request_revision.set(None)
    try:
        yield
    finally:
        state.drop_doc(doc)
        _request_revision.reset(revision_token)
        _current_doc.reset(token)


def test_metadata_save_acknowledges_exact_preceding_revision():
    state.set_design(Design())
    before, revision = state.copy_for_persist()
    result = state.acknowledge_workspace_save(before, before, revision, include_snapshot=False)
    assert result == {'design_id':before.id, 'previous_revision':revision, 'revision':revision+1}


def test_metadata_save_ack_reports_intervening_edit_revision():
    state.set_design(Design())
    before, revision = state.copy_for_persist()
    state.set_design(before)
    intervening = state.revision()
    result = state.acknowledge_workspace_save(before, before, revision, include_snapshot=False)
    assert result['previous_revision'] == intervening > revision
    assert result['revision'] == intervening+1


def test_save_to_departed_document_has_no_revision_ack():
    state.set_design(Design())
    before, revision = state.copy_for_persist()
    state.set_design(Design())
    assert state.acknowledge_workspace_save(before, before, revision, include_snapshot=False) is None


def test_frame_snapshot_preserves_intermediate_references_without_aliasing():
    from backend.core.lattice_frame_model import LatticeFrame

    design = Design()
    # Authoring replaces placement clusters in stages; undo must retain the exact
    # previous value without treating the snapshot as a fresh document import.
    design.lattice_frames = [LatticeFrame(id='frame', placement_cluster_id='pending')]
    snapshot = state._snapshot_copy(design)
    assert snapshot.model_dump() == design.model_dump()
    snapshot.lattice_frames[0].placement_cluster_id = 'changed'
    assert design.lattice_frames[0].placement_cluster_id == 'pending'
    with pytest.raises(ValueError, match='placement cluster is missing'):
        Design.model_validate(design.model_dump())

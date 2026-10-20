"""Real sealed-file recovery/edit/append preserves the bounded view-volume field."""
import pytest

from backend.api import state, part_evaluation_jobs as jobs, part_immutable_recovery as recovery
from backend.api import part_immutable_geometry_host as geometry
from backend.api import part_immutable_geometry_publication as authority
from backend.api import part_immutable_revision as revisions
from backend.api.part_immutable_persistence import capture_immutable
from tests.test_part_immutable_recovery import document as document
from tests.test_part_deformation_preview import native_source, patch
from tests.test_part_view_volume_preservation import volumes
from tests.test_group_organization_history import _verified


def start():
    identity = recovery.start_geometry({'expected_revision': 0})['job_id']
    assert jobs._jobs[identity].result['status'] == 'ready', jobs._jobs[identity].result
    jobs.commit(identity)


@pytest.mark.parametrize('family', ['bend', 'twist'])
def test_real_file_recover_edit_append_undo_redo_and_reload(document, monkeypatch, family):
    monkeypatch.setattr(authority, 'ENABLED', True)
    doc, owner = document
    source = native_source(family)
    source.view_volumes = volumes()
    original = revisions.prepare_geometry_revision(source)
    expected = [v.model_dump(mode='json') for v in source.view_volumes]
    owner.cache.write(owner.reserve_empty(doc), original)
    start()
    recovered = state._sessions[doc].design
    assert recovered.payload == original.payload
    geometry.edit(1, patch(family), expected_kind='deformation', expected_feature_id='edited-feature',
                  expected_design_id=source.id, expected_revision=1)
    edited = state._sessions[doc].design
    assert [v.model_dump(mode='json') for v in revisions.materialize_revision(edited).view_volumes] == expected
    geometry.append('bundle-create', {'cells': [[6, 6]], 'length_bp': 7, 'name': 'Tail'},
                    expected_design_id=source.id, expected_revision=2)
    appended = state._sessions[doc].design
    assert [v.model_dump(mode='json') for v in revisions.materialize_revision(appended).view_volumes] == expected
    assert owner.write_capture(capture_immutable(doc)) == 3
    geometry.history('undo', expected_design_id=source.id, expected_revision=3)
    assert state._sessions[doc].design is edited
    geometry.history('redo', expected_design_id=source.id, expected_revision=4)
    assert state._sessions[doc].design is appended
    assert owner.write_capture(capture_immutable(doc)) == 5
    state.drop_doc(doc)
    start()
    restored = state._sessions[doc].design
    assert restored.payload == appended.payload and restored is not appended
    model = revisions.materialize_revision(restored)
    assert [v.model_dump(mode='json') for v in model.view_volumes] == expected
    _verified(model)

"""Semantic provenance stays independent of autosave cadence and UI visibility."""
import pytest
from backend.api import state
from backend.api.crud import MetadataUpdateRequest, update_metadata
from backend.api.routes_design_loadouts import (
    create_loadout, select_loadout, rename_loadout, delete_loadout,
    LoadoutCreateBody, LoadoutRenameBody,
)
from backend.core.design_loadouts import decode_snapshot, encode_snapshot
from backend.core.document_operations import replay, verify_document
from backend.core.models import Design
from backend.core.project_revisions import refresh_active_revision
from experiments.recorded_review_process import ProcessRequired
from scripts.agent_structure_guard import audit, publish
from tests.test_agent_structure_guard import part


def save(tmp_path):
    design = refresh_active_revision(tmp_path, state.get_or_404())
    state.set_design(design)
    return design


def test_autosave_creates_main_once_and_does_not_change_construction(tmp_path):
    original = part().design
    saved = refresh_active_revision(tmp_path, original)
    for _ in range(5):
        saved = refresh_active_revision(tmp_path, saved)
    assert [row.kind for row in saved.document_history] == ['loadout-initialize']
    assert saved.feature_log == original.feature_log
    assert len(saved.loadouts[0].revision_records) <= 2
    assert audit(saved)['loadouts_checked'] == 1


def test_real_rename_create_switch_delete_and_reopen(tmp_path):
    state.load_design(part().design)
    save(tmp_path)
    update_metadata(MetadataUpdateRequest(name='A renamed part'))
    update_metadata(MetadataUpdateRequest(name='A renamed part'))
    create_loadout(LoadoutCreateBody(name='Alternative'))
    branch = state.get_or_404().active_loadout_id
    rename_loadout(branch, LoadoutRenameBody(name='Second'))
    rename_loadout(branch, LoadoutRenameBody(name='Second'))
    select_loadout('main')
    saved = save(tmp_path)
    assert [row.kind for row in saved.document_history] == [
        'loadout-initialize', 'document-metadata', 'loadout-create',
        'loadout-rename', 'loadout-select']
    assert audit(saved)['loadouts_checked'] == 2
    delete_loadout(branch)
    saved = save(tmp_path)
    assert verify_document(saved)['active'] == 'main'
    target = tmp_path / 'result.nadoc'
    publish(saved, target)
    reopened = Design.model_validate_json(target.read_text())
    assert audit(reopened)['document_operations'] == 6
    assert reopened.metadata.name == 'A renamed part'


def test_metadata_only_rename_replays_and_unknown_metadata_is_not_hidden():
    state.load_design(part().design)
    update_metadata(MetadataUpdateRequest(name='Renamed', description='Description', tags=['one']))
    design = state.get_or_404()
    assert audit(design)['status'] == 'verified'
    design.metadata.namd_peg_visible = not design.metadata.namd_peg_visible
    with pytest.raises(ProcessRequired, match='metadata'):
        audit(design)


@pytest.mark.parametrize('mutation', ['name', 'active', 'source', 'head', 'inactive_atoms'])
def test_tampered_document_or_inactive_branch_fails_closed(tmp_path, mutation):
    state.load_design(part().design)
    save(tmp_path)
    create_loadout(LoadoutCreateBody(name='Second'))
    saved = save(tmp_path).model_copy(deep=True)
    if mutation == 'name':
        saved.loadouts[0].name = 'Unrecorded'
    elif mutation == 'active':
        saved.active_loadout_id = 'main'
    elif mutation == 'source':
        saved.document_history[-1].source_recipe['commands'][0]['params']['length_bp'] = 6
    elif mutation == 'head':
        saved.loadouts[0].head_revision_id = 'a' * 64
    else:
        source = decode_snapshot(saved.loadouts[0].design_snapshot_gz_b64)
        source.helices[0].phase_offset += .2
        payload, size = encode_snapshot(source)
        saved.loadouts[0].design_snapshot_gz_b64 = payload
        saved.loadouts[0].snapshot_size_bytes = size
    with pytest.raises(ProcessRequired):
        publish(saved, tmp_path / 'bad.nadoc')
    assert not (tmp_path / 'bad.nadoc').exists()


def test_existing_unrecorded_loadouts_are_not_retroactively_initialized(tmp_path):
    saved = refresh_active_revision(tmp_path, part().design)
    saved.document_history = []
    resaved = refresh_active_revision(tmp_path, saved)
    assert resaved.document_history == []
    with pytest.raises(ProcessRequired, match='loadouts'):
        audit(resaved)


def test_failed_and_noop_operations_do_not_append_history(tmp_path):
    state.load_design(part().design)
    saved = save(tmp_path)
    before = list(saved.document_history)
    with pytest.raises(Exception):
        rename_loadout('missing', LoadoutRenameBody(name='Nothing'))
    assert state.get_or_404().document_history == before
    assert replay(before)['active'] == 'main'


def test_branch_specific_metadata_and_geometry_publication_preserve_intent(tmp_path):
    from backend.core.part_recipe_publication import preserve_document_state
    state.load_design(part().design)
    save(tmp_path)
    create_loadout(LoadoutCreateBody(name='Second'))
    other = state.get_or_404().active_loadout_id
    update_metadata(MetadataUpdateRequest(name='Other part'))
    save(tmp_path)
    select_loadout('main')
    assert state.get_or_404().metadata.name == 'Agent process test'
    saved = save(tmp_path)
    assert audit(saved)['loadouts_checked'] == 2
    select_loadout(other)
    current = state.get_or_404()
    candidate = preserve_document_state(current, part().design)
    assert candidate.document_history == current.document_history
    assert candidate.metadata.name == 'Other part'
    assert audit(refresh_active_revision(tmp_path, candidate))['status'] == 'verified'


def test_concurrent_first_autosave_preserves_semantic_rename(tmp_path):
    state.load_design(part().design)
    source, revision = state.get_design_with_revision()
    saved = refresh_active_revision(tmp_path, source)
    update_metadata(MetadataUpdateRequest(name='Concurrent rename'))
    state.acknowledge_workspace_save(source, saved, revision)
    current = state.get_or_404()
    assert current.metadata.name == 'Concurrent rename'
    assert [event.kind for event in current.document_history] == ['document-metadata', 'loadout-initialize']
    assert audit(save(tmp_path))['status'] == 'verified'


def test_native_authoring_proof_accepts_recorded_metadata():
    from backend.api.part_proof_commands import execute, dependencies
    from backend.core.part_history_contract import assess_part_history
    state.load_design(part().design)
    update_metadata(MetadataUpdateRequest(name='Recorded rename'))
    proof = assess_part_history(state.get_or_404(), execute=execute, dependencies=dependencies)
    assert proof['status'] == 'verified'


def test_unknown_document_operation_and_unrecorded_physical_reference_are_refused(tmp_path):
    from backend.core.document_operation_model import DocumentOperation
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DocumentOperation(kind='save', params={})
    design = refresh_active_revision(tmp_path, part().design)
    design.loadouts[0].protected = True
    with pytest.raises(ProcessRequired, match='Protected simulation'):
        audit(design)


def test_branch_creation_source_cannot_hide_unrecorded_geometry(tmp_path):
    state.load_design(part().design)
    save(tmp_path)
    state.get_or_404().helices[0].phase_offset += .1
    create_loadout(LoadoutCreateBody(name='Unrecorded input'))
    # Even if the final branch is restored to the original geometry, its
    # recorded creation input must reproduce independently.
    state.get_or_404().helices[0].phase_offset -= .1
    saved = save(tmp_path)
    with pytest.raises(ProcessRequired, match='source does not independently reproduce'):
        audit(saved)


def test_discard_current_on_select_restores_saved_metadata_without_erasing_journal(tmp_path):
    state.load_design(part().design)
    save(tmp_path)
    update_metadata(MetadataUpdateRequest(name='Unsaved rename'))
    select_loadout('main', save_current=False)
    current = state.get_or_404()
    assert current.metadata.name == 'Agent process test'
    assert [row.kind for row in current.document_history] == [
        'loadout-initialize', 'document-metadata', 'loadout-select']
    assert audit(save(tmp_path))['status'] == 'verified'
    before = state.get_or_404().document_history
    select_loadout('main')
    assert state.get_or_404().document_history == before


def test_delete_active_after_discard_uses_saved_fallback_metadata(tmp_path):
    state.load_design(part().design)
    save(tmp_path)
    create_loadout(LoadoutCreateBody(name='Second'))
    second = state.get_or_404().active_loadout_id
    select_loadout('main')
    save(tmp_path)
    update_metadata(MetadataUpdateRequest(name='Discard this'))
    select_loadout(second, save_current=False)
    delete_loadout(second)
    assert state.get_or_404().metadata.name == 'Agent process test'
    assert audit(save(tmp_path))['status'] == 'verified'


def test_assembly_part_loadouts_record_the_same_document_operations(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from backend.api import routes_assembly_loadouts as routes
    held = {'design': part().design}
    instance = SimpleNamespace(source=object())
    monkeypatch.setattr(routes.assembly_state, 'get_or_404', lambda: object())
    monkeypatch.setattr(routes, '_find_instance', lambda *_: instance)
    monkeypatch.setattr(routes, '_assembly_source_path', lambda *_: None)
    monkeypatch.setattr(routes, '_load_design_from_source', lambda *_: held['design'])
    monkeypatch.setattr(routes, '_assembly_response', lambda *_: {})
    def replace(assembly, instance, design):
        held['design'] = design
        return assembly, None
    monkeypatch.setattr(routes, '_replace_instance_design', replace)
    routes.create_instance_loadout('instance', routes.InstanceLoadoutCreateRequest(name='Second'))
    second = held['design'].active_loadout_id
    first = held['design'].loadouts[0].id
    routes.rename_instance_loadout('instance', second, routes.InstanceLoadoutRenameRequest(name='Renamed'))
    routes.select_instance_loadout('instance', first)
    routes.delete_instance_loadout('instance', second)
    saved = refresh_active_revision(tmp_path, held['design'])
    assert [event.kind for event in saved.document_history] == [
        'loadout-initialize', 'loadout-create', 'loadout-rename', 'loadout-select', 'loadout-delete']
    assert audit(saved)['loadouts_checked'] == 1


def test_competing_branch_mutation_does_not_publish_a_stale_operation(monkeypatch, tmp_path):
    from backend.api import routes_design_loadouts as routes
    from fastapi import HTTPException
    state.load_design(part().design)
    save(tmp_path)
    original = routes.encode_snapshot
    def competing(design):
        result = original(design)
        update_metadata(MetadataUpdateRequest(name='Concurrent winner'))
        return result
    monkeypatch.setattr(routes, 'encode_snapshot', competing)
    with pytest.raises(HTTPException) as error:
        create_loadout(LoadoutCreateBody(name='Stale candidate'))
    assert error.value.status_code == 409
    assert len(state.get_or_404().loadouts) == 1
    assert state.get_or_404().document_history[-1].kind == 'document-metadata'
    assert state.get_or_404().metadata.name == 'Concurrent winner'


def test_switch_then_autosave_persists_changed_inactive_branch_receipt(tmp_path):
    state.load_design(part().design)
    save(tmp_path)
    create_loadout(LoadoutCreateBody(name='Second'))
    other = state.get_or_404().active_loadout_id
    select_loadout('main')
    before = save(tmp_path)
    old_head = before.loadouts[0].head_revision_id
    update_metadata(MetadataUpdateRequest(name='Edited before switching'))
    select_loadout(other)
    pending = state.get_or_404().model_copy(deep=True)
    assert pending.loadouts[0].snapshot_dirty
    saved = save(tmp_path)
    # A sibling autosave from the same source adopts the identical winning
    # revision, including its now-clean inactive snapshot.
    sibling = refresh_active_revision(tmp_path, pending)
    assert audit(sibling)['loadouts_checked'] == 2
    assert saved.loadouts[0].head_revision_id != old_head
    assert not saved.loadouts[0].snapshot_dirty
    assert audit(saved)['loadouts_checked'] == 2
    select_loadout('main')
    assert state.get_or_404().metadata.name == 'Edited before switching'

"""Navigation establishes a baseline; undo/redo only traverse edits to it."""
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state, assembly_state
from backend.core.models import Design, DesignMetadata, Assembly

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_sessions():
    state.close_session()
    assembly_state.close_session()
    yield
    state.close_session()
    assembly_state.close_session()


def seed_old_design():
    state.close_session()
    state.set_design(Design(id='previous-file'))
    state.set_design(Design(id='previous-file', metadata=DesignMetadata(name='Edited old file')))
    state.undo()  # Seed redo as well as an active previous document.


@pytest.mark.parametrize('operation', ['new', 'import', 'same-id-import', 'load'])
def test_file_navigation_does_not_put_old_design_in_undo(operation, tmp_path):
    seed_old_design()
    incoming = Design(id='previous-file' if operation == 'same-id-import' else 'new-file')
    if operation == 'new':
        response = client.post('/api/design', json={'name': 'New'})
    elif operation == 'load':
        path = tmp_path / 'new.nadoc'
        path.write_text(incoming.to_json())
        response = client.post('/api/design/load', json={'path': str(path)})
    else:
        response = client.post('/api/design/import', json={'content': incoming.to_json()})
    assert response.status_code in (200, 201), response.text
    baseline = state.get_or_404().model_copy(deep=True)
    assert state.undo_depth() == state.redo_depth() == 0
    assert client.post('/api/design/undo').status_code == 404
    assert client.post('/api/design/redo').status_code == 404
    state.mutate_and_validate(lambda d: setattr(d.metadata, 'description', 'First edit'))
    state.undo()
    assert state.get_or_404() == baseline
    assert state.undo_depth() == 0
    state.redo()
    assert state.get_or_404().metadata.description == 'First edit'


def test_failed_import_keeps_current_design_and_history():
    seed_old_design()
    before = state.get_or_404().model_copy(deep=True)
    depths = (state.undo_depth(), state.redo_depth())
    assert client.post('/api/design/import', json={'content': 'broken'}).status_code == 400
    assert state.get_or_404() == before
    assert (state.undo_depth(), state.redo_depth()) == depths


@pytest.mark.parametrize('format_name', ['cadnano', 'scadnano'])
def test_interchange_import_starts_new_history(monkeypatch, format_name):
    import importlib
    module = importlib.import_module(f'backend.core.{format_name}')
    monkeypatch.setattr(module, f'import_{format_name}', lambda *args, **kwargs: (Design(id='imported'), []))
    seed_old_design()
    response = client.post(f'/api/design/import/{format_name}', json={'content': '{}'})
    assert response.status_code == 200, response.text
    assert state.undo_depth() == state.redo_depth() == 0


def test_new_bundle_undo_stops_at_empty_workspace():
    seed_old_design()
    response = client.post('/api/design/bundle', json={'cells': [[0, 0]], 'length_bp': 21})
    assert response.status_code == 201, response.text
    state.undo()
    assert not state.get_or_404().helices
    assert state.get_or_404().id != 'previous-file'
    assert state.undo_depth() == 0


@pytest.mark.parametrize('operation', ['new', 'import', 'load'])
def test_assembly_navigation_does_not_restore_previous_assembly(operation, tmp_path):
    assembly_state.close_session()
    assembly_state.set_assembly(Assembly(id='old-assembly'))
    assembly_state.set_assembly(Assembly(id='old-assembly', metadata=DesignMetadata(name='Old edited')))
    assembly_state.undo()
    incoming = Assembly(id='new-assembly')
    if operation == 'new':
        response = client.post('/api/assembly', json={'name': 'New'})
    elif operation == 'load':
        path = tmp_path / 'new.nass'
        path.write_text(incoming.to_json())
        response = client.post('/api/assembly/load', json={'path': str(path)})
    else:
        response = client.post('/api/assembly/import', json={'content': incoming.to_json()})
    assert response.status_code in (200, 201), response.text
    assert assembly_state.undo_depth() == assembly_state.redo_depth() == 0
    assert client.post('/api/assembly/undo').status_code == 404
    assert client.post('/api/assembly/redo').status_code == 404


def test_branch_selection_starts_a_new_undo_baseline():
    from backend.api.routes_design_loadouts import create_loadout, select_loadout, LoadoutCreateBody
    state.load_design(Design(id='branches'))
    create_loadout(LoadoutCreateBody(name='Second'))
    first = state.get_or_404().loadouts[0].id
    state.mutate_and_validate(lambda d: setattr(d.metadata, 'description', 'Second branch edit'))
    select_loadout(first)
    assert state.undo_depth() == state.redo_depth() == 0
    assert client.post('/api/design/undo').status_code == 404


def test_save_as_cannot_undo_back_to_original_file(monkeypatch, tmp_path):
    from backend.api import assembly
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    state.load_design(Design(id='source', metadata=DesignMetadata(identity_last_known_path='source.nadoc')))
    state.mutate_and_validate(lambda d: setattr(d.metadata, 'description', 'Edit'))
    response = client.post('/api/design/save-workspace', json={'path': 'copy.nadoc', 'overwrite': True})
    assert response.status_code == 200
    assert state.get_or_404().id != 'source'
    assert state.undo_depth() == state.redo_depth() == 0
    assert client.post('/api/design/undo').status_code == 404


def test_undo_keeps_current_workspace_location():
    state.load_design(Design(id='same-project'))
    state.mutate_and_validate(lambda d: setattr(d.metadata, 'description', 'Edit'))
    saved = state.get_or_404().model_copy(deep=True)
    saved.metadata.identity_last_known_path = 'new-folder/design.nadoc'
    saved.metadata.identity_confirmed_at = 'now'
    state.set_design_silent(saved)
    state.undo()
    assert state.get_or_404().metadata.description == ''
    assert state.get_or_404().metadata.identity_last_known_path == 'new-folder/design.nadoc'
    state.redo()
    assert state.get_or_404().metadata.identity_last_known_path == 'new-folder/design.nadoc'


@pytest.mark.parametrize('merge', [False, True])
def test_pdb_replace_is_navigation_but_merge_is_undoable(monkeypatch, merge):
    from backend.api.routes import _demo_design
    from backend.core import pdb_to_design
    state.load_design(_demo_design())
    state.mutate_and_validate(lambda d: setattr(d.metadata, 'description', 'Earlier edit'))
    before = state.get_or_404().model_copy(deep=True)
    merged = before.model_copy(deep=True)
    merged.metadata.description = 'Merged'
    monkeypatch.setattr(pdb_to_design, 'merge_pdb_into_design', lambda *args: (merged, None, []))
    monkeypatch.setattr(pdb_to_design, 'import_pdb', lambda *args: (Design(id='pdb-file'), None, []))
    response = client.post('/api/design/import/pdb', json={'content': 'fixture', 'merge': merge})
    assert response.status_code == 200, response.text
    if merge:
        assert state.undo_depth() == 2
        state.undo()
        assert state.get_or_404().metadata.description == 'Earlier edit'
        state.undo()
        assert state.get_or_404().metadata.description == ''
    else:
        assert state.undo_depth() == 0


def test_restore_session_drops_existing_undo_and_redo():
    from backend.api.doc_context import DEFAULT_DOC_ID
    seed_old_design()
    state.restore_doc_design(DEFAULT_DOC_ID, Design(id='recovered'))
    assert state.undo_depth() == state.redo_depth() == 0


def test_flatten_load_does_not_restore_previously_loaded_design():
    seed_old_design()
    assembly_state.load_assembly(Assembly(id='flatten-source'))
    response = client.post('/api/assembly/flatten/load-as-design')
    assert response.status_code == 200, response.text
    assert state.undo_depth() == state.redo_depth() == 0

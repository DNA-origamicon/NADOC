"""Shared typed graph distinguishes direct selections, global effects and unknowns."""
import pytest
from fastapi import HTTPException

from backend.api import assembly_state
from backend.api.assembly_history_dependencies import current_dependencies
from backend.core.assembly_dependencies import dependencies, GLOBAL_COMMANDS, LOCAL_COMMANDS
from backend.core.part_dependencies import DependencyIndex
from tests.test_assembly_command_replay import add_empty_part, gears


@pytest.fixture(autouse=True)
def session():
    assembly_state.close_session()
    yield
    assembly_state.close_session()


def test_registered_commands_all_have_reviewed_dependency_contracts():
    from backend.api.assembly_command_replay import COMMANDS
    assert set(COMMANDS) == GLOBAL_COMMANDS | LOCAL_COMMANDS


def test_instance_properties_and_duplicate_read_only_their_selected_instances(monkeypatch):
    from backend.core.models import Assembly
    from backend.api.assembly import patch_instance, PatchInstanceRequest, duplicate_instance, DuplicateInstanceRequest
    assembly_state.load_assembly(Assembly())
    a, _b = add_empty_part('A'), add_empty_part('B')
    patch_instance(a, PatchInstanceRequest(name='Renamed'))
    duplicate_instance(a, DuplicateInstanceRequest())
    source = assembly_state.get_or_404().model_copy(deep=True)
    monkeypatch.setattr(assembly_state, 'decode_assembly_snapshot', lambda *args: pytest.fail('Snapshot decoded'))
    graph = current_dependencies()
    rows = graph['features']
    assert graph['complete']
    assert rows[2]['parents'] == [rows[0]['id']]
    assert rows[3]['parents'] == [rows[2]['id']]
    assert not rows[1]['children']
    assert not any(row['conservative'] for row in rows)
    assert graph['revision'] == assembly_state.revision()
    assert graph['assembly_id'] == source.id
    assert assembly_state.get_or_404() == source


def test_state_dependent_commands_order_the_assembly_and_unknowns_remain_unknown():
    gears()
    graph = current_dependencies()
    rows = graph['features']
    assert rows[-1]['conservative']
    assert rows[-1]['known']
    assert rows[-1]['parents'] == [rows[-2]['id']]
    index = DependencyIndex()
    index.append('first', dependencies('assembly-add-instance', {'command_version': 1, 'inputs': {}, 'instance_id': 'a'}))
    index.append('unknown', dependencies('future-command', {}))
    index.append('last', dependencies('assembly-add-instance', {'command_version': 1, 'inputs': {}, 'instance_id': 'b'}))
    assert not index.complete
    assert index.affected(['first']) == {'first', 'unknown', 'last'}


def test_suppressed_definition_is_inactive_and_duplicate_history_ids_refuse_inspection():
    gears()
    source = assembly_state.get_or_404()
    source.feature_log[-1].suppressed = True
    result = current_dependencies()
    assert result['features'][-1]['suppressed']
    # Shared index conservatively retains prior global ordering even for a no-op.
    assert not result['features'][-1]['conservative']
    source.feature_log[-1].id = source.feature_log[0].id
    with pytest.raises(HTTPException) as error:
        current_dependencies()
    assert error.value.status_code == 409


def test_endpoint_is_read_only_and_document_scoped():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    gears()
    client = TestClient(app)
    revision = assembly_state.revision()
    response = client.get('/api/assembly/features/dependencies')
    assert response.status_code == 200
    assert response.json()['revision'] == revision
    assert assembly_state.revision() == revision
    assert client.get('/api/assembly/features/dependencies', headers={'X-NADOC-Doc': 'no-assembly'}).status_code == 404

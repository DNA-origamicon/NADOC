"""The ordinary upload must preserve original bytes and replayable provenance."""
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.core.part_history_contract import create_empty_part
from backend.core.part_cadnano_source import MAX_SOURCE_BYTES
from backend.core.part_input_sources import EmbeddedResolver, InputSource
from scripts.agent_structure_guard import audit, publish
from backend.core.models import Design
from tests.test_part_cadnano_commands import source


@pytest.fixture
def client():
    token = set_current_doc('__e2e__ordinary-cadnano-recording')
    app = FastAPI()
    app.include_router(crud.router, prefix='/api')
    state.load_design(create_empty_part('Import target', 'HONEYCOMB'))
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize('name', ['2x4sq.json', '6hb_cadnano_native_test1.json'])
def test_guide_source_pins_bytes_and_survives_publication_and_reopen(client, tmp_path, name):
    content = (Path('Examples/cadnano') / name).read_text()
    response = client.post('/api/design/import/cadnano', json={'content': content})
    assert response.status_code == 200, response.text
    design = state.get_or_404()
    row, = design.feature_log
    assert row.op_kind == 'cadnano-import'
    assert row.params['importer_version'] == 3
    assert EmbeddedResolver(design.input_sources)(InputSource.model_validate(row.params['source'])) == content.encode()
    assert response.json()['import_history']['status'] == 'reproduced_import'
    assert response.json()['revision'] == state.revision()
    assert state.undo_depth() == 0
    target = tmp_path / '__e2e__cadnano.nadoc'
    try:
        publish(design, target)
        audit(Design.model_validate_json(target.read_text()))
    finally:
        target.unlink(missing_ok=True)


def test_unqualified_upload_reports_unverified_without_claiming_a_recipe(client):
    response = client.post('/api/design/import/cadnano', json={'content': json.dumps(source()) + ' ' * MAX_SOURCE_BYTES})
    assert response.status_code == 200, response.text
    assert response.json()['import_history']['status'] == 'unverified'
    assert state.get_or_404().recipe_root is None


def test_unqualified_native_roundtrip_preserves_original_frame_without_claiming_a_recipe(client):
    from backend.core.cadnano import export_cadnano
    from backend.core.lattice import make_bundle_design

    native = make_bundle_design([(4, 6), (4, 7)], 42)
    data = export_cadnano(native)
    assert "nadoc_roundtrip" in data
    content = json.dumps(data) + " " * MAX_SOURCE_BYTES
    response = client.post('/api/design/import/cadnano', json={'content': content})
    assert response.status_code == 200, response.text
    assert response.json()['import_history']['status'] == 'unverified'
    imported = state.get_or_404()
    assert imported.recipe_root is None
    assert imported.feature_log == []

    def axes(design):
        return sorted((h.axis_start.x, h.axis_start.y, h.axis_start.z,
                       h.axis_end.x, h.axis_end.y, h.axis_end.z) for h in design.helices)

    assert axes(imported) == axes(native)


def test_native_preparation_failure_does_not_publish_or_retry_legacy(client, monkeypatch):
    from backend.api import routes_part_cadnano_import
    before = state.get_or_404().model_dump_json()
    revision = state.revision()
    def fail(*args, **kwargs):
        raise ValueError('recorded preparation refused')
    monkeypatch.setattr(routes_part_cadnano_import, '_prepare', fail)
    response = client.post('/api/design/import/cadnano', json={'content': json.dumps(source())})
    assert response.status_code == 400
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision

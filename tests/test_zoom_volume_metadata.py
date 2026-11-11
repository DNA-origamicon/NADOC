"""Inset magnification is display metadata, retained by document serialization."""
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.core.models import Design, Assembly


@pytest.mark.parametrize('host,model', [('design', Design), ('assembly', Assembly)])
def test_zoom_volume_roundtrip(host, model):
    client = TestClient(app)
    created = client.post(f'/api/{host}', json={'name': '__e2e__zoom-metadata'}).json()[host]
    entry = {'id': 'zoom-a', 'name': 'Detail', 'zoom_step': 3,
             'targets': [{'refs': [{'kind': 'strand', 'id': 's'}]}],
             'settings': {'enabled': True, 'representation': 'beads', 'position': 'br'}}
    body = {'document_id': created['id'], 'volumes': [entry]}
    response = client.put(f'/api/{host}/zoom-volumes', json=body)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {'zoom_volumes', 'revision'}
    loaded = client.get(f'/api/{host}').json()[host]
    reopened = model.model_validate_json(model.model_validate(loaded).model_dump_json())
    assert reopened.zoom_volumes[0].zoom_step == 3
    assert reopened.zoom_volumes[0].settings == entry['settings']
    assert reopened.zoom_volumes[0].targets == entry['targets']
    assert loaded.get('feature_log') == created.get('feature_log')
    assert client.put(f'/api/{host}/zoom-volumes', json={**body, 'document_id': 'wrong'}).status_code == 409
    assert client.put(f'/api/{host}/zoom-volumes', json={**body, 'volumes': [{**entry, 'zoom_step': 9}]}).status_code == 422
    assert client.put(f'/api/{host}/zoom-volumes', json={**body, 'volumes': [entry, entry]}).status_code == 422


def test_zoom_metadata_does_not_change_simulation_identity_or_bypass_strict_preservation():
    from backend.core.zoom_volume_model import ZoomVolume
    from backend.core.namd_input_provenance import design_digest
    from backend.api.part_immutable_preservation import preservation_digest
    from backend.core.part_command_errors import CommandContractError
    document = Design()
    before = design_digest(document)
    assert preservation_digest(document)
    document.zoom_volumes = [ZoomVolume(id='detail', zoom_step=2)]
    assert design_digest(document) == before
    with pytest.raises(CommandContractError, match='empty zoom_volumes'):
        preservation_digest(document)

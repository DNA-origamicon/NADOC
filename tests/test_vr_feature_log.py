import pytest
from pydantic import ValidationError
from backend.api.vr_feature_log import Snapshot, encode, parse_event


def test_history_rows_encode_initial_and_per_entry_capabilities():
    snapshot = Snapshot(version=1, acknowledged=0, title='Feature history', rows=[dict(id='r:0', label='F0'), dict(id='r:1', label='F1 "Bend"', edit=True, revert=True, delete=True)], targets=[])
    data = encode(snapshot)
    assert data.startswith('NADOC_FEATURE_LOG_1 1 0 0 2 0 ')
    assert data.endswith('1 0 1 1 1 0\n')
    with pytest.raises(ValidationError):
        Snapshot(**{**snapshot.model_dump(), 'version': 0})


@pytest.mark.parametrize('id', ['r:0', 'r:42', 't:2', 'a:3:delete', 'a:4:edit', 'a:7:revert', 'a:8:expand'])
def test_history_event_allowlist(id):
    event = dict(sequence=1, version=2, id=id)
    assert parse_event(event) == event
    assert parse_event({**event, 'sequence': True}) is None
    assert parse_event({**event, 'version': 0}) is None
    assert parse_event({**event, 'id': 'a:4:execute'}) is None


def test_history_snapshot_is_document_bound_and_roundtrips_event(tmp_path, monkeypatch):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_vr as vr, doc_context
    from backend.api.vr_feature_log import router
    event_path = tmp_path / 'events'
    monkeypatch.setattr(vr, '_require_local', lambda request: None)
    monkeypatch.setattr(vr, '_read_state', lambda: dict(doc_id='owner', event_path=str(event_path)))
    monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'owner')
    app = FastAPI()
    app.include_router(router)
    body = dict(version=1, acknowledged=0, title='Features', rows=[], targets=[])
    with TestClient(app) as client:
        assert client.post('/vr/feature-log', json=body).status_code == 200
        saved = (tmp_path / 'events.feature-log').read_bytes()
        assert not (tmp_path / 'events.feature-log.next').exists()
        monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'other')
        assert client.post('/vr/feature-log', json={**body, 'version': 2}).status_code == 409
        assert (tmp_path / 'events.feature-log').read_bytes() == saved
    event = dict(sequence=1, version=1, id='r:0')
    event_path.write_text(json.dumps(dict(sequence=4, level_sequence=1, selection_level='base', feature_log=event)))
    assert vr._event_payload(dict(event_path=str(event_path)))['feature_log'] == event

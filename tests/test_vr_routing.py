import pytest
from pydantic import ValidationError
from backend.api.vr_routing import Snapshot, encode, parse_event


def test_snapshot_keeps_job_specific_availability_and_quotes_labels():
    snapshot = Snapshot(version=1, acknowledged=0, title='Autoscaffold', roots=[], controls=[dict(id='v:1', label='RMSF "map"', enabled=False, active=False)])
    text = encode(snapshot)
    assert text.startswith('NADOC_ROUTING_1 1 0 0 1 "Autoscaffold"\n')
    assert 'RMSF \\"map\\"' in text
    assert text.endswith('0 0\n')
    with pytest.raises(ValidationError):
        Snapshot(**{**snapshot.model_dump(), 'version': 0})


def test_event_rejects_wrong_types_and_unbounded_native_requests():
    good = dict(sequence=1, version=2, id='v:1:2')
    assert parse_event(good) == good
    for patch in [dict(sequence=True), dict(version=0), dict(id='bad/path'), dict(id='v:"'), dict(sequence=2**40)]:
        assert parse_event({**good, **patch}) is None


def test_snapshot_is_local_document_bound_and_event_survives_envelope(tmp_path, monkeypatch):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_vr as vr, doc_context
    from backend.api.vr_routing import router
    event_path = tmp_path / 'events'
    monkeypatch.setattr(vr, '_require_local', lambda request: None)
    monkeypatch.setattr(vr, '_read_state', lambda: dict(doc_id='owner', event_path=str(event_path)))
    monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'owner')
    app = FastAPI(); app.include_router(router)
    body = dict(version=1, acknowledged=0, title='', roots=[], controls=[])
    with TestClient(app) as client:
        assert client.post('/vr/routing', json=body).status_code == 200
        saved = (tmp_path / 'events.routing').read_bytes()
        assert not (tmp_path / 'events.routing.next').exists()
        monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'other')
        assert client.post('/vr/routing', json={**body, 'version': 2}).status_code == 409
        assert (tmp_path / 'events.routing').read_bytes() == saved
    event = dict(sequence=1, version=1, id='e:cando')
    event_path.write_text(json.dumps(dict(sequence=4, level_sequence=1, selection_level='base', routing=event)))
    assert vr._event_payload(dict(event_path=str(event_path)))['routing'] == event

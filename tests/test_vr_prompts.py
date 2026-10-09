import json
import pytest
from pydantic import ValidationError
from backend.api.vr_prompts import Snapshot, encode, parse_event, router


def body(**changes):
    return dict(version=4, heartbeat=8, title='Delete strand?', message='Remove "S1"?\nThis can be undone.',
                options=[dict(id='0', label='Cancel'), dict(id='1', label='Delete')], **changes)


def test_wire_keeps_message_and_enforces_small_decisions():
    text = encode(Snapshot(**body(detail_allowed=False)))
    assert text.startswith('NADOC_PROMPT_1 4 8 2 0 ')
    assert 'Remove \\"S1\\"? This can be undone.' in text
    for options in [[dict(id=str(i), label='Option') for i in range(5)], [dict(id='0', label='A')]*2]:
        with pytest.raises(ValidationError):
            Snapshot(**{**body(), 'options': options})
    assert parse_event(dict(sequence=1, version=4, id='1')) == dict(sequence=1, version=4, id='1')
    assert parse_event(dict(sequence=True, version=4, id='1')) is None


def test_local_document_bound_publication_and_event_delivery(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_vr as vr, doc_context
    path = tmp_path / 'events'
    local = []
    monkeypatch.setattr(vr, '_require_local', lambda request: local.append(True))
    monkeypatch.setattr(vr, '_read_state', lambda: dict(doc_id='owner', event_path=str(path)))
    monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'owner')
    app = FastAPI();app.include_router(router)
    with TestClient(app) as client:
        assert client.post('/vr/prompt', json=body()).status_code == 200
        saved = path.with_suffix('.prompt').read_bytes()
        assert path.with_suffix('.prompt').stat().st_mode & 0o777 == 0o600
        monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'other')
        assert client.post('/vr/prompt', json=body()).status_code == 409
        assert path.with_suffix('.prompt').read_bytes() == saved
    assert len(local) == 2
    reply = dict(sequence=1, version=4, id='1')
    path.write_text(json.dumps(dict(sequence=4, level_sequence=1, selection_level='base', prompt=reply)))
    assert vr._event_payload(dict(event_path=str(path)))['prompt'] == reply

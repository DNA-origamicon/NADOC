import copy
import pytest
from backend.api.vr_references import validate_references


def model():
    return {'revision': 1, 'models': [{'id': 'test-reference',
        'vertices': [0, 0, 0, 60, 0, 0, 0, 30, 0],
        'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        'color': [.5, .6, .7], 'opacity': .5}]}


def test_ephemeral_reference_contract():
    data = model()
    assert validate_references(data) == data
    assert validate_references({'revision': 0, 'models': []})['models'] == []


@pytest.mark.parametrize('field,value', [('vertices', [0, 0, float('nan')]*3),
    ('vertices', [0]*8), ('opacity', -1), ('color', [2, 0, 0]), ('id', '../escape')])
def test_rejects_invalid_references(field, value):
    data = model(); data['models'][0][field] = value
    with pytest.raises(ValueError):
        validate_references(data)


def test_rejects_singular_or_nonuniform_transforms_and_duplicate_ids():
    for scale in (0, 2):
        data = model(); data['models'][0]['matrix'][0] = scale
        with pytest.raises(ValueError):
            validate_references(data)
    data = model(); data['models'].append(copy.deepcopy(data['models'][0]))
    with pytest.raises(ValueError):
        validate_references(data)


def test_bridge_is_document_bound_atomic_and_does_not_mutate_design(tmp_path, monkeypatch):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_vr as vr, doc_context
    from backend.api.vr_references import router
    path = tmp_path / 'events'
    monkeypatch.setattr(vr, '_read_state', lambda: {'doc_id': 'test', 'event_path': str(path)})
    monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'test')
    app = FastAPI(); app.include_router(router)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        data = model(); data['selected'] = 'test-reference'
        assert client.post('/vr/references', json=data).status_code == 200
        text = (tmp_path / 'events.references').read_text()
        assert text.startswith('NADOC_REFERENCES 1 1 1\n1 0 0 0 1 0 0 0 1\ntest-reference\n')
        assert not (tmp_path / 'events.references.next').exists()
        event = {'sequence': 1, 'revision': 1, 'id': 'test-reference', 'action': 'color'}
        (tmp_path / 'events.references-event').write_text(json.dumps(event))
        assert client.get('/vr/references').json()['event'] == event
        assert client.get('/vr/references', headers={'Origin': 'https://untrusted.example'}).status_code == 403
        monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'other')
        assert client.get('/vr/references').json() == {'session': None}
        assert client.post('/vr/references', json=data).status_code == 409
        assert (tmp_path / 'events.references').read_text() == text

"""Screening must not mistake image/keyword evidence for an authored design."""
import base64
import pymupdf
import pytest
from backend.core.article_reconstruction import screen_article, decode_pdf, lookup_doi


def pdf(text):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 40), text)
        return {'data': base64.b64encode(doc.tobytes()).decode()}


def results(payload):
    return {item['id']: item for item in screen_article(payload) if item.get('status') in ('passed', 'failed', 'deferred')}


def test_missing_paper_and_supplement_never_pass():
    checked = results({})
    assert len(checked) == 5
    assert [item['status'] for item in checked.values()] == ['failed'] * 3 + ['deferred'] * 2


def test_keywords_and_sequences_do_not_establish_reconstruction():
    checked = results({'paper': pdf('DNA origami'), 'supplements': [pdf('Fig. S1. caDNAno diagram')]})
    assert checked['paper']['status'] == 'passed'
    assert checked['origami']['status'] == 'passed'
    assert checked['supplement']['status'] == 'passed'
    assert checked['detail']['status'] == 'deferred'
    assert checked['reconstruction']['status'] == 'deferred'


def test_results_are_progressive_and_terminal():
    events = list(screen_article({'paper': pdf('Protein crystallography')}))
    assert [event['status'] for event in events[:6]][::2] == ['running'] * 3
    assert events[-1] == {'type': 'complete', 'can_reconstruct': False, 'ready_for_analysis': False, 'confidence': None}
    assert results({'paper': pdf('Protein crystallography')})['origami']['status'] == 'failed'


def test_bad_uploads_and_doi_are_rejected():
    with pytest.raises(ValueError):
        decode_pdf({'data': 'invalid'})
    with pytest.raises(ValueError):
        lookup_doi('http://localhost/private')


def test_doi_lookup_is_encoded_and_reports_findable_metadata(monkeypatch):
    import backend.core.article_reconstruction as module
    monkeypatch.setattr(module, 'lookup_doi', lambda doi: {'text': 'DNA origami study', 'notes': []})
    checked = results({'doi': '10.1234/example'})
    assert checked['paper']['status'] == 'passed'
    assert 'Paper found by DOI' in checked['paper']['detail']
    assert checked['origami']['status'] == 'passed'
    assert checked['reconstruction']['status'] == 'deferred'


def test_api_stream_and_invalid_envelopes():
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes_image_evaluation import router
    app = FastAPI()
    app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        for payload in ([], {'supplements': {}}, {'doi': 42}, {'paper': {'data': 42}}):
            assert client.post('/api/article-reconstruction/check', json=payload).status_code == 422
        response = client.post('/api/article-reconstruction/check', json={'paper': pdf('DNA origami')})
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[1]['status'] == 'passed'
        assert events[-1]['can_reconstruct'] is False


def test_caption_alone_allows_image_analysis_without_files_or_sequences():
    events = list(screen_article({'paper': pdf('DNA origami'), 'supplements': [pdf('Fig. S3. caDNAno diagram')]}))
    assert events[-1]['ready_for_analysis'] is True
    assert events[-1]['confidence'] is None
    assert events[-1]['can_reconstruct'] is False
    assert 'Staple list not confirmed' in events[5]['detail']


def test_design_software_mention_alone_is_not_a_supplement_caption():
    from backend.core.article_reconstruction import diagram_evidence
    assert diagram_evidence('We used caDNAno software to design this structure.') is None
    assert diagram_evidence('Supplementary Fig. S2 shows the caDNAno schematic.')
    assert diagram_evidence('Fig. 2. caDNAno diagram', supplement=True)


def test_doi_discovers_open_access_captions_and_survives_crossref_failure(monkeypatch):
    import httpx
    import backend.core.article_reconstruction as module
    requested = []
    def respond(request):
        requested.append(str(request.url))
        if request.url.host == 'api.crossref.org':
            return httpx.Response(503)
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'resultList': {'result': [{
                'doi': '10.1234/test', 'title': 'DNA origami', 'pmcid': 'PMC123', 'isOpenAccess': 'Y'}]}})
        return httpx.Response(200, text='<article><supplementary-material><caption>Figure S1. caDNAno diagram</caption></supplementary-material></article>')
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(module.httpx, 'Client', lambda **kwargs: client)
    events = list(screen_article({'doi': 'https://doi.org/10.1234/test'}))
    assert events[-1]['ready_for_analysis'] is True
    assert len(requested) == 3
    assert 'Crossref lookup unavailable' in events[1]['detail']
    assert 'Figure S1' in events[5]['detail']


def test_large_pdfs_and_combined_uploads_have_no_byte_cap():
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes_image_evaluation import router
    # Large inert comment preserves a real readable one-page PDF without images.
    raw = base64.b64decode(pdf('DNA origami. Supplement Fig. S1 caDNAno diagram')['data'])
    raw = raw.replace(b'\n', b'\n%' + b'x' * (27 * 1024 * 1024) + b'\n', 1)
    item = {'data': base64.b64encode(raw).decode()}
    assert len(decode_pdf(item)) > 25 * 1024 * 1024
    app = FastAPI()
    app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        response = client.post('/api/article-reconstruction/check', json={'paper': item, 'supplements': [item, item]})
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[-1]['ready_for_analysis'] is True
        response = client.post('/api/image-evaluation', content=raw)
        assert response.status_code == 200

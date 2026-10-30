"""Geometry evidence tests use synthetic vector PDFs with known routing symbols."""
import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api.routes_image_evaluation import router
from backend.core.image_evaluation import clusters, evaluate_pdf


def drawing_pdf():
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=230)
    # Six rows and four junction planes; final interval is visibly stretched.
    for row in range(6):
        y = 40 + row * 20
        for a, b in [(25, 95), (97, 200)]:
            page.draw_line((a, y), (b, y), color=(.5, .5, .5))
    for x in [60, 80, 100, 145]:
        for row in [0, 2, 4]:
            y = 40 + row * 20
            shape = page.new_shape()
            shape.draw_line((x-10, y), (x, y))
            shape.draw_bezier((x, y), (x-1, y+6), (x-1, y+14), (x, y+20))
            shape.draw_line((x, y+20), (x-10, y+20))
            shape.finish(color=(.5, .5, .5), closePath=False); shape.commit()
    page.insert_text((25, 200), 'Fig. S1. Synthetic routing test')
    data = doc.tobytes(); doc.close(); return data


def test_vector_evidence_distinguishes_observations_from_indices():
    report = evaluate_pdf(drawing_pdf())
    assert len(report['figures']) == 1
    f = report['figures'][0]
    assert len(f['rows']) == 6 and len(f['columns']) == 4
    assert len(f['crossovers']) == 12
    assert all(c['side'] == 'left' for c in f['crossovers'])
    assert any(flag['kind'] == 'spacing' and '2.25' in flag['detail'] for flag in f['flags'])
    assert sum(flag['kind'] == 'single-branch' for flag in f['flags']) == 12
    assert all(0 <= x <= 1000 for x in f['columns'] + f['rows'])
    assert f['image'].startswith('data:image/png;base64,')
    assert 'not verified' in ' '.join(f['limitations'])
    assert 'bp_index' not in f  # No silently asserted nucleotide register.


def test_clusters_does_not_chain_distinct_columns():
    assert clusters([10, 11, 20, 21], 2) == [10.5, 20.5]


def test_plain_pdf_and_invalid_upload():
    doc = pymupdf.open(); page = doc.new_page(); page.insert_text((50, 50), 'No routing here')
    assert evaluate_pdf(doc.tobytes())['figures'] == []
    doc.close()
    app = FastAPI(); app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        response = client.post('/api/image-evaluation', content=b'not pdf', headers={'content-type': 'application/pdf'})
        assert response.status_code == 422
        assert 'valid PDF' in response.json()['detail']
        assert client.post('/api/image-evaluation', content=drawing_pdf()).status_code == 200


def test_encrypted_pdf_rejected():
    doc = pymupdf.open(); doc.new_page()
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='reader'); doc.close()
    with pytest.raises(ValueError, match='Password-protected'):
        evaluate_pdf(data)


def test_image_panel_frames_are_not_routing_diagrams():
    doc = pymupdf.open(); page = doc.new_page()
    for row in range(4):
        for col in range(3):
            x, y = 30 + col * 100, 30 + row * 100
            shape = page.new_shape()
            shape.draw_polyline([(x, y), (x+80, y), (x+80, y+80), (x, y+80), (x, y)])
            shape.finish(color=(0, 0, 0), closePath=False); shape.commit()
    assert evaluate_pdf(doc.tobytes())['figures'] == []
    doc.close()

"""Progress is measured, ephemeral and isolated between document checks."""
import asyncio

import pytest
from fastapi import HTTPException

from backend.api import clash_progress as progress
from backend.api.doc_context import _current_doc


@pytest.fixture(autouse=True)
def clean_records():
    progress._records.clear()
    yield
    progress._records.clear()


def snapshot(key='test-check'):
    return asyncio.run(progress.snapshot(key))


def test_measured_progress_completion_and_release():
    with progress.tracking('test-check') as update:
        assert snapshot()['percent'] == 0
        update('Checking bonds', 128, 512)
        assert snapshot() == dict(state='running', stage='Checking bonds',
                                  completed=128, total=512, percent=25)
        update('Checking bonds', 512, 512)
        assert snapshot()['percent'] == 99  # Packaging has not returned yet.
    assert snapshot()['state'] == 'complete' and snapshot()['percent'] == 100
    asyncio.run(progress.release('test-check'))
    with pytest.raises(HTTPException) as exc:
        snapshot()
    assert exc.value.status_code == 404


def test_other_document_cannot_observe_or_cancel_and_cancel_stops_next_batch():
    with pytest.raises(HTTPException, match='cancelled'):
        with progress.tracking('test-check') as update:
            token = _current_doc.set('another-document')
            try:
                with pytest.raises(HTTPException) as exc:
                    snapshot()
                assert exc.value.status_code == 404
                asyncio.run(progress.release('test-check'))
            finally:
                _current_doc.reset(token)
            update('Checking bonds', 1, 5)
            asyncio.run(progress.release('test-check'))
            update('Checking bonds', 2, 5)
    assert not progress._records


def test_failure_and_duplicate_id_do_not_claim_complete():
    with pytest.raises(ValueError):
        with progress.tracking('test-check'):
            with pytest.raises(HTTPException) as exc:
                with progress.tracking('test-check'):
                    pass
            assert exc.value.status_code == 409
            raise ValueError('bad model')
    assert snapshot()['state'] == 'failed'
    assert snapshot()['percent'] == 0


def test_endpoint_reports_scanned_bonds_without_mutation(monkeypatch):
    from backend.api import routes_display_geometry as routes
    from backend.core import clash
    from backend.core.models import Design
    from tests.test_piercing_display import specimen
    design = Design()
    before = design.model_dump()
    monkeypatch.setattr(routes.design_state, 'get_or_404', lambda: design)
    monkeypatch.setattr(clash, 'clash_report', lambda *a, **kw: clash.ClashReport())
    monkeypatch.setattr(routes, '_display_atomistic_model', lambda d: specimen())
    result = routes.get_clashes(include_piercings=True, progress_id='test-check')
    assert result['piercing']['count'] == 1
    assert snapshot()['completed'] == snapshot()['total'] == 1
    assert snapshot()['percent'] == 100
    assert design.model_dump() == before

"""Screening a Connect draft must not publish an intermediate sequence edit."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_part_connection_compose import document as document
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import native_prefix as native_prefix


def test_screened_sequence_preview_preserves_source_revision_and_undo(document):
    from backend.api.routes_overhang_sequences import router
    source = document.session.design
    before = (source.model_dump_json(), document.session.revision,
              list(document.session.history), list(document.session.redo))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(f'/design/overhang/{source.overhangs[0].id}/generate-random?preview=true')
    assert response.status_code == 200, response.text
    sequence = response.json()['sequence']
    assert len(sequence) == 12 and set(sequence) <= set('ACGT')
    assert document.session.design is source
    assert (source.model_dump_json(), document.session.revision,
            list(document.session.history), list(document.session.redo)) == before

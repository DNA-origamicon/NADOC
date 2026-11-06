"""Folding objectives persist through the real recorded cluster command."""
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api import doc_context, state
from backend.api.main import app
from backend.core.models import Design
from experiments.recorded_review_process import Process
from scripts.agent_structure_guard import audit, publish


@contextmanager
def document(doc):
    token = doc_context.set_current_doc(doc)
    try:
        yield
    finally:
        doc_context.reset_current_doc(token)


@pytest.fixture
def editor():
    doc = f'folding-test-{uuid4()}'
    with document(doc):
        process = Process('Folding order test')
        process.append('bundle-create', {'_proof_version': 1,
            'history_seed': str(uuid4()), 'cells': [[0, 0]], 'length_bp': 21,
            'name': 'Folding order test', 'lattice_type': 'HONEYCOMB',
            'ligate_adjacent': False}, 'Create bundle')
        state.set_design(process.design)
        cluster = process.design.cluster_transforms[0].id
    with TestClient(app, headers={'X-NADOC-Doc': doc}) as client:
        yield client, doc, cluster
    with state._lock:
        state._sessions.pop(doc, None)


def test_assignment_clear_undo_and_saved_independent_replay(editor, tmp_path):
    client, doc, cluster = editor
    url = f'/api/design/cluster/{cluster}'
    response = client.patch(url, json={'folding_order': 2, 'commit': False, 'log': False})
    assert response.status_code == 200, response.text
    assigned = Design.model_validate(response.json()['design'])
    assert assigned.cluster_transforms[0].folding_order == 2
    assert assigned.feature_log[-1].authored_fields['folding_order'] == 2
    with TemporaryDirectory(dir=tmp_path) as scratch:
        destination = Path(scratch) / 'folding.nadoc'
        publish(assigned, destination)
        reopened = Design.model_validate_json(destination.read_text())
        assert reopened.cluster_transforms[0].folding_order == 2
        assert audit(reopened)['status'] == 'verified'
    # Omission retains the assignment, explicit null removes it.
    response = client.patch(url, json={'name': 'Renamed'})
    assert response.json()['design']['cluster_transforms'][0]['folding_order'] == 2
    response = client.patch(url, json={'folding_order': None})
    cleared = Design.model_validate(response.json()['design'])
    assert cleared.cluster_transforms[0].folding_order is None
    assert cleared.feature_log[-1].authored_fields['folding_order'] is None
    assert audit(cleared)['status'] == 'verified'
    response = client.post('/api/design/undo')
    assert response.status_code == 200, response.text
    with document(doc):
        assert state.get_or_404().cluster_transforms[0].folding_order == 2
    response = client.post('/api/design/redo')
    assert response.status_code == 200, response.text
    with document(doc):
        assert state.get_or_404().cluster_transforms[0].folding_order is None


@pytest.mark.parametrize('stage', [0, -1, 1.5, True, '2', 1000])
def test_invalid_stage_is_rejected_without_history_change(editor, stage):
    client, doc, cluster = editor
    with document(doc):
        before = state.get_or_404().model_dump_json()
    response = client.patch(f'/api/design/cluster/{cluster}', json={'folding_order': stage})
    assert response.status_code == 422
    with document(doc):
        assert state.get_or_404().model_dump_json() == before


def test_history_editor_accepts_stage_edits_and_rejects_invalid_values():
    from backend.api.part_transform_inputs import normalize
    from backend.core.part_command_errors import CommandContractError

    previous = {'_proof_version': 1, 'cluster_id': 'cluster',
        'translation': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'pivot': [0, 0, 0],
        'folding_order': 2}
    for stage in (1, 999, None):
        assert normalize('cluster_op', previous, {'folding_order': stage})['folding_order'] == stage
    for stage in (0, 1.5, True, '2', 1000):
        with pytest.raises(CommandContractError):
            normalize('cluster_op', previous, {'folding_order': stage})

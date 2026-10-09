"""Real editor workflow: extrusion, routing, history and new geometry."""

import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.core.lattice import make_bundle_design
from backend.core.models import Design
from tests.test_design_readiness import steps


@pytest.fixture
def editor(monkeypatch):
    monkeypatch.setattr(state, '_sessions', {})
    state.set_design(Design())
    return TestClient(app)


def readiness(editor):
    response = editor.get('/api/design/readiness')
    assert response.status_code == 200
    return steps(response.json())


def extrude(editor, cells):
    response = editor.post('/api/design/frame-extrusion', json={
        'expected_design_id': state.get_or_404().id,
        'expected_revision': state.revision(),
        'cells': cells, 'length_bp': 84, 'plane': 'XY',
    })
    assert response.status_code == 201, response.text


@pytest.mark.parametrize('variant', ['seamed', 'matched', 'seamless'])
def test_extrusion_routing_undo_and_new_geometry(editor, variant):
    extrude(editor, [[0, 0], [0, 1], [1, 0], [1, 1]])
    report = readiness(editor)
    assert not report['scaffold_routing']['complete']
    assert not report['staple_routing']['complete']

    response = editor.post(f'/api/design/auto-scaffold-{variant}')
    assert response.status_code == 200, response.text
    report = readiness(editor)
    assert report['scaffold_routing']['complete'], report['scaffold_routing']
    assert not report['staple_routing']['complete']

    response = editor.post('/api/design/full-autostaple', json={})
    assert response.status_code == 200, response.text
    report = readiness(editor)
    assert report['scaffold_routing']['complete']
    assert report['staple_routing']['complete'], report['staple_routing']

    assert editor.post('/api/design/undo').status_code == 200
    assert not readiness(editor)['staple_routing']['complete']
    assert editor.post('/api/design/redo').status_code == 200
    assert readiness(editor)['staple_routing']['complete']

    # Saving/loading preserves routing evidence, and a new extrusion must not
    # inherit credit from the previous commands in the feature log.
    state.set_design(Design.from_json(state.get_or_404().to_json()))
    assert readiness(editor)['staple_routing']['complete']
    extrude(editor, [[2, 0], [2, 1]])
    report = readiness(editor)
    assert not report['scaffold_routing']['complete']
    assert not report['staple_routing']['complete']


def test_sequence_assignment_alone_does_not_route_precursors(editor):
    state.set_design(make_bundle_design([(0, 0), (0, 1)], 84))
    assert editor.post('/api/design/assign-scaffold-sequence', json={'scaffold_name': 'M13mp18'}).status_code == 200
    assert editor.post('/api/design/assign-staple-sequences').status_code == 200
    report = readiness(editor)
    assert not report['scaffold_routing']['complete']
    assert not report['staple_routing']['complete']

"""Catalog imports are inert nanoparticles with the same rigid transforms as gold."""
import hashlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import doc_context, state
from backend.api.main import app
from backend.core.models import Design, QuantumDotSpec
from backend.core.oxdna_staleness import design_build_fingerprint
from backend.core.quantum_dots import DATA_DIR, quantum_dot_catalog

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_design():
    doc_context.set_current_doc(None)
    state.set_design(Design())
    yield
    state.close_session()


def test_catalog_has_vendor_spectra_sizes_and_deferred_coatings():
    response = client.get('/api/nanoparticles/quantum-dots/catalog')
    assert response.status_code == 200
    entries = response.json()['entries']
    assert len({e['vendor'] for e in entries}) >= 2
    assert len([e for e in entries if e['import_enabled']]) == 11
    assert {'Streptavidin', 'Carboxyl', 'Amine (PEG)'} <= {e['functionalization'] for e in entries}
    for entry in entries:
        spec = QuantumDotSpec.model_validate(entry)
        assert 0 < spec.diameter_range_nm[0] <= spec.diameter_range_nm[1]
        image = client.get(f"/api/nanoparticles/quantum-dots/catalog/{spec.catalog_id}/spectra")
        assert image.status_code == 200
        assert image.headers['content-type'] == 'image/png'
        assert image.content.startswith(b'\x89PNG')
        assert hashlib.sha256(image.content).hexdigest() == spec.spectra.sha256
        assert (DATA_DIR / spec.spectra.plot_file).is_file()
        assert spec.spectra.source_url.startswith('https://')
    assert client.get('/api/nanoparticles/quantum-dots/catalog/missing/spectra').status_code == 404


@pytest.mark.parametrize('entry', [e for e in quantum_dot_catalog()['entries'] if e['import_enabled']], ids=lambda e:e['catalog_id'])
def test_import_preserves_catalog_provenance_without_changing_dna(entry):
    before_fp = design_build_fingerprint(state.get_design())
    created = client.post('/api/design/nanoparticles/quantum-dots', json={'catalog_id': entry['catalog_id']})
    assert created.status_code == 201, created.text
    particle = state.get_design().nanoparticles[0]
    assert particle.id == created.json()['nanoparticle_id']
    assert particle.kind == 'quantum_dot'
    assert particle.diameter_nm == sum(entry['diameter_range_nm']) / 2
    assert particle.quantum_dot == QuantumDotSpec.model_validate(entry)
    assert design_build_fingerprint(state.get_design()) == before_fp
    assert state.get_design().nanoparticle_conjugations == []
    assert state.get_design().feature_log[-1].op_kind == 'nanoparticle-create'
    assert client.post('/api/design/undo').status_code == 200
    assert state.get_design().nanoparticles == []
    assert client.post('/api/design/redo').status_code == 200
    assert state.get_design().nanoparticles[0] == particle


def test_quantum_dot_moves_exactly_like_gold_and_survives_save_reload(tmp_path):
    gold = client.post('/api/design/nanoparticles/gold-nanospheres', json={'diameter_nm': 9.5}).json()['nanoparticle_id']
    dot = client.post('/api/design/nanoparticles/quantum-dots', json={'catalog_id':'nn-hecz-600','diameter_nm':9.2}).json()['nanoparticle_id']
    original_spec = state.get_design().nanoparticles[1].quantum_dot.model_dump()
    # Translation plus rotation about a non-origin pivot exercises the shared pose convention.
    for move in [dict(pivot=[2,3,4], translation=[5,-2,7], rotation=[0,0,0.6,0.8]),
                 dict(pivot=[-1,0,2], translation=[0,4,-3], rotation=[0,0.6,0,0.8])]:
        for pid in [gold,dot]:
            response = client.patch(f'/api/design/nanoparticles/{pid}', json={'gizmo_move':move})
            assert response.status_code == 200, response.text
        np.testing.assert_allclose(state.get_design().nanoparticles[0].pose.values, state.get_design().nanoparticles[1].pose.values)
    pose = state.get_design().nanoparticles[1].pose.values[:]
    path = tmp_path/'quantum-dot.nadoc'
    assert client.post('/api/design/save', json={'path':str(path)}).status_code == 200
    state.set_design(Design())
    assert client.post('/api/design/load', json={'path':str(path)}).status_code == 200
    loaded = next(p for p in state.get_design().nanoparticles if p.id == dot)
    assert loaded.quantum_dot.model_dump() == original_spec
    assert loaded.diameter_nm == 9.2
    assert loaded.pose.values == pose
    assert client.delete(f'/api/design/nanoparticles/{dot}').status_code == 200
    assert state.get_design().feature_log[-1].label == 'Delete quantum dot'


def test_import_and_resize_reject_invalid_sizes_and_deferred_variants():
    assert client.post('/api/design/nanoparticles/quantum-dots',json={'catalog_id':'missing'}).status_code == 404
    for entry in quantum_dot_catalog()['entries']:
        if not entry['import_enabled']:
            assert client.post('/api/design/nanoparticles/quantum-dots',json={'catalog_id':entry['catalog_id']}).status_code == 422
    for size in [0,-1,8,12,1001]:
        assert client.post('/api/design/nanoparticles/quantum-dots',json={'catalog_id':'nn-hecz-600','diameter_nm':size}).status_code == 422
    assert state.get_design().nanoparticles == []
    dot = client.post('/api/design/nanoparticles/quantum-dots',json={'catalog_id':'nn-hecz-600'}).json()['nanoparticle_id']
    assert client.patch(f'/api/design/nanoparticles/{dot}',json={'diameter_nm':30}).status_code == 422
    assert client.patch(f'/api/design/nanoparticles/{dot}',json={'diameter_nm':9.8}).status_code == 200
    assert client.post(f'/api/design/nanoparticles/{dot}/conjugation/estimate',json={'scheme':'direct_thiol'}).status_code == 422
    assert client.put(f'/api/design/nanoparticles/{dot}/conjugation',json={'sequence':'ACGT','count':1}).status_code == 422
    assert state.get_design().nanoparticle_conjugations == []


def test_quantum_dot_full_history_restores_pose_size_metadata_and_log():
    created = client.post('/api/design/nanoparticles/quantum-dots', json={'catalog_id': 'nn-hecz-600'})
    dot = created.json()['nanoparticle_id']
    states = [state.get_design().model_copy(deep=True)]
    operations = [
        {'gizmo_move': {'pivot': [0, 0, 0], 'translation': [3, 4, 5], 'rotation': [0, 0, 0.6, 0.8]}},
        {'gizmo_move': {'pivot': [3, 4, 5], 'translation': [1, 0, 0], 'rotation': [0, 0, 0, 1]}},
        {'diameter_nm': 9.8},
    ]
    for patch in operations:
        assert client.patch(f'/api/design/nanoparticles/{dot}', json=patch).status_code == 200
        states.append(state.get_design().model_copy(deep=True))
        entry = states[-1].feature_log[-1]
        assert entry.op_kind == 'nanoparticle-patch'
        assert entry.params['nanoparticle_id'] == dot
        assert 'quantum dot' in entry.label
    assert client.delete(f'/api/design/nanoparticles/{dot}').status_code == 200
    states.append(state.get_design().model_copy(deep=True))
    assert states[-1].feature_log[-1].label == 'Delete quantum dot'
    for expected in reversed(states[:-1]):
        assert client.post('/api/design/undo').status_code == 200
        assert state.get_design().nanoparticles == expected.nanoparticles
        assert state.get_design().feature_log == expected.feature_log
    for expected in states[1:]:
        assert client.post('/api/design/redo').status_code == 200
        assert state.get_design().nanoparticles == expected.nanoparticles
        assert state.get_design().feature_log == expected.feature_log


def test_automatic_animation_does_not_consume_dot_undo_or_clear_redo():
    client.post('/api/design/nanoparticles/quantum-dots', json={'catalog_id': 'nn-hecz-600'})
    dot = state.get_design().nanoparticles[0].model_copy(deep=True)
    for _ in range(2):
        assert client.post('/api/design/animations', json={'ensure_default': True}).status_code == 200
    assert len(state.get_design().animations) == 1
    client.post('/api/design/undo')
    assert state.get_design().nanoparticles == []
    client.post('/api/design/animations', json={'ensure_default': True})
    client.post('/api/design/redo')
    assert state.get_design().nanoparticles == [dot]

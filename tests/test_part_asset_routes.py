"""Ordinary UI routes publish one worker result and retain input-only history."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import state, part_evaluation_jobs as jobs, part_evaluation_capture as policy
from backend.api.doc_context import DocContextMiddleware, set_current_doc, reset_current_doc
from backend.api.routes_feature_log import router as history_router
from backend.api.routes_nanoparticles import router as particle_router
from backend.api.routes_nanoparticle_attachment import router as attachment_router
from backend.core.part_history_contract import create_empty_part
from tests.test_native_asset_evaluation import worker, poison
from tests.test_part_pending_np_connections import native_prefix as native_prefix, append

pytestmark = [pytest.mark.slow, pytest.mark.headless]
PATH = '/api/design/features/evaluation/jobs'
PARTICLES = '/api/design/nanoparticles'


@pytest.fixture
def client(monkeypatch):
    identity = '__asset_routes__' + str(uuid4())
    token = set_current_doc(identity)
    state.load_design(create_empty_part('Asset routes', 'HONEYCOMB'))
    previous = set(jobs._jobs)
    monkeypatch.setattr(policy, 'BIOTIN_APPEND_ENABLED', True)
    monkeypatch.setattr(policy, 'NP_FITTING_APPEND_ENABLED', True)
    monkeypatch.setattr(policy, 'GENERATED_ASSETS_ENABLED', True)
    monkeypatch.setattr(jobs, '_submit', jobs._run)
    # These checks isolate HTTP/replay correctness. Repeated live-clock capture
    # and publication measurements live in benchmark_native_asset_jobs.py.
    original_capture = policy.capture
    monkeypatch.setattr(policy, 'capture', lambda design, **kw: original_capture(
        design, **{**kw, 'seconds': 1.0}))
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    from backend.api.routes_generate_design import router as generator_router
    for router in (history_router, particle_router, attachment_router, generator_router):
        app.include_router(router, prefix='/api')
    try:
        with TestClient(app, headers={'X-NADOC-Doc': identity}) as client:
            yield client
    finally:
        with jobs._lock:
            for key in set(jobs._jobs) - previous:
                jobs._jobs.pop(key, None)
        with state._lock:
            state._sessions.pop(identity, None)
        reset_current_doc(token)


def start(client, method, path, body=None):
    source, revision = state.get_design_with_revision()
    params = {'expected_revision': revision, 'expected_design_id': source.id}
    if path.endswith('/attach-overhang'):
        body = {**body, **params}
    response = client.request(method, path, params=params, json=body)
    assert response.status_code in {200, 201, 202}, response.text
    identity = response.json()['job_id']
    assert state.get_or_404() is source and state.revision() == revision
    result = client.get(f'{PATH}/{identity}').json()
    assert result['result']['status'] == 'ready', result
    assert 'candidate' not in result['result']
    return identity


def publish(client, method, path, body=None):
    before, depth = state.revision(), state.undo_depth()
    identity = start(client, method, path, body)
    response = client.post(f'{PATH}/{identity}/commit')
    assert response.status_code == 200, response.text
    assert state.revision() == before + 1 and state.undo_depth() == depth + 1
    return state.get_or_404()


def test_generated_assembly_uses_existing_worker_and_single_publication(client):
    from tests.test_generated_asset_recipe import native_source
    state.load_design(native_source())
    source, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    response = client.post('/api/design/generate-design', json={'extend_rod': False,
        'expected_revision': revision})
    assert response.status_code == 200, response.text
    identity = response.json()['job_id']
    assert state.get_or_404() is source and state.revision() == revision
    result = client.get(f'{PATH}/{identity}').json()
    assert result['result']['status'] == 'ready', result
    assert len(result['result']['generation']['connections']) == 2
    response = client.post(f'{PATH}/{identity}/commit')
    assert response.status_code == 200, response.text
    assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
    assert len(state.get_or_404().duplexes) == 2
    assert all(getattr(e, 'params', {}).get('_proof_version') == 1
               for e in state.get_or_404().feature_log if e.feature_type == 'snapshot')
    assert client.post(f'{PATH}/{identity}/commit').status_code == 200
    assert state.revision() == revision + 1


def test_ordinary_coating_biotin_edit_remove_replay_and_undo(client):
    from backend.core.models import DesignAnimation, DesignLoadout
    from backend.core.design_loadouts import encode_snapshot
    animation = DesignAnimation(name='animation 1')
    state.get_or_404().animations = [animation]
    state.get_or_404().metadata.identity_last_known_path = '__e2e__saved-assets.nadoc'
    state.get_or_404().metadata.identity_confirmed_at = '2026-11-01T22:00:00+00:00'
    payload, size = encode_snapshot(state.get_or_404())
    loadout = DesignLoadout(id='main', design_snapshot_gz_b64=payload, snapshot_size_bytes=size)
    state.get_or_404().loadouts = [loadout]
    state.get_or_404().active_loadout_id = 'main'
    coated = publish(client, 'POST', f'{PARTICLES}/gold-nanospheres',
        {'diameter_nm': 10., 'coating': {'count_override': 1}})
    particle = coated.nanoparticles[0].id
    assert len(coated.feature_log) == 2 and coated.input_sources
    assert coated.animations == [animation]
    assert coated.loadouts == [loadout] and coated.active_loadout_id == 'main'
    assert coated.metadata.identity_last_known_path == '__e2e__saved-assets.nadoc'
    assert coated.metadata.identity_confirmed_at == '2026-11-01T22:00:00+00:00'
    attached = publish(client, 'POST', f'{PARTICLES}/{particle}/biotin-dna',
        {'sequence': 'acgtacgt', 'linker_nm': 2.})
    assert attached.feature_log[-1].params['sequence'] == 'ACGTACGT'
    prior_revision, prior_depth = state.revision(), state.undo_depth()
    failed = client.post(PATH, json={'operation': 'edit', 'index': 1,
        'params': {'count_override': 2}, 'expected_revision': prior_revision})
    assert failed.status_code == 202, failed.text
    refused = client.get(f'{PATH}/{failed.json()["job_id"]}').json()['result']
    assert refused['status'] != 'ready' and refused['issues'][0]['detail']['feature_id'] == attached.feature_log[2].id, refused
    assert state.get_or_404() is attached and state.revision() == prior_revision and state.undo_depth() == prior_depth
    attached = publish(client, 'POST', PATH, {'operation': 'edit', 'index': 1,
        'params': {'seed': 2}, 'expected_revision': state.revision()})
    assert attached.feature_log[1].params['seed'] == 2
    edited = publish(client, 'POST', PATH, {'operation': 'edit', 'index': 2,
        'params': {'sequence': 'ACGTACGA'}, 'expected_revision': state.revision()})
    assert edited.strands[0].sequence == 'ACGTACGA'
    assert edited.strands[0].id == attached.strands[0].id
    assert edited.metadata.identity_last_known_path == coated.metadata.identity_last_known_path
    assert worker(poison(edited), {'operation': 'verify'})['status'] == 'reproduced_import'
    removed = publish(client, 'DELETE', f'{PARTICLES}/{particle}/biotin-dna')
    assert not removed.strands and not removed.extensions
    state.undo()
    assert state.get_or_404().strands == edited.strands


def test_ordinary_fit_auto_select_move_relax_then_remove(client, native_prefix):
    source = append(native_prefix.model_copy(deep=True), 'assign-scaffold-sequence',
        {'_proof_version': 1, 'scaffold_name': 'M13mp18'}, 'scaffold-sequence')
    state.load_design(source)
    target = next(o.id for o in native_prefix.overhangs if not o.auxiliary_endpoint)
    fitted = publish(client, 'POST', f'{PARTICLES}/gold/attach-overhang', {'overhang_id': target})
    assert fitted.feature_log[-1].params['strand_id']
    assert fitted.feature_log[-1].params['np_fitting_version'] == 1
    publish(client, 'PATCH', f'{PARTICLES}/gold', {'gizmo_move': {
        'pivot': [0., 0., 0.], 'translation': [.1, .1, 0.], 'rotation': [0., 0., 0., 1.]}})
    relaxed = publish(client, 'POST', f'{PARTICLES}/gold/connection-versions/relax')
    assert all(v.relaxed for v in relaxed.nanoparticle_connection_versions)
    result = worker(poison(relaxed), {'operation': 'verify'})
    assert result['status'] == 'verified', result
    version = relaxed.nanoparticle_connection_versions[0].id
    response = client.delete(f'{PARTICLES}/gold/connection-versions/{version}')
    assert response.status_code == 200, response.text
    final = state.get_or_404()
    assert final.feature_log[-1].params['nanoparticle_application_version'] == 2
    assert not final.duplexes
    assert worker(poison(final), {'operation': 'verify'})['status'] == 'verified'


def test_cancelled_or_stale_private_coating_job_cannot_publish(client):
    source = state.get_or_404()
    args = ('POST', f'{PARTICLES}/gold-nanospheres', {'diameter_nm': 10., 'coating': {'count_override': 1}})
    job = start(client, *args)
    assert client.delete(f'{PATH}/{job}').status_code == 200
    assert client.post(f'{PATH}/{job}/commit').status_code == 409
    assert state.get_or_404() is source and state.undo_depth() == 0
    job = start(client, *args)
    state.load_design(create_empty_part('Another document', 'HONEYCOMB'))
    assert client.post(f'{PATH}/{job}/commit').status_code == 409
    assert not state.get_or_404().nanoparticles


def test_stale_ordinary_intent_refused_before_job(client):
    previous = set(jobs._jobs)
    response = client.post(f'{PARTICLES}/gold-nanospheres',
        params={'expected_revision': state.revision() + 1},
        json={'diameter_nm': 10., 'coating': {'count_override': 1}})
    assert response.status_code == 409 and set(jobs._jobs) == previous


def test_ordinary_choices_outside_native_bounds_return_actionable_error(client):
    previous = set(jobs._jobs)
    response = client.post(f'{PARTICLES}/gold-nanospheres',
        json={'diameter_nm': 10., 'coating': {'count_override': 65}})
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'invalid_asset_inputs'
    assert set(jobs._jobs) == previous and state.undo_depth() == 0


def test_coating_animation_admission_does_not_admit_authored_presentation(client):
    from backend.core.models import DesignAnimation
    state.get_or_404().animations = [DesignAnimation(fps=60)]
    response = client.post(f'{PARTICLES}/gold-nanospheres',
        json={'diameter_nm': 10., 'coating': {'count_override': 1}})
    assert response.status_code == 422, response.text
    assert 'animations' in response.text and state.undo_depth() == 0

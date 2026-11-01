"""Real asset job publication uses the existing revision-bound transaction."""
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import part_evaluation_capture as capturing, part_evaluation_jobs as jobs, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import import_root
from tests.test_native_asset_evaluation import append
from tests.test_nanoparticle_attachment import attachment_source as attachment_source

pytestmark = [pytest.mark.slow, pytest.mark.headless]


def wait(identity):
    deadline = monotonic() + 30
    while monotonic() < deadline:
        result = jobs.inspect(identity)
        if result['status'] != 'running':
            return result
        sleep(.02)
    pytest.fail('Asset publication worker timed out')


@pytest.mark.parametrize('family', ['biotin', 'fitting'])
def test_actual_capture_commit_undo_cancel_and_stale_result(family, attachment_source, monkeypatch):
    monkeypatch.setattr(capturing, 'BIOTIN_APPEND_ENABLED', True)
    monkeypatch.setattr(capturing, 'NP_FITTING_APPEND_ENABLED', True)
    doc = 'asset-job-' + str(uuid4())
    token = set_current_doc(doc)
    identities = []
    try:
        if family == 'biotin':
            source = append(create_empty_part('Coating', 'HONEYCOMB'), 'streptavidin-coating',
                {'action': 'create', 'diameter_nm': 10., 'coating': {'count_override': 1}})
            kind = 'nanoparticle-biotin-dna'
            params = {'action': 'create', 'nanoparticle_id': source.nanoparticles[0].id,
                      'sequence': 'ACGTACGT', 'linker_nm': 2.}
        else:
            source, particle_id = attachment_source
            source = source.copy_with(feature_log=[])
            source.recipe_root = import_root(source)
            kind = 'nanoparticle-attach-overhang'
            params = {'nanoparticle_id': particle_id, 'overhang_id': 'target_3p',
                      'strand_id': source.nanoparticle_conjugations[0].surface_strands[0].strand_id}
        for action in ('commit', 'cancel', 'stale'):
            state.load_design(source.model_copy(deep=True))
            original = state.get_or_404().model_dump_json()
            revision, depth = state.revision(), state.undo_depth()
            begin = monotonic()
            job = jobs.start({'operation': 'append', 'kind': kind, 'params': params,
                              'expected_revision': revision})
            identities.append(job['job_id'])
            capture_ms = (monotonic() - begin) * 1000
            result = wait(job['job_id'])
            assert result['result']['status'] == 'ready', result
            assert state.get_or_404().model_dump_json() == original and state.revision() == revision
            if action == 'commit':
                receipt = jobs.commit(job['job_id'])
                assert receipt['revision'] == revision + 1
                assert state.undo_depth() == depth + 1
                after = state.get_or_404().model_dump_json()
                assert after != original
                repeated = jobs.commit(job['job_id'])
                assert repeated['status'] == 'committed' and repeated['revision'] == receipt['revision']
                assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
                state.undo()
                assert state.get_or_404().model_dump_json() == original
                state.redo()
                assert state.get_or_404().model_dump_json() == after
            else:
                if action == 'cancel':
                    jobs.inspect(job['job_id'], cancel=True)
                else:
                    current = state.get_or_404()
                    state.set_design(current.copy_with(metadata=current.metadata.model_copy(update={'name': 'Intervening edit'})))
                protected, revision = state.get_or_404().model_dump_json(), state.revision()
                with pytest.raises(HTTPException) as error:
                    jobs.commit(job['job_id'])
                assert error.value.status_code == 409
                assert state.get_or_404().model_dump_json() == protected and state.revision() == revision
            print({'family': family, 'action': action, 'capture_ms': capture_ms,
                   'elapsed_ms': (monotonic() - begin) * 1000})
    finally:
        try:
            for identity in identities:
                try:
                    jobs.inspect(identity, cancel=True)
                    wait(identity)
                except HTTPException as error:
                    # The existing two-result retention cap can evict a prior
                    # terminal job before this test's third lifecycle begins.
                    assert error.status_code == 404
                finally:
                    with jobs._lock:
                        jobs._jobs.pop(identity, None)
        finally:
            state.drop_doc(doc)
            reset_current_doc(token)

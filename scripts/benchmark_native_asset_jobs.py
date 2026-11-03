"""Qualify fitted and biotin history using the existing coating job probes.

Run under just validate-safe. Output is JSON only. Repeated capture/publication
costs exclude the numerical worker; separately spawned jobs exercise that path.
No source, lock, recovery or capture allowance is enlarged.
"""
import json
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from threadpoolctl import threadpool_limits

from backend.api import state, part_evaluation_capture as policy
from backend.api.doc_context import DocContextMiddleware
from backend.api.part_evaluation import evaluate
from backend.api.routes_feature_log import router
from backend.core.models import Design, DesignAnimation, DesignLoadout
from backend.core.part_history_contract import create_empty_part
from scripts.benchmark_coating_jobs import repeated_case, actual_job, REVISION_PATH
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper
from tests.test_native_asset_evaluation import append, worker
from tests.test_part_pending_np_connections import native_prefix, append as native


def fixture(name, design, index, params):
    design = design.copy_with(animations=[DesignAnimation(name='animation 1')])
    from backend.core.design_loadouts import encode_snapshot
    payload, size = encode_snapshot(design)
    design = design.copy_with(loadouts=[DesignLoadout(id='main', design_snapshot_gz_b64=payload,
        snapshot_size_bytes=size)], active_loadout_id='main')
    request = {'operation': 'edit', 'index': index, 'params': params}
    begin = perf_counter()
    prepared = evaluate(design, {'request': request, 'header': {}})
    assert prepared['status'] == 'ready', prepared
    return dict(name=name, mode=name, requested_sites=0, actual_sites_before_removal=0,
        removed=False, design=design, request=request, prepared=prepared,
        separate_native_candidate_evaluation_ms=(perf_counter() - begin) * 1000)


def cases():
    source = native(native_prefix.__wrapped__(), 'assign-scaffold-sequence',
        {'_proof_version': 1, 'scaffold_name': 'M13mp18'}, 'scaffold-sequence')
    target = next(o.id for o in source.overhangs if not o.auxiliary_endpoint)
    fitted = append(source, 'nanoparticle-attach-overhang', {'nanoparticle_id': 'gold', 'overhang_id': target})
    motion = {'pivot': [0., 0., 0.], 'translation': [.1, .1, 0.], 'rotation': [0., 0., 0., 1.]}
    moved = append(fitted, 'nanoparticle-bound-move', {'nanoparticle_id': 'gold', 'gizmo_move': motion})
    yield fixture('fitted-move', moved, len(moved.feature_log) - 1, {'gizmo_move': motion})
    relaxed = append(moved, 'nanoparticle-connection-relax', {'nanoparticle_id': 'gold'})
    yield fixture('fitted-retained-relax', relaxed, len(relaxed.feature_log) - 1, {})
    for sites, length, copies in [(1, 8, 1), (1, 8, 4), (4, 32, 3)]:
        root = create_empty_part('Biotin qualification', 'HONEYCOMB')
        coated = append(root, 'streptavidin-coating', {'action': 'create', 'diameter_nm': 10. if sites == 1 else 20.,
            'coating': {'count_override': sites}})
        pid = coated.nanoparticles[0].id
        attached = append(coated, 'nanoparticle-biotin-dna', {'action': 'create', 'nanoparticle_id': pid,
            'sequence': 'ACGT' * (length // 4), 'dna_per_strep': copies, 'linker_nm': 2.})
        yield fixture(f'biotin-{sites}-sites-{length}-bases-{copies}-per-site', attached, 2, {'sequence': 'ACGT' * (length // 4)})
        removed = append(attached, 'nanoparticle-biotin-dna', {'action': 'remove', 'nanoparticle_id': pid})
        yield fixture(f'biotin-{sites}-{copies}-per-site-retained-removal', removed, 2, {'sequence': 'ACGT' * (length // 4)})


def main():
    previous_flags = policy.NP_FITTING_APPEND_ENABLED, policy.BIOTIN_APPEND_ENABLED
    policy.NP_FITTING_APPEND_ENABLED = policy.BIOTIN_APPEND_ENABLED = True
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(router, prefix='/api')

    @app.get(REVISION_PATH)
    def revision():
        token = _PHASE.set('light_request')
        try:
            return {'revision': state.revision()}
        finally:
            _PHASE.reset(token)

    originals = state._lock, state.capture_design_for_evaluation, state.set_design, state._snapshot_copy
    probe, snapshots = LockProbe(originals[0]), []
    def snapshot(design, **kwargs):
        begin = perf_counter()
        try:
            return originals[3](design, **kwargs)
        finally:
            snapshots.append((perf_counter() - begin) * 1000)
    doc = '__benchmark_native_assets_' + str(uuid4())
    report = {'scope': __doc__, 'repeats': 30, 'cases': [], 'live': [], 'cold': [], 'races': []}
    try:
        with threadpool_limits(limits=1):
            fixtures = list(cases())
            state._lock = probe
            state.capture_design_for_evaluation = phase_wrapper(originals[1], 'capture')
            state.set_design = phase_wrapper(originals[2], 'publication')
            state._snapshot_copy = snapshot
            with TestClient(app) as client:
                for case in fixtures:
                    report['cases'].append(repeated_case(client, doc, case, 30, probe, snapshots))
                    report['live'].append({'case': case['name'], **actual_job(client, doc, case)})
                    candidate = Design.model_validate(case['prepared']['candidate'])
                    for row in candidate.feature_log:
                        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = 'poisoned recovery'
                    proof = worker(candidate, {'operation': 'verify'})
                    report['cold'].append({'case': case['name'], 'status': proof['status']})
                report['races'] = [actual_job(client, doc, fixtures[0], mode) for mode in ('cancel', 'source_changed')]
    finally:
        state.drop_doc(doc)
        state._lock, state.capture_design_for_evaluation, state.set_design, state._snapshot_copy = originals
        policy.NP_FITTING_APPEND_ENABLED, policy.BIOTIN_APPEND_ENABLED = previous_flags
        report['session_cleanup_verified'] = doc not in state.revision_map()
        print(json.dumps(report, indent=2))
    passed = all(c['capture_refusals'] == 0 and c['correct_publications'] == 30 for c in report['cases'])
    passed &= all(c['start_http_status'] == 202 and c['commit_http_status'] == 200 and c['source_guard_correct']
        and c['shared_admission_released_after_reaping'] for c in report['live'])
    passed &= all(c['status'] in {'verified', 'reproduced_import'} for c in report['cold'])
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())

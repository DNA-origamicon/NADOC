"""Full generated assets must replay without their snapshots or fit results."""
from copy import deepcopy

import pytest

from backend.api.generated_history import build_recorded
from backend.api.part_evaluation_worker import native_thread_limit
from backend.api.part_proof_commands import execute_long, dependencies
from backend.core.part_history_contract import create_empty_part, assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.two_np_generator import GeneratorSettings, plan_rods
from tests.test_part_pending_np_connections import append, gold
from tests.test_two_np_generator import source as particle_source


def native_source(name='Generated assets', particles=None):
    result = create_empty_part(name, 'HONEYCOMB')
    particles = particle_source(displacement=(0, 0, 40)).nanoparticles if particles is None else particles
    for i, particle in enumerate(particles):
        result = append(result, 'nanoparticle-create', gold(f'gold-{i}'), f'particle-{i}')
        result = append(result, 'nanoparticle-patch', {'_proof_version': 1, 'nanoparticle_version': 1,
            'nanoparticle_id': f'gold-{i}', 'pose': particle.pose.values}, f'pose-{i}')
    return result


@pytest.fixture(scope='module')
def generated():
    with native_thread_limit():
        source = native_source()
        settings = GeneratorSettings(extend_rod=False, connections_per_particle=2)
        planned, _ = plan_rods(source, settings)
        result, report = build_recorded(source, planned, settings, native_assets=True)
        assert not report.get('history_unverified_steps'), report
        return source, result, settings


@pytest.mark.slow
def test_full_generated_multi_anchor_cold_replay_and_upstream_edit(generated):
    from backend.api.part_recipe_edit import prepare_change
    source, generated, _ = generated
    before = source.model_dump_json()
    loaded = type(generated).model_validate_json(generated.model_dump_json())
    for entry in loaded.feature_log:
        for key in ('design_snapshot_gz_b64', 'post_state_gz_b64', 'pre_state_gz_b64'):
            if key in type(entry).model_fields:
                setattr(entry, key, 'poisoned recovery')
    with native_thread_limit():
        result = assess_part_history(loaded, execute=execute_long, dependencies=dependencies)
        assert result['status'] == 'verified', result
        index = next(i for i, entry in enumerate(loaded.feature_log)
                     if getattr(entry, 'op_kind', None) == 'nanoparticle-conjugate')
        params = deepcopy(loaded.feature_log[index].params)
        params['spacer_nm'] = 0.8
        changed, _ = prepare_change(loaded, loaded, index, lambda: None, params=params,
            executor=execute_long, dependency_resolver=dependencies)
        assert len(changed.duplexes) == 4
        assert assess_part_history(changed, execute=execute_long, dependencies=dependencies)['status'] == 'verified'
    assert source.model_dump_json() == before
    assert [p.id for p in changed.nanoparticles] == [p.id for p in source.nanoparticles]


@pytest.mark.slow
def test_generated_teardown_preserves_other_anchors_and_replays(generated):
    from backend.api.part_generated_np_fitting import teardown_inputs
    from backend.core.models import SnapshotLogEntry
    _, source, _ = generated
    with native_thread_limit():
        version = source.nanoparticle_connection_versions[0]
        params = teardown_inputs(source, version.id)
        changed = execute_long('nanoparticle-connection-version-patch', source, params)
        changed = changed.copy_with(feature_log=[*source.feature_log, SnapshotLogEntry(
            op_kind='nanoparticle-connection-version-patch', params=params, label='Detach generated anchor')])
        retained = [v for v in source.nanoparticle_connection_versions if v.id != version.id]
        assert [v for v in changed.nanoparticle_connection_versions if v.id != version.id] == retained
        assert len(changed.duplexes) == 3
        assert assess_part_history(changed, execute=execute_long, dependencies=dependencies)['status'] == 'verified'


def test_additive_graft_refuses_stale_retained_ownership():
    from backend.api.part_thiol_commands import build
    from tests.test_part_pending_np_connections import graft
    source = native_source()
    first = build('nanoparticle-conjugate', source, graft('gold-0'))
    params = {**graft('gold-0'), 'thiol_version': 2, 'retained_conjugation_ids': []}
    before = first.model_dump(include=AUTHORING_FIELDS)
    with pytest.raises(ValueError, match='exactly'):
        build('nanoparticle-conjugate', first, params)
    assert first.model_dump(include=AUTHORING_FIELDS) == before


@pytest.mark.slow
def test_generator_reuses_retained_grafts_and_preserves_independent_dna():
    from uuid import uuid4
    from tests.test_part_pending_np_connections import graft
    source = native_source()
    source = append(source, 'extrude-segment', {'_proof_version': 1, 'history_seed': str(uuid4()),
        'cells': [[20, 20]], 'length_bp': 21, 'ligate_adjacent': False}, 'independent-dna')
    independent = {s.id: s for s in source.strands}
    for particle in source.nanoparticles:
        source = append(source, 'nanoparticle-conjugate', {**graft(particle.id, history_seed=str(uuid4())),
            'sequence': 'ACGTGACTCAGTACGATC'}, f'graft-{particle.id}')
    retained = {r.strand_id for c in source.nanoparticle_conjugations for r in c.surface_strands}
    settings = GeneratorSettings(extend_rod=False)
    with native_thread_limit():
        planned, _ = plan_rods(source, settings)
        result, report = build_recorded(source, planned, settings, native_assets=True)
        assert not report.get('history_unverified_steps'), report
        assert assess_part_history(result, execute=execute_long, dependencies=dependencies)['status'] == 'verified'
    assert {s.id: s for s in result.strands if s.id in independent} == independent
    assert {v.strand_id for v in result.nanoparticle_connection_versions} <= retained
    assert result.nanoparticle_conjugations and len(result.nanoparticle_conjugations) == 2


@pytest.mark.slow
@pytest.mark.parametrize('shape,particles,anchors', [('platform', 4, 3), ('curved-rod', 3, 1)])
def test_generated_shapes_reproduce_complete_authoring(shape, particles, anchors):
    from backend.core.platform_generator import plan_generated
    from tests.test_curved_rod_generator import source as multi_source
    source = native_source(particles=multi_source(count=particles).nanoparticles)
    before = source.model_dump_json()
    settings = GeneratorSettings(shape=shape, connections_per_particle=anchors)
    with native_thread_limit():
        planned, _ = plan_generated(source, settings)
        result, report = build_recorded(source, planned, settings, native_assets=True)
        assert not report.get('history_unverified_steps'), report
        assert len(result.duplexes) == particles * anchors
        assert assess_part_history(result, execute=execute_long, dependencies=dependencies)['status'] == 'verified'
    assert source.model_dump_json() == before


@pytest.mark.slow
def test_regeneration_detaches_previous_anchors_and_cold_replays(generated):
    _, source, _ = generated
    before = source.model_dump_json()
    settings = GeneratorSettings(extend_rod=False)
    with native_thread_limit():
        planned, _ = plan_rods(source, settings)
        result, report = build_recorded(source, planned, settings, native_assets=True)
        assert not report.get('history_unverified_steps'), report
        assert len(result.duplexes) == 2
        assert assess_part_history(result, execute=execute_long, dependencies=dependencies)['status'] == 'verified'
    assert source.model_dump_json() == before

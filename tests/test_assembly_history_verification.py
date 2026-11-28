"""Independent proof rejects missing process, changed state and mutable inputs."""

import pytest

from backend.api import assembly_state, state, crud
from backend.api.assembly import CreateAssemblyRequest, create_assembly, AddInstanceRequest, add_instance, PatchInstanceRequest, patch_instance, delete_instance
from backend.api.assembly_history_verification import verify
from backend.core.models import Assembly


@pytest.fixture(autouse=True)
def sessions():
    assembly_state.close_session()
    state.close_session()
    yield
    assembly_state.close_session()
    state.close_session()


def recorded():
    create_assembly(CreateAssemblyRequest(name='Recorded assembly'))
    crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=21))
    design = state.get_or_404().model_copy(deep=True)
    add_instance(AddInstanceRequest(name='Part', source={'type': 'inline', 'design': design.model_dump(mode='json')}))
    identity = assembly_state.get_or_404().instances[0].id
    patch_instance(identity, PatchInstanceRequest(name='Renamed', fixed=True))
    return assembly_state.get_or_404().model_copy(deep=True)


def test_new_root_is_explicit_and_legacy_load_does_not_infer_it():
    create_assembly(CreateAssemblyRequest(name='Empty'))
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert saved.recipe_root.initial_name == 'Empty'
    assert verify(saved)['status'] == 'verified'
    legacy = Assembly.from_json(Assembly().to_json())
    assert legacy.recipe_root is None
    assert verify(legacy)['issues'] == [{'code': 'missing_recipe_root'}]


def test_saved_proof_never_reads_recovery_and_preserves_live_sessions(monkeypatch):
    saved = recorded()
    for row in saved.feature_log:
        row.design_snapshot_gz_b64 = 'invalid recovery bytes'
        row.post_state_gz_b64 = 'invalid recovery bytes'
        row.evicted = True
    saved = Assembly.from_json(saved.to_json())
    before, revision = assembly_state.copy_for_persist()
    part = state.get_or_404().model_copy(deep=True)
    depths = assembly_state.undo_depth(), assembly_state.redo_depth()
    monkeypatch.setattr(assembly_state, 'decode_assembly_snapshot', lambda *args: pytest.fail('Recovery consulted'))
    result = verify(saved)
    assert result['status'] == 'verified', result
    assert result['checked_commands'] == 2
    assert len(result['source_proofs']) == 1
    assert assembly_state.copy_for_persist() == (before, revision)
    assert (assembly_state.undo_depth(), assembly_state.redo_depth()) == depths
    assert state.get_or_404() == part


@pytest.mark.parametrize('change', ['name', 'pose', 'source', 'metadata'])
def test_unrecorded_authoring_changes_fail_comparison(change):
    saved = recorded()
    if change == 'name':
        saved.instances[0].name = 'Unrecorded'
    elif change == 'pose':
        saved.instances[0].transform.values[3] += 10
    elif change == 'source':
        saved.instances[0].source.design.metadata.name = 'Unrecorded source'
    else:
        saved.metadata.name = 'Unrecorded assembly'
    result = verify(saved)
    assert result['status'] == 'mismatch', result
    assert result['issues'][0]['fields'] == ['metadata' if change == 'metadata' else 'instances']


def test_deleted_source_still_requires_upstream_process():
    recorded()
    delete_instance(assembly_state.get_or_404().instances[0].id)
    saved = assembly_state.get_or_404().model_copy(deep=True)
    assert verify(saved)['status'] == 'verified'
    source = saved.feature_log[0].params['inputs']['source']['design']
    source['feature_log'] = []
    source['recipe_root'] = None
    result = verify(saved)
    assert result['status'] == 'unverified'
    assert 'source part history' in result['issues'][0]['detail']
    assert result['issues'][0]['feature_id'] == saved.feature_log[0].id


def test_unpinned_source_refuses_before_external_file_resolution(monkeypatch):
    saved = recorded()
    saved.feature_log[0].params['inputs']['source'] = {'type': 'file', 'path': '/missing.nadoc', 'sha256': None, 'revision': None, 'revision_sha256': None}
    from backend.api import assembly
    monkeypatch.setattr(assembly, '_load_design_from_source', lambda *args: pytest.fail('External source read'))
    result = verify(saved)
    assert result['status'] == 'unverified'
    assert 'pinned revision' in result['issues'][0]['detail']


def test_display_preferences_excluded_but_suppressed_definition_validated():
    saved = recorded()
    saved.instances[0].visible = False
    saved.instances[0].representation = 'beads'
    assert verify(saved)['status'] == 'verified'
    saved.feature_log[1].suppressed = True
    saved.instances[0].name = 'Part'
    saved.instances[0].fixed = False
    assert verify(saved)['status'] == 'verified'
    saved.feature_log[1].params['inputs']['unknown'] = 1
    assert verify(saved)['issues'][0]['code'] == 'invalid_command'


def test_cancellation_propagates_without_result_or_publication():
    saved = recorded()
    def cancelled():
        raise InterruptedError('cancel')
    with pytest.raises(InterruptedError):
        verify(saved, checkpoint=cancelled)
    assert assembly_state.get_or_404() == saved


def test_pinned_file_revision_proves_without_external_file_and_reuses_source_proof(monkeypatch):
    saved = recorded()
    design = saved.instances[0].source.design
    from backend.core.models import PartSourceFile
    from backend.core.assembly_source_versions import pin_source
    pinned = pin_source(PartSourceFile(path='/nonexistent-recorded-source.nadoc'), design)
    add_instance(AddInstanceRequest(source=pinned.model_dump(mode='json')))
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    from backend.api import assembly_history_verification as module
    original = module.assess_part_history
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'assess_part_history', counted)
    result = verify(saved)
    assert result['status'] == 'verified', result
    assert len(calls) == 1


def test_unknown_model_fields_invalid_roots_and_boolean_command_versions_fail_closed():
    from backend.core.models import Assembly
    from backend.core.assembly_history_contract import create_empty_assembly
    class FutureAssembly(Assembly):
        future_authoring_state: str = ''
    future = FutureAssembly.model_validate(create_empty_assembly().model_dump())
    assert verify(future)['issues'][0]['code'] == 'unclassified_fields'
    invalid = create_empty_assembly()
    invalid.recipe_root = invalid.recipe_root.model_copy(update={'version': 2})
    assert verify(invalid)['issues'][0]['code'] == 'invalid_recipe_root'
    saved = recorded()
    saved.feature_log[0].params['command_version'] = True
    assert verify(saved)['issues'][0]['code'] == 'invalid_command'


def test_invalid_intermediate_reference_is_reported_even_if_later_deleted():
    from backend.api.routes_assembly_joints import AddJointRequest, add_joint, delete_joint
    saved = recorded()
    add_joint(AddJointRequest(instance_b_id=saved.instances[0].id, cluster_id_b='missing cluster'))
    failed_row = assembly_state.get_or_404().feature_log[-1].id
    delete_joint(assembly_state.get_or_404().joints[0].id)
    saved = assembly_state.get_or_404().model_copy(deep=True)
    result = verify(saved)
    assert result['status'] == 'failed', result
    assert result['structure']['status'] == 'valid'
    assert result['issues'][0]['code'] == 'invalid_intermediate_references'
    assert result['issues'][0]['feature_id'] == failed_row
    assert assembly_state.get_or_404() == saved

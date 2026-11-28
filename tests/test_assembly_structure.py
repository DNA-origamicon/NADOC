"""Assembly relation checks diagnose invalid selections without modifying state."""
import pytest

from backend.api import assembly_state, state
from backend.core.assembly_structure import assess_references
from tests.test_assembly_command_replay import gears, add_empty_part


@pytest.fixture(autouse=True)
def sessions():
    assembly_state.close_session()
    state.close_session()
    yield
    assembly_state.close_session()
    state.close_session()


def test_joint_parent_gear_and_belt_references_and_limits():
    from backend.api.routes_assembly_belts import CreateBeltPathRequest, create_belt_path
    gears()
    a, b = assembly_state.get_or_404().joints
    create_belt_path(CreateBeltPathRequest(pulley_a={'joint_id': a.id, 'radius': 2},
                                         pulley_b={'joint_id': b.id, 'radius': 2}))
    original = assembly_state.get_or_404().model_copy(deep=True)
    assert assess_references(original)['status'] == 'valid'
    broken = original.model_copy(deep=True)
    broken.joints[0].instance_a_id = 'missing parent'
    broken.gear_relations[0].endpoint_a_instance_id = 'wrong endpoint'
    broken.belt_paths[0].pulley_b.joint_id = 'missing joint'
    result = assess_references(broken)
    assert result['status'] == 'invalid'
    assert {e['code'] for e in result['issues']} == {'missing_reference', 'endpoint_not_on_joint'}
    assert len(result['issues']) == 3
    assert assembly_state.get_or_404() == original
    assert assess_references(broken, max_issues=1)['status'] == 'incomplete'
    assert assess_references(original, max_items=1)['status'] == 'incomplete'


def test_group_cycles_duplicate_members_and_identity_collisions():
    from backend.api.routes_assembly_groups import CreateGroupRequest, create_group
    gears()
    a, b = assembly_state.get_or_404().instances
    create_group(CreateGroupRequest(instance_ids=[a.id]))
    create_group(CreateGroupRequest(instance_ids=[b.id]))
    original = assembly_state.get_or_404().model_copy(deep=True)
    assert assess_references(original)['status'] == 'valid'
    broken = original.model_copy(deep=True)
    broken.groups[0].subgroup_ids = [broken.groups[1].id]
    broken.groups[1].subgroup_ids = [broken.groups[0].id]
    broken.groups[1].instance_ids.append(a.id)
    broken.instances.append(broken.instances[0])
    result = assess_references(broken)
    assert {e['code'] for e in result['issues']} >= {'duplicate_identity', 'multiple_group_parents', 'group_cycle_or_unresolved_child'}


def test_source_overhang_and_subdomain_references():
    from tests.test_assembly_overhang_command_replay import pair, bind
    from backend.api.routes_assembly_overhangs import sync_assembly_duplexes
    pair_root, ends = pair()
    bind(ends)
    sync_assembly_duplexes()
    saved = assembly_state.get_or_404().model_copy(deep=True)
    assert assess_references(saved)['status'] == 'valid'
    saved.overhang_bindings[0].sub_domain_a_id = 'missing subdomain'
    saved.duplexes[0].right.overhang_id = 'missing overhang'
    result = assess_references(saved)
    assert result['status'] == 'invalid'
    assert len(result['issues']) == 2
    assert all(e['code'] == 'missing_reference' for e in result['issues'])


def test_cancellation_and_identity_size_bound():
    gears()
    original = assembly_state.get_or_404().model_copy(deep=True)
    def cancelled():
        raise InterruptedError('cancel')
    with pytest.raises(InterruptedError):
        assess_references(original, checkpoint=cancelled)
    original.instances[0].id = 'x' * 513
    assert assess_references(original)['issues'][0]['code'] == 'invalid_identity'


def test_rider_connector_and_protein_attachment_references():
    from backend.core.models import ProteinAsset, ProteinAttachment, ProteinTargetAssembly
    gears()
    cargo = add_empty_part('Cargo')
    saved = assembly_state.get_or_404().model_copy(deep=True)
    asset = ProteinAsset()
    saved.protein_assets = [asset]
    saved.protein_attachments = [ProteinAttachment(asset_id=asset.id, target=ProteinTargetAssembly(instance_id=cargo))]
    assert assess_references(saved)['status'] == 'valid'
    saved.protein_attachments[0].target.interface_label = 'Missing connector'
    assert assess_references(saved)['issues'][0]['code'] == 'missing_reference'
    saved.protein_attachments[0].asset_id = 'Missing protein'
    assert len(assess_references(saved)['issues']) == 2


def test_cluster_overrides_and_internal_joint_selections_are_source_qualified():
    from tests.test_assembly_history_verification import recorded
    saved = recorded()
    instance = saved.instances[0]
    override = instance.source.design.cluster_transforms[0].model_copy(deep=True)
    instance.cluster_transform_overrides = [override]
    assert assess_references(saved)['status'] == 'valid'
    override.id = 'missing cluster'
    instance.joint_states = {'missing internal joint': 0.1}
    report = assess_references(saved)
    assert report['status'] == 'invalid'
    assert len(report['issues']) == 2


def test_missing_pinned_revision_is_incomplete_without_reading_disk(monkeypatch):
    from backend.core.models import PartSourceFile
    gears()
    saved = assembly_state.get_or_404().model_copy(deep=True)
    saved.instances[0].source = PartSourceFile(path='/not-readable.nadoc')
    saved.joints[0].cluster_id_b = 'requires source resolution'
    from pathlib import Path
    monkeypatch.setattr(Path, 'read_text', lambda *a, **k: pytest.fail('External file read'))
    report = assess_references(saved)
    assert report['status'] == 'incomplete'
    assert report['limit'] == 'unpinned_source_reference_check'

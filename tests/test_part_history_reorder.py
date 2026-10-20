"""Native reordering resolves dependencies and proves the proposed recipe."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api.part_evaluation import EvaluationRequest, evaluate
from backend.api.part_history_reorder import prepare_reorder
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import ClusterRigidTransform, Design, MinorMutationLogEntry, RoutingClusterLogEntry
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import import_root


def native_source():
    source = Design(cluster_transforms=[ClusterRigidTransform(id=i) for i in ['a', 'b', 'c']])
    source.recipe_root = import_root(source)
    log = []
    for identity in ['a', 'b', 'c']:
        params = {'joint_id': identity, 'cluster_id': identity, 'local_axis_origin': [0, 0, 0],
                  'local_axis_direction': [0, 0, 1], '_proof_version': 1}
        source = execute('joint-place', source, params)
        log.append(RoutingClusterLogEntry(id=identity, children=[MinorMutationLogEntry(
            id=identity + '-child', op_subtype='joint-place', label=identity, params=params)]))
    source.feature_log = log
    return source


def test_native_independent_rows_move_with_children_recovery_and_cold_replay():
    source = native_source()
    before = source.model_dump()
    candidate, _ = prepare_reorder(source, 0, 2, executor=execute, dependency_resolver=dependencies)
    assert [e.id for e in candidate.feature_log] == ['b', 'c', 'a']
    assert [e.children[0].id for e in candidate.feature_log] == ['b-child', 'c-child', 'a-child']
    assert source.model_dump() == before
    from backend.api import state
    restored = state.decode_design_snapshot(candidate.feature_log[-1].post_state_gz_b64)
    assert restored.cluster_joints == candidate.cluster_joints
    reopened = Design.model_validate_json(candidate.model_dump_json())
    assert assess_part_history(reopened, execute=execute, dependencies=dependencies)['status'] == 'reproduced_import'


def test_evaluator_dispatch_and_rollback_refusal():
    source = native_source()
    operation = {'header': {}, 'request': {'operation': 'reorder', 'index': 2, 'destination': 0,
                                          'expected_revision': 1}}
    result = evaluate(source, operation)
    assert result['status'] == 'ready', result
    assert [e['id'] for e in result['candidate']['feature_log']] == ['c', 'a', 'b']
    source.feature_log_cursor = 0
    result = evaluate(source, operation)
    assert result['status'] == 'failed'
    assert 'end of history' in result['issues'][0]['detail']


@pytest.mark.parametrize('extra', [{'expected_revision': None}, {'destination': True}, {'cascade': True},
                                  {'sub_index': 0}, {'params': {}}, {'kind': 'sweep'}])
def test_request_requires_exact_revision_and_whole_row_move(extra):
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({'operation': 'reorder', 'index': 0, 'destination': 1,
                                           'expected_revision': 1, **extra})


@pytest.mark.parametrize('outcome', ['commit', 'cancel', 'stale'])
def test_reorder_uses_existing_atomic_job_publication(monkeypatch, outcome):
    from backend.api import part_evaluation_jobs as jobs, state
    from backend.api.doc_context import set_current_doc, reset_current_doc

    class Worker:
        def __init__(self, source, operation):
            self.source, self.operation = source, operation
        def start(self):
            pass
        def wait(self, timeout):
            return True
        def result(self):
            return evaluate(self.source, self.operation)
        def close(self):
            pass

    monkeypatch.setattr(jobs, 'EvaluationWorker', Worker)
    monkeypatch.setattr(jobs, '_submit', jobs._run)
    token = set_current_doc('history-reorder-test')
    identity = None
    try:
        state.load_design(native_source())
        original, revision = state.get_design_with_revision()
        depth = state.undo_depth()
        identity = jobs.start({'operation': 'reorder', 'index': 0, 'destination': 2,
                               'expected_revision': revision})['job_id']
        assert jobs.inspect(identity)['result']['status'] == 'ready'
        assert state.get_design_with_revision() == (original, revision)
        assert state.undo_depth() == depth
        if outcome == 'cancel':
            jobs.inspect(identity, cancel=True)
        elif outcome == 'stale':
            state.set_design(original.model_copy(update={'name': 'Changed after evaluation'}))
        if outcome != 'commit':
            current = state.get_design_with_revision()
            with pytest.raises(HTTPException):
                jobs.commit(identity)
            assert state.get_design_with_revision() == current
            return
        receipt = jobs.commit(identity)
        assert state.undo_depth() == depth + 1
        assert [e.id for e in state.get_or_404().feature_log] == ['b', 'c', 'a']
        assert jobs.commit(identity)['revision'] == receipt['revision']
        assert state.undo_depth() == depth + 1
        state.undo()
        assert [e.id for e in state.get_or_404().feature_log] == ['a', 'b', 'c']
        state.redo()
        assert [e.id for e in state.get_or_404().feature_log] == ['b', 'c', 'a']
    finally:
        if identity:
            with jobs._lock:
                jobs._jobs.pop(identity, None)
        state.close_session()
        reset_current_doc(token)


def scoped_deformation_source(left_kind='bend', right_kind='twist'):
    from uuid import uuid4
    from tests.test_part_deformation_preview import _append
    from backend.api.crud import BundleRequest
    from backend.core.part_history_contract import create_empty_part
    from backend.core.models import ClusterCreateLogEntry, DeformationLogEntry, DeformationOp, SnapshotLogEntry
    source = create_empty_part('__e2e__scoped-order', 'HONEYCOMB')
    params = BundleRequest(cells=[[0, 0], [0, 1], [0, 2]], length_bp=42,
                           history_seed=uuid4()).model_dump(mode='json')
    source = _append(source, SnapshotLogEntry(op_kind='bundle-create', label='Bundle',
                     params={**params, '_proof_version': 1}))
    clusters = []
    for helix in source.helices[:2]:
        cluster = ClusterRigidTransform(id=str(uuid4()), name='Arm', helix_ids=[helix.id])
        source = _append(source, ClusterCreateLogEntry(cluster_id=cluster.id, name=cluster.name,
            helix_ids=cluster.helix_ids, cluster_snapshot=cluster, proof_version=1))
        clusters.append(cluster.id)
    for index, kind in enumerate([left_kind, right_kind]):
        identity = 'edited-feature' if index == 0 else 'right-feature'
        op = DeformationOp(id=identity + '-operation', type=kind, plane_a_bp=4, plane_b_bp=32,
            affected_helix_ids=[source.helices[index].id], cluster_ids=[clusters[index]],
            params={'kind': kind, **({'curvature_deg_per_bp': -.2, 'direction_deg': 35}
                                   if kind == 'bend' else {'total_degrees': -14})})
        source = _append(source, DeformationLogEntry(id=identity, deformation_id=op.id,
            op_snapshot=op, proof_version=1))
    return source


@pytest.mark.parametrize('left_kind,right_kind', [('bend', 'twist'), ('twist', 'bend'), ('bend', 'bend'), ('twist', 'twist')])
def test_independent_native_deformations_move_without_geometry_change(left_kind, right_kind):
    source = scoped_deformation_source(left_kind, right_kind)
    before = source.model_dump()
    index = len(source.feature_log) - 2
    candidate, _ = prepare_reorder(source, index, index + 1, executor=execute, dependency_resolver=dependencies)
    assert [e.id for e in candidate.feature_log[-2:]] == ['right-feature', 'edited-feature']
    assert ordered_display(candidate) == ordered_display(source)
    assert assess_part_history(candidate, execute=execute, dependencies=dependencies)['status'] == 'verified'
    assert source.model_dump() == before
    restored, _ = prepare_reorder(candidate, index + 1, index, executor=execute, dependency_resolver=dependencies)
    assert [e.id for e in restored.feature_log] == [e.id for e in source.feature_log]
    assert ordered_display(restored) == ordered_display(source)


def ordered_display(source):
    from backend.core.part_dna_comparison import project_for_deformation_preview
    display = project_for_deformation_preview(source)
    # The requested feature ordering is metadata; compare every geometry byte,
    # axis, strand/domain record and deformation definition independently of it.
    display['display_topology']['deformations'].sort(key=lambda op: op['id'])
    return display


def scoped_sweep_source():
    from uuid import uuid4
    from backend.core.sweep import SweepRequest
    from backend.core.models import SnapshotLogEntry
    from tests.test_part_deformation_preview import _append
    source = scoped_deformation_source()
    params = SweepRequest(sweep_id=str(uuid4()), cells=[source.helices[0].grid_pos],
        source_helix_id=source.helices[0].id, source_end='end',
        points_nm=[(0, 0, 0), (0, 0, 4)], ligate_adjacent=False).model_dump(mode='json')
    return _append(source, SnapshotLogEntry(id='downstream-sweep', op_kind='sweep', label='Attached Sweep',
        params={**params, '_proof_version': 1}))


def test_scoped_deformation_reorder_regenerates_downstream_sweep():
    source = scoped_sweep_source()
    index = len(source.feature_log) - 3
    candidate, _ = prepare_reorder(source, index, index + 1, executor=execute, dependency_resolver=dependencies)
    assert candidate.feature_log[-1].id == source.feature_log[-1].id
    assert candidate.feature_log[-1].params == source.feature_log[-1].params
    assert ordered_display(candidate) == ordered_display(source)
    reopened = Design.model_validate_json(candidate.model_dump_json())
    assert assess_part_history(reopened, execute=execute, dependencies=dependencies)['status'] == 'verified'


@pytest.mark.parametrize('producer_first', [True, False])
def test_move_refuses_an_actual_missing_producer_and_names_the_failing_child(producer_first):
    source = native_source()
    params = {'joint_id': 'a', 'name': 'Updated', '_proof_version': 1}
    source = execute('joint-update', source, params)
    source.feature_log.append(RoutingClusterLogEntry(id='update-row', children=[
        MinorMutationLogEntry(id='update-child', op_subtype='joint-update', label='Update joint', params=params)]))
    before = source.model_dump()
    with pytest.raises(HTTPException) as error:
        prepare_reorder(source, 0 if producer_first else 3, 3 if producer_first else 0,
                        executor=execute, dependency_resolver=dependencies)
    assert error.value.detail['feature_id'] == 'update-child'
    assert 'Update joint cannot regenerate' in error.value.detail['detail']
    assert source.model_dump() == before


def test_shared_resources_do_not_forbid_a_valid_parametric_reorder():
    source = native_source()
    for identity, name in [('first-update', 'First'), ('second-update', 'Second')]:
        params = {'joint_id': 'a', 'name': name, '_proof_version': 1}
        source = execute('joint-update', source, params)
        source.feature_log.append(RoutingClusterLogEntry(id=identity, children=[
            MinorMutationLogEntry(id=identity + '-child', op_subtype='joint-update', label=name, params=params)]))
    candidate, _ = prepare_reorder(source, 3, 4, executor=execute, dependency_resolver=dependencies)
    assert next(joint for joint in candidate.cluster_joints if joint.id == 'a').name == 'First'
    assert next(joint for joint in source.cluster_joints if joint.id == 'a').name == 'Second'
    assert assess_part_history(candidate, execute=execute, dependencies=dependencies)['status'] == 'reproduced_import'


@pytest.mark.parametrize('mode', ['independent', 'end'])
def test_sweep_and_extrude_reorder_through_native_replay(mode):
    from tests.sweep_history_fixture import fixture
    source = fixture(mode)
    candidate, _ = prepare_reorder(source, 1, 2, executor=execute, dependency_resolver=dependencies)
    assert [row.id for row in candidate.feature_log] == ['bundle', 'later-extrusion', 'selected-sweep']
    assert assess_part_history(candidate, execute=execute, dependencies=dependencies)['status'] == 'verified'
    assert {helix.id for helix in candidate.helices} == {helix.id for helix in source.helices}
    assert {strand.id for strand in candidate.strands} == {strand.id for strand in source.strands}


@pytest.mark.parametrize('index,destination', [(0, 1), (1, 0)])
def test_initial_bundle_cannot_erase_an_earlier_feature_during_reorder(index, destination):
    from tests.sweep_history_fixture import fixture
    source = fixture('independent')
    before = source.model_dump()
    with pytest.raises(HTTPException) as error:
        prepare_reorder(source, index, destination, executor=execute, dependency_resolver=dependencies)
    assert error.value.detail['code'] == 'history_root_order'
    assert source.model_dump() == before


def test_valid_feature_reorder_can_change_geometry():
    from backend.core.design_geometry import _geometry_for_design
    source = scoped_sweep_source()
    candidate, _ = prepare_reorder(source, len(source.feature_log) - 1, len(source.feature_log) - 3,
                                   executor=execute, dependency_resolver=dependencies)
    assert _geometry_for_design(candidate) != _geometry_for_design(source)
    assert assess_part_history(candidate, execute=execute, dependencies=dependencies)['status'] == 'verified'


def test_extrude_cannot_move_after_the_sweep_that_reads_its_new_helix():
    from uuid import uuid4
    from backend.core.sweep import SweepRequest
    from tests.sweep_history_fixture import fixture
    from tests.test_part_sweep_preview import snapshot
    source = fixture('independent')
    created = next(helix for helix in source.helices if tuple(helix.grid_pos) == (8, 8))
    source = snapshot(source, 'sweep', SweepRequest(sweep_id=str(uuid4()), cells=[[8, 8]],
        source_helix_id=created.id, source_end='end', points_nm=[[0, 0, 0], [0, 0, 4]],
        ligate_adjacent=False).model_dump(mode='json'), 'dependent-sweep')
    before = source.model_dump()
    with pytest.raises(HTTPException) as error:
        prepare_reorder(source, 2, 3, executor=execute, dependency_resolver=dependencies)
    assert error.value.detail['feature_id'] == 'dependent-sweep'
    assert 'cannot regenerate' in error.value.detail['detail']
    assert source.model_dump() == before


def test_reorder_refuses_invalid_intermediate_state_even_if_the_final_state_repairs_it():
    source = native_source()
    before = source.model_dump()

    def transiently_invalid(kind, current, params):
        from backend.core.lattice_frame_model import LatticeFrame
        if params.get('joint_id') == 'c':
            current = current.model_copy(update={'lattice_frames': []})
        result = execute(kind, current, params)
        if params.get('joint_id') == 'b' and not current.cluster_joints:
            result = result.model_copy(update={'lattice_frames': [
                LatticeFrame(id='temporary-frame', placement_cluster_id='missing')]})
        return result

    with pytest.raises(HTTPException) as error:
        prepare_reorder(source, 0, 2, executor=transiently_invalid, dependency_resolver=dependencies)
    assert error.value.detail['code'] == 'recipe_not_reproducible'
    assert error.value.detail['assessment']['status'] == 'failed'
    assert source.model_dump() == before

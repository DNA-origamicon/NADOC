"""Global rigid kinematics: closure, fixed reference, slack and failure."""
import json

import numpy as np
import pytest
from fastapi import Response, HTTPException

from backend.core.flexible_network import solve_network


def body(size=1):
    return dict(size=size, pivot=[0, 0, 0], translation=[0, 0, 0], rotation=[0, 0, 0, 1])


def edge(identity, a, b, pa, pb, contour=1):
    return dict(id=identity, a=a, b=b, pa=pa, pb=pb, contour=contour)


def test_closed_chain_rotates_and_satisfies_every_edge_with_largest_fixed():
    bodies = {k: body(10 if k == 'root' else 1) for k in ('root', 'a', 'b')}
    edges = [
        edge('1', 'root', 'a', [0, 0, 0], [5, 0, 0]),
        edge('2', 'a', 'b', [5, 4, 0], [8, 0, 0]),
        edge('3', 'b', 'root', [8, 4, 0], [4, 0, 0]),
    ]
    result = solve_network(bodies, edges)
    assert result['converged']
    assert result['fixed_cluster_ids'] == ['root']
    assert {t['cluster_id'] for t in result['transforms']} == {'a', 'b'}
    assert all(c['length_nm'] <= 1.001 for c in result['connections'])
    assert any(np.linalg.norm(t['rotation'][:3]) > .1 for t in result['transforms'])
    reverse = solve_network(dict(reversed(list(bodies.items()))), list(reversed(edges)))
    assert reverse == result


def test_slack_is_free_and_noop_has_no_transforms():
    result = solve_network({'a': body(10), 'b': body()},
                           [edge('slack', 'a', 'b', [0, 0, 0], [.2, 0, 0])])
    assert result['converged']
    assert result['transforms'] == []
    assert result['connections'][0]['length_nm'] == .2


def test_disconnected_components_pin_largest_in_each():
    result = solve_network({'a': body(10), 'b': body(), 'c': body(), 'd': body(20)},
                           [edge('1', 'a', 'b', [0, 0, 0], [4, 0, 0]),
                            edge('2', 'c', 'd', [0, 0, 0], [4, 0, 0])])
    assert result['converged']
    assert result['fixed_cluster_ids'] == ['a', 'd']


def test_infeasible_rigid_lengths_report_all_final_residuals():
    result = solve_network({'root': body(10), 'a': body()},
                           [edge('1', 'root', 'a', [-5, 0, 0], [0, 0, 0]),
                            edge('2', 'root', 'a', [5, 0, 0], [0, 0, 0])])
    assert not result['converged']
    assert result['max_excess_nm'] >= 4
    assert len(result['connections']) == 2


def test_invalid_anchor_fails_instead_of_silently_skipping():
    with pytest.raises(ValueError, match='finite'):
        solve_network({'a': body(), 'b': body()},
                      [edge('bad', 'a', 'b', [float('nan'), 0, 0], [0, 0, 0])])


def test_contacts_relax_even_when_tethers_are_slack_and_root_stays_fixed():
    capsules = [dict(id=k, owner=k, p=[x, 0, 0], q=[x, 0, 2])
                for k, x in [('root', 0), ('arm', .8)]]
    result = solve_network({'root': body(10), 'arm': body()},
                           [edge('1', 'root', 'arm', [0, 0, 1], [.8, 0, 1], 4)], capsules=capsules)
    assert result['converged']
    assert result['initial_contacts']['overlap_count'] == 1
    assert result['contacts']['max_penetration_nm'] <= .001
    assert result['max_excess_nm'] <= .001
    assert [t['cluster_id'] for t in result['transforms']] == ['arm']


def test_impossible_contacts_do_not_report_tether_only_success():
    capsules = [dict(id=k, owner=k, p=[x, 0, 0], q=[x, 0, 0])
                for k, x in [('root', 0), ('arm', .1)]]
    result = solve_network({'root': body(10), 'arm': body()},
                           [edge('1', 'root', 'arm', [0, 0, 0], [.1, 0, 0], .2)], capsules=capsules)
    assert not result['converged']
    assert result['max_excess_nm'] > .001 or result['contacts']['max_penetration_nm'] > .001


def test_recorded_network_relax_reopens_replays_undoes(tmp_path, monkeypatch):
    from backend.api import state
    from backend.api.doc_context import set_current_doc, reset_current_doc
    from backend.api.crud import ScadnanoImportRequest, import_scadnano_design
    from backend.api.routes_flexible_segments import (
        FlexibleSegmentBatchBody, batch_flexible_segment, FlexibleRelaxBody, flexible_relax,
    )
    from backend.core.models import Design
    from tests.test_short_flexible_import import short_hinge_source
    from scripts.agent_structure_guard import audit, publish

    token = set_current_doc('network-relax-test')
    try:
        import_scadnano_design(ScadnanoImportRequest(content=json.dumps(short_hinge_source())))
        scaffold = next(s for s in state.get_or_404().strands if s.is_scaffold)
        marks = [dict(strand_id=scaffold.id, domain_index=i, bp_index=7,
                      direction=d.direction.value) for i, d in enumerate(scaffold.domains)]
        batch_flexible_segment(FlexibleSegmentBatchBody(marks=marks), Response())
        before = state.get_or_404().model_copy(deep=True)
        depth = state.undo_depth()
        response = flexible_relax(FlexibleRelaxBody(scope='all'))
        result = response['relaxation']
        assert result['converged']
        assert result['solver'] == 'rigid-flex-staged-contact-v1'
        assert result['contacts']['max_penetration_nm'] <= .001
        assert result['transforms']
        after = state.get_or_404()
        assert after.strands == before.strands
        assert after.flexible_segment_marks == before.flexible_segment_marks
        fixed = set(result['fixed_cluster_ids'])
        assert [c for c in before.cluster_transforms if c.id in fixed] == [
            c for c in after.cluster_transforms if c.id in fixed]
        assert len(after.feature_log) == len(before.feature_log) + 1
        assert state.undo_depth() == depth + 1
        assert after.feature_log[-1].params['relaxation']['fixed_cluster_ids'] == result['fixed_cluster_ids']
        publish(after, tmp_path / 'network.nadoc')
        audit(Design.from_json((tmp_path / 'network.nadoc').read_text()))
        state.undo()
        assert state.get_or_404().cluster_transforms == before.cluster_transforms
        state.redo()
        assert state.get_or_404().cluster_transforms == after.cluster_transforms
        assert flexible_relax(FlexibleRelaxBody(scope='all'))['unchanged']
        assert len(state.get_or_404().feature_log) == len(after.feature_log)
        with pytest.raises(HTTPException):
            flexible_relax(FlexibleRelaxBody(scope='one', conn_id='missing'))
        assert state.get_or_404().cluster_transforms == after.cluster_transforms
        # Both solver nonconvergence and a falsely optimistic pose report must
        # fail atomically (including revision and undo), before any publication.
        import copy
        from backend.core import flexible_network
        frozen = state.get_or_404().model_dump_json()
        revision, depth = state.revision(), state.undo_depth()
        for converged in (False, True):
            bad = copy.deepcopy(result)
            bad['converged'] = converged
            bad['max_excess_nm'] = 10.
            bad['transforms'][0]['translation'][0] += 100.
            with monkeypatch.context() as patch:
                patch.setattr(flexible_network, 'solve_design_network', lambda *a, **kw: bad)
                with pytest.raises(HTTPException):
                    flexible_relax(FlexibleRelaxBody(scope='all'))
            assert state.get_or_404().model_dump_json() == frozen
            assert (state.revision(), state.undo_depth()) == (revision, depth)
        # A successful predicted clearance must not bypass the native geometry
        # check at commit. Inject an intersecting measured duplex pair only.
        from backend.core import flexible_contacts
        bad = copy.deepcopy(result)
        ids = list(result['cluster_sizes'])
        with monkeypatch.context() as patch:
            patch.setattr(flexible_network, 'solve_design_network', lambda *a, **kw: bad)
            patch.setattr(flexible_contacts, 'design_capsules', lambda *a, **kw: [
                dict(id=k, owner=k, p=[0, 0, 0], q=[0, 0, 1]) for k in ids[:2]])
            with pytest.raises(HTTPException, match='overlap'):
                flexible_relax(FlexibleRelaxBody(scope='all'))
        assert state.get_or_404().model_dump_json() == frozen
        assert (state.revision(), state.undo_depth()) == (revision, depth)

    finally:
        (tmp_path / 'network.nadoc').unlink(missing_ok=True)
        state.close_session()
        reset_current_doc(token)


def test_local_jj_hinge_numeric_regression_is_read_only():
    """Optional local evidence; never author a derivative of this legacy file."""
    import hashlib
    from pathlib import Path
    from backend.core.models import Design
    from backend.core.flexible_network import solve_design_network

    path = Path('workspace/Assembly Tests/JJ_Hinge_AuNP_stacked_poly_FINAL_with_fluors.nadoc')
    if not path.exists():
        pytest.skip('Local JJ_Hinge diagnostic source unavailable')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != '124d17dcb985ae9ec6aba26ac0657e190e33f94c2cd0b4c2836c800cc5ebf0a5':
        pytest.skip('Local JJ_Hinge source has changed since this regression')
    design = Design.model_validate_json(raw)
    if len(design.flexible_connections) != 11:
        pytest.skip('User has edited the local diagnostic source')
    result = solve_design_network(design)
    assert result['converged']
    assert len(result['connections']) == 11
    assert result['max_excess_nm'] < .001
    assert not set(result['fixed_cluster_ids']) & {t['cluster_id'] for t in result['transforms']}
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(raw).digest()


def test_absolute_pose_composition_with_existing_rotation_and_offset_pivot():
    from scipy.spatial.transform import Rotation

    bodies = {'root': body(10), 'arm': {
        'size': 1, 'pivot': [11, -3, 8], 'translation': [4, 7, 1],
        'rotation': Rotation.from_rotvec([.4, -.3, .2]).as_quat().tolist(),
    }}
    edges = [edge('1', 'root', 'arm', [0, 0, 0], [5, 0, 0]),
             edge('2', 'root', 'arm', [0, 4, 0], [9, 0, 0])]
    result = solve_network(bodies, edges)
    assert result['converged']
    old, new = bodies['arm'], result['transforms'][0]
    old_r, new_r = Rotation.from_quat(old['rotation']), Rotation.from_quat(new['rotation'])
    for e in edges:
        local = old_r.inv().apply(np.array(e['pb']) - old['pivot'] - np.array(old['translation']))
        world = new_r.apply(local) + new['pivot'] + np.array(new['translation'])
        assert np.linalg.norm(world - e['pa']) <= e['contour'] + .001

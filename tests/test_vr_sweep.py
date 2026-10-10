"""The native draft and acknowledgement share desktop Sweep history authority."""
import json
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api.routes_vr import (
    _parse_tool_config, _event_payload, _write_preflight_feedback,
    _write_tool_execution_feedback, VRToolPreflightFeedbackRequest, VRToolExecutionFeedbackRequest,
)


def draft():
    return dict(mode='sweep', target_kind='none', target_identity=None, target_owner_tokens=[],
                painted_footprint={'lattice_type': 'HONEYCOMB', 'cells': [[0, 0], [0, 1]]},
                points_nm=[[0, 0, 0], [0, 0, 10], [5, 3, 18]], extrude_from='XY',
                strand_filter='both', ligate_adjacent=True)


def test_sweep_survives_event_transport_and_binds_action_time_config(tmp_path):
    raw = draft()
    parsed = _parse_tool_config(raw, 8)
    assert parsed == raw
    raw['points_nm'][1][2] = 123
    assert parsed['points_nm'][1] == [0, 0, 10]
    path = tmp_path / 'event.json'
    path.write_text(json.dumps(dict(sequence=12, tool_sequence=3, tool_mode='sweep', tool_action='confirm',
        tool_config_sequence=8, tool_action_config_sequence=8, tool_config=parsed)))
    event = _event_payload({'event_path': str(path)})
    assert event['tool_mode'] == 'sweep'
    assert event['tool_config'] == parsed
    assert event['tool_action_config_sequence'] == 8


@pytest.mark.parametrize('changes', [
    {'points_nm': [[0, 0, 0], [float('nan'), 0, 1]]},
    {'points_nm': [[0, 0, 0], [True, 0, 1]]}, {'points_nm': [[0, 0, 0], [10001, 0, 0]]},
    {'points_nm': [[0, 0, 0]] * 257}, {'freeform_placement': {}}, {'source_helix_id': 'helix:1'},
    {'painted_footprint': {'lattice_type': 'HONEYCOMB', 'cells': [[10001, 0]]}},
    {'target_kind': 'end', 'target_identity': 'nuc:end', 'target_owner_tokens': ['owner:1']},
])
def test_unbounded_or_unsupported_sweep_is_rejected(changes):
    with pytest.raises(ValueError):
        _parse_tool_config({**draft(), **changes}, 1)


def test_incomplete_draft_is_transportable_during_painting_and_free_draw():
    for points in [[], [[0, 0, 0]]]:
        raw = {**draft(), 'points_nm': points, 'painted_footprint': {'lattice_type': 'SQUARE', 'cells': []}}
        assert _parse_tool_config(raw, 1) == raw


def test_sweep_preflight_and_execution_use_existing_feedback_protocol(tmp_path):
    preflight_path, execution_path = tmp_path / 'preflight', tmp_path / 'execution'
    session = {'preflight_feedback_path': str(preflight_path), 'tool_execution_feedback_path': str(execution_path)}
    preflight = VRToolPreflightFeedbackRequest(preflight_sequence=1, tool_config_sequence=8,
        tool_mode='sweep', target_kind='none', status='ok', reason='validated')
    assert _write_preflight_feedback(session, preflight) == (True, 1)
    assert 'sweep none - validated' in preflight_path.read_text()
    execution = VRToolExecutionFeedbackRequest(execution_sequence=1, tool_sequence=3,
        tool_mode='sweep', tool_action='confirm', target_kind='none', status='succeeded',
        reason='committed', feature_log_entry_id='sweep:1')
    assert _write_tool_execution_feedback(session, execution) == (True, 1)
    assert 'sweep confirm none - succeeded committed sweep:1' in execution_path.read_text()
    assert _write_tool_execution_feedback(session, execution) == (False, 1)


def test_native_sweep_s_curve_can_be_edited_in_desktop_history_and_undo_redone():
    import numpy as np
    from backend.api import state
    from backend.core.models import Design
    from backend.core.deformation import deformed_helix_axes
    state.set_design(Design())
    before, revision = state.copy_for_persist()
    client = TestClient(app)
    # Exercise the actual native draft validator before the same request mapping
    # used by buildVRSweepPlan. The fitted stroke remains ordinary Sweep points.
    raw = draft()
    raw['points_nm'] = [[2, -1, 1], [5, 1, 5], [0, 2, 10], [-5, 1, 15], [0, 0, 20]]
    native = _parse_tool_config(raw, 8)
    request = dict(cells=native['painted_footprint']['cells'], points_nm=native['points_nm'],
                   plane=native['extrude_from'], strand_filter=native['strand_filter'],
                   ligate_adjacent=native['ligate_adjacent'],
                   expected_design_id=before.id, expected_revision=revision)
    preview = client.post('/api/design/sweep/preview?include_geometry=false', json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()['revision'] == revision
    assert 'helix_paths_nm' not in preview.json()
    assert not state.get_or_404().feature_log
    response = client.post('/api/design/sweep', json=request)
    assert response.status_code == 201, response.text
    committed = state.get_or_404()
    entry = committed.feature_log[0]
    assert len(committed.feature_log) == 1 and entry.op_kind == 'sweep'
    assert entry.params['points_nm'] == native['points_nm']
    assert entry.design_snapshot_gz_b64 and entry.post_state_gz_b64
    assert response.json()['vr_transaction'] == {
        'feature_log_entry_id': entry.id, 'target_count': 2,
    }

    def geometry(design):
        return [axis['samples'] for axis in deformed_helix_axes(design)]

    original_geometry = geometry(committed)
    original_ids = [h.id for h in committed.helices]
    # Rehydrate the persisted .nadoc model (including compressed feature
    # snapshots) before opening the editor, without inventing another mutation.
    state.set_design_silent(Design.model_validate_json(committed.model_dump_json()))
    changed_points = [list(p) for p in entry.params['points_nm']]
    changed_points[0][0] += 3
    changed_points[2][0] += 3
    changed = {**entry.params, 'points_nm': changed_points}
    # Desktop preview must remain read-only and restore the saved feature's
    # pre-state so editing does not duplicate the swept lattice.
    changed['expected_revision'] = state.copy_for_persist()[1]
    saved = state.get_or_404().model_dump_json()
    preview = client.post('/api/design/sweep/preview?feature_index=0', json=changed)
    assert preview.status_code == 200, preview.text
    assert state.get_or_404().model_dump_json() == saved
    response = client.post('/api/design/features/0/edit', json={'params': changed})
    assert response.status_code == 200, response.text
    edited = state.get_or_404()
    assert len(edited.feature_log) == 1
    assert edited.feature_log[0].id == entry.id
    assert edited.feature_log[0].params['points_nm'] == changed_points
    assert edited.feature_log[0].params['sweep_id'] == entry.params['sweep_id']
    assert [h.id for h in edited.helices] == original_ids
    assert len(edited.deformations) == 1
    assert edited.deformations[0].params.points_nm[2] == tuple(changed_points[2])
    edited_geometry = geometry(edited)
    assert json.dumps(edited_geometry) != json.dumps(original_geometry)

    # Undo edit, undo creation, redo creation, redo edit: the stable feature
    # identity, persisted knots, and rendered geometry survive every boundary.
    assert client.post('/api/design/undo').status_code == 200
    undone = state.get_or_404()
    assert undone.feature_log[0].id == entry.id
    assert undone.feature_log[0].params['points_nm'] == native['points_nm']
    np.testing.assert_allclose(geometry(undone), original_geometry, atol=1e-10)
    assert client.post('/api/design/undo').status_code == 200
    assert not state.get_or_404().helices
    assert not state.get_or_404().feature_log
    assert client.post('/api/design/redo').status_code == 200
    recreated = state.get_or_404()
    assert recreated.feature_log[0].id == entry.id
    assert recreated.feature_log[0].params['points_nm'] == native['points_nm']
    np.testing.assert_allclose(geometry(recreated), original_geometry, atol=1e-10)
    assert client.post('/api/design/redo').status_code == 200
    restored = state.get_or_404()
    assert restored.feature_log[0].id == entry.id
    assert restored.feature_log[0].params['points_nm'] == changed_points
    np.testing.assert_allclose(geometry(restored), edited_geometry, atol=1e-10)


def test_sweep_orientations_survive_transport_and_warning_preview_is_sequenced(tmp_path):
    raw = {**draft(), 'orientations_deg': [None, [15,30,45], [0,90,90]]}
    assert _parse_tool_config(raw, 9)['orientations_deg'] == raw['orientations_deg']
    path = tmp_path / 'preflight'
    session = {'preflight_feedback_path': str(path)}
    body = VRToolPreflightFeedbackRequest(preflight_sequence=4,tool_config_sequence=9,
        tool_mode='sweep', target_kind='none', status='warn', reason='backend_warning',
        sweep_preview=dict(path=[[0,0,0],[0,0,10]],cloud=[[1,0,0]],bases=[[1,0,0,0,1,0,0,0,1]],warning_segments=[0]))
    assert _write_preflight_feedback(session,body) == (True,4)
    record = path.read_text()
    assert record.startswith('NADOCVR_PREFLIGHT 3 9 4 warn sweep none - backend_warning 2 1 1 1 ')
    assert _write_preflight_feedback(session,body.model_copy(update={'preflight_sequence':3})) == (False,4)
    assert path.read_text() == record
    counted = body.model_copy(update={'preflight_sequence':5, 'sweep_preview':body.sweep_preview.model_copy(update={'total_new_bp':1234})})
    assert _write_preflight_feedback(session,counted) == (True,5)
    assert path.read_text().startswith('NADOCVR_PREFLIGHT 4 ')
    assert path.read_text().rstrip().endswith(' 1234')
    with pytest.raises(ValueError):
        VRToolPreflightFeedbackRequest(**{**body.model_dump(),'sweep_preview':{'path':[],'cloud':[],'bases':[], 'warning_segments':[0]}})

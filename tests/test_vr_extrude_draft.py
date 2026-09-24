import json
import pytest
from backend.core.vr_extrude_draft import validate_painted_footprint, MAX_PAINTED_CELLS, MAX_VR_EVENT_BYTES
from backend.api.routes_vr import _parse_tool_config, _event_payload

DRAFT = {'mode': 'extrude', 'target_identity': None, 'target_kind': 'none',
         'target_owner_tokens': [], 'length_bp': 21, 'direction_sign': 1,
         'strand_filter': 'both', 'ligate_adjacent': False, 'footprint_state': 'unresolved',
         'extrude_from': 'XY'}


def test_cells_survive_transport_without_claiming_commit_readiness(tmp_path):
    footprint = {'lattice_type': 'HONEYCOMB', 'cells': [[-1, 2], [0, 0], [1, -2]]}
    result = _parse_tool_config({**DRAFT, 'painted_footprint': footprint}, 1)
    assert result['painted_footprint'] == footprint
    assert result['footprint_state'] == 'unresolved'
    footprint['cells'][0][0] = 99
    assert result['painted_footprint']['cells'][0] == [-1, 2]
    # More than the old 4KB event limit, but within the native draft capacity.
    large = {'lattice_type': 'SQUARE', 'cells': [[i, -i] for i in range(MAX_PAINTED_CELLS)]}
    raw = {'sequence': 1, 'tool_config_sequence': 1,
           'tool_config': {**DRAFT, 'painted_footprint': large}}
    text = json.dumps(raw)
    assert 4096 < len(text) < MAX_VR_EVENT_BYTES
    path = tmp_path/'event.json'; path.write_text(text)
    assert _event_payload({'event_path': str(path)})['tool_config']['painted_footprint'] == large


@pytest.mark.parametrize('cells', [[[0, 0], [0, 0]], [[True, 0]], [[.5, 0]], [[0, 100001]],
                                 [[0]], [[float('nan'), 0]], [[0, 0]]*(MAX_PAINTED_CELLS+1)])
def test_invalid_cells_rejected(cells):
    with pytest.raises(ValueError):
        validate_painted_footprint({'lattice_type': 'HONEYCOMB', 'cells': cells})


def test_empty_selection_is_valid_but_unknown_lattice_is_not():
    assert validate_painted_footprint({'lattice_type': 'SQUARE', 'cells': []})['cells'] == []
    with pytest.raises(ValueError):
        validate_painted_footprint({'lattice_type': 'FREEFORM', 'cells': []})


def test_event_size_limit_rejects_otherwise_valid_json(tmp_path):
    path = tmp_path/'event.json'
    raw = {'sequence': 123, 'tool_config_sequence': 1, 'tool_config': DRAFT}
    text = json.dumps(raw)
    path.write_text(text)
    assert _event_payload({'event_path': str(path)})['sequence'] == 123
    path.write_text(text + ' ' * MAX_VR_EVENT_BYTES)
    assert _event_payload({'event_path': str(path)})['sequence'] == 0


def test_action_keeps_click_time_config_sequence_even_after_new_paint(tmp_path):
    path = tmp_path/'event.json'
    event = {'sequence': 12, 'tool_sequence': 3, 'tool_mode': 'extrude',
             'tool_action': 'confirm', 'tool_config_sequence': 9,
             'tool_action_config_sequence': 8, 'tool_config': DRAFT}
    path.write_text(json.dumps(event))
    assert _event_payload({'event_path': str(path)})['tool_action_config_sequence'] == 8
    del event['tool_action_config_sequence']
    path.write_text(json.dumps(event))
    assert _event_payload({'event_path': str(path)})['tool_action_config_sequence'] == 0


@pytest.mark.parametrize('value', [True, -1, 10, 1.5, '8'])
def test_invalid_action_config_binding_rejected(tmp_path, value):
    path = tmp_path/'event.json'
    path.write_text(json.dumps({'sequence':12, 'tool_config_sequence':9,
        'tool_config':DRAFT, 'tool_action_config_sequence':value}))
    assert _event_payload({'event_path':str(path)})['sequence']==0


def test_targetless_execution_feedback_is_only_for_extrusion(tmp_path):
    from backend.api.routes_vr import VRToolExecutionFeedbackRequest, _write_tool_execution_feedback
    from fastapi import HTTPException
    path=tmp_path/'feedback.txt'
    body=VRToolExecutionFeedbackRequest(execution_sequence=1, tool_sequence=2,
        tool_mode='extrude',tool_action='confirm',target_kind='none',target_identity=None,
        status='succeeded',reason='committed',feature_log_entry_id='feature:3')
    assert _write_tool_execution_feedback({'tool_execution_feedback_path':str(path)},body)==(True,1)
    assert 'extrude confirm none - succeeded committed feature:3' in path.read_text()
    with pytest.raises(HTTPException):
        _write_tool_execution_feedback({'tool_execution_feedback_path':str(path)},body.model_copy(update={'tool_mode':'move_rotate','execution_sequence':2}))


def test_freeform_pose_transport_and_target_scope():
    from backend.core.vr_freeform_placement import validate_freeform_placement
    pose = {'translation_nm':[12,-4,8], 'rotation_xyzw':[0,.6,0,.8]}
    result = _parse_tool_config({**DRAFT,'freeform_placement':pose},1)
    assert result['freeform_placement'] == pose
    pose['translation_nm'][0] = 99
    assert result['freeform_placement']['translation_nm'][0] == 12
    for bad in [None, {**pose,'scale':2}, {**pose,'translation_nm':[True,0,0]},
                {**pose,'translation_nm':[float('nan'),0,0]},
                {**pose,'translation_nm':[1e7,0,0]}, {**pose,'rotation_xyzw':[0,0,0,0]}]:
        with pytest.raises(ValueError):
            validate_freeform_placement(bad)
    with pytest.raises(ValueError):
        _parse_tool_config({**DRAFT,'target_kind':'end','target_identity':'nuc:end',
                           'target_owner_tokens':['end:token'],'freeform_placement':pose},1)

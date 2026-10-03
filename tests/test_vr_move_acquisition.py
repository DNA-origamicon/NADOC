from tools.vr_workflows.move_acquisition import remote_target


def test_near_hover_cannot_end_remote_approach_early():
    state = {'move_nearby': True, 'move_beam_end': [0, 0, 0],
             'hands': [{}, {'position': [.1, 0, 0]}]}
    assert not remote_target(state)
    state['hands'][1]['position'] = [.15, 0, 0]
    assert not remote_target(state)
    state['hands'][1]['position'] = [.45, 0, 0]
    assert remote_target(state)
    state['move_nearby'] = False
    assert not remote_target(state)
    state['move_nearby'] = True
    state['move_beam_end'] = None
    assert not remote_target(state)

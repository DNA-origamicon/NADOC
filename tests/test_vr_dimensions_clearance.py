"""Dimension tour must reject menu-owned triggers and geometry collisions."""
from copy import deepcopy
from tools.vr_workflows.dimensions_check import measurement_clearance


def state():
    return {'sidebars': [{}, {'input_mode': 'pointer', 'grip_targets':
        [[0, 0, -1], [1, 0, -1], [.5, .5, -1], [.5, -.5, -1]]}],
        'hands': [{'position': [x, 0, -.8], 'orientation_xyzw': [0, 0, 0, 1],
                   'input_owner': 'dimension'} for x in (-.5, -.25)]}


def test_measurement_workspace_clear_of_whole_frame():
    assert measurement_clearance(state())['passed']
    for position in ([.5, 0, -.8], [-.05, 0, -.8]):
        bad = state()
        bad['hands'][0]['position'] = position
        assert not measurement_clearance(bad)['passed']


def test_menu_focus_and_input_ownership_are_not_measurement():
    good = state()
    for owner in ('menu', 'none', 'scene'):
        bad = deepcopy(good)
        bad['hands'][0]['input_owner'] = owner
        assert not measurement_clearance(bad)['passed']
    good['sidebars'][1]['input_mode'] = 'trackpad'
    assert not measurement_clearance(good)['passed']


def test_ray_can_hit_menu_even_when_tip_is_clear():
    bad = state()
    # Aim diagonally from the left into the panel without moving the tip into it.
    bad['hands'][0]['position'][2] = -.5
    bad['hands'][0]['orientation_xyzw'] = [0, -.5, 0, 3**.5/2]
    result = measurement_clearance(bad)
    assert result['hands'][0]['tip_left_clearance_m'] > .1
    assert result['hands'][0]['ray_hits_panel']
    assert not result['passed']


def test_pinned_line_must_remain_clear_after_model_moves():
    bad=state()
    bad['dimensions']={'selected':1,'entries':[{'id':1,'endpoints':[
        {'world':[-.4,0,-1],'valid':True},{'world':[.1,0,-1],'valid':True}]}]}
    assert not measurement_clearance(bad)['passed']

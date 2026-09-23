import pytest
from tools.vr_workflows.profile_wheel import wheel_travel


@pytest.mark.parametrize('current,target,expected',[(0,42,.025),(63,42,-.015),(42,42,0)])
def test_mid_detent_travel(current,target,expected):
    assert wheel_travel(current,target,21,.01) == pytest.approx(expected)


def test_wheel_rejects_unreachable_partial_detent():
    with pytest.raises(ValueError):
        wheel_travel(0,40,21,.01)


def test_drag_failure_releases_trigger_and_retains_acquisition(monkeypatch, tmp_path):
    import json
    from tools.vr_workflows.profile_wheel import set_wheel_length
    class Live:
        def __init__(self):
            self.state = {'extrude':{'length_bp':0,'base_pairs_per_detent':21,
                'wheel_notch_travel_m':.01,'cells':[], 'wheel_hovered':True,'wheel_dragging':False},
                'hands':[{}, {'position':[0,0,0],'orientation_xyzw':[0,0,0,1]}],
                'controls':[{'label':'EXTRUDE LENGTH WHEEL','position':[0,0,-1],
                    'hit_half_right':[.1,0,0],'hit_half_up':[0,.1,0]}]}
            self.pressed = False
        def send(self, operation, **args):
            assert operation == 'button'
            self.pressed = args['pressed']
            self.state['extrude']['wheel_dragging'] = self.pressed
        def frame(self):
            pass
    live = Live()
    monkeypatch.setattr('tools.vr_workflows.profile_wheel.reach_target', lambda *args: {'samples':[]})
    def fail(*args):
        raise TimeoutError('late playback')
    monkeypatch.setattr('tools.vr_workflows.profile_wheel.drag',fail)
    path = tmp_path/'wheel.json'
    with pytest.raises(TimeoutError):
        set_wheel_length(live,path,42,'steady_fast')
    assert not live.pressed
    assert json.loads(path.read_text())[0]['acquisition'][0]['hit']


@pytest.mark.parametrize('start,target,button',[(35,42,'+'),(49,42,'-')])
def test_fine_length_bounded_and_each_effect_recorded(start,target,button):
    from types import SimpleNamespace
    from tools.vr_workflows.profile_wheel import fine_length
    live = SimpleNamespace(state={'extrude':{'length_bp':start,'cells':[[0,0]]}})
    records, clicks = [], []
    def click(label):
        clicks.append(label)
        live.state['extrude']['length_bp'] += 1 if label == '+' else -1
    fine_length(live,target,7,click,records.append)
    assert clicks == [button]*7
    assert len(records) == 7
    assert live.state['extrude']['length_bp'] == target


def test_fine_length_rejects_large_correction_and_ineffective_click():
    from types import SimpleNamespace
    from tools.vr_workflows.profile_wheel import fine_length
    live = SimpleNamespace(state={'extrude':{'length_bp':0,'cells':[]}})
    with pytest.raises(ValueError):
        fine_length(live,42,7,lambda label: None,lambda record: None)
    with pytest.raises(RuntimeError,match='unexpected state'):
        fine_length(live,1,7,lambda label: None,lambda record: None)


def test_final_wheel_drag_can_use_fine_correction_without_fourth_drag(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from tools.vr_workflows.profile_wheel import set_wheel_length
    state = {'extrude':{'length_bp':0,'base_pairs_per_detent':7,'wheel_notch_travel_m':.01,
        'cells':[],'wheel_hovered':True,'wheel_dragging':False},
        'hands':[{}, {'position':[0,0,0],'orientation_xyzw':[0,0,0,1]}],
        'controls':[{'label':'EXTRUDE LENGTH WHEEL','position':[0,0,-1],
            'hit_half_right':[.1,0,0],'hit_half_up':[0,.1,0]}]}
    def send(operation,**args):
        state['extrude']['wheel_dragging'] = args['pressed']
    live = SimpleNamespace(state=state,send=send,frame=lambda:None)
    outcomes = iter([77,28,49])
    def drag(*args):
        state['extrude']['length_bp'] = next(outcomes)
        return []
    monkeypatch.setattr('tools.vr_workflows.profile_wheel.reach_target',lambda *args:{'samples':[]})
    monkeypatch.setattr('tools.vr_workflows.profile_wheel.drag',drag)
    clicks=[]
    def click(label):
        clicks.append(label)
        state['extrude']['length_bp'] += 1 if label=='+' else -1
    result=set_wheel_length(live,tmp_path/'trace.json',42,'variable_deliberate',fine_click=click)
    assert len(result)==4
    assert clicks==['-']*7
    assert state['extrude']['length_bp']==42

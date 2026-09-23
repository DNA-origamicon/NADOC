import json
import pytest
from tools.vr_workflows.profile_controls import ProfileControls, hover_label


class Live:
    def __init__(self):
        self.state = {'controls':[{'label':'+', 'position':[0,0,-1],
                       'hit_half_right':[.1,0,0], 'hit_half_up':[0,.1,0]}],
                      'hands':[{}, {'position':[0,0,0], 'orientation_xyzw':[0,0,0,1]}],
                      'hover':'_', 'config_sequence':1}
        self.clicks = 0
    def button(self, name):
        assert name == 'trigger'
        self.clicks += 1
        self.state['config_sequence'] += 1
    def frame(self):
        pass


def test_hover_feedback_does_not_turn_wrong_rectangle_into_hit(monkeypatch, tmp_path):
    live = Live()
    def reach(*args):
        # Stale/incorrect hover feedback must not override the geometric miss.
        live.state['hands'][1]['position'] = [1,0,0]
        return {'samples':[]}
    monkeypatch.setattr('tools.vr_workflows.profile_controls.reach_target', reach)
    path = tmp_path/'trials.json'
    with pytest.raises(RuntimeError, match='three reaches'):
        ProfileControls(live,path,'variable_fast').click('+')
    trials = json.loads(path.read_text())
    assert len(trials) == 3
    assert all(not t['clicked'] for t in trials)
    assert live.clicks == 0


def test_miss_then_acquire_retains_both_attempts(monkeypatch, tmp_path):
    live = Live()
    seeds = []
    def reach(_live, target, preset, seed):
        seeds.append(seed)
        live.state['hover'] = 'none' if len(seeds)==1 else '_'
        return {'samples':[], 'seed':seed}
    monkeypatch.setattr('tools.vr_workflows.profile_controls.reach_target', reach)
    path = tmp_path/'trials.json'
    result = ProfileControls(live,path,'steady_fast',20).click('+')
    assert seeds == [20,21]
    assert live.clicks == 1
    assert [t['clicked'] for t in json.loads(path.read_text())] == [False,True]
    assert result['metrics']['width_m'] == .2
    assert result['after_click']['config_sequence'] == 2


@pytest.mark.parametrize('label,expected',[('SIZE +','size_'),('+','_'),('-','-'),('AUTO / DRILL','auto_drill'),('BACK TO TOOLS','back_to_tools')])
def test_native_hover_label_contract(label,expected):
    assert hover_label(label) == expected


def test_framing_callback_does_not_use_semantic_activation():
    from tools.vr_motion.extrude_probe import framed_origin
    class FramingLive:
        def __init__(self):
            self.operations=[]
            self.state={'extrude':{'panel_orientation_xyzw':[0,0,0,1],'panel_position':[0,0,-1]}}
        def send(self, operation, **args):
            self.operations.append(operation)
        def frame(self):
            pass
    live=FramingLive()
    activations=[]
    framed_origin(live,{'position':[0,0,0],'orientation_xyzw':[0,0,0,1]},
                  activate=lambda:activations.append('visible UI'))
    assert activations==['visible UI','visible UI']
    assert live.operations==['pose','pose']


@pytest.mark.parametrize('owner,allowed',[('menu',False),('lattice',True)])
def test_tablet_requires_production_input_ownership(monkeypatch,tmp_path,owner,allowed):
    live=Live()
    live.state['controls'][0]['label']='LATTICE EXIT'
    live.state['hands'][1]['input_owner']=owner
    live.state['extrude']={'open':True,'cells':[[0,0]]}
    def click(name):
        live.clicks+=1
        live.state['extrude']['open']=False
    live.button=click
    monkeypatch.setattr('tools.vr_workflows.profile_controls.reach_target',lambda *args:{'samples':[]})
    driver=ProfileControls(live,tmp_path/'tablet.json','steady_fast')
    if allowed:
        driver.click('LATTICE EXIT')
        assert live.clicks==1
    else:
        with pytest.raises(RuntimeError,match='three reaches'):
            driver.click('LATTICE EXIT')
        assert live.clicks==0


def test_center_paint_must_preserve_cells(monkeypatch,tmp_path):
    live=Live()
    live.state['controls'][0]['label']='CENTER PAINT'
    live.state['hands'][1]['input_owner']='lattice'
    live.state['extrude']={'open':True,'cells':[[0,0]]}
    def wrong_action(name):
        live.state['extrude']['cells']=[]
    live.button=wrong_action
    monkeypatch.setattr('tools.vr_workflows.profile_controls.reach_target',lambda *args:{'samples':[]})
    with pytest.raises(RuntimeError,match='changed the draft'):
        ProfileControls(live,tmp_path/'tablet.json','steady_fast').click('CENTER PAINT')


def test_feedback_mode_requires_sustained_acquisition_not_only_final_hit(monkeypatch,tmp_path):
    live=Live()
    callbacks=[]
    def reach(*args,acquired):
        callbacks.append(acquired(live.state))
        return {'samples':[], 'acquired_with_feedback':False}
    monkeypatch.setattr('tools.vr_workflows.profile_controls.reach_target',reach)
    with pytest.raises(RuntimeError,match='three reaches'):
        ProfileControls(live,tmp_path/'feedback.json','variable_fast',feedback=True).click('+')
    assert callbacks==[True,True,True]
    assert live.clicks==0

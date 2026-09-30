"""Motion diagnostics keep input release and discoverability under failure."""
from types import SimpleNamespace
import pytest
from tools.vr_workflows import representation_motion
from tools.vr_workflows.tour_catalog import catalog, arguments


def test_motion_tour_uses_browser_launch_and_unchanged_validation_dispatch():
    tour=next(x for x in catalog()['tours'] if x['id']=='representation-motion')
    assert tour['module']=='browser_representation_tour'
    assert '--motion' in arguments(tour,True) and '--validate' in arguments(tour,True)


def test_failed_grip_motion_releases_button_and_retains_failure(tmp_path,monkeypatch):
    commands=[]
    live=SimpleNamespace(state=dict(sidebars=[dict(open=False),dict(open=False)],
        head_position=[0,1.6,0],presentation=dict(model_to_tracking_rows=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])),
        send=lambda op,**kw:commands.append((op,kw)), frame=lambda:None)
    def late(*args,**kwargs):raise TimeoutError('motion deadline missed')
    monkeypatch.setattr(representation_motion,'reach_target',late)
    with pytest.raises(TimeoutError):representation_motion.check(live,tmp_path/'motion','steady_fast')
    assert commands[-1]==('button',dict(hand=1,button='grip',pressed=False))
    assert 'motion deadline missed' in (tmp_path/'motion/motion.json').read_text()

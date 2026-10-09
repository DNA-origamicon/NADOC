import time
from types import SimpleNamespace
import pytest
from experiments.cpd_anti_additive import continue_cube_v11 as m


def setup(tmp_path,fail=False):
    calls=[]
    def stage(case,out,cp,first,steps,seed,stride,deadline,cores,obs):
        calls.append((cp,first,steps,seed,stride,obs));out.mkdir()
        if fail:raise RuntimeError('physical failure')
        return dict(native_and_registered_geometry_passed=True,performance=dict(native_wall_seconds=100,native_seconds_per_ns=100))
    e=SimpleNamespace(N=2,authorize=lambda:None,box_from_xsc=lambda p:([140]*3,[1080000]),physical=lambda *a:dict(passed=True),read_binary=lambda *a:None,run_stage=stage)
    p=dict(output=str(tmp_path/'continuation'),checkpoint_prefix=str(tmp_path/'checkpoint'),seed=84017,deadline_epoch=time.time()+10000,reference_segment_seconds=110,reference_native_seconds_per_ns=100,prior_audit={'path':'recorded prior audit'})
    return p,e,calls


def test_exact_eight_point_nine_ns_continuation_without_duplicate_first_two_ns(tmp_path):
    p,e,calls=setup(tmp_path);m.execute(p,e)
    assert len(calls)==9
    assert [c[1] for c in calls]==[1080000]+list(range(1530000,5530000,500000))
    assert calls[0][2]==450000
    assert all(c[2]==500000 and c[4:]==(5000,True) for c in calls[1:])
    assert calls[1][0].parent.name=='segment-02'
    a=m.read(tmp_path/'continuation/assessment.json')
    assert a['continued_ns']==8.9 and a['validation_endpoint_ns']==10 and not a['simulation_ready']
    with pytest.raises(FileExistsError):m.execute(p,e)


def test_failed_segment_stops_before_next_launch(tmp_path):
    p,e,calls=setup(tmp_path,True)
    with pytest.raises(RuntimeError):m.execute(p,e)
    assert len(calls)==1

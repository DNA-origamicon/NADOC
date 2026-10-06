from pathlib import Path
from types import SimpleNamespace
import time
import pytest
from experiments.cpd_anti_additive import gpu_cube_validation_v6 as m


def test_segment_time_admission_reserves_margin():
    m.require_segment_time(time.time()+2000,1000)
    for deadline,estimate in [(time.time()+1000,1000),(time.time()-1,1000),(time.time()+2000,0)]:
        with pytest.raises(RuntimeError):m.require_segment_time(deadline,estimate)


def engine(tmp_path,slow=False,failed=False):
    calls=[]
    def run_stage(case,out,cp,first,steps,seed,stride,deadline,cores,observables):
        calls.append((cp,first,steps,seed,stride,cores,observables));out.mkdir(parents=True)
        if failed:raise RuntimeError('Physical gate failed')
        return dict(native_and_registered_geometry_passed=True,performance=dict(native_seconds_per_ns=150 if slow else 100,native_wall_seconds=100))
    e=SimpleNamespace(ROOT=tmp_path,N=2,authorize=lambda:None,box_from_xsc=lambda p:([140]*3,[530000]),physical=lambda *a:dict(passed=True),read_binary=lambda *a:None,run_stage=run_stage)
    plan=dict(case='anti',replica=1,checkpoint_prefix=str(tmp_path/'start'),deadline_epoch=time.time()+10000,seed=44017,reference_segment_seconds=110,reference_native_seconds_per_ns=100)
    (tmp_path/'anti/replica-1').mkdir(parents=True)
    return e,plan,calls


def test_ten_segments_chain_full_restart_and_preserve_pending_readiness(tmp_path):
    e,plan,calls=engine(tmp_path);m.execute(plan,e)
    assert len(calls)==10
    for i,call in enumerate(calls):
        assert call[1:]==(530000+i*500000,500000,44117+i*100,5000,4,True)
        if i:assert call[0].parent.name==f'segment-{i:02d}'
    result=m.read(tmp_path/'anti/replica-1/validation/assessment.json')
    assert result['ns']==10 and not result['simulation_ready'] and result['physical_structural_and_performance_review_pending']
    with pytest.raises(FileExistsError):m.execute(plan,e)


@pytest.mark.parametrize('kind',['slow','failed'])
def test_failure_or_slowdown_stops_before_next_segment(tmp_path,kind):
    e,plan,calls=engine(tmp_path,slow=kind=='slow',failed=kind=='failed')
    with pytest.raises(RuntimeError):m.execute(plan,e)
    assert len(calls)==1
    assert not (tmp_path/'anti/replica-1/validation/assessment.json').exists()
    if kind=='slow':assert (tmp_path/'anti/replica-1/validation/boundary_review_required.json').exists()

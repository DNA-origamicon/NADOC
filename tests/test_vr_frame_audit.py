"""Timing reports must not silently turn missing/blocked frames into healthy FPS."""
import pytest
from tools.vr_workflows.frame_audit import report, distribution
from tools.vr_workflows.tour_catalog import catalog, arguments


def line(frame, epoch, *, submitted=1, tool='none', overflow=0):
    return (f'VR_FRAME_AUDIT epoch_ms={epoch} frame={frame} representation=full tool={tool} '
            f'period_ms=10 submitted={submitted} focused=1 total_ms=9 overflow={overflow} '
            'xr_wait_ms=7 xr_wait_calls=1 eye_draw_ms=2 eye_draw_calls=2\n')


def test_complete_intervals_and_runtime_waits_are_not_gpu_cost():
    result=report(line(1,0)+line(2,10)+line(3,20),[dict(name='idle',start_ms=5,end_ms=30)])
    case=result['cases'][0]
    assert case['frames']==2
    assert case['application_submission_fps']==100
    assert case['phase_wall_ms']['xr_wait_ms']['p95']==7
    assert case['phase_calls']['eye_draw_calls']==4
    assert case['outer_wall_ms']['p95']==9
    assert case['non_runtime_wait_wall_ms']['p95']==2
    assert result['valid']


def test_disjoint_tool_intervals_cannot_manufacture_fps_or_drop_counts():
    result=report(line(1,0)+line(2,10,tool='move_rotate')+line(3,20),target_budget_ms=10)
    case=result['cases'][0]
    assert not case['continuous_frames']
    assert case['application_submission_fps'] is None
    assert case['submission_gap_ms'] is None
    assert case['submission_gaps_over_1_5_target_budget'] is None


def test_no_frames_lost_trace_overflow_and_missing_cases_are_explicit():
    assert not report('')['valid']
    assert not report(line(1,0)+'VR_TRACE_DROPPED count=1')['valid']
    assert not report(line(1,0,overflow=1))['valid']
    result=report(line(1,0),[dict(name='missing',start_ms=100,end_ms=200)])
    assert result['missing_intervals']==['missing']


def test_fallback_is_never_counted_as_submitted_fps():
    case=report(line(1,0,submitted=0)+line(2,10,submitted=0))['cases'][0]
    assert case['application_submission_fps'] is None
    assert case['fallback_or_unfocused_frames']==2


def test_adaptive_runtime_period_does_not_hide_fixed_refresh_budget_misses():
    text=''.join(line(i,i*40).replace('period_ms=10','period_ms=40').replace('total_ms=9','total_ms=39') for i in range(1,4))
    case=report(text,target_budget_ms=1000/90)['cases'][0]
    assert case['runtime_period_ms']['p50']==40
    assert case['non_runtime_wait_over_budget_frames']==0  # Legacy adaptive-period comparison.
    assert case['non_runtime_wait_over_target_budget_frames']==3
    assert case['submission_gaps_over_1_5_target_budget']==2


def test_percentiles_include_outliers_and_empty_data():
    assert distribution([]) is None
    assert distribution([1]*99+[100])==dict(samples=100,p50=1,p95=1,p99=1,maximum=100)


def test_audit_is_discoverable_and_validation_requests_four_profiles():
    tour=next(t for t in catalog()['tours'] if t['id']=='frame-audit')
    assert '--validate' in arguments(tour,True)


def test_native_recorder_is_opt_in_and_exclusive(tmp_path):
    import os
    import subprocess
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    source=tmp_path/'probe.cpp'
    source.write_text('''#include "frame_audit.hpp"
int main() {
 nadoc_vr::FrameAudit audit;
 audit.begin(); audit.mark("eye_draw"); audit.mark("eye_draw");
 audit.finish(7,"full","none",11.111,true,true);
}
''')
    binary=tmp_path/'probe'
    subprocess.run(['/usr/bin/g++','-std=c++20','-pthread','-I',str(root/'native/vr_viewer/src'),str(source),'-o',str(binary)],check=True,env={**os.environ,'PATH':'/usr/bin:/bin'})
    disabled=subprocess.check_output([str(binary)],env={**os.environ,'NADOC_VR_FRAME_AUDIT':'0'},text=True)
    assert disabled==''
    enabled=subprocess.check_output([str(binary)],env={**os.environ,'NADOC_VR_FRAME_AUDIT':'1'},text=True)
    from tools.vr_workflows.frame_audit import parse
    row=parse(enabled)[0]
    assert row['eye_draw_calls']==2
    assert row['tail_calls']==1
    assert row['eye_draw_ms']+row['tail_ms']==pytest.approx(row['total_ms'],abs=2e-6)


def test_reach_recorder_retains_failures_outside_playback(tmp_path, monkeypatch):
    import json
    from tools.vr_workflows.audit_intervals import record_reach
    path=tmp_path/'reaches.jsonl'
    monkeypatch.setenv('NADOC_VR_AUDIT_INTERVALS',str(path))
    class Live:
        state={'frame':7,'representation':'stick'}
    @record_reach
    def fail(live):
        assert not path.exists()
        raise TimeoutError('original deadline')
    with pytest.raises(TimeoutError,match='original deadline'): fail(Live())
    value=json.loads(path.read_text())
    assert value['error']=='original deadline'
    assert value['representation']=='stick'
    assert value['end_ms']>=value['start_ms']


def test_calculation_subscopes_are_not_added_to_exclusive_phases():
    text=line(1,0).strip()+' calc_setStyle_ms=2 calc_setStyle_calls=1\n'
    case=report(text)['cases'][0]
    assert 'calc_setStyle_ms' not in case['phase_wall_ms']
    assert case['calculation_inclusive_wall_ms']['calc_setStyle_ms']['p95']==2


def test_corrupt_record_invalidates_report_without_hiding_good_evidence():
    result=report(line(1,0)+'VR_FRAME_AUDIT epoch_ms=bad interrupted native output\n')
    assert not result['valid']
    assert result['malformed_records']==1
    assert result['cases'][0]['frames']==1


def test_deformation_framing_preserves_head_scale_and_rejects_overlap():
    from copy import deepcopy
    import numpy as np
    from tools.vr_workflows.bend_layout import check, translation_for_clear_view
    eye=dict(eye='left',position=[0,0,0],orientation_xyzw=[0,0,0,1],
             fov_left_right_up_down=[-.7,.7,.7,-.7],width=1000,height=1000)
    evidence=dict(eyes=[eye,{**eye,'eye':'right','position':[.06,0,0]}],state={
        'bend':dict(active=True,ready=False,targets=[{'world':[0,-.1,-1]},{'world':[.2,.1,-1]}]),
        'twist':dict(active=False,ready=False,targets=[]),
        'sidebars':[{},dict(open=True,grip_targets=[[-.2,0,-1],[.6,0,-1],[.2,.5,-1],[.2,-.5,-1]])]})
    original=deepcopy(evidence)
    assert not check(evidence)['passed']
    delta=translation_for_clear_view(evidence)
    assert evidence==original
    for point in evidence['state']['bend']['targets']:
        point['world']=(np.array(point['world'])+delta).tolist()
    assert check(evidence)['passed']
    assert evidence['eyes']==original['eyes']
    assert evidence['state']['sidebars']==original['state']['sidebars']


def test_representation_setup_runs_once_per_owned_session(tmp_path,monkeypatch):
    from tools.vr_workflows import audit_representation as setup
    monkeypatch.setenv('NADOC_VR_AUDIT_REPRESENTATION','stick')
    monkeypatch.setenv('NADOC_VR_AUDIT_INTERVALS',str(tmp_path/'reaches.jsonl'))
    calls=[]
    monkeypatch.setattr(setup,'_prepare',lambda live,rep,trials:calls.append((live.session,rep)))
    class Live:
        session='one'
    live=Live()
    setup.prepare(live);setup.prepare(live)
    assert calls==[('one','stick')]
    live.session='two';setup.prepare(live)
    assert calls[-1]==('two','stick') and len(calls)==2


def test_held_atomistic_deformation_handles_remain_layout_targets():
    from tools.vr_workflows.bend_layout import check
    eye=dict(eye='left',position=[0,0,0],orientation_xyzw=[0,0,0,1],
             fov_left_right_up_down=[-.7,.7,.7,-.7],width=1000,height=1000)
    bend=dict(active=True,ready=False,grabbing=True,targets=[],
              handles=[[-.5,-.1,-1],[-.3,.1,-1]],endpoints=[[-.5,-.1,-1],[-.3,.1,-1]])
    evidence=dict(eyes=[eye,{**eye,'eye':'right'}],state={'bend':bend,'sidebars':[{},
        dict(open=True,grip_targets=[[.1,0,-1],[.5,0,-1],[.3,.4,-1],[.3,-.4,-1]])]})
    assert check(evidence)['passed']
    bend['handles']=[[.3,0,-1],[-.3,.1,-1]]
    assert not check(evidence)['passed']  # A held handle behind the panel still fails.

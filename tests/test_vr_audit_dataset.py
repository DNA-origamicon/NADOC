import json
from tools.vr_workflows.audit_dataset import collect


def test_matching_precomputed_budget_is_preserved_without_raw_log(tmp_path):
    from tools.vr_workflows.audit_dataset import add_target_budget
    case={'interval':'whole-run','representation':'full','tool':'move','frames':4,
          'target_budget_ms':1000/90,'non_runtime_wait_over_target_budget_frames':3,
          'submission_gaps_over_1_5_target_budget':None}
    add_target_budget([{'cases':[case]}],tmp_path/'absent.log',[],1000/90)
    assert case['non_runtime_wait_over_target_budget_frames']==3
    assert case['submission_gaps_over_1_5_target_budget'] is None
    add_target_budget([{'cases':[case]}],tmp_path/'absent.log',[],1000/120)
    assert case['non_runtime_wait_over_target_budget_frames'] is None


def test_sparse_trace_zero_requires_known_inventory_and_valid_trace():
    from tools.vr_workflows.audit_dataset import append_cases
    calculations=[]
    append_cases({'cases':[{'interval':'test','representation':'full','tool':'move',
                           'calculation_active_frame_wall_ms':{'calc_unknown_ms':{'samples':1,'p95':3}}}]},
                 {'trace_valid':True},{},{},[],calculations,[],
                 ['calc_cached_ms'])
    counts={row['calculation']:row['calls'] for row in calculations}
    assert counts=={'calc_cached_ms':0,'calc_unknown_ms':None}
    invalid=[]
    append_cases({'cases':[{'interval':'test','representation':'full','tool':'move'}]},
                 {'trace_valid':False},{},{},[],invalid,[],['calc_cached_ms'])
    assert invalid[0]['calls'] is None


def test_failed_workflow_retains_measured_frames_and_missing_gpu(tmp_path):
    (tmp_path/'matrix.json').write_text(json.dumps({'validation':True,'results':[
        {'tool':'move','profile':'variable_fast','representation':'surface',
         'passed':False,'reach_intervals':1,'failure_excerpt':['late playback']}]}))
    case=tmp_path/'move-surface-variable_fast';case.mkdir()
    (case/'frame-audit.json').write_text(json.dumps({'valid':True,'cases':[
        {'interval':'reach-1','representation':'surface','tool':'move','frames':12,
         'application_submission_fps':25,'phase_calls':{'calc_setStyle_calls':12},
         'calculation_active_frame_wall_ms':{'calc_setStyle_ms':{'samples':12,'p95':40}},
         'phase_wall_ms':{'input_ms':{'samples':12,'p95':42}}}]}))
    (case/'reaches.jsonl').write_text(json.dumps({'name':'reach-1','start_ms':1,'end_ms':500,'error':'late playback'})+'\n')
    (case/'host-resources.json').write_text(json.dumps({'before':{'mem_available_kib':9000000},
        'after':{'mem_available_kib':8000000},'delta':{'swap_out_pages':0,'swap_in_pages':10}}))
    (case/'compositor-summary.json').write_text(json.dumps({'cases':[
        {'name':'reach-1','samples':0,'gpu_ms':None,'dropped':0,'repeated':0,'mispresented':0}]}))
    data=collect([tmp_path])
    assert data['runs'][0]['workflow_passed'] is False
    assert data['runs'][0]['host_before_mem_available_kib']==9000000
    assert data['runs'][0]['host_delta_swap_out_pages']==0
    row=data['intervals'][0]
    assert row['frames']==12 and row['application_submission_fps']==25
    assert row['interval_error']=='late playback'
    assert row['gpu_ms_p95'] is None and row['compositor_dropped'] is None
    assert row['compositor_samples']==0
    assert data['calculations'][0]['calls']==12
    assert data['calculations'][0]['active_frame_inclusive_ms_p95']==40
    assert len(data['coverage'])==1
    assert data['coverage'][0]['latest_workflow_passed'] is False
    assert data['coverage'][0]['latest_requested_representation_frame_rows']==12


def test_bare_assertion_and_ansi_traceback_keep_the_actual_gate(tmp_path):
    from tools.vr_workflows.audit_dataset import failure_details
    path=tmp_path/'tour.log'
    path.write_text('\x1b[2m[WebServer]\x1b[22m ValueError: unrelated teardown\n'
                    '    assert not pending.exists()\n'
                    '           ^^^^^^^^^^^^^^^^^^^^\nAssertionError\n')
    assert failure_details(path,[])==['AssertionError: assert not pending.exists()']


def test_browser_expectation_retains_signed_values(tmp_path):
    from tools.vr_workflows.audit_dataset import failure_details
    path=tmp_path/'tour.log'
    path.write_text('Error: expect(received).toBe(expected) // Object.is equality\n\n'
                    'Expected: \x1b[32m6\x1b[39m\nReceived: \x1b[31m-6\x1b[39m\n')
    assert failure_details(path,[])[0].endswith('Expected: 6; Received: -6')


def test_coverage_does_not_hide_a_failed_retry_behind_an_earlier_pass(tmp_path):
    campaigns=[]
    for name,passed in (('original',True),('retry',False)):
        campaign=tmp_path/name;campaign.mkdir();campaigns.append(campaign)
        (campaign/'matrix.json').write_text(json.dumps({'results':[
            {'tool':'move','representation':'full','passed':passed}]}))
    data=collect(campaigns)
    assert len(data['runs'])==2
    coverage=data['coverage'][0]
    assert coverage['attempts']==2 and coverage['any_attempt_passed']
    assert coverage['latest_campaign']==str(campaigns[-1])
    assert coverage['latest_workflow_passed'] is False


def test_completed_workflow_with_missing_timing_is_not_a_valid_audit(tmp_path):
    (tmp_path/'matrix.json').write_text(json.dumps({'results':[
        {'tool':'move','representation':'full','passed':False,'tour_exit_code':0}]}))
    result=collect([tmp_path])['runs'][0]
    assert result['workflow_passed'] is True
    assert result['audit_passed'] is False
    assert result['trace_valid'] is None


def test_fixed_budget_counts_exclude_boundary_frames_but_session_keeps_them(tmp_path):
    from tools.vr_workflows.audit_dataset import add_target_budget
    path=tmp_path/'viewer.log'
    path.write_text(''.join(f'VR_FRAME_AUDIT epoch_ms={i*40} frame={i+1} representation=surface tool=move total_ms=39 period_ms=40 submitted=1 focused=1 xr_end_ms=7\n' for i in range(3)))
    interval=dict(interval='reach-1',representation='surface',tool='move',frames=2)
    session=dict(interval='whole-run',representation='surface',tool='move',frames=3)
    add_target_budget([{'cases':[interval]},{'cases':[session]}],path,
                      [{'name':'reach-1','start_ms':0,'end_ms':80}],1000/90)
    assert interval['non_runtime_wait_over_target_budget_frames']==2
    assert interval['submission_gaps_over_1_5_target_budget']==1
    assert session['non_runtime_wait_over_target_budget_frames']==3
    assert session['submission_gaps_over_1_5_target_budget']==2


def test_simulation_size_proof_counts_residues_without_counting_solvent(tmp_path):
    from tools.vr_workflows.simulation_tour import psf_inventory
    path=tmp_path/'model.psf'
    path.write_text('PSF\n\n4 !NATOM\n1 DNA1 1 ADE N1 N 0 14\n2 DNA1 1 ADE C1 C 0 12\n'
                    '3 DNA2 1 THY N1 N 0 14\n4 WAT1 2 TIP3 OH2 O 0 16\n')
    result=psf_inventory(path)
    assert result['atoms_including_solvent']==4
    assert result['nucleic_acid_residues']==2


def test_controller_observation_requires_real_geometry_and_clear_space(tmp_path):
    import numpy as np
    import pytest
    from tools.vr_workflows.audit_observation import clear_wrist
    eye=dict(width=64,height=64,position=[0,0,0],orientation_xyzw=[0,0,0,1],
             fov_left_right_up_down=[-.785398,.785398,.785398,-.785398])
    evidence={'eyes':[{**eye,'eye':name} for name in ('left','right')],
              'state':{'hands':[{},dict(position=[.28,-.3,-.5],orientation_xyzw=[0,0,0,1])]}}
    (tmp_path/'evidence.json').write_text(json.dumps(evidence))
    ids=np.zeros((64,64),dtype=np.uint32);ids[32:]=1
    for name in ('left','right'):ids.tofile(tmp_path/(name+'.ids.u32'))
    assert clear_wrist(tmp_path)[1]>0  # Move above the occluding lower-half model.
    ids[:]=0;ids[:,32:]=1
    for name in ('left','right'):ids.tofile(tmp_path/(name+'.ids.u32'))
    assert clear_wrist(tmp_path)[0]<0  # A full model may occupy the whole right side.
    for value,message in ((0,'No molecular pixels'),(1,'No visible wrist pose')):
        for name in ('left','right'):np.full((64,64),value,dtype=np.uint32).tofile(tmp_path/(name+'.ids.u32'))
        with pytest.raises(RuntimeError,match=message):clear_wrist(tmp_path)


def test_nick_target_requires_stereo_framing_and_prefers_near_side():
    import numpy as np
    import pytest
    from tools.vr_workflows.audit_observation import front_bond
    eye=dict(width=64,height=64,position=[0,0,0],orientation_xyzw=[0,0,0,1],
             fov_left_right_up_down=[-.785398,.785398,.785398,-.785398])
    evidence={'eyes':[{**eye,'eye':name} for name in ('left','right')]}
    bonds=[{'a':[0,0,-2],'b':[.01,0,-2]}, {'a':[0,0,-1],'b':[.01,0,-1]},
           {'a':[4,0,-.5],'b':[4.01,0,-.5]}]
    assert front_bond(evidence,bonds)==1
    with pytest.raises(RuntimeError,match='No bond'):front_bond(evidence,bonds[2:])
    with pytest.raises(RuntimeError,match='No bond'):
        front_bond(evidence,bonds,[np.zeros((64,64),dtype=bool),np.ones((64,64),dtype=bool)])


def test_calculation_inventory_includes_modules_and_nonstandard_scope_names(tmp_path):
    from tools.vr_workflows.audit_dataset import calculation_inventory
    (tmp_path / 'main.cpp').write_text('CalculationScope refreshScope("activateSceneRefresh");')
    (tmp_path / 'hover.inc').write_text('CalculationScope auditScope("updateStaticSnapHighlights");')
    (tmp_path / 'helper.hpp').write_text('CalculationScope nested("activateSceneRefresh");')
    (tmp_path / 'not-source.txt').write_text('CalculationScope ignored("notCode");')
    scopes, files = calculation_inventory(tmp_path)
    assert scopes == ['calc_activateSceneRefresh_ms', 'calc_updateStaticSnapHighlights_ms']
    assert len(files) == 3
    assert all(len(digest) == 64 for digest in files.values())

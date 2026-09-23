"""Opt-in physical Confirm/scene-refresh diagnostic; artifacts are output only."""
import sys,json,time,os
sys.path.insert(0,os.getcwd())
from pathlib import Path
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.extrude_probe import framed_origin,put
from tools.vr_workflows.profile_input import reach_target, zoom_scene, aim_orientation
from tools.vr_workflows.profile_controls import ProfileControls
from tools.vr_workflows.control_approach import lattice_approach
from tools.vr_workflows.menu_navigation import activate_extrude
from tools.vr_workflows.demo_view import reveal as reveal_demo, hold as hold_demo
from tools.vr_motion.metrics import rotate, dot, sub
socket,output=sys.argv[1:3];out=Path(output);out.mkdir(parents=True,exist_ok=True)
undo = sys.argv[3:] == ["undo"]
b=Bridge(socket)
deadline=time.monotonic()+30
while True:
    try: state=b.call('scrywrite_observe',{})
    except OSError:
        if time.monotonic()>deadline:raise
        continue
    if state.get('focused'):break
    if time.monotonic()>deadline:raise RuntimeError('viewer not focused')
    time.sleep(.1)
live=LiveSession(b,physical=True,allow_transactions=True)
reveal_demo(live)
profile_controls = (ProfileControls(live,out/'control-profile.json',
    os.environ.get('NADOC_VR_PROFILE','steady_fast'),int(os.environ.get('NADOC_VR_SEED','0'))+10000,
    feedback=os.environ.get('NADOC_VR_FEEDBACK_ACQUISITION') == '1',
    approach=os.environ.get('NADOC_VR_APPROACH_CONTROLS') == '1')
    if os.environ.get('NADOC_VR_PROFILE_CONTROLS') == '1' else None)
def click_control(label):
    if profile_controls:
        return profile_controls.click(label)
    live.send('aim_menu',hand=1,label=label);live.frame();live.button('trigger');live.frame()
def activate_extrude_menu():
    activate_extrude(live,click_control,out)

def verify_undo():
    before = live.state['scene_revision']
    feature = live.state['committed_feature_id']
    eye,_=live.capture_to(out/'before-undo',discard_source=True)
    origin=framed_origin(live,eye['eyes'][0],activate=activate_extrude_menu if os.environ.get('NADOC_VR_MENU_ACTIVATION') == '1' else None);put(live,origin['position'],origin['orientation_xyzw'])
    if live.state['menu'] == 'closed':
        live.button('menu', hand=1)
    labels = {c['label'] for c in live.state['controls']}
    path = ['BACK TO TOOLS', 'UNDO'] if 'BACK TO TOOLS' in labels else ['TOOLS', 'UNDO'] if 'TOOLS' in labels else ['UNDO']
    for label in path:
        assert label in {c['label'] for c in live.state['controls']}, live.state['menu']
        click_control(label)
    undo_started=time.monotonic()
    deadline=undo_started+120
    while live.state['status'] != 'UNDONE' or live.state.get('scene_revision',0) <= before:
        if time.monotonic()>deadline:raise RuntimeError('Undo not applied: '+str(live.state))
        live.frame();time.sleep(.1)
    (out/'undo-timing.json').write_text(json.dumps({'undo_and_snapshot_seconds':time.monotonic()-undo_started,'diagnostic_timeout_seconds':120}))
    live.capture_to(out/'undone-before-framing',discard_source=True)
    if os.environ.get('NADOC_VR_UNDO_EXPECT_AUTHORED') == '1':
        for label in ['BACK','RECENTER']:
            click_control(label)
    live.capture_to(out/'undone',discard_source=True)
    import array
    for eye in ['left','right']:
        ids=array.array('I');ids.frombytes((out/'undone'/f'{eye}.ids.u32').read_bytes())
        if os.environ.get('NADOC_VR_UNDO_EXPECT_AUTHORED') == '1':
            assert sum(value != 0 for value in ids) >= 100, 'original geometry missing after undo'
        else:
            assert not any(ids), 'stale authored pixels after undo'
    (out/'undone-state.json').write_text(json.dumps(live.state,indent=2))
    print(json.dumps({'status':live.state['status'],'undone_feature':feature,'scene_revision':live.state['scene_revision']}))

if undo:
    try:verify_undo()
    except Exception:
        (out/'failure-state.json').write_text(json.dumps(live.state,indent=2))
        raise
    finally:live.release()
    raise SystemExit(0)

try:
    eye,_=live.capture_to(out/'anchor',discard_source=True)
    zoom_mode=os.environ.get('NADOC_VR_PAINT_ZOOM','1')
    zoom=(.026/live.state['extrude']['lattice_hit_radius_m']
          if zoom_mode == 'fit' else float(zoom_mode))
    if zoom != 1:zoom_scene(live,live.state['head_position'],zoom)
    origin=framed_origin(live,eye['eyes'][0],activate=activate_extrude_menu if os.environ.get('NADOC_VR_MENU_ACTIVATION') == '1' else None);put(live,origin['position'],origin['orientation_xyzw'])
    if os.environ.get('NADOC_VR_CLEAR_TARGET') == '1':
        # End → freeform transition through ordinary empty-space selection.
        # Inspect closes the old lattice and drops its footprint.
        if live.state['menu'] == 'closed':
            live.button('menu',hand=0);live.frame()
        labels={c['label'] for c in live.state['controls']}
        path=(['BACK TO TOOLS'] if 'BACK TO TOOLS' in labels else ['TOOLS'] if 'TOOLS' in labels else [])+['INSPECT']
        for label in path:
            assert label in {c['label'] for c in live.state['controls']}, live.state['menu']
            click_control(label)
        if live.state['menu'] != 'closed':
            live.button('menu',hand=0);live.frame()
        position=[a+b for a,b in zip(live.state['head_position'],[0,.7,0])]
        put(live,position,aim_orientation(position,[position[0],position[1]+1,position[2]]))
        live.button('trigger');live.frame()
        deadline=time.monotonic()+5
        while live.state['selection_kind'] != 'none':
            if time.monotonic()>deadline:raise RuntimeError('Empty-space trigger did not clear end selection')
            live.frame();time.sleep(.1)
        (out/'cleared-target.json').write_text(json.dumps(live.state,indent=2))
        put(live,origin['position'],origin['orientation_xyzw'])
    if os.environ.get('NADOC_VR_MENU_ACTIVATION') == '1':
        activate_extrude_menu()
    else:
        live.send('activate',tool='extrude');live.frame()
    (out/'paint-presentation.json').write_text(json.dumps({'zoom':zoom,'zoom_mode':zoom_mode,'hit_radius_m':live.state['extrude']['lattice_hit_radius_m'],'panel_position':live.state['extrude']['panel_position'],'panel_orientation_xyzw':live.state['extrude']['panel_orientation_xyzw']}))
    approach_cells = os.environ.get('NADOC_VR_APPROACH_CELLS') == '1'
    if not approach_cells and os.environ.get('NADOC_VR_PAINT_APPROACH') == 'normal':
        panel=live.state['extrude']
        normal=rotate(panel['panel_orientation_xyzw'],[0,0,1])
        side=1 if dot(sub(live.state['hands'][1]['position'],panel['panel_position']),normal)>=0 else -1
        position=[a+side*.25*b for a,b in zip(panel['panel_position'],normal)]
        put(live,position,aim_orientation(position,panel['panel_position']))
    cells = [[0,0],[0,1],[1,0],[2,1],[0,2],[1,2]]
    paint_trials=[]
    preset=os.environ.get('NADOC_VR_PROFILE','steady_fast')
    seed=int(os.environ.get('NADOC_VR_SEED','0'))
    for index,(row,col) in enumerate(cells):
        visible=lambda: next((c['position'] for c in live.state['extrude']['visible_cells']
                              if c['row']==row and c['column']==col),None)
        target=visible()
        if target is None:
            before=json.loads(json.dumps(live.state['extrude']))
            click_control('CENTER PAINT')
            assert live.state['extrude']['cells']==before['cells'], 'view centering changed paint'
            target=visible()
            (out/'center-paint.json').write_text(json.dumps({'before':before,'after':live.state['extrude']},indent=2))
            live.capture_to(out/'centered-paint',discard_source=True)
        assert target is not None, f'cell remains outside viewport after centering: {row},{col}'
        acquired=False
        for attempt in range(3):
            destination = lattice_approach(live.state['extrude'],target,live.state['hands'][1]['position']) if approach_cells else None
            trial=reach_target(live,target,preset,seed+index+attempt*1000,
                acquired=(lambda state: state['extrude']['hover']==[row,col])
                if os.environ.get('NADOC_VR_FEEDBACK_ACQUISITION') == '1' else None,
                target_position=destination)
            trial['approach_policy'] = 'panel_normal_30cm_v1' if approach_cells else 'stationary_aim'
            trial['cell']=[row,col]
            trial['attempt']=attempt+1
            trial['hover_before_click']=live.state['extrude']['hover']
            trial['clicked']=(trial['hover_before_click']==[row,col] and
                (os.environ.get('NADOC_VR_FEEDBACK_ACQUISITION') != '1' or trial['acquired_with_feedback']))
            if trial['clicked']:
                live.button('trigger');live.frame()
                acquired=True
            trial['cells_after_click']=live.state['extrude']['cells']
            paint_trials.append(trial)
            (out/'paint-profile.json').write_text(json.dumps(paint_trials,indent=2))
            if acquired:break
        assert acquired, f'cell acquisition failed after three reaches: {row},{col}'
    assert sorted(live.state['extrude']['cells'])==sorted(cells),live.state['extrude']
    hold_demo(live,'painted footprint')
    if os.environ.get('NADOC_VR_PROFILE_WHEEL') == '1':
        from tools.vr_workflows.profile_wheel import set_wheel_length
        for _ in range(int(os.environ.get('NADOC_VR_WHEEL_SIZE_STEPS','0'))):
            click_control('SIZE +')
        live.capture_to(out/'wheel-before-drag',discard_source=True)
        set_wheel_length(live,out/'wheel-profile.json',42,preset,seed+20000,
            fine_click=profile_controls.click if profile_controls and os.environ.get('NADOC_VR_FINE_LENGTH') == '1' else None)
    else:
        for length in range(1,43):
            click_control('+')
            assert live.state['extrude']['length_bp']==length,live.state['extrude']
    if os.environ.get('NADOC_VR_FREEFORM') == '1':
        click_control('FREEFORM')
        assert live.state['menu']=='closed', 'Freeform did not arm'
        position=[origin['position'][0]+.15,origin['position'][1]+.10,origin['position'][2]]
        if os.environ.get('NADOC_VR_PROFILE_PLACEMENT') == '1':
            placement_motion=reach_target(live,position,preset,seed+30000,
                target_position=position,target_orientation=origin['orientation_xyzw'])
            (out/'freeform-placement-profile.json').write_text(json.dumps(placement_motion,indent=2))
        else:
            put(live,position,origin['orientation_xyzw'])
        placement_pose=dict(live.state['hands'][1])
        live.button('trigger');live.frame()
        assert live.state['menu']=='tool_config', 'Freeform placement not captured'
        (out/'freeform-capture.json').write_text(json.dumps({'position':position,'orientation':origin['orientation_xyzw'],
            'actual_capture_pose':placement_pose,'state':live.state},indent=2))
        live.capture_to(out/'freeform-preview',discard_source=True)
        put(live,origin['position'],origin['orientation_xyzw'])
    click_control('BACK TO TOOLS')
    # Wait for browser validation to be published, without holding any input.
    deadline=time.monotonic()+10
    while not live.state.get("painted_commit_ready"):
        if time.monotonic()>deadline:raise RuntimeError("preflight not ready: "+str(live.state))
        live.frame();time.sleep(.1)
    before_revision=live.state.get('scene_revision',0)
    before_feature=live.state.get('committed_feature_id')
    click_control('CONFIRM')
    commit_started=time.monotonic()
    deadline=commit_started+120
    while live.state['status']!='COMMITTED' or live.state.get('committed_feature_id') == before_feature:
        if time.monotonic()>deadline:raise RuntimeError('commit not acknowledged: '+str(live.state))
        live.frame();time.sleep(.1)
    deadline=commit_started+120
    while live.state.get('scene_revision',0)<=before_revision:
        if time.monotonic()>deadline:raise RuntimeError('native scene revision not applied')
        live.frame();time.sleep(.1)
    (out/'commit-timing.json').write_text(json.dumps({'commit_and_snapshot_seconds':time.monotonic()-commit_started,'diagnostic_timeout_seconds':120}))
    live.capture_to(out/'committed',discard_source=True)
    for label in ['LATTICE EXIT','BACK','RECENTER']:
        click_control(label)
    live.capture_to(out/'framed',discard_source=True)
    import array
    counts=[]
    for eye in ['left','right']:
        ids=array.array('I');ids.frombytes((out/'framed'/f'{eye}.ids.u32').read_bytes())
        counts.append(sum(value!=0 for value in ids))
    (out/'visible-pixels.json').write_text(json.dumps({'authored_pixels':counts}))
    assert min(counts)>=100,counts
    if os.environ.get('NADOC_VR_REVIEW_VIEW') == '1':
        from tools.vr_workflows.review_view import improve_review
        improve_review(live,out/'framed',out/'review',expected_groups=2 if os.environ.get('NADOC_VR_FREEFORM') == '1' else 1)
        if os.environ.get('NADOC_VR_DESKTOP_REVIEW') == '1':
            from tools.vr_motion.desktop_check import run as check_desktop
            desktop=check_desktop(socket,out/'desktop-review',live=live,reveal=os.environ.get('NADOC_VR_DEMO') == '1')
            assert desktop['passed'], desktop
    hold_demo(live,'committed extrusion')
    (out/'committed-state.json').write_text(json.dumps(live.state,indent=2))
    print(json.dumps({'status':live.state['status'],'feature':live.state['committed_feature_id']}))
except Exception:
    (out/'failure-state.json').write_text(json.dumps(live.state,indent=2))
    raise
finally:live.release()

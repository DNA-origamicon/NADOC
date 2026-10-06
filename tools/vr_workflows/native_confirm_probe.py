"""Opt-in physical Confirm/scene-refresh diagnostic; artifacts are output only."""
import sys,json,time,os
sys.path.insert(0,os.getcwd())
from pathlib import Path
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.extrude_probe import put
from tools.vr_workflows.profile_input import reach_target, zoom_scene, aim_orientation
from tools.vr_workflows.profile_controls import ProfileControls
from tools.vr_workflows.control_approach import lattice_approach
from tools.vr_workflows.menu_navigation import sidebar_click
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
from tools.vr_workflows.audit_representation import prepare as prepare_audit_representation, wait_startup
wait_startup(live)
prepare_audit_representation(live)
reveal_demo(live)
profile_controls = (ProfileControls(live,out/'control-profile.json',
    os.environ.get('NADOC_VR_PROFILE','steady_fast'),int(os.environ.get('NADOC_VR_SEED','0'))+10000,
    feedback=os.environ.get('NADOC_VR_FEEDBACK_ACQUISITION') == '1',
    approach=os.environ.get('NADOC_VR_APPROACH_CONTROLS') == '1')
    if os.environ.get('NADOC_VR_PROFILE_CONTROLS') == '1' else None)
from tools.vr_workflows.extrude_sidebar import SidebarControls
sidebar_controls=SidebarControls(live,out,os.environ.get('NADOC_VR_PROFILE','steady_fast'))
def click_control(label):
    identifiers={'+':'more','-':'less','CONFIRM':'confirm','UNDO':'undo','FREEFORM':'freeform'}
    if label in identifiers:
        return sidebar_controls.click('extrude:'+identifiers[label])
    if profile_controls:
        return profile_controls.click(label)
    live.send('aim_menu',hand=1,label=label);live.frame();live.button('trigger');live.frame()
def activate_extrude_menu():
    sidebar_controls.activate()

def verify_undo():
    before = live.state['scene_revision']
    feature = live.state['committed_feature_id']
    live.capture_to(out/'before-undo',discard_source=True)
    sidebar_click(live,click_control,'tab:tools')
    sidebar_click(live,click_control,'tool-extrude')
    sidebar_controls.click('extrude:undo')
    undo_started=time.monotonic()
    deadline=undo_started+120
    while live.state['status'] != 'UNDONE' or live.state.get('scene_revision',0) <= before:
        if time.monotonic()>deadline:raise RuntimeError('Undo not applied: '+str(live.state))
        live.frame();time.sleep(.1)
    (out/'undo-timing.json').write_text(json.dumps({'undo_and_snapshot_seconds':time.monotonic()-undo_started,'diagnostic_timeout_seconds':120}))
    live.capture_to(out/'undone-before-framing',discard_source=True)
    if os.environ.get('NADOC_VR_UNDO_EXPECT_AUTHORED') == '1':
        sidebar_controls.click('extrude:recenter')
        sidebar_controls.click('extrude:back')
        live.button('menu',hand=1);live.frame()
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
    origin={'position':live.state['hands'][1]['position'],'orientation_xyzw':eye['eyes'][0]['orientation_xyzw']}
    if os.environ.get('NADOC_VR_CLEAR_TARGET') == '1':
        # Inspect releases the prior end target before choosing empty space.
        sidebar_click(live,click_control,'tab:tools')
        sidebar_click(live,click_control,'tool-inspect')
        for hand in (0,1):
            if live.state['sidebars'][hand]['open']:
                live.button('menu',hand=hand);live.frame()
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
    # Matches tests/conftest.py SIX_HB_CELLS and the desktop seed translated
    # by four columns (parity preserved). Six cells alone do not prove a ring.
    square = live.state['extrude']['square']
    period = 8 if square else 7
    target_length = 6*period
    if os.environ.get('NADOC_VR_LATTICE'):
        assert square == (os.environ['NADOC_VR_LATTICE'] == 'SQUARE')
    cells = ([[0,0],[0,1],[0,2],[1,0],[1,1],[1,2]] if square else
             [[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]])
    slice_reference = os.environ.get('NADOC_VR_SLICE_REFERENCE') == '1'
    if slice_reference:
        assert square
        expected_source = [[0,column] for column in range(8)]
        assert sorted(live.state['extrude']['occupied_cells']) == expected_source
        assert live.state['extrude']['lattice_context_resolved']
        cells = [[row,column] for row in (1,2) for column in range(3)]
        live.capture_to(out/'existing-1x8-slice',discard_source=True)
    paint_trials=[]
    preset=os.environ.get('NADOC_VR_PROFILE','steady_fast')
    seed=int(os.environ.get('NADOC_VR_SEED','0'))
    grid_zoom=float(os.environ.get('NADOC_VR_PAINT_GRID_ZOOM','1'))
    if grid_zoom != 1:
        from tools.vr_workflows.lattice_grip_check import zoom_lattice
        zoom_lattice(live,out/'diagnostic-grid-zoom',preset,grid_zoom)
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
    if slice_reference:
        live.capture_to(out/'existing-and-painted-slice',discard_source=True)
    hold_demo(live,'painted footprint')
    from tools.vr_workflows.lattice_grip_check import run as check_lattice_grips
    check_lattice_grips(live,out/'lattice-grips',preset)
    for identifier, expected in [('more',period),('less',0),('more-period',3*period),
                                 ('less-period',0)]:
        control=next(c for c in live.state['controls'] if c.get('id')=='extrude:'+identifier)
        step=3*period if identifier.endswith('-period') else period
        label=('+' if identifier.startswith('more') else '-')+str(step)+' BP'
        assert control['label']==f'RIGHT / {label} [extrude:{identifier}]',control
        sidebar_controls.click('extrude:'+identifier)
        assert live.state['extrude']['length_bp']==expected,live.state['extrude']
    for expected in [3*period,target_length]:
        sidebar_controls.click('extrude:more-period')
        assert live.state['extrude']['length_bp']==expected,live.state['extrude']
    if os.environ.get('NADOC_VR_PROFILE_WHEEL') == '1':
        sidebar_controls.click('extrude:less-period')
        sidebar_controls.click('extrude:less-period')
        from tools.vr_workflows.profile_wheel import set_wheel_length
        live.capture_to(out/'wheel-before-drag',discard_source=True)
        set_wheel_length(live,out/'wheel-profile.json',target_length,preset,seed+20000,
            fine_click=click_control, fine_step=period)
        live.capture_to(out/'wheel-after-drag',discard_source=True)
        # The fine wheel must reach a non-period-aligned value and return by
        # exactly one bp through real trigger drags, preserving the footprint.
        for direction, target in [('up',target_length+1),('down',target_length)]:
            set_wheel_length(live,out/f'fine-wheel-{direction}-profile.json',target,
                preset,seed+21000+(direction=='down')*1000,wheel='fine')
            assert live.state['extrude']['length_bp']==target
            live.capture_to(out/f'fine-wheel-{direction}',discard_source=True)
        hold_demo(live,'Coarse and fine menu wheels set extrusion length')
    if os.environ.get('NADOC_VR_FREEFORM') == '1':
        click_control('FREEFORM')
        assert not live.state['sidebars'][1]['open'], 'Freeform did not arm'
        position=[origin['position'][0]+.15,origin['position'][1]+.10,origin['position'][2]]
        if os.environ.get('NADOC_VR_PROFILE_PLACEMENT') == '1':
            placement_motion=reach_target(live,position,preset,seed+30000,
                target_position=position,target_orientation=origin['orientation_xyzw'])
            (out/'freeform-placement-profile.json').write_text(json.dumps(placement_motion,indent=2))
        else:
            put(live,position,origin['orientation_xyzw'])
        placement_pose=dict(live.state['hands'][1])
        live.button('trigger');live.frame()
        assert live.state['sidebars'][1]['open'] and live.state['sidebars'][1]['tab']=='extrude', 'Freeform placement not captured'
        (out/'freeform-capture.json').write_text(json.dumps({'position':position,'orientation':origin['orientation_xyzw'],
            'actual_capture_pose':placement_pose,'state':live.state},indent=2))
        live.capture_to(out/'freeform-preview',discard_source=True)
        put(live,origin['position'],origin['orientation_xyzw'])
    # Wait for browser validation to be published, without holding any input.
    deadline=time.monotonic()+10
    while not live.state.get("painted_commit_ready"):
        if time.monotonic()>deadline:raise RuntimeError("preflight not ready: "+str(live.state))
        live.frame();time.sleep(.1)
    live.capture_to(out/'confirm-ready',discard_source=True)
    if slice_reference:
        preview=live.state['extrude']['model_preview']
        assert sorted(p['cell'] for p in preview)==sorted(cells)
        import math
        positions={tuple(p['cell']):p['start_nm'] for p in preview}
        assert math.isclose(math.dist(positions[1,0],positions[2,0]),2.25,abs_tol=1e-4)
        assert math.isclose(math.dist(positions[1,0],positions[1,1]),2.25,abs_tol=1e-4)
        assert all(math.isclose(math.dist(p['start_nm'],p['end_nm']),target_length*.334,abs_tol=1e-4) for p in preview)
    before_revision=live.state.get('scene_revision',0)
    before_feature=live.state.get('committed_feature_id')
    click_control('CONFIRM')
    commit_started=time.monotonic()
    assert not live.state['extrude']['open'], 'Confirm left the lattice painter open'
    assert not live.state['extrude']['editor_active'], 'Confirm left Extrude active'
    assert not live.state['sidebars'][1]['open'], 'Confirm left the right sidebar open'
    assert not live.state['extrude']['model_preview'], 'Confirm left native draft geometry visible'
    assert not any(w['dragging'] for w in live.state['extrude']['wheels'])
    (out/'confirm-dismissed-state.json').write_text(json.dumps(live.state,indent=2))
    observation_timeouts=[]
    def commit_frame():
        # Observe is read-only: a scene import can exceed the socket's 3 s
        # response window. Keep the existing 120 s commit/refresh deadline;
        # never retry Confirm or relax controller motion timing.
        try: live.frame()
        except TimeoutError:
            observation_timeouts.append(time.monotonic()-commit_started)
    deadline=commit_started+120
    while live.state['status']!='COMMITTED' or live.state.get('committed_feature_id') == before_feature:
        if time.monotonic()>deadline:raise RuntimeError('commit not acknowledged: '+str(live.state))
        commit_frame();time.sleep(.1)
    deadline=commit_started+120
    while live.state.get('scene_revision',0)<=before_revision:
        if time.monotonic()>deadline:raise RuntimeError('native scene revision not applied')
        commit_frame();time.sleep(.1)
    (out/'commit-timing.json').write_text(json.dumps({'commit_and_snapshot_seconds':time.monotonic()-commit_started,'diagnostic_timeout_seconds':120,'read_only_observation_timeouts_s':observation_timeouts}))
    live.capture_to(out/'committed',discard_source=True)
    assert not live.state['extrude']['open'] and not live.state['sidebars'][1]['open']
    assert not live.state['extrude']['configuration_active'] and not live.state['extrude']['confirm_pending']
    assert not live.state['extrude']['cells'] and not live.state['extrude']['model_preview']
    assert live.state['extrude']['undo_available']
    (out/'confirmed-closed-state.json').write_text(json.dumps(live.state,indent=2))
    if slice_reference:
        assert sorted(live.state['extrude']['occupied_cells'])==sorted(expected_source+cells)
    # Reframe through the normal Visualization menu, after checking that Confirm
    # itself dismissed the entire editor. This does not reactivate Extrude.
    from tools.vr_workflows.extrude_sidebar import SidebarControls
    framing_controls=sidebar_controls or SidebarControls(live,out,preset)
    live.button('menu',hand=1);live.frame()
    framing_controls.click('tab:visualization')
    framing_controls.click('reset-btn')
    live.button('menu',hand=1);live.frame()
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
        # Same-frame adjacent extrusion extends the source cluster. Only a
        # separately placed freeform extrusion expects two rendered clusters.
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

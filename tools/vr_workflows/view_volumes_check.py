"""Isolated physical-runtime trigger-grab, face-resize, grip and persistence check."""
import argparse
import json
import time
import uuid
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from fastapi.testclient import TestClient
from backend.api import state, routes_vr
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design, ViewVolume
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.presets import PRESETS
from tools.vr_motion.visual_checks import project
from tools.vr_workflows.menu_grip_check import move
from tools.vr_workflows.menu_tour import enlarge_mirror


def highlight_pixels(directory, evidence, points):
    from PIL import Image
    checks = []
    for eye in evidence['eyes']:
        rgb = np.asarray(Image.open(directory/(eye['eye']+'.png')).convert('RGB'))
        hits = 0
        for p in points:
            xy = project(list(p), eye)
            if xy is None:
                continue
            x,y = map(round, xy)
            if not (4 <= x < eye['width']-4 and 4 <= y < eye['height']-4):
                continue
            patch = rgb[y-4:y+5,x-4:x+5].astype(float)
            hits += bool(((patch[:,:,0]>180)&(patch[:,:,1]>100)&(patch[:,:,1]<245)&(patch[:,:,2]<120)).any())
        checks.append({'eye':eye['eye'],'fraction':hits/max(1,len(points))})
    return checks


def face_samples(entry, face, presentation):
    """Sample inset face edges, away from the orange controller at its center."""
    sides=len(entry['faces'])-2
    half=np.asarray(entry['half_nm']);center=np.asarray(entry['center_nm'])
    ring=([(np.cos(i*np.pi/3)*min(half[:2]),np.sin(i*np.pi/3)*min(half[:2])) for i in range(6)]
          if sides==6 else [(-half[0],-half[1]),(half[0],-half[1]),(half[0],half[1]),(-half[0],half[1])])
    corners=np.array([[x,y,z] for z in (-half[2],half[2]) for x,y in ring])
    indices=([face,(face+1)%sides,(face+1)%sides+sides,face+sides] if face<sides
             else list(range(0 if face==sides else sides,sides if face==sides else 2*sides)))
    vertices=Rotation.from_quat(entry['rotation_xyzw']).apply(corners[indices])+center
    middle=vertices.mean(axis=0)
    samples=(vertices+np.roll(vertices,-1,axis=0))*.5*.85+middle*.15
    local=(samples-np.asarray(presentation['source_center_nm']))*presentation['normalization_model_per_nm']+np.asarray(presentation['normalized_offset_model'])
    world=np.c_[local,np.ones(len(local))] @ np.asarray(presentation['model_to_tracking_rows']).T
    return world[:,:3].tolist()


def highlight_passed(checks):
    return {c['eye'] for c in checks} == {'left','right'} and all(c['fraction'] >= .5 for c in checks)


def wait_for(live, predicate, timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        live.frame()
        if predicate():return
        time.sleep(.05)
    raise AssertionError('View-volume state did not reach the expected result')


def review(live, title, seconds):
    """Holds occur outside motion trials; refresh poses to retain the input lease."""
    print(title, flush=True)
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        for h,pose in enumerate(live.state['hands']):
            live.send('pose',hand=h,position=pose['position'],orientation=pose['orientation_xyzw'])
        live.frame();time.sleep(.05)


def menu_controls(live, output, eye_rotation, hold):
    from tools.vr_workflows.menu_focus_check import seek
    from tools.vr_workflows.menu_tour import scroll_page
    head=np.asarray(live.state['head_position'])
    for h in (0,1):
        live.send('pose',hand=h,position=(head+eye_rotation.apply([-.3 if h==0 else .3,-.3,-.4])).tolist(),orientation=eye_rotation.as_quat().tolist())
    if not live.state['sidebars'][1]['open']:live.button('menu',hand=1)
    def click(identifier):
        seek(live,1,identifier);live.button('trigger',hand=1)
        wait_for(live,lambda:not live.state['view_volumes']['pending'])
    click('tab:visualization')
    title='section:visualization:template:view-volumes'
    for _ in range(16):
        if any(c['id']==title for c in live.state['controls']):break
        scroll_page(live,1,1)
    click(title)
    assert live.state['sidebars'][1]['tab']=='view-volumes'
    initial={e['id'] for e in live.state['view_volumes']['entries']}
    created=[]
    for shape in ('box','hexagonal'):
        click('volume:new:'+shape)
        wait_for(live,lambda:len(live.state['view_volumes']['entries'])==len(initial)+len(created)+1)
        key=next(e['id'] for e in live.state['view_volumes']['entries'] if e['id'] not in initial|set(created))
        created.append(key)
        assert len(next(e for e in live.state['view_volumes']['entries'] if e['id']==key)['faces'])==(6 if shape=='box' else 8)
    live.capture_to(output/'menu-created',files=('left.png','right.png','mirror.png','evidence.json'),discard_source=True)
    review(live,'Square and hex volumes created through the Visualization menu',hold)
    key=created[0]
    for visible in (False,True):
        click('volume:outline:'+key)
        assert next(e for e in live.state['view_volumes']['entries'] if e['id']==key)['outline']==visible
        review(live,'Volume outline '+('shown' if visible else 'hidden'),hold)
    for enabled in (False,True):
        click('volume:enabled:'+key)
        assert next(v for v in state.get_or_404().view_volumes if v.id==key).enabled==enabled
        review(live,'Volume representation '+('enabled' if enabled else 'disabled'),hold)
    for key in created:click('volume:delete:'+key)
    assert {e['id'] for e in live.state['view_volumes']['entries']}==initial
    review(live,'Temporary volumes deleted; original desktop volume preserved',hold)
    click('volume:toggle')
    assert live.state['sidebars'][1]['tab']!='view-volumes'
    for h in (0,1):
        if live.state['sidebars'][h]['open']:live.button('menu',hand=h)
    return {'create_box':True,'create_hex':True,'outline':True,'enabled':True,'delete':True,'return':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.development-artifacts/vr-view-volumes')/('grabs-'+uuid.uuid4().hex[:12]))
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--validate', action='store_true')
    mode.add_argument('--demo', action='store_true', help='Paced walkthrough; stays open for review until stopped')
    parser.add_argument('--hold', type=float, default=2, help='Demo seconds per review stage (0..30)')
    parser.add_argument('--exit', action='store_true', help='Close the demo after the walkthrough')
    args = parser.parse_args()
    if not 0 <= args.hold <= 30:parser.error('--hold must be 0..30 seconds')
    args.output.mkdir(parents=True, exist_ok=False)
    hold=args.hold if args.demo else 0
    if routes_vr._read_state():
        raise RuntimeError('Another native viewer is active; refusing to replace it.')
    doc = '__test_vr_volumes_'+uuid.uuid4().hex[:12]
    token = set_current_doc(doc)
    design = _demo_design()
    design.view_volumes = [ViewVolume(id='volume', name='Trigger grab test', min_corner=(-3,-3,0), max_corner=(3,3,10))]
    state.set_design(design)
    client = TestClient(app, client=('127.0.0.1',50000), headers={'X-NADOC-Doc':doc})
    live = None; launched = False
    results=[]; trials=[]
    try:
        response = client.post('/api/vr/launch', json={'scrywrite_live':'transactions'})
        (args.output/'launch-response.json').write_text(response.text)
        assert response.status_code == 200, response.text
        launched = True; launch = routes_vr._read_state()
        (args.output/'launch.json').write_text(json.dumps(launch,indent=2))
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                live=LiveSession(Bridge(launch['scrywrite_socket']), physical=True, allow_transactions=True)
                break
            except (RuntimeError,OSError,ValueError):time.sleep(.2)
        assert live is not None
        enlarge_mirror(live)
        initial,_=live.capture_to(args.output/'initial-view',files=('left.png','right.png','mirror.png','evidence.json'),discard_source=True)
        eye_rotation=Rotation.from_quat(initial['eyes'][0]['orientation_xyzw'])
        for h in (0,1):
            if live.state['sidebars'][h]['open']:live.button('menu',hand=h)
        menu_checks=menu_controls(live,args.output,eye_rotation,hold)
        def entry():return live.state['view_volumes']['entries'][0]
        def button(name, hand, pressed):
            live.send('button', button=name, hand=hand, pressed=pressed);live.frame()
        def capture(name, points, highlighted=True):
            directory=args.output/name
            evidence,_=live.capture_to(directory,files=('left.png','right.png','mirror.png','evidence.json'),discard_source=True)
            checks=highlight_pixels(directory,evidence,points)
            (directory/'highlight-checks.json').write_text(json.dumps(checks,indent=2))
            if highlighted:assert highlight_passed(checks),checks
            return checks
        for preset in PRESETS if args.validate else ['steady_fast']:
            for shape in ('box','hexagonal'):
                # Restore fixture geometry between profiles, outside measured motion.
                presentation=live.state['presentation'];model=np.asarray(presentation['model_to_tracking_rows'])
                scale=presentation['normalization_model_per_nm'];world_scale=np.linalg.norm(model[:3,0])*scale
                target=np.array(live.state['head_position'])+eye_rotation.apply([0,-.1,-.75])
                local=(np.linalg.inv(model) @ np.r_[target,1])[:3]
                center=np.asarray(launch['view_rotation']).T @ ((local-np.asarray(presentation['normalized_offset_model']))/scale+np.asarray(presentation['source_center_nm']))
                half=np.array([.13,.13,.18])/world_scale
                model_rotation=model[:3,:3]/np.linalg.norm(model[:3,0])
                document_rotation=Rotation.from_matrix(np.asarray(launch['view_rotation']).T @ model_rotation.T @ eye_rotation.as_matrix()).as_quat()
                state.get_or_404().view_volumes=[ViewVolume(id='volume',name=shape,shape=shape,min_corner=tuple(center-half),max_corner=tuple(center+half),rotation=tuple(document_rotation))]
                for h in (0,1):
                    live.send('pose',hand=h,position=(target+eye_rotation.apply([(-.4 if h==0 else .4),-.2,0])).tolist(),orientation=eye_rotation.as_quat().tolist())
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    live.frame()
                    if len(entry()['faces'])==(6 if shape=='box' else 8) and np.linalg.norm(np.asarray(entry()['world_center'])-target)<.002:break
                    time.sleep(.05)
                assert np.linalg.norm(np.asarray(entry()['world_center'])-target)<.002
                base=f'{preset}-{shape}'
                centroid=np.array(entry()['world_center'])
                samples=[centroid+np.eye(3)[i]*s*.014 for i in range(3) for s in (-1,1)]
                cold=capture(base+'-cold',samples,highlighted=False)
                move(live,{0:centroid.tolist()},preset,trials)
                assert live.state['view_volumes']['nearby_centroids'][0]=='volume'
                hot=capture(base+'-centroid',samples)
                review(live,f'{shape}: centroid highlighted; hold Trigger to move and rotate',hold)
                assert sum(c['fraction'] for c in hot)>sum(c['fraction'] for c in cold)
                button('trigger',0,True);assert live.state['view_volumes']['hand']==0
                before=np.array(entry()['world_center'])
                hand_before=live.state['hands'][0]
                offset=Rotation.from_quat(hand_before['orientation_xyzw']).inv().apply(before-np.array(hand_before['position']))
                move(live,{0:(np.array(live.state['hands'][0]['position'])+[.08,.03,0]).tolist()},preset,trials)
                hand_after=live.state['hands'][0]
                expected=np.array(hand_after['position'])+Rotation.from_quat(hand_after['orientation_xyzw']).apply(offset)
                trials[-1]['volume_result']=live.state['view_volumes']
                trials[-1]['expected_world_center']=expected.tolist()
                assert np.allclose(entry()['world_center'],expected,atol=.001), (entry()['world_center'],expected)
                initial_q=entry()['rotation_xyzw']
                hand=live.state['hands'][0]
                q=(Rotation.from_euler('z',25,degrees=True)*Rotation.from_quat(hand['orientation_xyzw'])).as_quat()
                live.send('pose',hand=0,position=hand['position'],orientation=q.tolist());live.frame()
                assert abs(np.dot(initial_q,entry()['rotation_xyzw']))<.995
                review(live,'First Trigger holds position and rotation',hold)
                face_index=1;face=entry()['faces'][face_index]
                move(live,{1:face['world_center']},preset,trials)
                assert live.state['view_volumes']['nearby_faces'][1]==face_index
                capture(base+'-face',face_samples(entry(),face_index,live.state['presentation']))
                review(live,'Second controller highlights the nearby face',hold)
                button('trigger',1,True);assert live.state['view_volumes']['resize_face']==face_index
                before=np.array(entry()['half_nm']);face=entry()['faces'][face_index]
                move(live,{1:(np.array(live.state['hands'][1]['position'])+np.array(face['world_normal'])*.06).tolist()},preset,trials)
                after=np.array(entry()['half_nm']);assert after[0]>before[0]*1.1
                assert abs(after[2]-before[2])<.002
                review(live,'Both Triggers: resize symmetrically about the held centroid',hold)
                button('trigger',1,False);assert live.state['view_volumes']['resize_face']==-1
                # Exercise the length axis as well as the side/radius dimension.
                cap=len(entry()['faces'])-1;face=entry()['faces'][cap]
                move(live,{1:face['world_center']},preset,trials)
                assert live.state['view_volumes']['nearby_faces'][1]==cap
                capture(base+'-end-face',face_samples(entry(),cap,live.state['presentation']))
                button('trigger',1,True);assert live.state['view_volumes']['resize_face']==cap
                before_half=np.array(entry()['half_nm']);before_center=np.array(entry()['center_nm'])
                start=np.array(live.state['hands'][1]['position']);normal=np.array(face['world_normal'])
                move(live,{1:(start+normal*.06).tolist()},preset,trials)
                delta=float((np.array(live.state['hands'][1]['position'])-start) @ normal)/world_scale
                expected_half=before_half.copy();expected_half[2]=max(.001/world_scale,before_half[2]+delta)
                assert np.allclose(entry()['half_nm'],expected_half,atol=.002)
                assert np.allclose(entry()['center_nm'],before_center,atol=.002)
                review(live,'End-face Trigger changes length without changing width or radius',hold)
                button('trigger',1,False);assert live.state['view_volumes']['resize_face']==-1
                # Keep the centroid trigger held and move the part with grip.
                pose_before={k:entry()[k] for k in ('center_nm','half_nm','rotation_xyzw')}
                model_before=live.state['presentation']['model_to_tracking_rows']
                button('grip',0,True)
                move(live,{0:(np.array(live.state['hands'][0]['position'])+[.05,0,0]).tolist()},preset,trials)
                button('grip',0,False)
                assert not np.allclose(model_before,live.state['presentation']['model_to_tracking_rows'])
                for k,v in pose_before.items():assert np.allclose(entry()[k],v,atol=.002),(k,entry()[k],v)
                review(live,'Grip moves the scene while the volume stays attached to the part',hold)
                button('trigger',0,False);assert live.state['view_volumes']['hand']==-1
                deadline=time.monotonic()+4
                while time.monotonic()<deadline:
                    live.frame()
                    if not live.state['view_volumes']['pending']:break
                    time.sleep(.05)
                assert not live.state['view_volumes']['pending']
                record=state.get_or_404().view_volumes[0]
                launch_rotation=np.asarray(launch['view_rotation'])
                assert np.allclose(launch_rotation @ ((np.array(record.min_corner)+record.max_corner)/2),entry()['center_nm'],atol=.002)
                assert np.allclose((np.array(record.max_corner)-record.min_corner)/2,entry()['half_nm'],atol=.002)
                exported=Rotation.from_matrix(launch_rotation @ Rotation.from_quat(record.rotation).as_matrix()).as_quat()
                assert abs(np.dot(exported,entry()['rotation_xyzw']))>.99999
                content=state.get_or_404().to_json();(args.output/(base+'.nadoc')).write_text(content)
                assert Design.from_json(content).view_volumes==state.get_or_404().view_volumes
                results.append({'preset':preset,'shape':shape,'passed':True})
        (args.output/'result.json').write_text(json.dumps({'passed':True,'mode':'demo' if args.demo else 'validation' if args.validate else 'check','menu':menu_checks,'results':results},indent=2))
        print('View-volume walkthrough passed; evidence: '+str(args.output),flush=True)
        if args.demo and not args.exit:
            print('Volume remains visible for review. Stop tour or Ctrl+C closes this owned viewer.',flush=True)
            while True:review(live,'Reviewing final volume',30)
    except KeyboardInterrupt:
        if not (args.output/'result.json').exists():
            (args.output/'result.json').write_text(json.dumps({'passed':False,'stopped':True,'results':results},indent=2))
        print('View-volume demo stopped.',flush=True)
    finally:
        (args.output/'trials.json').write_text(json.dumps(trials,indent=2))
        try:
            if live:live.release()
        finally:
            try:
                if launched:client.post('/api/vr/stop')
            finally:
                state.drop_doc(doc);reset_current_doc(token)


if __name__=='__main__':main()

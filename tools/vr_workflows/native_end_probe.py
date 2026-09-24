"""Physical end Confirm diagnostic using rendered IDs and ordinary controller-volume selection.

Optional profile acquisition retains the rendered terminal as its intended target.
"""
import array
import json
import math
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.extrude_probe import framed_origin, put
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.profile_input import aim_orientation, zoom_scene, reach_target
from tools.vr_workflows.profile_controls import ProfileControls
from tools.vr_workflows.menu_navigation import activate_extrude
from tools.vr_workflows.demo_view import reveal as reveal_demo, hold as hold_demo


def run(socket, output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    deadline = time.monotonic()+30
    while not bridge.call('scrywrite_observe', {}).get('focused'):
        if time.monotonic()>deadline:
            raise RuntimeError('Viewer did not become focused')
        time.sleep(.1)
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    reveal_demo(live)
    preset = os.environ.get('NADOC_VR_PROFILE','steady_fast')
    seed = int(os.environ.get('NADOC_VR_SEED','0'))
    controls = (ProfileControls(live,out/'control-profile.json',preset,seed+40000,
        feedback=os.environ.get('NADOC_VR_FEEDBACK_ACQUISITION') == '1',
        approach=os.environ.get('NADOC_VR_APPROACH_CONTROLS') == '1')
        if os.environ.get('NADOC_VR_PROFILE_END') == '1' else None)
    def click(label):
        if controls:
            return controls.click(label)
        live.send('aim_menu', hand=1, label=label)
        live.frame()
        (out/('control-'+label.replace(' ','_')+'.json')).write_text(json.dumps(live.state,indent=2))
        if label != 'LATTICE EXIT' and live.state['hover'] != ''.join(c.lower() if c.isalnum() else '_' for c in label):
            raise RuntimeError(f'Control aim missed {label}: {live.state["hover"]}')
        live.button('trigger')
        live.frame()
        if label == 'LATTICE EXIT' and live.state['extrude']['open']:
            raise RuntimeError('Lattice exit did not close paint')
    try:
        evidence, _ = live.capture_to(out/'anchor', discard_source=True)
        origin = framed_origin(live, evidence['eyes'][0],
            activate=(lambda: activate_extrude(live,click,out)) if controls else None)
        put(live, origin['position'], origin['orientation_xyzw'])
        live.send('pose',hand=0,position=origin['position'],orientation=origin['orientation_xyzw'])
        live.frame()
        if live.state['menu'] != 'closed':
            live.button('menu',hand=0)
        live.button('menu',hand=0)
        live.frame()
        click('RECENTER')
        live.button('menu',hand=0)
        live.frame()
        if 'LATTICE EXIT' in {c['label'] for c in live.state['controls']}:
            click('LATTICE EXIT')
        click('END')
        live.button('menu', hand=0)
        zoom = float(os.environ.get('NADOC_VR_END_ZOOM', '1'))
        if zoom != 1:
            live.capture_to(out/'before-zoom', discard_source=True)
            zoom_scene(live, live.state['head_position'], zoom)
            (out/'zoom.json').write_text(json.dumps({'factor':zoom,'purpose':'separate terminal targets before selection'}))
        evidence, _ = live.capture_to(out/'pick', discard_source=True)
        eye = evidence['eyes'][0]
        objects = json.loads((out/'pick/objects.json').read_text())
        ends = {}
        for obj in objects:
            for token in obj['owner_tokens']:
                owner = json.loads(unquote(token))
                if owner[0] == 'end' and ':41:' in owner[1] and obj['identity'].endswith(':backbone'):
                    ends[obj['id']] = obj
        ids = array.array('I')
        ids.frombytes((out/'pick/left.ids.u32').read_bytes())
        pixels = [i for i, value in enumerate(ids) if value in ends]
        if not pixels:
            raise RuntimeError('No visible far-end pixels')
        # Most visible terminal primitive; choose an actual pixel near its centroid.
        from collections import Counter
        identity = Counter(ids[i] for i in pixels).most_common(1)[0][0]
        pixels = [i for i in pixels if ids[i] == identity]
        width, height = eye['width'], eye['height']
        cx = sum(i % width for i in pixels)/len(pixels)
        cy = sum(i // width for i in pixels)/len(pixels)
        index = min(pixels, key=lambda i:(i % width-cx)**2+(i//width-cy)**2)
        left, right, up, down = map(math.tan, eye['fov_left_right_up_down'])
        # ID buffers use GL bottom-up rows, like depth.
        direction = rotate(eye['orientation_xyzw'], [
            left+(right-left)*((index % width+.5)/width),
            down+(up-down)*((index//width+.5)/height), -1])
        depths = array.array('f')
        depths.frombytes((out/'pick/left.depth.f32').read_bytes())
        near, far = evidence['depth_near_m'], evidence['depth_far_m']
        axial_distance = near*far/(far-depths[index]*(far-near))
        target = [a+axial_distance*b for a,b in zip(eye['position'],direction)]
        length = math.sqrt(sum(v*v for v in direction))
        # Production selection sphere is 12cm ahead of the controller, not a ray.
        position = [a-.12*b/length for a,b in zip(target,direction)]
        if controls:
            motion = reach_target(live,target,preset,seed+50000,target_position=position)
            (out/'end-selection-profile.json').write_text(json.dumps(motion,indent=2))
        else:
            put(live, position, aim_orientation(position,target))
        live.send('button', hand=1,button='trigger',pressed=True)
        live.frame()
        live.capture_to(out/'selection-volume',discard_source=True)
        live.send('button',hand=1,button='trigger',pressed=False)
        live.frame()
        deadline = time.monotonic()+5
        while live.state['selection_kind'] != 'end' and time.monotonic()<deadline:
            live.frame()
            time.sleep(.1)
        (out/'picked.json').write_text(json.dumps({'expected':ends[identity], 'state':live.state},indent=2))
        if live.state['selection_kind'] != 'end':
            raise RuntimeError('Controller did not select an end')
        expected_ends = {t for t in ends[identity]['owner_tokens'] if json.loads(unquote(t))[0]=='end'}
        if not expected_ends.intersection(live.state['owner_tokens']):
            raise RuntimeError('Selected end differs from visible target')
        put(live, origin['position'], origin['orientation_xyzw'])
        if controls:
            activate_extrude(live,click,out,preserve_selection=True)
        else:
            live.send('activate', tool='extrude')
            live.frame()
        for _ in range(21):
            click('+')
        click('BACK TO TOOLS')
        deadline = time.monotonic()+15
        while not live.state.get('painted_commit_ready'):
            if time.monotonic() > deadline:
                raise RuntimeError('End preflight did not become ready')
            live.frame()
            time.sleep(.1)
        before = live.state['scene_revision']
        click('CONFIRM')
        deadline = time.monotonic()+120
        while live.state['status'] != 'COMMITTED' or live.state['scene_revision'] <= before:
            if time.monotonic() > deadline:
                raise RuntimeError('End commit/scene refresh not acknowledged')
            live.frame()
            time.sleep(.1)
        live.capture_to(out/'committed', discard_source=True)
        hold_demo(live,'blunt-end extension committed')
        (out/'committed-state.json').write_text(json.dumps(live.state,indent=2))
        print(json.dumps({'status':live.state['status'],'feature':live.state['committed_feature_id']}))
    except Exception:
        for sidecar in Path(socket).parent.glob('*.json'):
            (out/('runtime-'+sidecar.name)).write_bytes(sidecar.read_bytes())
        (out/'failure-state.json').write_text(json.dumps(live.state,indent=2))
        raise
    finally:
        live.release()


if __name__ == '__main__':
    run(*sys.argv[1:3])

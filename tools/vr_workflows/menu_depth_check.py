"""Stereo foreground/behind-menu controller depth regression, with real input."""
import json
import numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.menu_tour import click
from tools.vr_workflows.room_ui_check import capture
from tools.vr_workflows.profile_input import reach_target


def run(live, catalog, output, preset):
    del catalog
    trials=[]
    results=[]
    try:
        for hand in (0,1):
            if live.state['sidebars'][hand]['open']:live.button('menu',hand=hand)
        live.button('menu',hand=0)
        click(live,0,'tab:scene',preset,trials)
        anchor=capture(live,output/'anchor')
        head=np.mean([e['position'] for e in anchor['eyes']],axis=0)
        panel=live.state['sidebars'][0]
        from scipy.spatial.transform import Rotation
        edges=np.asarray(panel['grip_targets'])
        right=edges[1]-edges[0];right/=np.linalg.norm(right)
        up=edges[2]-edges[3];up/=np.linalg.norm(up)
        q=Rotation.from_matrix(np.column_stack((right,up,np.cross(right,up)))).as_quat().tolist()
        center=np.asarray(panel['position'])
        normal=np.asarray(rotate(q,[0,0,1]))
        if np.dot(normal,head-center)<0:normal=-normal
        live.send('scene_visibility',visibility='hidden')
        for hand in (0,1):
            live.send('pose',hand=hand,position=(head+[0,-1,0]).tolist(),orientation=q)
        live.frame()
        baseline=capture(live,output/'panel')
        masks={}
        for eye in baseline['eyes']:
            shape=(eye['height'],eye['width']);name=eye['eye']
            masks[name]=binary_erosion(np.flipud(np.fromfile(output/'panel'/(name+'.classes.u8'),np.uint8).reshape(shape))==3,iterations=5)
        for label,depth in [('front',.28),('behind',-.28)]:
            destination=center+normal*depth
            trial=reach_target(live,destination.tolist(),preset,991+len(trials),target_position=destination.tolist(),target_orientation=q)
            trials.append(trial)
            live.frame()
            evidence=capture(live,output/label)
            for eye in evidence['eyes']:
                name=eye['eye'];shape=(eye['height'],eye['width'])
                classes=np.flipud(np.fromfile(output/label/(name+'.classes.u8'),np.uint8).reshape(shape))
                rgb=np.asarray(Image.open(output/label/(name+'.png')).convert('RGB'))
                mask=(classes==5)&masks[name]
                pixels=int(mask.sum())
                sharp=int((mask&(rgb[:,:,0]>200)&(rgb[:,:,1]>80)&(rgb[:,:,1]<180)&(rgb[:,:,2]<80)).sum())
                row=dict(eye=name,side=label,controller_pixels_in_panel=pixels,sharp_orange_pixels=sharp)
                results.append(row)
                assert pixels>50 and sharp>20 if label=='front' else pixels==0, row
        # Negative control: with the panel removed, the same rear controller
        # must become visible at the covered pixels in both eyes.
        live.button('menu',hand=0);live.frame()
        uncovered=capture(live,output/'behind-uncovered')
        for eye in uncovered['eyes']:
            name=eye['eye'];shape=(eye['height'],eye['width'])
            classes=np.flipud(np.fromfile(output/'behind-uncovered'/(name+'.classes.u8'),np.uint8).reshape(shape))
            visible=int(((classes==5)&masks[name]).sum())
            assert visible>50, 'Rear controller must be present behind the panel'
            results.append(dict(eye=name,side='behind-uncovered',controller_pixels_in_panel=visible))
        live.button('menu',hand=0);live.frame()
        from tools.vr_motion.desktop_check import run as desktop_check
        desktop=desktop_check(live.bridge.socket_path,output/'desktop',live=live,reveal=True)
        assert desktop['passed'],desktop
        return dict(passed=True,pixels=results,desktop=desktop)
    finally:
        (output/'depth-results.json').write_text(json.dumps(results,indent=2))
        (output/'reaches.json').write_text(json.dumps(trials,indent=2))
        live.send('scene_visibility',visibility='normal')
        live.release()

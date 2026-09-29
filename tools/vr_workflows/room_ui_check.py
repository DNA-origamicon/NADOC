"""Native stereo evidence for frosted menus and the runtime-calibrated floor."""
import json
import time
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.menu_tour import click
from tools.vr_workflows.menu_pixels import check


def capture(live, output):
    evidence,_=live.capture_to(output,files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','evidence.json'],discard_source=True)
    return evidence


def boundary_pixels(image, eye, floor):
    """Project calibrated stage edges independently into the captured eye."""
    matrix=np.asarray(floor['stage_to_local'])
    w,h=floor['width_m']/2,floor['depth_m']/2
    q=eye['orientation_xyzw'];inverse=[-q[0],-q[1],-q[2],q[3]]
    left,right,up,down=np.tan(eye['fov_left_right_up_down'])
    hits=total=0
    for axis in (0,1):
        for sign in (-1,1):
            for t in np.linspace(-.95,.95,80):
                p=[sign*w if axis==0 else t*w,.002,t*h if axis==0 else sign*h,1]
                local=(matrix@p)[:3]
                v=rotate(inverse,local-eye['position'])
                if v[2]>=0:continue
                x=int((v[0]/-v[2]-left)/(right-left)*eye['width'])
                y=int((up-v[1]/-v[2])/(up-down)*eye['height'])
                if 4<x<eye['width']-4 and 4<y<eye['height']-4:
                    total+=1
                    a=image[y-3:y+4,x-3:x+4,:3]
                    hits+=bool(((a[:,:,1]>a[:,:,0]*1.6)&(a[:,:,2]>a[:,:,0]*1.6)&(a[:,:,1]>70)).any())
    return dict(samples=total,hits=hits)


def panel_interior(eye,controls):
    """Exclude tinted controls when measuring the neutral glass substrate."""
    mask=Image.new('L',(eye['width'],eye['height']),255)
    draw=ImageDraw.Draw(mask)
    q=eye['orientation_xyzw'];inverse=[-q[0],-q[1],-q[2],q[3]]
    left,right,up,down=np.tan(eye['fov_left_right_up_down'])
    for c in controls:
        if not c.get('sidebar'):continue
        corners=[]
        for x,y in [(-1,-1),(1,-1),(1,1),(-1,1)]:
            p=np.asarray(c['position'])+x*1.15*np.asarray(c['hit_half_right'])+y*1.15*np.asarray(c['hit_half_up'])
            v=rotate(inverse,p-eye['position'])
            corners.append(((v[0]/-v[2]-left)/(right-left)*eye['width'],(up-v[1]/-v[2])/(up-down)*eye['height']))
        draw.polygon(corners,fill=0)
    return np.asarray(mask)>0


def run(live, catalog, output, preset):
    del catalog
    trials=[]
    try:
        for hand in (0,1):
            if live.state['sidebars'][hand]['open']:live.button('menu',hand=hand)
        anchor=capture(live,output/'anchor')
        floor=anchor['state']['room_floor']
        assert floor['located'], 'Runtime has no located STAGE floor; do not invent a floor height'
        head=np.mean([e['position'] for e in anchor['eyes']],axis=0)
        q=anchor['eyes'][0]['orientation_xyzw']
        p=live.state['presentation'];matrix=np.asarray(p['model_to_tracking_rows'])
        center=(matrix@np.r_[p['normalized_offset_model'],1])[:3]
        live.send('pose',hand=1,position=center.tolist(),orientation=[0,0,0,1]);live.frame()
        live.send('button',hand=1,button='grip',pressed=True);live.frame()
        live.send('pose',hand=1,position=(head+rotate(q,[0,0,-1.15])).tolist(),orientation=[0,0,0,1]);live.frame()
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
        live.button('menu',hand=0);live.frame()
        panel=live.state['sidebars'][0];edge=np.asarray(panel['grip_targets'][0])
        delta=head+rotate(q,[-.02,-.04,-.70])-panel['position']
        live.send('pose',hand=1,position=edge.tolist(),orientation=q);live.frame()
        live.send('button',hand=1,button='grip',pressed=True);live.frame()
        assert live.state['sidebars'][0]['grip_state']=='moving'
        live.send('pose',hand=1,position=(edge+delta).tolist(),orientation=q);live.frame()
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
        # Release the grip from a clearly headward point, not exactly in the
        # panel plane where the approach-side calculation is ambiguous.
        live.send('pose',hand=1,position=(head+rotate(q,[.25,-.3,-.35])).tolist(),orientation=q)
        live.frame()
        # Measured navigation retains the production controls and motion presets.
        time.sleep(1)
        click(live,0,'tab:scene',preset,trials)
        for hand in (0,1):
            live.send('pose',hand=hand,position=(head+rotate(q,[0,-1,0])).tolist(),orientation=[0,0,0,1])
        live.frame()
        glass=capture(live,output/'glass')
        pixels=check(output/'glass',glass)
        (output/'menu-pixels.json').write_text(json.dumps(pixels,indent=2))
        assert pixels['passed'], [c for c in pixels['controls'] if not c['passed']]
        # A blank surface must not masquerade as a rendered menu.
        from unittest.mock import patch
        with patch('tools.vr_workflows.menu_pixels.Image.open',return_value=Image.new('RGB',(glass['eyes'][0]['width'],glass['eyes'][0]['height']),'white')):
            assert not check(output/'glass',glass)['passed']
        live.button('menu',hand=0);live.frame()
        raw=capture(live,output/'uncovered')
        checks=[]
        for eye in raw['eyes']:
            name=eye['eye'];shape=(eye['height'],eye['width'])
            classes=np.fromfile(output/'uncovered'/(name+'.classes.u8'),np.uint8).reshape(shape)
            image=np.asarray(Image.open(output/'uncovered'/(name+'.png')).convert('RGB')).astype(float)
            covered=np.asarray(Image.open(output/'glass'/(name+'.png')).convert('RGB')).astype(float)
            overlay=np.fromfile(output/'glass'/(name+'.classes.u8'),np.uint8).reshape(shape)==3
            # Compare low-contrast panel interiors against an independently blurred
            # background. Sharp labels and blue selected controls are excluded.
            blurred=gaussian_filter(image,(10.5,10.5,0))
            predicted=.10*(np.array([.90,.92,.94])*255)+.90*blurred
            flat=.10*(np.array([.90,.92,.94])*255)
            mask=panel_interior(eye,glass['state']['controls']) & overlay & (covered.max(2)<140) & (blurred.max(2)>12)
            count=int(mask.sum())
            error=float(np.abs(covered[mask]-predicted[mask]).mean()) if count else 999
            opaque_error=float(np.abs(covered[mask]-flat).mean()) if count else 999
            cyan=(image[:,:,1]>image[:,:,0]*1.6)&(image[:,:,2]>image[:,:,0]*1.6)&(image[:,:,1]>70)&(classes==2)
            edge_mask=mask & (np.abs(image-blurred).max(2)>15)
            sharp_error=float(np.abs(covered[edge_mask]-(.10*(np.array([.90,.92,.94])*255)+.90*image[edge_mask])).mean())
            blur_edge_error=float(np.abs(covered[edge_mask]-predicted[edge_mask]).mean())
            row=dict(eye=name,edge_samples=int(edge_mask.sum()),sharp_error=sharp_error,blur_edge_error=blur_edge_error,floor_pixels=int((classes==2).sum()),boundary_pixels=int(cyan.sum()),glass_samples=count,blur_error=error,opaque_error=opaque_error)
            row['calibrated_edge']=boundary_pixels(image,eye,raw['state']['room_floor'])
            shifted={**raw['state']['room_floor'],'stage_to_local':np.asarray(raw['state']['room_floor']['stage_to_local']).copy()}
            shifted['stage_to_local'][0,3]+=0.3
            row['wrong_edge']=boundary_pixels(image,eye,shifted)
            checks.append(row)
        (output/'room-pixels.json').write_text(json.dumps(checks,indent=2))
        assert all(c['floor_pixels']>100 for c in checks), checks
        assert all(c['glass_samples']>100 and c['blur_error']<15 and c['blur_error']<c['opaque_error'] for c in checks), checks
        assert all(c['edge_samples']>100 and c['blur_edge_error']<c['sharp_error']*.5 for c in checks),checks
        if floor['bounded']:
            assert all(c['boundary_pixels']>20 and c['calibrated_edge']['samples']>20 and c['calibrated_edge']['hits']/c['calibrated_edge']['samples']>.9 for c in checks),checks
            assert all(c['wrong_edge']['hits']/max(1,c['wrong_edge']['samples'])<.5 for c in checks),checks
        # Flat opaque gray is an explicit negative case for the translucency oracle.
        assert all(c['opaque_error']>c['blur_error'] for c in checks)
        live.button('menu',hand=0);live.frame()
        # The other sidebar uses the same glass surface and keeps native inputs.
        live.button('menu',hand=1);live.frame()
        click(live,1,'tab:visualization',preset,trials)
        capture(live,output/'both-sidebars')
        from tools.vr_motion.desktop_check import run as desktop_check
        desktop=desktop_check(live.bridge.socket_path,output/'desktop',live=live,reveal=True)
        assert desktop['passed'],desktop
        return dict(passed=True,room=floor,pixels=checks,desktop=desktop)
    finally:
        (output/'reaches.json').write_text(json.dumps(trials,indent=2))
        live.release()

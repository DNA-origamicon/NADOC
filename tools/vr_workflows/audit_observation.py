"""Choose a visible controller observation pose from captured molecular pixels."""
import json
from pathlib import Path
import numpy as np
from tools.vr_motion.metrics import rotate
from tools.vr_motion.visual_checks import project


def front_bond(evidence, bonds, masks=None):
    """Choose a near-side bond with room for the scissors in both eye views.

    This is a target-selection heuristic, not a visibility pass. The existing
    stereo/mirror pixel oracle must still establish scissors and bond visibility.
    """
    head=np.mean([eye['position'] for eye in evidence['eyes']],axis=0)
    q=evidence['eyes'][0]['orientation_xyzw']
    candidates=[]
    for index,bond in enumerate(bonds):
        mid=(np.asarray(bond['a'])+bond['b'])/2
        points=[np.asarray(bond['a']),np.asarray(bond['b'])]
        points.extend(mid+rotate(q,[x,y,z]) for x in (-.06,.06)
                      for y in (-.04,.06) for z in (0,.12))
        visible=True
        for eye_index,eye in enumerate(evidence['eyes']):
            for point in points:
                pixel=project(point,eye)
                if pixel is None or not (.1*eye['width']<pixel[0]<.9*eye['width'] and
                                          .1*eye['height']<pixel[1]<.9*eye['height']):
                    visible=False;break
            if not visible:break
            if masks is not None:
                # Keep the open blades clear in the setup image. Closed blades
                # converge on the bond itself, so background clearance cannot
                # establish their visibility; the unchanged pixel oracle must.
                mask=masks[eye_index]
                angle=.65
                for side in (-1,1):
                    for t in (.025,.04,.052):
                        point=mid+rotate(q,[side*np.sin(angle)*t,np.cos(angle)*t-.022,0])
                        pixel=project(point,eye)
                        if pixel is None:visible=False;break
                        x,y=map(round,pixel)
                        if mask[y-5:y+6,x-5:x+6].any():visible=False;break
                    if not visible:break
            if not visible:break
        if visible:candidates.append((float(np.linalg.norm(mid-head)),index))
    if not candidates:raise RuntimeError('No bond has stereo framing clearance for scissors')
    return min(candidates)[1]


def clear_wrist(directory, hand=1):
    directory=Path(directory)
    evidence=json.loads((directory/'evidence.json').read_text())
    masks=[]
    for eye in evidence['eyes']:
        ids=np.fromfile(directory/(eye['eye']+'.ids.u32'),dtype=np.uint32).reshape(eye['height'],eye['width'])
        if not ids.any():raise RuntimeError('No molecular pixels for controller observation placement')
        masks.append(ids!=0)
    head=np.mean([eye['position'] for eye in evidence['eyes']],axis=0)
    q=evidence['eyes'][0]['orientation_xyzw']
    wrist=evidence['state']['hands'][hand]
    tip=np.array(rotate(wrist['orientation_xyzw'],[0,0,-.12]))
    candidates=[]
    # A full origami can fill the matching side of the view. Consider visible
    # poses across the front of the body too, instead of assuming that side is
    # empty. All candidates stay in ordinary arm reach; the pixel gate is fixed.
    for x in (.28,.4,.55,-.28,-.4,-.55):
        for y in (-.1,0,.1,.2,.3,.4):
            for z in (-.35,-.5,-.65):
                position=head+rotate(q,[x if hand else -x,y,z])
                center=position+tip
                # Clearance encloses the whole sphere/scissors, not just a
                # favorable subset of the oracle's sample points.
                corners=[center+[dx,dy,dz] for dx in (-.07,.07) for dy in (-.07,.07) for dz in (-.07,.07)]
                clear=True
                for eye,mask in zip(evidence['eyes'],masks):
                    points=[project(p,eye) for p in corners]
                    if any(p is None for p in points):clear=False;break
                    lo=np.floor(np.min(points,axis=0)).astype(int)
                    hi=np.ceil(np.max(points,axis=0)).astype(int)
                    if np.any(lo<8) or hi[0]>=eye['width']-8 or hi[1]>=eye['height']-8 or mask[lo[1]:hi[1]+1,lo[0]:hi[0]+1].any():
                        clear=False;break
                if clear:candidates.append(position)
    if not candidates:raise RuntimeError('No visible wrist pose clears the captured model')
    return min(candidates,key=lambda p:np.linalg.norm(p-wrist['position'])).tolist()
